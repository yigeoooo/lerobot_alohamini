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

    def get_observation(self, *, include_cameras=True):
        assert include_cameras is False
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
    assert config.cameras == {}


@pytest.mark.parametrize("mask", range(8))
def test_camera_selection_only_opens_explicit_devices(mask):
    from pathlib import Path

    options = {"head_camera": "/dev/head", "left_wrist_camera": "/dev/left", "right_wrist_camera": 2}
    selected = {name: device for i, (name, device) in enumerate(options.items()) if mask & (1 << i)}
    config = make_vr_robot_config(
        robot_model="alohamini2pro", left_port="/dev/left", right_port="/dev/right", **selected
    )
    names = ("forward", "wrist_left", "wrist_right")
    assert list(config.cameras) == [name for i, name in enumerate(names) if mask & (1 << i)]
    for name, camera in config.cameras.items():
        assert (camera.width, camera.height) == ((1280, 720) if name == "forward" else (640, 480))
        assert camera.fps == 30
        assert camera.fourcc == "MJPG"
        assert (
            camera.index_or_path
            == {"forward": Path("/dev/head"), "wrist_left": Path("/dev/left"), "wrist_right": 2}[name]
        )


@pytest.mark.parametrize(
    "args,devices",
    [
        ([], {}),
        (
            ["--head-camera", "--left-wrist-camera", "--right-wrist-camera"],
            {
                "forward": "/dev/am_camera_forward",
                "wrist_left": "/dev/am_camera_wrist_left",
                "wrist_right": "/dev/am_camera_wrist_right",
            },
        ),
        (
            ["--left-wrist-camera", "/dev/video8", "--right-wrist-camera", "2"],
            {
                "wrist_left": "/dev/video8",
                "wrist_right": "2",
            },
        ),
    ],
)
def test_camera_cli_passes_selected_devices_to_robot_and_gateway(monkeypatch, args, devices):
    from lerobot.robots.alohamini import alohamini
    from lerobot.vr_gateway import server

    configs = []

    def robot(config):
        configs.append(config)
        return SimpleNamespace(calibration={})

    monkeypatch.setattr(alohamini, "AlohaMini", robot)
    monkeypatch.setattr(
        server, "make_vr_arm_ik", lambda *a, **k: SimpleNamespace(position_scale=0.5, tip_frames={})
    )
    monkeypatch.setattr(server, "create_app", lambda robot, config, **k: config)
    runs = []
    monkeypatch.setattr("uvicorn.run", lambda app, **k: runs.append(app))
    monkeypatch.setattr(sys, "argv", ["vr_gateway", *args])
    # main sets this flag; restore the process environment after the test.
    monkeypatch.setenv("LEROBOT_VR_DIAGNOSTICS", "0")
    server.main()
    assert {name: str(camera.index_or_path) for name, camera in configs[0].cameras.items()} == devices
    assert runs[0].camera_names == tuple(devices)


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
    gateway = VRGateway(_RobotStub(), VRGatewayConfig(camera_names=("forward",), max_frame_width=0))
    frame = np.array([[[255, 0, 0]], [[0, 255, 0]]], dtype=np.uint8)

    payload = gateway.encode_payload({"forward": frame})

    assert cv2.converted is not None
    assert payload["frames"]["forward"]["jpeg_b64"] == "anBlZw=="


def test_video_preserves_720p_detail_and_does_not_upscale_smaller_frames():
    import base64

    cv2 = pytest.importorskip("cv2")
    gateway = VRGateway(_RobotStub(), VRGatewayConfig(camera_names=("forward",)))
    # Fine grayscale lines reveal both downscaling and excessive JPEG losses.
    columns = np.where(np.arange(1280) % 8 < 4, 32, 224).astype(np.uint8)
    frame = np.repeat(np.tile(columns, (720, 1))[:, :, None], 3, axis=2)
    encoded = gateway.encode_payload({"forward": frame})["frames"]["forward"]
    decoded = cv2.imdecode(np.frombuffer(base64.b64decode(encoded["jpeg_b64"]), np.uint8), cv2.IMREAD_COLOR)
    assert decoded.shape == frame.shape
    assert np.mean(np.abs(decoded.astype(float) - frame)) < 3
    small = gateway.encode_payload({"forward": frame[:360, :480]})["frames"]["forward"]
    assert (small["video_width"], small["video_height"]) == (480, 360)


def test_three_camera_frames_keep_identity_colors_and_dimensions():
    import base64

    cv2 = pytest.importorskip("cv2")
    names = ("forward", "wrist_left", "wrist_right")
    gateway = VRGateway(_RobotStub(), VRGatewayConfig(camera_names=names, max_frame_width=64))
    colors = ((255, 0, 0), (0, 255, 0), (0, 0, 255))
    observation = {
        name: np.full((60, 80, 3), color, np.uint8) for name, color in zip(names, colors, strict=True)
    }
    observation["arm_left_shoulder_pan.pos"] = 12.0
    observation["unselected"] = np.zeros((20, 20, 3), np.uint8)
    payload = gateway.encode_payload(observation)
    assert payload["cameras"] == list(names)
    assert payload["state"] == {"arm_left_shoulder_pan.pos": 12.0}
    assert list(payload["frames"]) == list(names)
    for name, color in zip(names, colors, strict=True):
        encoded = payload["frames"][name]
        assert (encoded["video_width"], encoded["video_height"]) == (64, 48)
        decoded = cv2.imdecode(
            np.frombuffer(base64.b64decode(encoded["jpeg_b64"]), np.uint8), cv2.IMREAD_COLOR
        )
        np.testing.assert_allclose(decoded.mean(axis=(0, 1)), color[::-1], atol=2)
    assert gateway.encode_payload(observation, include_frame=False)["frames"] == {}
    assert VRGateway(_RobotStub()).encode_payload(observation)["frames"] == {}
    observation["wrist_left"] = np.array([], np.uint8)  # A bad frame cannot hide the other feeds.
    assert set(gateway.encode_payload(observation)["frames"]) == {"forward", "wrist_right"}


def test_camera_timeout_does_not_interrupt_feedback_other_cameras_or_control():
    frame = np.zeros((4, 4, 3), np.uint8)
    reads = []

    def read(*, max_age_ms):
        reads.append(max_age_ms)
        return frame

    def stale(**kwargs):
        raise TimeoutError("camera is stale")

    robot = _RobotStub()
    robot.cameras = {
        "forward": SimpleNamespace(read_latest=read),
        "wrist_left": SimpleNamespace(read_latest=stale),
        "wrist_right": SimpleNamespace(read_latest=read),
    }
    gateway = VRGateway(robot, VRGatewayConfig(camera_names=tuple(robot.cameras)))
    assert "arm_left_shoulder_pan.pos" in gateway.capture_observation()
    assert reads == []
    assert set(gateway.capture_camera_frames()) == {"forward", "wrist_right"}
    assert reads == [500, 500]
    gateway.process_message({"type": "base", "x.vel": 0.1})
    assert robot.sent[-1]["x.vel"] == 0.1
    robot.cameras["wrist_left"].read_latest = read
    assert set(gateway.capture_camera_frames()) == set(robot.cameras)


@pytest.mark.parametrize("side", ["left", "right"])
@pytest.mark.parametrize("home_loaded", [False, True])
def test_legacy_gripper_keeps_motor_endpoints_with_or_without_home(side, home_loaded):
    class GripperRobot(_RobotStub):
        def get_observation(self, *, include_cameras=True):
            return {
                **super().get_observation(include_cameras=include_cameras),
                "arm_left_gripper.pos": 5.0,
                "arm_right_gripper.pos": 6.0,
            }

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


def test_record_toggle_requires_pc_and_reports_dataset_status():
    gateway = VRGateway(_RobotStub(), VRGatewayConfig())
    unavailable = gateway.process_message({"type": "record_toggle"})
    assert unavailable["status"] == "recorder_unavailable"
    assert gateway.status_payload()["recording_recorder_connected"] is False

    gateway.set_recorder_connected(True)
    gateway.update_recorder_status(
        {
            "type": "recorder_status",
            "dataset_root": "/tmp/vr_dataset",
            "dataset_repo_id": "vr/test",
            "dataset_exists": False,
            "dataset_frames": 0,
            "dataset_episodes": 0,
            "recorder_phase": "ready",
        }
    )
    status = gateway.status_payload()
    assert status["recording_recorder_connected"] is True
    assert status["recording_dataset_root"] == "/tmp/vr_dataset"
    assert status["recording_dataset_frames"] == 0
    assert gateway.process_message({"type": "record_toggle"})["status"] == "started"
    assert gateway.status_payload()["recording_active"] is True
    assert gateway.process_message({"type": "record_toggle"})["status"] == "stopped"
    assert gateway.status_payload()["recording_active"] is False


def test_recording_metadata_uses_standard_hardware_feature_helpers():
    robot = _RobotStub()
    robot.name = "AlohaMiniRobot"
    robot.action_features = {"joint.pos": float}
    robot.observation_features = {"joint.pos": float, "forward": (2, 3, 3)}
    gateway = VRGateway(robot, VRGatewayConfig(camera_names=("forward",), recording_fps=25))
    metadata = gateway.recording_metadata()
    assert metadata["fps"] == 25
    assert metadata["robot_type"] == "AlohaMiniRobot"
    assert metadata["dataset_features"]["action"]["names"] == ["joint.pos"]
    assert metadata["dataset_features"]["observation.images.forward"]["shape"] == (2, 3, 3)


def test_recording_sample_contains_complete_action_and_rejects_stale_camera():
    robot = _RobotStub()
    robot.action_features = {"arm_left_shoulder_pan.pos": float}
    robot.observation_features = {"arm_left_shoulder_pan.pos": float, "forward": (4, 4, 3)}
    camera = SimpleNamespace(
        latest_timestamp=1.0,
        read_latest=lambda **kwargs: np.zeros((4, 4, 3), dtype=np.uint8),
    )
    robot.cameras = {"forward": camera}
    gateway = VRGateway(robot, VRGatewayConfig(camera_names=("forward",)))
    gateway.capture_observation()
    gateway.set_recorder_connected(True)
    gateway.update_recorder_status({"recorder_phase": "ready"})
    assert gateway.process_message({"type": "record_toggle"})["status"] == "started"
    gateway._send({"arm_left_shoulder_pan.pos": 12.0})
    sample = gateway.capture_recording_sample()
    assert sample["action"]["arm_left_shoulder_pan.pos"] == 12.0
    assert sample["frames"]["forward"]["jpeg_b64"]
    with pytest.raises(RuntimeError, match="camera is stale"):
        gateway.capture_recording_sample()


def test_recording_skips_duplicate_camera_frame_and_resumes_when_camera_advances():
    robot = _RobotStub()
    robot.action_features = {"arm_left_shoulder_pan.pos": float}
    camera = SimpleNamespace(
        latest_timestamp=time.monotonic(),
        read_latest=lambda **kwargs: np.zeros((4, 4, 3), dtype=np.uint8),
    )
    robot.cameras = {"wrist_right": camera}
    gateway = VRGateway(robot, VRGatewayConfig(camera_names=("wrist_right",)))
    gateway.capture_observation()
    assert gateway.capture_recording_sample() is not None
    # A camera running asynchronously can expose the same recent frame twice.
    # This should skip one sample, not terminate the user's episode.
    assert gateway.capture_recording_sample() is None
    camera.latest_timestamp += 0.04
    assert gateway.capture_recording_sample() is not None


def test_recording_waits_for_matching_pc_save_confirmation():
    gateway = VRGateway(_RobotStub(), VRGatewayConfig())
    gateway.set_recorder_connected(True)
    assert gateway.process_message({"type": "record_toggle"})["status"] == "recorder_not_ready"
    gateway.update_recorder_status({"recorder_phase": "ready"})
    started = gateway.process_message({"type": "record_toggle"})
    episode = started["episode"]
    gateway.note_recording_sample()
    # Heartbeats must not reset an active recording to idle.
    gateway.update_recorder_status({"recorder_phase": "ready"})
    assert gateway.status_payload()["recording_phase"] == "recording"
    gateway.process_message({"type": "record_toggle"})
    assert gateway.status_payload()["recording_phase"] == "saving"
    assert gateway.process_message({"type": "record_toggle"})["status"] == "saving"
    gateway.update_recorder_status(
        {
            "recorder_phase": "saved",
            "episode": episode - 1,
            "saved_episode": episode - 1,
            "saved_episode_frames": 1,
        }
    )
    assert gateway.status_payload()["recording_phase"] == "saving"
    gateway.update_recorder_status(
        {
            "recorder_phase": "saved",
            "episode": episode,
            "saved_episode": episode,
            "saved_episode_frames": 1,
            "dataset_frames": 1,
            "dataset_episodes": 1,
        }
    )
    assert gateway.status_payload()["recording_phase"] == "saved"
    assert gateway.status_payload()["recording_saved_episode"] == episode
    assert gateway.status_payload()["recording_saved_frames"] == 1
    assert gateway.process_message({"type": "record_toggle"})["status"] == "started"


def test_recording_save_failure_and_disconnect_are_not_idle():
    gateway = VRGateway(_RobotStub(), VRGatewayConfig())
    gateway.set_recorder_connected(True)
    gateway.update_recorder_status({"recorder_phase": "ready"})
    episode = gateway.process_message({"type": "record_toggle"})["episode"]
    gateway.process_message({"type": "record_toggle"})
    gateway.update_recorder_status({"recorder_phase": "error", "episode": episode, "error": "disk full"})
    assert gateway.status_payload()["recording_phase"] == "error"
    assert "disk full" in gateway.status_payload()["recording_last_error"]
    gateway.set_recorder_connected(False)
    assert "disk full" in gateway.status_payload()["recording_last_error"]


def test_recorder_reconnect_clears_saved_message_and_uses_current_dataset_counts():
    gateway = VRGateway(_RobotStub(), VRGatewayConfig())
    gateway.set_recorder_connected(True)
    gateway.update_recorder_status({"recorder_phase": "ready"})
    episode = gateway.process_message({"type": "record_toggle"})["episode"]
    gateway.note_recording_sample()
    gateway.process_message({"type": "record_toggle"})
    gateway.update_recorder_status(
        {
            "recorder_phase": "saved",
            "episode": episode,
            "saved_episode": episode,
            "saved_episode_frames": 1,
            "dataset_frames": 1,
            "dataset_episodes": 1,
        }
    )
    gateway.set_recorder_connected(False)
    gateway.set_recorder_connected(True)
    gateway.update_recorder_status(
        {
            "recorder_phase": "ready",
            "dataset_frames": 0,
            "dataset_episodes": 0,
            "dataset_verified": True,
        }
    )
    status = gateway.status_payload()
    assert status["recording_phase"] == "idle"
    assert status["recording_saved_episode"] is None
    assert status["recording_dataset_episodes"] == 0


def test_recording_displays_dataset_episode_after_gateway_restart():
    gateway = VRGateway(_RobotStub(), VRGatewayConfig())
    gateway.set_recorder_connected(True)
    gateway.update_recorder_status(
        {
            "recorder_phase": "ready",
            "dataset_verified": True,
            "dataset_episodes": 5,
            "dataset_frames": 100,
        }
    )
    ack = gateway.process_message({"type": "record_toggle"})
    assert ack["dataset_episode"] == 5
    assert gateway.status_payload()["recording_dataset_episode"] == 5
    assert gateway.status_payload()["recording_dataset_episodes"] == 5


def test_recorder_startup_validation_error_is_reported_without_an_active_episode():
    gateway = VRGateway(_RobotStub(), VRGatewayConfig())
    gateway.set_recorder_connected(True)
    gateway.update_recorder_status(
        {
            "recorder_phase": "error",
            "episode": None,
            "dataset_verified": False,
            "error": "数据集校验失败：缺少数据文件",
        }
    )
    status = gateway.status_payload()
    assert status["recording_phase"] == "error"
    assert status["recording_dataset_verified"] is False
    assert "缺少数据文件" in status["recording_last_error"]
    assert gateway.process_message({"type": "record_toggle"})["status"] == "recorder_not_ready"


def test_recorder_websocket_propagates_saved_episode_to_health():
    from fastapi.testclient import TestClient

    from lerobot.vr_gateway.server import create_app

    def receive_until(socket, predicate):
        for _ in range(100):
            message = socket.receive_json()
            if predicate(message):
                return message
        pytest.fail("expected recording transition was not received")

    robot = _RobotStub()
    robot.action_features = {"arm_left_shoulder_pan.pos": float}
    robot.observation_features = robot.action_features
    with TestClient(create_app(robot, VRGatewayConfig())) as client:
        with client.websocket_connect("/record") as obsolete:
            obsolete.send_json({"type": "hello", "protocol": 1})
            assert "版本不匹配" in obsolete.receive_json()["error"]
        with client.websocket_connect("/record") as recorder:
            recorder.send_json({"type": "hello", "protocol": 2, "dataset_root": "/tmp/vr-test"})
            assert recorder.receive_json()["protocol"] == 2
            recorder.send_json({"type": "recorder_status", "recorder_phase": "ready"})
            deadline = time.monotonic() + 2
            while not client.get("/health").json()["recording_recorder_ready"]:
                assert time.monotonic() < deadline
                time.sleep(0.01)
            with client.websocket_connect("/ws") as operator:
                operator.send_json({"type": "record_toggle"})
                started = receive_until(operator, lambda m: m.get("for") == "record_toggle")
                assert started["status"] == "started"
                receive_until(recorder, lambda m: m["type"] == "sample")
                operator.send_json({"type": "record_toggle"})
                saving = receive_until(recorder, lambda m: m.get("phase") == "saving")
                assert client.get("/health").json()["recording_phase"] == "saving"
                recorder.send_json(
                    {
                        "type": "recorder_status",
                        "recorder_phase": "saved",
                        "episode": saving["episode"],
                        "saved_episode": saving["episode"],
                        "saved_episode_frames": saving["frames"],
                        "dataset_frames": saving["frames"],
                        "dataset_episodes": 1,
                    }
                )
                receive_until(recorder, lambda m: m.get("phase") == "saved")
                health = client.get("/health").json()
                assert health["recording_phase"] == "saved"
                assert health["recording_saved_frames"] == saving["frames"]
                assert health["recording_dataset_root"] == "/tmp/vr-test"


def test_incomplete_feedback_release_uses_last_measured_position_not_leading_goal():
    gateway = _session_gateway()
    gateway.process_message(_arm(left=0))
    gateway.process_message(_arm(left=1))
    gateway._last_state.pop("arm_left_shoulder_pan.pos")
    gateway.process_message(_arm())
    assert gateway.robot.sent[-1]["arm_left_shoulder_pan.pos"] == 0


@pytest.mark.parametrize("camera_names", [(), ("forward", "wrist_left", "wrist_right")])
def test_websocket_reconnect_never_reconnects_robot_and_rejects_second_operator(camera_names):
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
    robot.cameras = {
        name: SimpleNamespace(read_latest=lambda **kwargs: np.zeros((4, 4, 3), np.uint8))
        for name in camera_names
    }
    config = VRGatewayConfig(camera_names=camera_names)
    with TestClient(create_app(robot, config, arm_ik=_SessionIK())) as client:
        assert robot.connects == 1
        assert client.get("/health").json()["cameras"] == list(camera_names)
        with client.websocket_connect("/ws") as socket:
            hello = socket.receive_json()
            assert hello["protocol"] == 4
            assert hello["cameras"] == list(camera_names)
            observation = socket.receive_json()
            assert observation["type"] == "observation"
            assert set(observation["frames"]) == set(camera_names)
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
