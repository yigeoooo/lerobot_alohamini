"""FastAPI/WebSocket gateway used by a Quest browser.

The gateway deliberately keeps arm IK out of the transport layer.  Arm messages are
accepted as an extension point, while current arm targets are held when sending base
or lift commands.  Only the ``forward`` camera is ever emitted to the browser.

Transport design
----------------
The serial motor buses are the hard rate limit: a single :meth:`RobotLike.send_action`
performs several ``sync_read``/``sync_write`` round trips per bus, so the robot can only
absorb a few tens of full actions per second.  The browser, however, produces several
messages per animation frame.  Inbound messages are therefore *staged* (cheap, no robot
I/O) and a fixed-rate control loop *flushes* the newest staged state as a single action.
Coalescing keeps the newest arm pose instead of queueing every pose behind the bus.

Held targets are the values last *commanded*, never the measured joint positions.  Using
measured positions makes every base or lift heartbeat re-command the arm to where it
currently is, which cancels the arm target that was issued a few milliseconds earlier.
"""

import asyncio
import base64
import contextlib
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

logger = logging.getLogger(__name__)

BASE_VELOCITY_KEYS = ("x.vel", "y.vel", "theta.vel")
LIFT_HEIGHT_KEY = "lift_axis.height_mm"
LIFT_VELOCITY_KEY = "lift_axis.vel"

# Acknowledgements for these message types are not worth a WebSocket frame each: they
# arrive at the animation-frame rate and carry no information the browser acts on.  A
# periodic ``status`` message reports the same state instead.
QUIET_ACK_TYPES = frozenset({"base", "arm", "controller_pose", "head_pose", "pose"})


class RobotLike(Protocol):
    is_connected: bool
    last_remote_state: dict[str, Any]

    def connect(self) -> None: ...
    def disconnect(self) -> None: ...
    def get_observation(self) -> dict[str, Any]: ...
    def send_action(self, action: dict[str, Any]) -> dict[str, Any]: ...


class ArmIK(Protocol):
    """Optional arm IK adapter.  Implementations map a pose to joint targets."""

    def pose_to_action(self, payload: dict[str, Any], state: dict[str, Any]) -> dict[str, float]: ...


@dataclass
class VRGatewayConfig:
    remote_ip: str = "192.168.11.2"
    # State polling also runs the robot's overcurrent protection, so it cannot be turned
    # off entirely, but it competes with control for the serial buses.  10 Hz leaves the
    # bus mostly free for actions while still refreshing the browser's state view.
    poll_hz: float = 10.0
    # One coalesced action per tick.  Matches the browser's 40 ms send cadence.
    control_hz: float = 25.0
    # Camera frames are emitted at most this often, independently of state polling.
    video_hz: float = 10.0
    watchdog_timeout_s: float = 1.0
    camera_name: str = "forward"
    jpeg_quality: int = 55
    # Downscale wide frames before encoding: encode time and base64 payload size both
    # scale with pixel count, and the headset view is letterboxed anyway.
    max_frame_width: int = 480
    # Poses older than this (measured against the client clock, see ``_pose_age_s``) are
    # dropped so a burst released after a WiFi stall cannot replay as a lurch.
    max_pose_age_s: float = 0.25
    # Safety backstop on how far an arm joint target may jump in one control tick.
    # The IK owns tracking smoothness; this only catches a bad solve or a burst resumed
    # after a stall, which matters because the motor bus "degrees" write path does not
    # clamp and ``max_relative_target`` is disabled on this robot.  Set to 0 to disable.
    max_joint_step_deg: float = 20.0
    # Throttle for repeated operator-facing warnings (IK rejections, stale poses).
    warn_period_s: float = 2.0
    # Cadence of the unsolicited ``status`` message sent to the browser.
    status_period_s: float = 1.0
    gripper_action_key: str = "gripper.position"


@dataclass
class GatewayStats:
    """Counters surfaced to the operator so silent failures become visible."""

    actions_sent: int = 0
    ik_applied: int = 0
    ik_rejected: int = 0
    poses_stale: int = 0
    messages_coalesced: int = 0
    joint_steps_clamped: int = 0
    arm_reanchor_rejected: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "actions_sent": self.actions_sent,
            "ik_applied": self.ik_applied,
            "ik_rejected": self.ik_rejected,
            "poses_stale": self.poses_stale,
            "messages_coalesced": self.messages_coalesced,
            "joint_steps_clamped": self.joint_steps_clamped,
            "arm_reanchor_rejected": self.arm_reanchor_rejected,
        }


def _json_safe(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    return value


def _is_holdable_state_key(key: str) -> bool:
    """Return whether a measured observation value may seed a held command target.

    Only position-like readings qualify.  Measured *velocities* must never be fed back
    as commands: ``get_observation`` reports the base's actual wheel velocity, so holding
    it would make the base perpetuate its own motion, and the lift's measured velocity
    would override the height controller inside ``LiftAxis.apply_action``.
    """
    return key.endswith(".pos") or key.endswith(".height_mm")


class VRGateway:
    def __init__(self, robot: RobotLike, config: VRGatewayConfig | None = None, arm_ik: ArmIK | None = None):
        self.robot = robot
        self.config = config or VRGatewayConfig()
        self.arm_ik = arm_ik
        self.last_action_at = time.monotonic()
        self.last_message_at = time.monotonic()
        self.estopped = False
        # ``clutch`` freezes the arms without stopping the base.  Default off so the arms
        # follow the controller grips as soon as the operator squeezes them.
        self.arm_frozen = False
        self.calibrated = False
        self.stats = GatewayStats()
        self._send_lock = asyncio.Lock()
        self._robot_lock = asyncio.Lock()
        self._last_state: dict[str, Any] = {}
        self._last_controller_buttons: dict[str, tuple[bool, ...]] = {}
        self._last_base_updates: tuple[float, float, float] = (0.0, 0.0, 0.0)
        # Last values actually commanded.  These, not the measured state, are what the
        # gateway holds for joints that the current message does not address.
        self._commanded: dict[str, Any] = dict.fromkeys(BASE_VELOCITY_KEYS, 0.0)
        self._pending_updates: dict[str, Any] = {}
        self._pending_arm: dict[str, Any] | None = None
        self._last_arm_status: str | None = None
        self._warned_at: dict[str, float] = {}
        # Offset between the browser's clock and ours, estimated from the least delayed
        # sample seen so far (see ``_pose_age_s``).
        self._clock_offset_s: float | None = None

    @property
    def clutch_enabled(self) -> bool:
        """Backwards-compatible alias for the arm freeze flag."""
        return self.arm_frozen

    @staticmethod
    def _format_axis(value: float) -> str:
        """Format a controller axis for concise, readable operator logs."""
        return f"{value:+.3f}"

    def _state(self) -> dict[str, Any]:
        return getattr(self.robot, "last_remote_state", {}) or self._last_state

    def _warn(self, key: str, message: str, *args: Any) -> None:
        """Emit a warning at most once per ``warn_period_s`` for the given key."""
        now = time.monotonic()
        if now - self._warned_at.get(key, -1e9) < self.config.warn_period_s:
            return
        self._warned_at[key] = now
        logger.warning(message, *args)

    # ------------------------------------------------------------------ actions

    def _held_action(self) -> dict[str, Any]:
        """Build a complete action, holding uncommanded joints at their last command.

        Measured positions only seed joints that have never been commanded, which keeps
        the very first action after connect (and after an E-stop or clutch release) sane.
        """
        action: dict[str, Any] = {}
        for key, value in self._state().items():
            if _is_holdable_state_key(key):
                action[key] = _json_safe(value)
        action.update(self._commanded)
        for key in BASE_VELOCITY_KEYS:
            action.setdefault(key, 0.0)
        if LIFT_VELOCITY_KEY in self._commanded:
            # The two lift keys are mutually exclusive: ``LiftAxis.apply_action`` applies
            # the height controller first and then lets a velocity key overwrite it.
            action.pop(LIFT_HEIGHT_KEY, None)
        return action

    def _remember(self, updates: dict[str, Any]) -> None:
        """Latch explicitly commanded values so later actions hold them."""
        for key, value in updates.items():
            if key == LIFT_HEIGHT_KEY:
                self._commanded.pop(LIFT_VELOCITY_KEY, None)
            elif key == LIFT_VELOCITY_KEY:
                self._commanded.pop(LIFT_HEIGHT_KEY, None)
            elif not (_is_holdable_state_key(key) or key in BASE_VELOCITY_KEYS):
                continue
            self._commanded[key] = value

    def _reset_arm_targets(self) -> None:
        """Forget commanded arm targets so the next action reseeds from measured state."""
        for key in [key for key in self._commanded if key.endswith(".pos")]:
            del self._commanded[key]

    def _limit_joint_steps(self, updates: dict[str, float]) -> dict[str, float]:
        """Clamp how far each arm joint target may move from its previous command.

        A pure safety backstop, deliberately generous (the default allows ~500 deg/s at
        25 Hz, faster than these servos actually move).  It exists because nothing else
        downstream bounds an arm goal: the motors bus writes degrees without clamping and
        ``max_relative_target`` is ``None`` on this robot.
        """
        limit = self.config.max_joint_step_deg
        if limit <= 0:
            return updates
        state = self._state()
        limited = dict(updates)
        for key, value in updates.items():
            if not key.endswith(".pos"):
                continue
            reference = self._commanded.get(key, state.get(key))
            if reference is None:
                continue
            delta = float(value) - float(reference)
            if abs(delta) <= limit:
                continue
            self.stats.joint_steps_clamped += 1
            limited[key] = float(reference) + (limit if delta > 0 else -limit)
            self._warn(
                "joint_step",
                "[VR] clamped %s step of %+.1f deg to %+.1f deg (%d clamped so far)",
                key,
                delta,
                limit if delta > 0 else -limit,
                self.stats.joint_steps_clamped,
            )
        return limited

    def _send(self, updates: dict[str, Any], *, mark_activity: bool = True) -> dict[str, Any]:
        updates = self._limit_joint_steps(updates)
        self._remember(updates)
        action = self._held_action()
        action.update(updates)
        if self.estopped:
            action.update(dict.fromkeys(BASE_VELOCITY_KEYS, 0.0))
            action[LIFT_VELOCITY_KEY] = 0.0
            action.pop(LIFT_HEIGHT_KEY, None)
        result = self.robot.send_action(action)
        self.stats.actions_sent += 1
        if mark_activity:
            self.last_action_at = time.monotonic()
        return result

    # ------------------------------------------------------------------- staging

    def _pose_age_s(self, message: dict[str, Any]) -> float | None:
        """Estimate how long ago the browser sampled this pose, in seconds.

        The headset clock is not synchronised with ours, so absolute timestamps are
        meaningless.  Instead track the largest ``client - server`` offset observed: that
        sample is the one that travelled fastest, and every later sample's shortfall
        against it is its extra delay.  A slow leak lets the estimate follow clock drift.
        """
        raw = message.get("client_time_ms", message.get("t"))
        if raw is None:
            return None
        try:
            client_s = float(raw) / 1000.0
        except (TypeError, ValueError):
            return None
        offset = client_s - time.monotonic()
        if self._clock_offset_s is None:
            self._clock_offset_s = offset
            return 0.0
        # 1 ms of leak per sample re-syncs at ~2.5 %/s at the nominal 25 Hz pose rate.
        self._clock_offset_s = max(offset, self._clock_offset_s - 0.001)
        return max(0.0, self._clock_offset_s - offset)

    def _freeze_arms(self, frozen: bool) -> None:
        self.arm_frozen = frozen
        if not frozen:
            return
        self._pending_arm = None
        if self.arm_ik is not None and hasattr(self.arm_ik, "update"):
            try:
                self.arm_ik.update({"active": False}, self._state())
            except Exception:  # pragma: no cover - defensive, IK is third-party
                logger.exception("failed to deactivate arm IK")
        # Hold wherever the arms physically are rather than at a stale IK target.
        self._reset_arm_targets()

    def stage_message(self, message: dict[str, Any]) -> dict[str, Any]:
        """Validate one protocol message and fold it into the pending command state.

        Performs no robot I/O; :meth:`flush` applies the result.  Later messages of the
        same kind overwrite earlier ones, so a backlog collapses to its newest entry.
        """
        kind = str(message.get("type", "")).lower()
        self.last_message_at = time.monotonic()

        if kind in {"ping", "hello"}:
            return {"type": "ack", "for": kind}

        if kind == "controller_pose":
            # Controller pose packets include the WebXR gamepad button values.
            # Log only transitions (rather than every frame) so the operator can
            # identify the Quest browser's actual A/B button indices.
            hand = str(message.get("hand", "unknown"))
            raw_buttons = message.get("buttons", ())
            try:
                values = tuple(float(value) for value in raw_buttons)
            except (TypeError, ValueError):
                values = ()
            buttons = tuple(value > 0.5 for value in values)
            previous = self._last_controller_buttons.get(hand, ())
            if buttons != previous:
                pressed = [index for index, active in enumerate(buttons) if active]
                logger.info("[VR] %s controller buttons pressed=%s", hand, pressed)
                for index, active in enumerate(buttons):
                    was_active = previous[index] if index < len(previous) else False
                    if active != was_active:
                        state = "DOWN" if active else "UP"
                        value = values[index] if index < len(values) else 0.0
                        logger.info("[VR] %s button_index=%d state=%s value=%.3f", hand, index, state, value)
                self._last_controller_buttons[hand] = buttons
            return {"type": "ack", "for": kind, "status": "received"}

        if kind in {"head_pose", "pose"}:
            return {"type": "ack", "for": kind, "status": "received"}

        if kind in {"calibrate", "calibration"}:
            self.calibrated = bool(message.get("enabled", True))
            return {"type": "ack", "for": "calibrate", "enabled": self.calibrated}

        if kind == "clutch":
            self._freeze_arms(bool(message.get("enabled", True)))
            logger.info("[VR] arm freeze %s", "engaged" if self.arm_frozen else "released")
            return {"type": "ack", "for": "clutch", "enabled": self.arm_frozen}

        if kind in {"estop", "e_stop"}:
            self.estopped = bool(message.get("enabled", True))
            if self.estopped:
                # Drop the latched base velocity so releasing the E-stop cannot lurch,
                # and let the arms reseed from wherever they ended up.
                self._commanded.update(dict.fromkeys(BASE_VELOCITY_KEYS, 0.0))
                self._pending_arm = None
                self._reset_arm_targets()
            self._pending_updates.update(dict.fromkeys(BASE_VELOCITY_KEYS, 0.0))
            return {"type": "ack", "for": "estop", "enabled": self.estopped}

        if kind in {"base", "drive"}:
            if self.estopped:
                return {"type": "ack", "for": "base", "ignored": "estop"}
            updates = {name: float(message.get(name, 0.0)) for name in BASE_VELOCITY_KEYS}
            source = str(message.get("source", message.get("input", "joystick")))
            current_base = tuple(updates[name] for name in BASE_VELOCITY_KEYS)
            # The browser only sends on change plus a slow keepalive; still, do not log
            # idle all-zero packets.
            if current_base != self._last_base_updates and any(abs(value) > 1e-6 for value in current_base):
                logger.info(
                    "[VR] base %s: x=%s y=%s theta=%s",
                    source,
                    self._format_axis(updates["x.vel"]),
                    self._format_axis(updates["y.vel"]),
                    self._format_axis(updates["theta.vel"]),
                )
            self._last_base_updates = current_base
            self._stage_updates(updates)
            return {"type": "ack", "for": "base"}

        if kind == "lift":
            if self.estopped:
                return {"type": "ack", "for": "lift", "ignored": "estop"}
            state = self._state()
            button = message.get("button", message.get("input", ""))
            if "velocity" in message or "vel" in message:
                velocity = float(message.get("velocity", message.get("vel", 0.0)))
                logger.info(
                    "[VR] lift button %s: velocity=%+.0f", str(button).upper() if button else "", velocity
                )
                self._stage_updates({LIFT_VELOCITY_KEY: velocity})
                return {"type": "ack", "for": "lift", "velocity": velocity}
            if "height_mm" in message:
                target = float(message["height_mm"])
            else:
                target = float(state.get(LIFT_HEIGHT_KEY, 0.0)) + float(message.get("delta_mm", 0.0))
            if button:
                logger.info(
                    "[VR] lift button %s: delta=%+.1f mm target=%.1f mm",
                    str(button).upper(),
                    float(message.get("delta_mm", 0.0)),
                    target,
                )
            else:
                logger.info("[VR] lift target=%.1f mm", target)
            self._stage_updates({LIFT_HEIGHT_KEY: target})
            return {"type": "ack", "for": "lift", "height_mm": target}

        if kind == "gripper":
            if self.estopped:
                return {"type": "ack", "for": "gripper", "ignored": "estop"}
            value = float(message.get("position", message.get("value", 0.0)))
            state = self._state()
            key = self.config.gripper_action_key
            if key not in state:
                key = next(
                    (k for k in state if "gripper" in k.lower() and k.endswith((".pos", ".position"))), key
                )
            if key not in state and self.config.gripper_action_key == "gripper.position":
                return {"type": "ack", "for": "gripper", "status": "unbound", "value": value}
            self._stage_updates({key: value})
            return {"type": "ack", "for": "gripper", "status": "applied", "value": value}

        if kind in {"arm", "arm_pose"}:
            if self.arm_ik is None:
                return {"type": "ack", "for": "arm", "status": "ik_unavailable"}
            if self.estopped:
                return {"type": "ack", "for": "arm", "ignored": "estop"}
            if self.arm_frozen:
                return {"type": "ack", "for": "arm", "ignored": "clutch"}
            # Release packets must always be accepted: dropping a delayed active=false
            # would leave the old clutch reference live and make the next grip engage
            # against stale controller poses. Only active pose samples are freshness-gated.
            active = bool(message.get("active"))
            age = self._pose_age_s(message) if active else None
            if active and age is not None and age > self.config.max_pose_age_s:
                self.stats.poses_stale += 1
                self._warn(
                    "stale_pose",
                    "[VR] dropping arm pose delayed by %.0f ms (limit %.0f ms); %d dropped so far",
                    age * 1e3,
                    self.config.max_pose_age_s * 1e3,
                    self.stats.poses_stale,
                )
                return {"type": "ack", "for": "arm", "status": "stale"}
            if self._pending_arm is not None:
                self.stats.messages_coalesced += 1
            self._pending_arm = message
            return {
                "type": "ack",
                "for": "arm",
                "status": "staged",
                "reanchor": bool(message.get("reanchor")),
            }

        if kind in {"reanchor", "align"}:
            if self.arm_ik is None:
                return {"type": "ack", "for": "reanchor", "status": "ik_unavailable"}
            if self.estopped:
                return {"type": "ack", "for": "reanchor", "ignored": "estop"}
            left = message.get("left") or message.get("left_pose")
            right = message.get("right") or message.get("right_pose")
            if not left or not right:
                self.stats.arm_reanchor_rejected += 1
                return {
                    "type": "ack",
                    "for": "reanchor",
                    "status": "rejected",
                    "reason": "missing_controller_pose",
                }
            active = {
                "type": "arm_pose",
                "active": True,
                "left": left,
                "right": right,
                "reanchor": True,
            }
            if "client_time_ms" in message:
                active["client_time_ms"] = message["client_time_ms"]
            if self._pending_arm is not None:
                self.stats.messages_coalesced += 1
            self._pending_arm = active
            return {"type": "ack", "for": "reanchor", "status": "staged"}

        raise ValueError(f"unknown message type: {kind!r}")

    def _stage_updates(self, updates: dict[str, Any]) -> None:
        if LIFT_HEIGHT_KEY in updates:
            self._pending_updates.pop(LIFT_VELOCITY_KEY, None)
        elif LIFT_VELOCITY_KEY in updates:
            self._pending_updates.pop(LIFT_HEIGHT_KEY, None)
        for key in updates:
            if key in self._pending_updates:
                self.stats.messages_coalesced += 1
                break
        self._pending_updates.update(updates)

    # ------------------------------------------------------------------ flushing

    def _arm_updates(self, payload: dict[str, Any]) -> dict[str, float]:
        """Run the IK for one pose, counting and reporting rejections."""
        state = self._state()
        try:
            if hasattr(self.arm_ik, "update"):
                updates = self.arm_ik.update(payload, state)
            else:
                updates = self.arm_ik.pose_to_action(payload, state)
        except Exception:
            self.stats.ik_rejected += 1
            self._last_arm_status = "ik_error"
            logger.exception("[VR] arm IK raised; pose discarded")
            return {}
        if updates:
            self.stats.ik_applied += 1
            self._last_arm_status = "reanchored" if payload.get("reanchor") else "applied"
            return updates
        # An empty result while the operator is squeezing both grips means the IK
        # rejected the pose; without this the arm just silently stops tracking.
        if payload.get("active"):
            self.stats.ik_rejected += 1
            reason = getattr(self.arm_ik, "engage_reason", None) or "no_joint_targets"
            self._last_arm_status = f"rejected:{reason}"
            self._warn(
                "ik_rejected",
                "[VR] arm IK rejected %d of %d active poses (%s)",
                self.stats.ik_rejected,
                self.stats.ik_rejected + self.stats.ik_applied,
                reason,
            )
        else:
            self._last_arm_status = "held"
            # Clutch released: drop the latched targets so the arms hold where they are.
            self._reset_arm_targets()
        return {}

    def flush(self) -> bool:
        """Apply the newest staged command state as a single ``send_action``.

        Returns ``True`` when an action was sent.
        """
        updates = self._pending_updates
        self._pending_updates = {}
        arm_payload = self._pending_arm
        self._pending_arm = None
        self._last_arm_status = None
        if arm_payload is not None:
            updates.update(self._arm_updates(arm_payload))
        if not updates:
            return False
        self._send(updates)
        return True

    def process_message(self, message: dict[str, Any]) -> dict[str, Any]:
        """Validate, dispatch and immediately apply one protocol message.

        Equivalent to :meth:`stage_message` followed by :meth:`flush`; the WebSocket
        endpoint splits the two so that message handling never blocks on the motor buses.
        """
        ack = self.stage_message(message)
        self.flush()
        if ack.get("for") in {"arm", "reanchor"} and self._last_arm_status is not None:
            ack["status"] = self._last_arm_status
            if self._last_arm_status.startswith("rejected:"):
                ack["reason"] = self._last_arm_status.split(":", 1)[1]
        return ack

    def watchdog(self) -> bool:
        """Send a zero-velocity command when browser traffic stops.

        Only the base velocity is zeroed; arm and lift targets stay latched, so a dropped
        connection parks the base without dropping the arms.
        """
        if time.monotonic() - self.last_message_at <= self.config.watchdog_timeout_s:
            return False
        self.last_message_at = time.monotonic()
        if all(abs(float(self._commanded.get(key, 0.0))) <= 1e-6 for key in BASE_VELOCITY_KEYS):
            return False
        logger.warning(
            "[VR] watchdog: no browser traffic for %.1fs, stopping base", self.config.watchdog_timeout_s
        )
        self._send(dict.fromkeys(BASE_VELOCITY_KEYS, 0.0), mark_activity=False)
        return True

    # -------------------------------------------------------------- observation

    def capture_observation(self) -> dict[str, Any]:
        """Read the robot.  Must run under the robot lock; does no encoding."""
        observation = self.robot.get_observation()
        self._last_state = {k: v for k, v in observation.items() if not isinstance(v, np.ndarray)}
        with contextlib.suppress(Exception):
            # Some robot implementations expose this as a read-only property.
            self.robot.last_remote_state = self._last_state
        return observation

    def encode_payload(self, observation: dict[str, Any], *, include_frame: bool = True) -> dict[str, Any]:
        """Serialise an observation for the browser.  Safe to run outside the robot lock.

        JPEG encoding plus base64 costs tens of milliseconds on a Pi 5; keeping it off the
        lock stops it from delaying inbound control messages.
        """
        payload: dict[str, Any] = {
            "type": "observation",
            "camera": self.config.camera_name,
            "state": {k: _json_safe(v) for k, v in observation.items() if not isinstance(v, np.ndarray)},
        }
        frame = observation.get(self.config.camera_name)
        if include_frame and isinstance(frame, np.ndarray):
            try:
                import cv2

                width = self.config.max_frame_width
                if width and frame.shape[1] > width:
                    height = max(1, round(frame.shape[0] * width / frame.shape[1]))
                    frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
                # AlohaMini camera observations are RGB, while OpenCV expects BGR.
                # Convert explicitly so browser JPEGs preserve the camera colors.
                frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                ok, encoded = cv2.imencode(
                    ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), self.config.jpeg_quality]
                )
                if ok:
                    payload["jpeg_b64"] = base64.b64encode(encoded.tobytes()).decode("ascii")
            except Exception:  # pragma: no cover - camera/codec is platform specific
                logger.exception("failed to encode forward camera frame")
        return payload

    def observation_payload(self) -> dict[str, Any]:
        """Read the robot and serialise it in one step (used by tests and simple callers)."""
        return self.encode_payload(self.capture_observation())

    def status_payload(self) -> dict[str, Any]:
        """Operator-visible gateway health, sent periodically instead of per-message acks."""
        timings = getattr(self.robot, "logs", {}) or {}
        return {
            "type": "status",
            "estop": self.estopped,
            "arm_frozen": self.arm_frozen,
            "calibrated": self.calibrated,
            "ik_available": self.arm_ik is not None,
            "arm_ik_active": bool(getattr(self.arm_ik, "active", False)),
            "arm_homing": bool(getattr(self.arm_ik, "homing", False)),
            "arm_home_max_error_deg": getattr(self.arm_ik, "home_max_error_deg", None),
            "arm_engage_reason": getattr(self.arm_ik, "engage_reason", None),
            "arm_pending": self._pending_arm is not None,
            "arm_pending_reanchor": bool(self._pending_arm and self._pending_arm.get("reanchor")),
            "control_hz": self.config.control_hz,
            **self.stats.as_dict(),
            "action_ms": round(float(timings.get("action_timing_ms", {}).get("action_total", 0.0)), 1),
            "observation_ms": round(
                float(timings.get("observation_timing_ms", {}).get("robot_observation_total", 0.0)), 1
            ),
        }


def create_app(robot: RobotLike, config: VRGatewayConfig | None = None, arm_ik: ArmIK | None = None):
    try:
        from fastapi import FastAPI, WebSocket, WebSocketDisconnect
        from fastapi.responses import HTMLResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("Install the 'vr' extra to run the VR gateway") from exc

    gateway = VRGateway(robot, config, arm_ik)
    app = FastAPI(title="LeRobot AlohaMini VR Gateway")
    static_dir = Path(__file__).with_name("static")
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return _INDEX_HTML

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "ok": True,
            "robot_connected": bool(getattr(robot, "is_connected", False)),
            "camera": gateway.config.camera_name,
            **gateway.stats.as_dict(),
        }

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            if not getattr(robot, "is_connected", False):
                await asyncio.to_thread(robot.connect)
            await websocket.send_json(
                {
                    "type": "hello",
                    "camera": gateway.config.camera_name,
                    "protocol": 2,
                    "control_hz": gateway.config.control_hz,
                }
            )

            async def send_json(payload: dict[str, Any]) -> None:
                async with gateway._send_lock:
                    await websocket.send_json(payload)

            async def control_loop() -> None:
                """Own the robot buses: one coalesced action per tick, plus the watchdog."""
                interval = 1.0 / max(gateway.config.control_hz, 1.0)
                while True:
                    async with gateway._robot_lock:
                        await asyncio.to_thread(gateway.flush)
                        await asyncio.to_thread(gateway.watchdog)
                    await asyncio.sleep(interval)

            async def observation_loop() -> None:
                """Poll state and stream video without holding the lock during encoding."""
                interval = 1.0 / max(gateway.config.poll_hz, 1.0)
                frames_per_video = max(1, round(gateway.config.poll_hz / max(gateway.config.video_hz, 0.1)))
                tick = 0
                last_status = 0.0
                while True:
                    async with gateway._robot_lock:
                        observation = await asyncio.to_thread(gateway.capture_observation)
                    include_frame = tick % frames_per_video == 0
                    payload = await asyncio.to_thread(
                        gateway.encode_payload, observation, include_frame=include_frame
                    )
                    await send_json(payload)
                    now = time.monotonic()
                    if now - last_status >= gateway.config.status_period_s:
                        last_status = now
                        await send_json(gateway.status_payload())
                    tick += 1
                    await asyncio.sleep(interval)

            tasks = [asyncio.create_task(control_loop()), asyncio.create_task(observation_loop())]
            try:
                while True:
                    raw = await websocket.receive_text()
                    try:
                        # Staging is pure Python bookkeeping, so it runs inline on the
                        # event loop: no lock, no thread hop, no queueing behind the buses.
                        reply = gateway.stage_message(json.loads(raw))
                    except (ValueError, TypeError, json.JSONDecodeError) as exc:
                        reply = {"type": "error", "error": str(exc)}
                    if _should_reply(reply):
                        await send_json(reply)
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        except WebSocketDisconnect:
            logger.info("Quest WebSocket disconnected")
        finally:
            try:
                gateway._send(dict.fromkeys(BASE_VELOCITY_KEYS, 0.0), mark_activity=False)
            except Exception:
                logger.exception("failed to stop robot on WebSocket disconnect")

    return app


def _should_reply(reply: dict[str, Any]) -> bool:
    """Suppress per-message acks for the high-rate streams; keep anything informative."""
    if reply.get("type") != "ack":
        return True
    if reply.get("for") not in QUIET_ACK_TYPES:
        return True
    return "ignored" in reply or reply.get("status") in {"rejected", "stale", "ik_error", "ik_unavailable"}


_STATIC_INDEX = Path(__file__).with_name("static") / "index.html"
try:
    _INDEX_HTML = _STATIC_INDEX.read_text(encoding="utf-8")
except OSError:
    _INDEX_HTML = "<!doctype html><meta charset='utf-8'><title>AlohaMini VR</title><p>VR frontend assets unavailable.</p>"


def main() -> None:  # pragma: no cover - CLI convenience
    import argparse

    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from lerobot.robots.alohamini.alohamini import AlohaMini
    from lerobot.robots.alohamini.config_alohamini import AlohaMiniConfig

    from .arm_ik import AlohaMiniDualArmIK

    parser = argparse.ArgumentParser(description="Serve AlohaMini VR teleoperation over WebSocket")
    parser.add_argument(
        "--robot-model", default="alohamini2pro", choices=["alohamini1", "alohamini2", "alohamini2pro"]
    )
    parser.add_argument("--left-port", default="/dev/am_arm_follower_left")
    parser.add_argument("--right-port", default="/dev/am_arm_follower_right")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--ws", choices=["auto", "websockets", "wsproto"], default="auto")
    parser.add_argument("--control-hz", type=float, default=VRGatewayConfig.control_hz)
    parser.add_argument("--poll-hz", type=float, default=VRGatewayConfig.poll_hz)
    parser.add_argument("--video-hz", type=float, default=VRGatewayConfig.video_hz)
    parser.add_argument("--jpeg-quality", type=int, default=VRGatewayConfig.jpeg_quality)
    parser.add_argument("--max-frame-width", type=int, default=VRGatewayConfig.max_frame_width)
    parser.add_argument("--max-pose-age-s", type=float, default=VRGatewayConfig.max_pose_age_s)
    args = parser.parse_args()
    robot_config = AlohaMiniConfig(
        id="AlohaMiniRobot",
        robot_model=args.robot_model,
        left_port=args.left_port,
        right_port=args.right_port,
        use_degrees=True,
    )
    # VR opens only the head/forward camera; wrist cameras remain untouched.
    robot_config.cameras = {"forward": robot_config.cameras["forward"]}
    robot = AlohaMini(robot_config)
    urdf = Path(__file__).parent / "assets" / "alohamini2pro" / "urdf" / "alohamini2pro.urdf"
    if not urdf.is_file():
        raise FileNotFoundError(
            f"AlohaMini 2 Pro URDF is required at {urdf}; sync src/lerobot/vr_gateway/assets "
            "to the Raspberry Pi before starting the VR gateway."
        )
    arm_ik = AlohaMiniDualArmIK(urdf)
    gateway_config = VRGatewayConfig(
        camera_name="forward",
        control_hz=args.control_hz,
        poll_hz=args.poll_hz,
        video_hz=args.video_hz,
        jpeg_quality=args.jpeg_quality,
        max_frame_width=args.max_frame_width,
        max_pose_age_s=args.max_pose_age_s,
    )
    uvicorn.run(create_app(robot, gateway_config, arm_ik=arm_ik), host=args.host, port=args.port, ws=args.ws)


if __name__ == "__main__":
    main()
