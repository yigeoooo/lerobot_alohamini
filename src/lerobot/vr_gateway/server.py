"""FastAPI/WebSocket gateway used by a Quest browser.

The gateway deliberately keeps arm IK out of the transport layer.  Arm messages are
accepted as an extension point, while current arm targets are held when sending base
or lift commands. Head and wrist cameras are enabled individually at startup.

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
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from .arm_session import SIDES, ArmSessions

logger = logging.getLogger(__name__)


def _diagnostics_enabled() -> bool:
    return os.environ.get("LEROBOT_VR_DIAGNOSTICS", "").strip().lower() in {"1", "true", "yes", "on"}


def _parse_bool(value: str | bool) -> bool:
    """Parse a human-friendly CLI boolean such as ``true`` or ``false``."""
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"invalid boolean value: {value!r}; use true or false")


def _parse_camera_device(value: str) -> int | Path:
    return int(value) if value.isdecimal() else Path(value)


# Feetech degree commands for joints whose encoder direction differs from the URDF
# axes. The wrist-roll encoder direction is inverted on both arms per the installed
# ROS2 hardware calibration.
ALOHAMINI_ROBOT_TO_URDF_JOINT_SIGNS = {
    "shoulder_pan": 1.0,
    "shoulder_lift": -1.0,
    "elbow_flex": -1.0,
    "wrist_flex": 1.0,
    "wrist_yaw": 1.0,
    "wrist_roll": -1.0,
}

VR_ARM_GOAL_VELOCITY = 2000
VR_ARM_ACCELERATION = 100
VR_MAX_RELATIVE_TARGET_DEG = 5.0

BASE_VELOCITY_KEYS = ("x.vel", "y.vel", "theta.vel")
LIFT_HEIGHT_KEY = "lift_axis.height_mm"
LIFT_VELOCITY_KEY = "lift_axis.vel"

# Acknowledgements for these message types are not worth a WebSocket frame each: they
# arrive at the animation-frame rate and carry no information the browser acts on.  A
# periodic ``status`` message reports the same state instead.
QUIET_ACK_TYPES = frozenset({"base", "arm", "gripper", "controller_pose", "head_pose", "pose"})


class RobotLike(Protocol):
    is_connected: bool
    last_remote_state: dict[str, Any]

    def connect(self) -> None: ...
    def disconnect(self) -> None: ...
    def get_observation(self, *, include_cameras: bool = True) -> dict[str, Any]: ...
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
    camera_names: tuple[str, ...] = ()
    jpeg_quality: int = 90
    # Preserve the VR camera's 720p details. Encoding stays outside the robot lock;
    # retain CLI overrides for slower links without upscaling smaller sources.
    max_frame_width: int = 1280
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
    max_feedback_age_s: float = 0.5
    arm_pose_timeout_s: float = 0.3


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


def make_vr_robot_config(
    *,
    robot_model: str,
    left_port: str,
    right_port: str,
    arm_ik_mode: str = "legacy",
    arm_goal_velocity: int | None = None,
    arm_acceleration: int = VR_ARM_ACCELERATION,
    max_relative_target: float | None = None,
    head_camera: int | str | Path | None = None,
    left_wrist_camera: int | str | Path | None = None,
    right_wrist_camera: int | str | Path | None = None,
):
    """Use the old actuator settings by default; retain calibrated mode explicitly."""
    from lerobot.cameras.opencv.configuration_opencv import OpenCVCameraConfig
    from lerobot.robots.alohamini.config_alohamini import AlohaMiniConfig

    if arm_ik_mode not in {"legacy", "calibrated"}:
        raise ValueError(f"Unknown arm IK mode: {arm_ik_mode}")
    if arm_goal_velocity is None:
        arm_goal_velocity = VR_ARM_GOAL_VELOCITY if arm_ik_mode == "legacy" else 100
    if max_relative_target is None and arm_ik_mode == "calibrated":
        max_relative_target = VR_MAX_RELATIVE_TARGET_DEG
    config = AlohaMiniConfig(
        id="AlohaMiniRobot",
        robot_model=robot_model,
        left_port=left_port,
        right_port=right_port,
        use_degrees=True,
        require_calibration_match=True,
        arm_goal_velocity=arm_goal_velocity,
        arm_acceleration=arm_acceleration,
        max_relative_target=max_relative_target,
        cameras={
            name: OpenCVCameraConfig(
                index_or_path=_parse_camera_device(str(device)),
                fps=30,
                width=1280 if name == "forward" else 640,
                height=720 if name == "forward" else 480,
                fourcc="MJPG",
            )
            for name, device in (
                ("forward", head_camera),
                ("wrist_left", left_wrist_camera),
                ("wrist_right", right_wrist_camera),
            )
            if device is not None
        },
    )
    return config


def make_vr_arm_ik(calibration: dict, *, mode: str = "legacy", mapping_dir: Path | None = None, **options):
    """Choose the complete arm mapping and tuning without connecting to hardware."""
    from .calibration.profile import DEFAULT_MAPPING_DIR, ArmMapping

    if mode not in {"legacy", "calibrated"}:
        raise ValueError(f"Unknown arm IK mode: {mode}")
    mapping = ArmMapping.load(mapping_dir if mapping_dir is not None else DEFAULT_MAPPING_DIR, calibration)
    # CLI omissions defer to each mode's defaults, rather than mixing two profiles.
    options = {name: value for name, value in options.items() if value is not None}
    if mode == "legacy":
        from .legacy_ik import make_legacy_ik

        return make_legacy_ik(mapping, **options)
    from .calibrated_ik import make_calibrated_ik

    return make_calibrated_ik(mapping, **options)


class VRGateway:
    def __init__(self, robot: RobotLike, config: VRGatewayConfig | None = None, arm_ik: ArmIK | None = None):
        self.robot = robot
        self.config = config or VRGatewayConfig()
        self.arm_ik = arm_ik
        self.control_period_s: float | None = None
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
        self._mailbox_lock = threading.RLock()
        self.arm_sessions = ArmSessions()
        self._state_sampled_at: float | None = None
        self._measured_arm_positions: dict[str, float] = {}
        self._desired: dict[str, Any] = {}
        self._hold_reference: dict[str, float] = {}
        self._pending_alignment: dict[str, Any] | None = None
        self._pending_settings: dict[str, float] = {}
        self._torque = dict.fromkeys(SIDES, "unknown")
        self._torque_sampled_at = 0.0
        self._watchdog_stopped = False

    @property
    def clutch_enabled(self) -> bool:
        """Backwards-compatible alias for the arm freeze flag."""
        return self.arm_frozen

    @staticmethod
    def _format_axis(value: float) -> str:
        """Format a controller axis for concise, readable operator logs."""
        return f"{value:+.3f}"

    def _state(self) -> dict[str, Any]:
        state = dict(self._last_state or getattr(self.robot, "last_remote_state", {}) or {})
        if self._state_sampled_at is not None:
            state["_vr_state_sampled_at"] = self._state_sampled_at
        return state

    def _feedback_fresh(self) -> bool:
        return self._state_sampled_at is not None and (
            0.0 <= time.monotonic() - self._state_sampled_at <= self.config.max_feedback_age_s
        )

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
        action.update(self._hold_reference)
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

    def _reset_arm_targets(self, sides=SIDES) -> dict[str, float]:
        """Latch a measured hold once per release, independently for each arm."""
        hold = {}
        state = {
            **self._measured_arm_positions,
            **{
                key: value
                for key, value in self._state().items()
                if isinstance(value, (int, float, np.number)) and np.isfinite(float(value))
            },
        }
        for side in sides:
            for key, value in state.items():
                if (
                    key.startswith(f"arm_{side}_")
                    and key.endswith(".pos")
                    and "gripper" not in key
                    and isinstance(value, (int, float, np.number))
                    and np.isfinite(float(value))
                ):
                    hold[key] = float(value)
                    self._desired.pop(key, None)
        # Even if feedback has expired, this last measured position is closer to
        # rest than a leading target. Never continuously reseed on base heartbeats.
        self._hold_reference.update(hold)
        return hold

    def _limit_joint_steps(self, updates: dict[str, float]) -> dict[str, float]:
        """Bound each joint step from the last driver-accepted target.

        The hardware driver additionally bounds target lead from measured joints.
        """
        limit = self.config.max_joint_step_deg
        if limit <= 0:
            return updates
        state = self._state()
        limited = dict(updates)
        for key, value in updates.items():
            if not key.endswith(".pos"):
                continue
            reference = self._hold_reference.get(key, self._commanded.get(key, state.get(key)))
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
        self._desired.update(updates)
        updates = self._limit_joint_steps(updates)
        action = self._held_action()
        action.update(updates)
        if LIFT_HEIGHT_KEY in updates:
            action.pop(LIFT_VELOCITY_KEY, None)
        elif LIFT_VELOCITY_KEY in updates:
            action.pop(LIFT_HEIGHT_KEY, None)
        if self.estopped:
            action.update(dict.fromkeys(BASE_VELOCITY_KEYS, 0.0))
            action[LIFT_VELOCITY_KEY] = 0.0
            action.pop(LIFT_HEIGHT_KEY, None)
        if _diagnostics_enabled():
            arm_action = {
                key: value
                for key, value in sorted(action.items())
                if key.startswith("arm_") and key.endswith(".pos")
            }
            logger.info(
                "[VR-DIAG] sent_action arm_joints=%s lift=%s base=%s",
                arm_action,
                action.get(LIFT_VELOCITY_KEY),
                {key: action.get(key) for key in BASE_VELOCITY_KEYS},
            )
        result = self.robot.send_action(action)
        self._remember(result)
        for key in result:
            self._hold_reference.pop(key, None)
        if self.arm_ik is not None and hasattr(self.arm_ik, "accept_action"):
            self.arm_ik.accept_action(result)
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
        self.arm_sessions.stop("paused")

    def _arm_motion_active(self) -> bool:
        """Return whether an arm clutch is active or queued for the next flush."""
        if self._pending_arm is not None and bool(self._pending_arm.get("active")):
            return True
        return bool(getattr(self.arm_ik, "active", False))

    def stage_message(self, message: dict[str, Any]) -> dict[str, Any]:
        with self._mailbox_lock:
            return self._stage_message(message)

    def _stage_message(self, message: dict[str, Any]) -> dict[str, Any]:
        """Validate one protocol message and fold it into the pending command state.

        Performs no robot I/O; :meth:`flush` applies the result.  Later messages of the
        same kind overwrite earlier ones, so a backlog collapses to its newest entry.
        """
        kind = str(message.get("type", "")).lower()
        self.last_message_at = time.monotonic()
        self._watchdog_stopped = False

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
                self.arm_sessions.stop("estop")
            self._pending_updates.update(dict.fromkeys(BASE_VELOCITY_KEYS, 0.0))
            return {"type": "ack", "for": "estop", "enabled": self.estopped}

        if kind in {"base", "drive"}:
            if self.estopped:
                return {"type": "ack", "for": "base", "ignored": "estop"}
            if self._arm_motion_active():
                self._stage_updates(dict.fromkeys(BASE_VELOCITY_KEYS, 0.0))
                return {"type": "ack", "for": "base", "ignored": "arm_clutch"}
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
            if self._arm_motion_active():
                self._stage_updates({LIFT_VELOCITY_KEY: 0.0})
                return {"type": "ack", "for": "lift", "ignored": "arm_clutch"}
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
            if not np.isfinite(value):
                raise ValueError("gripper value must be finite")
            side = message.get("side")
            if side is not None:
                if side not in SIDES:
                    raise ValueError("gripper side must be left or right")
                if self.arm_frozen or not self._feedback_fresh():
                    return {"type": "ack", "for": "gripper", "ignored": "paused_or_stale_feedback"}
                age = self._pose_age_s(message)
                if age is not None and age > self.config.max_pose_age_s:
                    self._pending_updates.pop(f"arm_{side}_gripper.pos", None)
                    return {"type": "ack", "for": "gripper", "status": "stale"}
                mapping = getattr(self.arm_ik, "arm_mapping", None)
                closure = float(np.clip(value, 0.0, 1.0))
                if getattr(self.arm_ik, "mode", "legacy") == "legacy":
                    # Grippers remain RANGE_0_100 even with arm use_degrees=True.
                    # On both installed hands increasing encoder position opens;
                    # this uses existing motor calibration, not a Home mapping.
                    if f"arm_{side}_gripper.pos" not in self._state():
                        return {"type": "ack", "for": "gripper", "status": "unbound"}
                    target = 100.0 * (1.0 - closure)
                else:
                    if mapping is None:
                        return {"type": "ack", "for": "gripper", "status": "unbound"}
                    entry = mapping.mappings[side]["joints"]["gripper"]
                    meta = mapping.metadata["motors"][f"arm_{side}_gripper"]
                    tick = entry["open_tick"] + closure * (entry["closed_tick"] - entry["open_tick"])
                    target = 100.0 * (tick - meta["range_min"]) / (meta["range_max"] - meta["range_min"])
                self._stage_updates({f"arm_{side}_gripper.pos": float(np.clip(target, 0.0, 100.0))})
                return {"type": "ack", "for": "gripper", "status": "staged"}
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
            active = any(bool(message.get(f"{side}_active", message.get("active"))) for side in SIDES)
            age = self._pose_age_s(message) if active else None
            if active and age is not None and age > self.config.max_pose_age_s:
                self.arm_sessions.stop("stale_pose")
                self._pending_arm = None
                self.stats.poses_stale += 1
                self._warn(
                    "stale_pose",
                    "[VR] dropping arm pose delayed by %.0f ms (limit %.0f ms); %d dropped so far",
                    age * 1e3,
                    self.config.max_pose_age_s * 1e3,
                    self.stats.poses_stale,
                )
                return {"type": "ack", "for": "arm", "status": "stale"}
            # Latch heading once per shared clutch session, before coalescing
            # poses. A joining/re-gripping hand inherits it while either hand
            # remains active. Legacy clients without auto_align keep Y behavior.
            auto_head = None
            if message.get("auto_align") and active and not any(self.arm_sessions.requested.values()):
                from .arm_ik import pose_to_matrix
                from .coordinates import aligned_xr_basis

                pose = pose_to_matrix(message.get("head"))
                try:
                    if pose is None:
                        raise ValueError("missing head pose")
                    aligned_xr_basis(pose[:3, :3])
                except ValueError:
                    return {
                        "type": "ack",
                        "for": "arm",
                        "status": "rejected",
                        "reason": "head_tracking_required",
                    }
                auto_head = message["head"]
            if self._pending_arm is not None:
                self.stats.messages_coalesced += 1
            self._pending_arm = self.arm_sessions.stage(message, time.monotonic())
            if auto_head is not None and self._pending_arm["active"]:
                self._pending_alignment = auto_head
                self.arm_sessions.reset_sides.update(SIDES)
            # The browser sends base/lift and arm packets in the same frame. If
            # this arm packet engages a clutch, cancel any velocity staged just
            # before it so the first arm tick is stationary too.
            if self._pending_arm["active"]:
                self._pending_updates.update(dict.fromkeys(BASE_VELOCITY_KEYS, 0.0))
                self._pending_updates[LIFT_VELOCITY_KEY] = 0.0
            return {
                "type": "ack",
                "for": "arm",
                "status": "staged",
                "reanchor": bool(message.get("reanchor")),
            }

        if kind == "arm_settings":
            if self.arm_ik is None:
                return {"type": "ack", "for": kind, "status": "ik_unavailable"}
            settings = {}
            for name, lo, hi in (("position_scale", 0.1, 2.0), ("max_joint_speed_deg_s", 5.0, 90.0)):
                if name in message:
                    value = float(message[name])
                    if not np.isfinite(value) or not lo <= value <= hi:
                        raise ValueError(f"{name} must be between {lo} and {hi}")
                    settings[name] = value
            self._pending_settings.update(settings)
            self.arm_sessions.reset_sides.update(SIDES)
            return {"type": "ack", "for": kind, "status": "staged"}

        if kind in {"reanchor", "align"}:
            if self.arm_ik is None:
                return {"type": "ack", "for": "reanchor", "status": "ik_unavailable"}
            if self.estopped:
                return {"type": "ack", "for": "reanchor", "ignored": "estop"}
            if kind == "align":
                from .arm_ik import pose_to_matrix
                from .coordinates import aligned_xr_basis

                pose = pose_to_matrix(message.get("head"))
                if pose is None:
                    raise ValueError("alignment requires a current head pose")
                aligned_xr_basis(pose[:3, :3])
                age = self._pose_age_s(message)
                if age is not None and age > self.config.max_pose_age_s:
                    return {"type": "ack", "for": kind, "status": "stale"}
                self._pending_alignment = message["head"]
                self.arm_sessions.reset_sides.update(SIDES)
                return {"type": "ack", "for": kind, "status": "staged"}
            if not message.get("left") and not message.get("right"):
                self.arm_sessions.reset_sides.update(SIDES)
                return {"type": "ack", "for": kind, "status": "staged"}
            left = message.get("left") or message.get("left_pose")
            right = message.get("right") or message.get("right_pose")
            if not left and not right:
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
                "left_active": bool(left),
                "right_active": bool(right),
            }
            if "client_time_ms" in message:
                active["client_time_ms"] = message["client_time_ms"]
            if self._pending_arm is not None:
                self.stats.messages_coalesced += 1
            self._pending_arm = self.arm_sessions.stage(active, time.monotonic())
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
        if payload.get("active") and not self._feedback_fresh():
            self._last_arm_status = "rejected:stale_feedback"
            with self._mailbox_lock:
                self.arm_sessions.stop("stale_feedback")
            return self._release_arms(SIDES)
        previous = set(getattr(self.arm_ik, "active_sides", ()))
        if _diagnostics_enabled():
            fact_joints = {
                key: state[key] for key in sorted(state) if key.startswith("arm_") and key.endswith(".pos")
            }
            logger.info(
                "[VR-DIAG] gateway_arm_payload active=%s left_active=%s right_active=%s "
                "left=%s right=%s fact_joints=%s lift_height_mm=%s",
                bool(payload.get("active")),
                bool(payload.get("left_active", payload.get("active"))),
                bool(payload.get("right_active", payload.get("active"))),
                payload.get("left"),
                payload.get("right"),
                fact_joints,
                state.get(LIFT_HEIGHT_KEY),
            )
        try:
            if hasattr(self.arm_ik, "update"):
                updates = self.arm_ik.update(payload, state)
            else:
                updates = self.arm_ik.pose_to_action(payload, state)
        except Exception:
            self.stats.ik_rejected += 1
            self._last_arm_status = "ik_error"
            logger.exception("[VR] arm IK raised; pose discarded")
            with self._mailbox_lock:
                self.arm_sessions.stop("ik_error")
            return self._release_arms(SIDES)
        released = previous - set(getattr(self.arm_ik, "active_sides", previous))
        hold = self._reset_arm_targets(released)
        if updates:
            self.stats.ik_applied += 1
            self._last_arm_status = "reanchored" if payload.get("reanchor") else "applied"
            return {**hold, **updates}
        # An empty result while the operator is squeezing both grips means the IK
        # rejected the pose; without this the arm just silently stops tracking.
        if payload.get("active"):
            self.stats.ik_rejected += 1
            reason = getattr(self.arm_ik, "engage_reason", None) or "no_joint_targets"
            if reason.startswith(
                ("missing_state", "invalid_state", "invalid_calibrated_state", "stale_feedback")
            ):
                with self._mailbox_lock:
                    self.arm_sessions.stop("stale_feedback")
                hold.update(self._release_arms(SIDES))
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
        return hold

    def _release_arms(self, sides) -> dict[str, float]:
        if not sides:
            return {}
        if self.arm_ik is not None:
            if hasattr(self.arm_ik, "release"):
                self.arm_ik.release(sides)
            elif hasattr(self.arm_ik, "update"):
                self.arm_ik.update({"active": False}, self._state())
        return self._reset_arm_targets(sides)

    def flush(self) -> bool:
        """Apply the newest staged command state as a single ``send_action``.

        Returns ``True`` when an action was sent.
        """
        with self._mailbox_lock:
            expired = self.arm_sessions.expired(time.monotonic(), self.config.arm_pose_timeout_s)
            if not self._feedback_fresh():
                expired.update(side for side in SIDES if self.arm_sessions.requested[side])
            if expired:
                self.arm_sessions.stop("input_or_feedback_timeout", expired)
                if self._pending_arm:
                    for side in expired:
                        self._pending_arm[f"{side}_active"] = False
                    self._pending_arm["active"] = any(
                        self._pending_arm.get(f"{side}_active") for side in SIDES
                    )
            updates, self._pending_updates = self._pending_updates, {}
            arm_payload, self._pending_arm = self._pending_arm, None
            resets = self.arm_sessions.take_resets()
            alignment, self._pending_alignment = self._pending_alignment, None
            settings, self._pending_settings = self._pending_settings, {}
        updates.update(self._release_arms(resets))
        if alignment is not None and hasattr(self.arm_ik, "align"):
            self.arm_ik.align(alignment)
        for name, value in settings.items():
            setattr(self.arm_ik, name, value)
        self._last_arm_status = None
        if arm_payload is not None:
            updates.update(self._arm_updates(arm_payload))
        if self.estopped or self.arm_frozen or not self._feedback_fresh():
            updates = {key: value for key, value in updates.items() if "gripper" not in key}
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

        Base/lift handling retains the existing behavior. Arm sessions are reset;
        renewed traffic must release and re-grip before following can resume.
        """
        if time.monotonic() - self.last_message_at <= self.config.watchdog_timeout_s:
            return False
        if self._watchdog_stopped:
            return False
        self._watchdog_stopped = True
        self.last_message_at = time.monotonic()
        had_arms = self._arm_motion_active()
        if had_arms:
            self.reset_connection("watchdog")
        hold = self._release_arms(SIDES) if had_arms else {}
        if not hold and all(abs(float(self._commanded.get(key, 0.0))) <= 1e-6 for key in BASE_VELOCITY_KEYS):
            return False
        logger.warning(
            "[VR] watchdog: no browser traffic for %.1fs, stopping base", self.config.watchdog_timeout_s
        )
        self._send({**hold, **dict.fromkeys(BASE_VELOCITY_KEYS, 0.0)}, mark_activity=False)
        return True

    def reset_connection(self, reason: str = "disconnected") -> None:
        with self._mailbox_lock:
            self._pending_arm = None
            self._pending_updates.clear()
            self._pending_alignment = None
            self._pending_settings.clear()
            self._clock_offset_s = None
            self.arm_sessions.stop(reason)

    def disconnect_client(self) -> None:
        self.reset_connection()
        self._send(
            {**self._release_arms(SIDES), **dict.fromkeys(BASE_VELOCITY_KEYS, 0.0)}, mark_activity=False
        )

    # -------------------------------------------------------------- observation

    def capture_observation(self) -> dict[str, Any]:
        """Read the robot.  Must run under the robot lock; does no encoding."""
        started_at = time.monotonic()
        observation = self.robot.get_observation(include_cameras=False)
        # Timestamp acquisition start, not the end of camera retrieval/encoding.
        timing = observation.get("_host_timing", {})
        self._state_sampled_at = float(timing.get("state_sample_started_monotonic_s", started_at))
        self._last_state = {k: v for k, v in observation.items() if not isinstance(v, np.ndarray)}
        self._measured_arm_positions.update(
            {
                key: float(value)
                for key, value in self._last_state.items()
                if key.startswith("arm_")
                and key.endswith(".pos")
                and isinstance(value, (int, float, np.number))
                and np.isfinite(float(value))
            }
        )
        with contextlib.suppress(Exception):
            # Some robot implementations expose this as a read-only property.
            self.robot.last_remote_state = self._last_state
        if time.monotonic() - self._torque_sampled_at > 2.0:
            self._torque_sampled_at = time.monotonic()
            for side in SIDES:
                bus = getattr(self.robot, f"{side}_bus", None)
                motors = getattr(self.robot, f"{side}_arm_motors", None)
                self._torque[side] = "unknown"
                if bus is not None and motors:
                    try:
                        values = bus.sync_read("Torque_Enable", motors, normalize=False)
                        if values and set(values) == set(motors):
                            enabled = [bool(value) for value in values.values()]
                            self._torque[side] = (
                                "enabled" if all(enabled) else ("disabled" if not any(enabled) else "mixed")
                            )
                    except Exception:
                        self._warn("torque_read", "[VR] torque readback unavailable")
        return observation

    def capture_camera_frames(self) -> dict[str, Any]:
        """Peek each enabled camera outside the robot lock; isolate missing/stale feeds."""
        frames = {}
        cameras = getattr(self.robot, "cameras", {})
        for name in self.config.camera_names:
            try:
                frames[name] = cameras[name].read_latest(max_age_ms=500)
            except Exception as exc:
                self._warn(f"camera_{name}", "[VR] camera %s unavailable: %s", name, exc)
        return frames

    def encode_payload(self, observation: dict[str, Any], *, include_frame: bool = True) -> dict[str, Any]:
        """Serialise an observation for the browser.  Safe to run outside the robot lock.

        JPEG encoding plus base64 costs tens of milliseconds on a Pi 5; keeping it off the
        lock stops it from delaying inbound control messages.
        """
        payload: dict[str, Any] = {
            "type": "observation",
            "cameras": list(self.config.camera_names),
            "state": {k: _json_safe(v) for k, v in observation.items() if not isinstance(v, np.ndarray)},
            "frames": {},
        }
        if not include_frame:
            return payload
        for name in self.config.camera_names:
            frame = observation.get(name)
            if not isinstance(frame, np.ndarray):
                continue
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
                    payload["frames"][name] = {
                        "jpeg_b64": base64.b64encode(encoded.tobytes()).decode("ascii"),
                        "video_width": frame.shape[1],
                        "video_height": frame.shape[0],
                    }
            except Exception:  # pragma: no cover - camera/codec is platform specific
                self._warn(f"encode_{name}", "[VR] failed to encode camera %s", name)
        return payload

    def observation_payload(self) -> dict[str, Any]:
        """Read the robot and serialise it in one step (used by tests and simple callers)."""
        return self.encode_payload({**self.capture_observation(), **self.capture_camera_frames()})

    def status_payload(self) -> dict[str, Any]:
        """Operator-visible gateway health, sent periodically instead of per-message acks."""
        timings = getattr(self.robot, "logs", {}) or {}
        limit_reader = getattr(self.arm_ik, "joint_limit_warnings", None)
        limit_warnings = limit_reader(self._state()) if limit_reader and self._feedback_fresh() else []
        return {
            "type": "status",
            "joint_limit_warnings": limit_warnings,
            "robot_connected": bool(getattr(self.robot, "is_connected", False)),
            "feedback_fresh": self._feedback_fresh(),
            "feedback_age_ms": None
            if self._state_sampled_at is None
            else round((time.monotonic() - self._state_sampled_at) * 1000.0, 1),
            "arms": {
                side: {
                    "connected": bool(
                        getattr(getattr(self.robot, f"{side}_bus", None), "is_connected", False)
                    ),
                    "torque": self._torque[side]
                    if time.monotonic() - self._torque_sampled_at < 3.0
                    else "unknown",
                    "state": "following"
                    if side in getattr(self.arm_ik, "active_sides", ())
                    and self._feedback_fresh()
                    and not self.arm_sessions.blocked[side]
                    else "hold",
                    "reason": self.arm_sessions.blocked[side],
                }
                for side in SIDES
            },
            "arm_settings": {
                "position_scale": getattr(self.arm_ik, "position_scale", None),
                "max_joint_speed_deg_s": getattr(self.arm_ik, "max_joint_speed_deg_s", None),
            },
            "tcp_frames": getattr(self.arm_ik, "tip_frames", {}),
            "ik_retry_attempts": getattr(self.arm_ik, "retry_attempts", 0),
            "ik_retry_accepted": getattr(self.arm_ik, "retry_accepted", 0),
            "control_hz_actual": round(1.0 / self.control_period_s, 1)
            if self.control_period_s is not None and self.control_period_s > 0
            else None,
            "estop": self.estopped,
            "arm_frozen": self.arm_frozen,
            "calibrated": self.calibrated,
            "arm_mapping_loaded": getattr(self.arm_ik, "arm_mapping", None) is not None,
            "arm_ik_mode": getattr(self.arm_ik, "mode", "legacy"),
            "ik_available": self.arm_ik is not None,
            "arm_ik_active": bool(getattr(self.arm_ik, "active", False)),
            "arm_active_sides": sorted(getattr(self.arm_ik, "active_sides", ())),
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


async def run_control_loop(gateway: VRGateway, robot_io) -> None:
    """Service the latest command and watchdog once per control period."""
    interval = 1.0 / max(gateway.config.control_hz, 1.0)
    previous = None
    while True:
        started = time.monotonic()
        if previous is not None:
            gateway.control_period_s = started - previous
        previous = started
        await robot_io(gateway.flush)
        await robot_io(gateway.watchdog)
        # Serial I/O and IK consume this period. Do not add a second full
        # interval after them or build a backlog of catch-up ticks after a stall.
        await asyncio.sleep(max(0.0, interval - (time.monotonic() - started)))


def create_app(robot: RobotLike, config: VRGatewayConfig | None = None, arm_ik: ArmIK | None = None):
    try:
        from fastapi import FastAPI, WebSocket, WebSocketDisconnect
        from fastapi.responses import HTMLResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("Install the 'vr' extra to run the VR gateway") from exc

    gateway = VRGateway(robot, config, arm_ik)

    @contextlib.asynccontextmanager
    async def lifespan(app):
        # Hardware connection/configuration (including lift setup) happens once
        # at gateway startup, never as a side effect of opening/reloading the UI.
        if not getattr(robot, "is_connected", False):
            await asyncio.to_thread(robot.connect)
        yield

    app = FastAPI(title="LeRobot AlohaMini VR Gateway", lifespan=lifespan)
    client_lock = asyncio.Lock()

    async def robot_io(function):
        async with gateway._robot_lock:
            work = asyncio.create_task(asyncio.to_thread(function))
            try:
                return await asyncio.shield(work)
            except asyncio.CancelledError:
                # Cancelling to_thread doesn't stop serial I/O. Keep ownership
                # until it finishes, then send the disconnect hold afterwards.
                await work
                raise

    static_dir = Path(__file__).with_name("static")
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        return HTMLResponse(_INDEX_HTML, headers={"Cache-Control": "no-store"})

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "ok": True,
            "robot_connected": bool(getattr(robot, "is_connected", False)),
            "cameras": list(gateway.config.camera_names),
            **gateway.stats.as_dict(),
        }

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()
        if client_lock.locked():
            await websocket.send_json({"type": "error", "error": "Another operator is connected"})
            await websocket.close(code=1008)
            return
        await client_lock.acquire()
        try:
            gateway.reset_connection("new_connection")
            await robot_io(gateway.capture_observation)
            await websocket.send_json(
                {
                    "type": "hello",
                    "cameras": list(gateway.config.camera_names),
                    "protocol": 4,
                    "control_hz": gateway.config.control_hz,
                }
            )

            async def send_json(payload: dict[str, Any]) -> None:
                async with gateway._send_lock:
                    await websocket.send_json(payload)

            async def control_loop() -> None:
                await run_control_loop(gateway, robot_io)

            async def observation_loop() -> None:
                """Poll state and stream video without holding the lock during encoding."""
                interval = 1.0 / max(gateway.config.poll_hz, 1.0)
                frames_per_video = max(1, round(gateway.config.poll_hz / max(gateway.config.video_hz, 0.1)))
                tick = 0
                last_status = 0.0
                last_limits = None
                while True:
                    started_at = time.monotonic()
                    observation = await robot_io(gateway.capture_observation)
                    include_frame = tick % frames_per_video == 0
                    if include_frame:
                        observation.update(await asyncio.to_thread(gateway.capture_camera_frames))
                    payload = await asyncio.to_thread(
                        gateway.encode_payload, observation, include_frame=include_frame
                    )
                    await send_json(payload)
                    now = time.monotonic()
                    status = gateway.status_payload()
                    if (
                        status["joint_limit_warnings"] != last_limits
                        or now - last_status >= gateway.config.status_period_s
                    ):
                        last_status = now
                        last_limits = status["joint_limit_warnings"]
                        await send_json(status)
                    tick += 1
                    await asyncio.sleep(max(0.0, interval - (time.monotonic() - started_at)))

            async def receive_loop():
                while True:
                    raw = await websocket.receive_text()
                    try:
                        # Staging is pure Python bookkeeping, so it runs inline on the
                        # event loop: no lock, no thread hop, no queueing behind the buses.
                        reply = gateway.stage_message(json.loads(raw))
                        if reply.get("for") in {"clutch", "estop", "align", "reanchor", "arm_settings"}:
                            await send_json(gateway.status_payload())
                    except (ValueError, TypeError, json.JSONDecodeError) as exc:
                        reply = {"type": "error", "error": str(exc)}
                    if _should_reply(reply):
                        await send_json(reply)

            tasks = [asyncio.create_task(loop()) for loop in (control_loop, observation_loop, receive_loop)]
            try:
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        except WebSocketDisconnect:
            logger.info("Quest WebSocket disconnected")
        finally:
            try:
                await robot_io(gateway.disconnect_client)
            except Exception:
                logger.exception("failed to stop robot on WebSocket disconnect")
            finally:
                client_lock.release()

    return app


def _should_reply(reply: dict[str, Any]) -> bool:
    """Suppress per-message acks for the high-rate streams; keep anything informative."""
    if reply.get("type") != "ack":
        return True
    if reply.get("for") not in QUIET_ACK_TYPES:
        return True
    return "ignored" in reply or reply.get("status") in {
        "rejected",
        "stale",
        "ik_error",
        "ik_unavailable",
        "unbound",
    }


_STATIC_INDEX = Path(__file__).with_name("static") / "index.html"
try:
    _INDEX_HTML = _STATIC_INDEX.read_text(encoding="utf-8")
except OSError:
    _INDEX_HTML = "<!doctype html><meta charset='utf-8'><title>AlohaMini VR</title><p>VR frontend assets unavailable.</p>"


def main() -> None:  # pragma: no cover - CLI convenience
    import argparse
    from dataclasses import asdict

    import uvicorn

    parser = argparse.ArgumentParser(description="Serve AlohaMini VR teleoperation over WebSocket")
    parser.add_argument(
        "--diagnostics",
        nargs="?",
        const=True,
        default=False,
        type=_parse_bool,
        help="print controller, measured-joint, FK, IK, and sent-action diagnostics (true/false)",
    )
    parser.add_argument(
        "--robot-model", default="alohamini2pro", choices=["alohamini1", "alohamini2", "alohamini2pro"]
    )
    parser.add_argument("--left-port", default="/dev/am_arm_follower_left")
    parser.add_argument("--right-port", default="/dev/am_arm_follower_right")
    for option, device in (
        ("head-camera", "/dev/am_camera_forward"),
        ("left-wrist-camera", "/dev/am_camera_wrist_left"),
        ("right-wrist-camera", "/dev/am_camera_wrist_right"),
    ):
        parser.add_argument(
            f"--{option}",
            nargs="?",
            const=device,
            default=None,
            type=_parse_camera_device,
            metavar="DEVICE",
            help=f"enable camera (default device: {device}); omitted means disabled",
        )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--ws", choices=["auto", "websockets", "wsproto"], default="auto")
    parser.add_argument("--control-hz", type=float, default=VRGatewayConfig.control_hz)
    parser.add_argument("--poll-hz", type=float, default=VRGatewayConfig.poll_hz)
    parser.add_argument("--video-hz", type=float, default=VRGatewayConfig.video_hz)
    parser.add_argument("--jpeg-quality", type=int, default=VRGatewayConfig.jpeg_quality)
    parser.add_argument("--max-frame-width", type=int, default=VRGatewayConfig.max_frame_width)
    parser.add_argument("--max-pose-age-s", type=float, default=VRGatewayConfig.max_pose_age_s)
    parser.add_argument(
        "--arm-ik-mode",
        choices=["legacy", "calibrated"],
        default="legacy",
        help="legacy: original CAD gestures; calibrated: standard base/TCP; both require captured Home",
    )
    parser.add_argument(
        "--position-scale", type=float, default=None, help="legacy default 0.5; calibrated 1.0"
    )
    parser.add_argument("--max-joint-speed-deg-s", type=float, default=90.0)
    parser.add_argument(
        "--arm-goal-velocity", type=int, default=None, help="native units: legacy 2000; calibrated 100"
    )
    parser.add_argument("--arm-acceleration", type=int, default=VR_ARM_ACCELERATION)
    parser.add_argument(
        "--max-relative-target-deg",
        type=float,
        default=None,
        help="driver joint lead limit in degrees; legacy disabled; calibrated 5",
    )
    parser.add_argument(
        "--max-target-position-lead-mm",
        type=float,
        default=None,
        help="TCP position lead limit in mm; legacy disabled; calibrated 25",
    )
    parser.add_argument(
        "--max-target-orientation-lead-deg",
        type=float,
        default=None,
        help="TCP orientation lead limit in degrees; legacy disabled; calibrated 15",
    )
    parser.add_argument(
        "--arm-mapping-dir",
        type=Path,
        default=None,
        help="Home mapping for either mode; defaults to ~/.config/lerobot/alohamini/arm_mapping",
    )
    args = parser.parse_args()
    os.environ["LEROBOT_VR_DIAGNOSTICS"] = "1" if args.diagnostics else "0"
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from lerobot.robots.alohamini.alohamini import AlohaMini

    if args.robot_model != "alohamini2pro":
        parser.error("VR arm IK currently requires --robot-model alohamini2pro")
    robot_config = make_vr_robot_config(
        robot_model=args.robot_model,
        left_port=args.left_port,
        right_port=args.right_port,
        arm_ik_mode=args.arm_ik_mode,
        arm_goal_velocity=args.arm_goal_velocity,
        arm_acceleration=args.arm_acceleration,
        max_relative_target=args.max_relative_target_deg,
        head_camera=args.head_camera,
        left_wrist_camera=args.left_wrist_camera,
        right_wrist_camera=args.right_wrist_camera,
    )
    robot = AlohaMini(robot_config)
    arm_ik = make_vr_arm_ik(
        {name: asdict(value) for name, value in robot.calibration.items()},
        mode=args.arm_ik_mode,
        mapping_dir=args.arm_mapping_dir,
        smooth=1.0,
        position_scale=args.position_scale,
        max_joint_speed_deg_s=args.max_joint_speed_deg_s,
        state_blend=0.1,
        max_target_position_lead_m=None
        if args.max_target_position_lead_mm is None
        else args.max_target_position_lead_mm / 1000.0,
        max_target_orientation_lead_rad=None
        if args.max_target_orientation_lead_deg is None
        else np.deg2rad(args.max_target_orientation_lead_deg),
    )
    logger.info(
        "VR arm mode=%s position_scale=%s Goal_Velocity=%s max_relative_target=%s tcp=%s",
        args.arm_ik_mode,
        arm_ik.position_scale,
        robot_config.arm_goal_velocity,
        robot_config.max_relative_target,
        arm_ik.tip_frames,
    )
    gateway_config = VRGatewayConfig(
        camera_names=tuple(robot_config.cameras),
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
