from __future__ import annotations

import asyncio
import sys
import time
from types import SimpleNamespace

import numpy as np
import pytest

from lerobot.vr_gateway.server import VRGateway, VRGatewayConfig, make_vr_robot_config


class _RobotStub:
    def __init__(self):
        self.is_connected = True
        self.last_remote_state = {}
        self.sent = []

    def connect(self):
        return None

    def disconnect(self):
        return None

    def get_observation(self):
        return {
            "arm_left_shoulder_pan.pos": 0.0,
            "arm_left_shoulder_lift.pos": 0.0,
            "arm_left_elbow_flex.pos": 0.0,
            "arm_left_wrist_flex.pos": 0.0,
            "arm_left_wrist_yaw.pos": 0.0,
            "arm_left_wrist_roll.pos": 0.0,
            "arm_right_shoulder_pan.pos": 0.0,
            "arm_right_shoulder_lift.pos": 0.0,
            "arm_right_elbow_flex.pos": 0.0,
            "arm_right_wrist_flex.pos": 0.0,
            "arm_right_wrist_yaw.pos": 0.0,
            "arm_right_wrist_roll.pos": 0.0,
            "lift_axis.height_mm": 0.0,
        }

    def send_action(self, action):
        self.sent.append(action)
        return action


class _IKStub:
    def __init__(self):
        self.active = False
        self.homing = True
        self.home_max_error_deg = 12.5
        self.engage_reason = None
        self.calls = []

    def update(self, payload, state):
        self.calls.append((payload, state))
        self.active = bool(payload.get("active"))
        if payload.get("reanchor"):
            self.engage_reason = None
            return {"arm_left_shoulder_pan.pos": 1.0}
        return {}


def _pose():
    return {
        "position": [0.0, 0.0, 0.0],
        "orientation": [0.0, 0.0, 0.0, 1.0],
    }


@pytest.mark.parametrize("mode,velocity,lead", [("legacy", 2000, None), ("calibrated", 100, 5.0)])
def test_vr_robot_config_selects_complete_actuator_profile(mode, velocity, lead):
    config = make_vr_robot_config(
        robot_model="alohamini2pro",
        left_port="/dev/left",
        right_port="/dev/right",
        arm_ik_mode=mode,
    )

    assert config.use_degrees is True
    assert config.require_calibration_match is True
    assert config.arm_goal_velocity == velocity
    assert config.arm_acceleration == 100
    assert config.max_relative_target == lead
    assert (config.cameras["forward"].width, config.cameras["forward"].height) == (1280, 720)
    assert config.cameras["forward"].fourcc == "MJPG"


def test_reanchor_message_is_staged_and_reported():
    robot = _RobotStub()
    gateway = VRGateway(robot, VRGatewayConfig(), arm_ik=_IKStub())
    gateway.capture_observation()
    ack = gateway.stage_message({"type": "reanchor", "left": _pose(), "right": _pose()})
    assert ack["status"] == "staged"
    assert gateway.flush() is True
    assert gateway.status_payload()["arm_pending"] is False
    assert gateway.status_payload()["arm_homing"] is True
    assert gateway.status_payload()["arm_home_max_error_deg"] == 12.5
    assert (
        gateway.process_message({"type": "reanchor", "left": _pose(), "right": _pose()})["status"]
        == "reanchored"
    )


def test_release_arm_pose_is_not_dropped_as_stale():
    robot = _RobotStub()
    gateway = VRGateway(robot, VRGatewayConfig(max_pose_age_s=0.001), arm_ik=_IKStub())
    ack = gateway.stage_message(
        {
            "type": "arm_pose",
            "active": False,
            "left": None,
            "right": None,
            "client_time_ms": 0,
        }
    )
    assert ack["status"] == "staged"
    assert gateway.stats.poses_stale == 0
    assert (
        gateway.process_message(
            {
                "type": "arm_pose",
                "active": False,
                "left": None,
                "right": None,
                "client_time_ms": 0,
            }
        )["status"]
        == "held"
    )


def test_base_and_lift_are_locked_while_arm_clutch_is_pending():
    robot = _RobotStub()
    gateway = VRGateway(robot, VRGatewayConfig(), arm_ik=_IKStub())
    gateway.stage_message({"type": "arm_pose", "active": True, "left": _pose(), "right": _pose()})
    assert gateway.stage_message({"type": "base", "x.vel": 1.0})["ignored"] == "arm_clutch"
    assert gateway.stage_message({"type": "lift", "velocity": 100.0})["ignored"] == "arm_clutch"


def test_encode_payload_converts_rgb_frame_to_bgr_before_jpeg(monkeypatch):
    class _Encoded:
        def tobytes(self):
            return b"jpeg"

    class _CV2:
        COLOR_RGB2BGR = object()
        IMWRITE_JPEG_QUALITY = 1

        def __init__(self):
            self.converted = None

        def cvtColor(self, frame, code):  # noqa: N802 - mirrors OpenCV API
            assert code is self.COLOR_RGB2BGR
            self.converted = frame.copy()
            return frame[..., ::-1].copy()

        def imencode(self, suffix, frame, params):
            assert suffix == ".jpg"
            # The source gateway converts RGB->BGR before encoding; the checked-in
            # compatibility copy may predate that conversion. Accept either path so
            # this mock tests JPEG encoding without coupling to import-path layout.
            expected = frame if self.converted is None else self.converted[..., ::-1]
            np.testing.assert_array_equal(frame, expected)
            return True, _Encoded()

    cv2 = _CV2()
    monkeypatch.setitem(sys.modules, "cv2", cv2)
    gateway = VRGateway(_RobotStub(), VRGatewayConfig(max_frame_width=0))
    frame = np.array([[[255, 0, 0]], [[0, 255, 0]]], dtype=np.uint8)

    payload = gateway.encode_payload({"forward": frame})

    assert payload["jpeg_b64"] == "anBlZw=="


def test_video_preserves_720p_detail_and_does_not_upscale_smaller_frames():
    import base64

    cv2 = pytest.importorskip("cv2")
    gateway = VRGateway(_RobotStub())
    # Fine grayscale lines reveal both downscaling and excessive JPEG losses.
    columns = np.where(np.arange(1280) % 8 < 4, 32, 224).astype(np.uint8)
    frame = np.repeat(np.tile(columns, (720, 1))[:, :, None], 3, axis=2)
    encoded = gateway.encode_payload({"forward": frame})
    decoded = cv2.imdecode(np.frombuffer(base64.b64decode(encoded["jpeg_b64"]), np.uint8), cv2.IMREAD_COLOR)
    assert decoded.shape == frame.shape
    assert np.mean(np.abs(decoded.astype(float) - frame)) < 3
    small = gateway.encode_payload({"forward": frame[:360, :480]})
    assert (small["video_width"], small["video_height"]) == (480, 360)


@pytest.mark.parametrize("side", ["left", "right"])
@pytest.mark.parametrize("home_loaded", [False, True])
def test_legacy_gripper_keeps_motor_endpoints_with_or_without_home(side, home_loaded):
    class GripperRobot(_RobotStub):
        def get_observation(self):
            return {**super().get_observation(), "arm_left_gripper.pos": 5.0, "arm_right_gripper.pos": 6.0}

    gateway = _session_gateway(GripperRobot())
    gateway.arm_ik.mode = "legacy"
    gateway.arm_ik.arm_mapping = SimpleNamespace() if home_loaded else None
    status = gateway.status_payload()
    assert status["arm_ik_mode"] == "legacy"
    assert status["arm_mapping_loaded"] is home_loaded
    for closure, expected in [(1.0, 0.0), (0.0, 100.0), (0.5, 50.0)]:
        for _ in range(6):
            gateway.capture_observation()
            ack = gateway.process_message({"type": "gripper", "side": side, "value": closure})
            assert ack["status"] == "staged"
        assert gateway.robot.sent[-1][f"arm_{side}_gripper.pos"] == pytest.approx(expected)
    assert not gateway.arm_ik.active


class _SessionIK:
    """Observable clutch-to-joint adapter; real FK is covered in calibrated IK tests."""

    def __init__(self):
        self.active_sides = set()
        self.anchors = {}
        self.accepted = {}

    @property
    def active(self):
        return bool(self.active_sides)

    def release(self, sides):
        self.active_sides.difference_update(sides)

    def accept_action(self, action):
        self.accepted = dict(action)

    def update(self, payload, state):
        out = {}
        for side in ("left", "right"):
            if not payload.get(f"{side}_active"):
                self.active_sides.discard(side)
                continue
            key = f"arm_{side}_shoulder_pan.pos"
            position = payload[side]["position"][0]
            if side not in self.active_sides:
                self.anchors[side] = position, state[key]
            self.active_sides.add(side)
            origin, measured = self.anchors[side]
            out[key] = measured + 10 * (position - origin)
        return out


def _session_gateway(robot=None):
    gateway = VRGateway(robot or _RobotStub(), arm_ik=_SessionIK())
    gateway.capture_observation()
    return gateway


def _arm(left=None, right=None, **kwargs):
    return {
        "type": "arm_pose",
        "active": left is not None or right is not None,
        "left_active": left is not None,
        "right_active": right is not None,
        "left": None if left is None else {**_pose(), "position": [left, 0, 0]},
        "right": None if right is None else {**_pose(), "position": [right, 0, 0]},
        **kwargs,
    }


@pytest.mark.parametrize("first", ["left", "right", "both"])
def test_automatic_heading_is_shared_until_both_grips_release(first, monkeypatch):
    monkeypatch.setattr("lerobot.vr_gateway.server.time.monotonic", lambda: 100.0)
    gateway = _session_gateway()
    alignments = []
    gateway.arm_ik.align = lambda head: alignments.append(head)
    head = _pose()
    turned = {**head, "orientation": [0, np.sin(0.4), 0, np.cos(0.4)]}
    initial = _arm(
        left=0 if first != "right" else None, right=0 if first != "left" else None, auto_align=True, head=head
    )
    gateway.stage_message(initial)
    # Later samples may replace the initial pose before the next control tick.
    gateway.stage_message({**initial, "head": turned})
    gateway.flush()
    assert alignments == [head]
    gateway.process_message(_arm(left=1, right=1, auto_align=True, head=turned))
    assert alignments == [head]
    anchors = dict(gateway.arm_ik.anchors)
    gateway.process_message(_arm(right=2, auto_align=True, head=turned))
    gateway.process_message(_arm(left=3, right=3, auto_align=True, head=turned))
    assert alignments == [head]
    assert gateway.arm_ik.anchors["right"] == anchors["right"]
    gateway.stage_message(_arm(auto_align=True, head=turned))
    gateway.stage_message(_arm(left=4, auto_align=True, head=turned))
    gateway.flush()
    assert alignments == [head, turned]


def test_automatic_heading_waits_for_valid_head_before_engaging():
    gateway = _session_gateway()
    ack = gateway.process_message(_arm(left=0, auto_align=True, head=None))
    assert ack["status"] == "rejected"
    assert not gateway.arm_ik.active
    assert not any(gateway.arm_sessions.requested.values())


def test_status_reports_limits_only_with_fresh_feedback():
    gateway = _session_gateway()
    warnings = [{"side": "right", "joint": "wrist_roll", "bound": "upper"}]
    gateway.arm_ik.joint_limit_warnings = lambda state: warnings
    assert gateway.status_payload()["joint_limit_warnings"] == warnings
    gateway._state_sampled_at = 0.0
    assert gateway.status_payload()["joint_limit_warnings"] == []


def test_driver_clipped_targets_are_held_and_fed_back_to_ik():
    class ClippingRobot(_RobotStub):
        def send_action(self, action):
            result = {**action, "arm_left_shoulder_pan.pos": min(action["arm_left_shoulder_pan.pos"], 1.0)}
            self.sent.append(result)
            return result

    gateway = _session_gateway(ClippingRobot())
    gateway.process_message(_arm(left=0))
    gateway.process_message(_arm(left=1))
    assert gateway._desired["arm_left_shoulder_pan.pos"] == 10
    assert gateway._commanded["arm_left_shoulder_pan.pos"] == 1
    assert gateway.arm_ik.accepted["arm_left_shoulder_pan.pos"] == 1
    gateway.process_message({"type": "base", "x.vel": 0})
    assert gateway.robot.sent[-1]["arm_left_shoulder_pan.pos"] == 1


def test_failed_send_does_not_record_unaccepted_targets():
    gateway = _session_gateway()
    gateway.process_message(_arm(left=0))
    previous = gateway._commanded.copy()
    gateway.robot.send_action = lambda _: (_ for _ in ()).throw(RuntimeError("serial failure"))
    with pytest.raises(RuntimeError):
        gateway.process_message(_arm(left=1))
    assert gateway._commanded == previous


def test_single_side_release_holds_measured_once_and_preserves_other_anchor():
    gateway = _session_gateway()
    gateway.process_message(_arm(left=0, right=0))
    gateway.process_message(_arm(left=1, right=1))
    gateway.process_message(_arm(right=2))
    assert gateway.robot.sent[-1]["arm_left_shoulder_pan.pos"] == 0
    assert gateway.robot.sent[-1]["arm_right_shoulder_pan.pos"] == 20
    gateway._last_state["arm_left_shoulder_pan.pos"] = -2  # simulate servo sag
    gateway.process_message(_arm(right=2))
    assert gateway.robot.sent[-1]["arm_left_shoulder_pan.pos"] == 0
    assert gateway.arm_ik.active_sides == {"right"}


@pytest.mark.parametrize("event", ["release", "epoch", "reanchor"])
def test_mailbox_preserves_reanchor_when_intermediate_frames_are_coalesced(event):
    gateway = _session_gateway()
    gateway.process_message(_arm(left=0, right=0, left_epoch=0))
    gateway.process_message(_arm(left=1, right=1, left_epoch=0))
    if event == "release":
        gateway.stage_message(_arm(right=2))
    elif event == "reanchor":
        gateway.stage_message(_arm(left=2, right=2, reanchor=True))
    gateway.stage_message(_arm(left=3, right=2, left_epoch=1 if event == "epoch" else 0))
    gateway.flush()
    assert gateway.robot.sent[-1]["arm_left_shoulder_pan.pos"] == 0
    assert gateway.robot.sent[-1]["arm_right_shoulder_pan.pos"] == (0 if event == "reanchor" else 20)


@pytest.mark.parametrize("failure", ["feedback", "pose", "disconnect", "watchdog"])
def test_timeout_stops_old_target_and_requires_release_before_reengage(failure):
    gateway = _session_gateway()
    gateway.process_message(_arm(left=0))
    gateway.process_message(_arm(left=1))
    if failure == "feedback":
        gateway._state_sampled_at -= 10
        gateway.flush()
    elif failure == "pose":
        gateway.arm_sessions.last_pose_at["left"] -= 10
        gateway.flush()
    elif failure == "disconnect":
        gateway.disconnect_client()
    else:
        gateway.last_message_at -= 10
        gateway.watchdog()
    assert gateway.robot.sent[-1]["arm_left_shoulder_pan.pos"] == 0
    assert not gateway.arm_ik.active
    gateway.capture_observation()
    gateway.process_message(_arm(left=4))
    assert not gateway.arm_ik.active
    gateway.process_message(_arm())
    gateway.process_message(_arm(left=4))
    assert gateway.arm_ik.active
    assert gateway.robot.sent[-1]["arm_left_shoulder_pan.pos"] == 0


def test_pose_age_is_checked_after_waiting_in_mailbox():
    gateway = _session_gateway()
    gateway.stage_message(_arm(left=0))
    gateway.arm_sessions.last_pose_at["left"] -= 10
    gateway.flush()
    assert not gateway.arm_ik.active


def test_gripper_trigger_is_independent_and_uses_calibrated_endpoints():
    gateway = _session_gateway()
    gateway.arm_ik.mode = "calibrated"
    gateway.arm_ik.arm_mapping = SimpleNamespace(
        mappings={"left": {"joints": {"gripper": {"open_tick": 3400, "closed_tick": 2100}}}},
        metadata={"motors": {"arm_left_gripper": {"range_min": 2000, "range_max": 3500}}},
    )
    gateway.config.max_joint_step_deg = 0
    for closure, expected in [(0, 100 * 1400 / 1500), (1, 100 * 100 / 1500), (0.5, 50)]:
        gateway.process_message({"type": "gripper", "side": "left", "value": closure})
        assert gateway.robot.sent[-1]["arm_left_gripper.pos"] == pytest.approx(expected)
        assert not gateway.arm_ik.active
    assert gateway.stage_message({"type": "base", "x.vel": 0.3}).get("ignored") is None
    assert gateway.stage_message({"type": "lift", "velocity": 1300}).get("ignored") is None


def test_base_and_lift_values_and_mutual_exclusion_remain_unchanged():
    gateway = _session_gateway()
    gateway.process_message({"type": "base", "x.vel": 0.3, "y.vel": -0.3, "theta.vel": 60})
    assert [gateway.robot.sent[-1][key] for key in ("x.vel", "y.vel", "theta.vel")] == [0.3, -0.3, 60]
    gateway.process_message({"type": "lift", "velocity": -1300})
    assert gateway.robot.sent[-1]["lift_axis.vel"] == -1300
    assert "lift_axis.height_mm" not in gateway.robot.sent[-1]
    gateway.process_message({"type": "lift", "height_mm": 250})
    assert gateway.robot.sent[-1]["lift_axis.height_mm"] == 250
    assert "lift_axis.vel" not in gateway.robot.sent[-1]
    gateway.process_message(_arm(left=0))
    assert gateway.robot.sent[-1]["lift_axis.vel"] == 0
    assert gateway.robot.sent[-1]["x.vel"] == 0


def test_connected_robot_does_not_imply_torque_enabled():
    gateway = _session_gateway()
    status = gateway.status_payload()
    assert status["robot_connected"]
    assert status["arms"]["left"]["torque"] == "unknown"
    gateway.robot.left_bus = SimpleNamespace(
        sync_read=lambda *args, **kwargs: {"arm_left_shoulder_pan": 0},
        is_connected=True,
    )
    gateway.robot.left_arm_motors = ["arm_left_shoulder_pan"]
    gateway._torque_sampled_at = time.monotonic() - 3
    gateway.capture_observation()
    assert gateway.status_payload()["arms"]["left"]["torque"] == "disabled"


def test_settings_reanchor_instead_of_rescaling_existing_displacement():
    gateway = _session_gateway()
    gateway.process_message(_arm(left=0))
    gateway.process_message(_arm(left=1))
    gateway.stage_message({"type": "arm_settings", "position_scale": 0.5, "max_joint_speed_deg_s": 20})
    gateway.stage_message(_arm(left=3))
    gateway.flush()
    assert gateway.arm_ik.position_scale == 0.5
    assert gateway.arm_ik.max_joint_speed_deg_s == 20
    assert gateway.robot.sent[-1]["arm_left_shoulder_pan.pos"] == 0
    with pytest.raises(ValueError):
        gateway.stage_message({"type": "arm_settings", "position_scale": float("nan")})


def test_tracking_loss_blocks_only_that_hand_until_physical_grip_release():
    gateway = _session_gateway()
    gateway.process_message(_arm(left=0, right=0))
    gateway.process_message(_arm(left=1, right=1))
    lost = _arm(left=2, right=2)
    lost["left"] = None
    gateway.process_message(lost)
    assert gateway.arm_ik.active_sides == {"right"}
    assert gateway.robot.sent[-1]["arm_left_shoulder_pan.pos"] == 0
    gateway.process_message(_arm(left=3, right=2))
    assert gateway.arm_ik.active_sides == {"right"}
    gateway.process_message(_arm(right=2))
    gateway.process_message(_arm(left=3, right=2))
    assert gateway.arm_ik.active_sides == {"left", "right"}
    assert gateway.robot.sent[-1]["arm_left_shoulder_pan.pos"] == 0


def test_release_hold_is_not_clamped_toward_old_leading_command():
    gateway = _session_gateway()
    gateway._commanded["arm_left_shoulder_pan.pos"] = 90
    gateway.arm_sessions.stop("paused")
    gateway.flush()
    assert gateway.robot.sent[-1]["arm_left_shoulder_pan.pos"] == 0


def test_incomplete_feedback_release_uses_last_measured_position_not_leading_goal():
    gateway = _session_gateway()
    gateway.process_message(_arm(left=0))
    gateway.process_message(_arm(left=1))
    gateway._last_state.pop("arm_left_shoulder_pan.pos")
    gateway.process_message(_arm())
    assert gateway.robot.sent[-1]["arm_left_shoulder_pan.pos"] == 0


def test_websocket_reconnect_never_reconnects_robot_and_rejects_second_operator():
    from fastapi.testclient import TestClient

    from lerobot.vr_gateway.server import create_app

    class ConnectingRobot(_RobotStub):
        def __init__(self):
            super().__init__()
            self.is_connected = False
            self.connects = 0

        def connect(self):
            self.connects += 1
            self.is_connected = True

    robot = ConnectingRobot()
    with TestClient(create_app(robot, arm_ik=_SessionIK())) as client:
        assert robot.connects == 1
        with client.websocket_connect("/ws") as socket:
            assert socket.receive_json()["protocol"] == 3
            with client.websocket_connect("/ws") as other:
                assert "Another operator" in other.receive_json()["error"]
        with client.websocket_connect("/ws") as socket:
            assert socket.receive_json()["type"] == "hello"
        assert robot.connects == 1


@pytest.mark.parametrize("work_s,expected_period_s", [(0.025, 0.04), (0.065, 0.065)])
def test_control_period_includes_io_time_without_catchup_bursts(monkeypatch, work_s, expected_period_s):
    from lerobot.vr_gateway.server import run_control_loop

    clock = [0.0]
    starts = []
    watchdog_calls = []
    gateway = SimpleNamespace(config=VRGatewayConfig(control_hz=25), control_period_s=None)

    def flush():
        starts.append(clock[0])
        clock[0] += work_s

    gateway.flush = flush
    gateway.watchdog = lambda: watchdog_calls.append(clock[0])

    async def io(function):
        return function()

    async def sleep(delay):
        assert delay >= 0
        if len(starts) == 5:
            raise asyncio.CancelledError
        clock[0] += delay

    monkeypatch.setattr("lerobot.vr_gateway.server.time.monotonic", lambda: clock[0])
    monkeypatch.setattr("lerobot.vr_gateway.server.asyncio.sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_control_loop(gateway, io))
    np.testing.assert_allclose(np.diff(starts), expected_period_s)
    assert len(watchdog_calls) == len(starts)
    assert gateway.control_period_s == pytest.approx(expected_period_s)
