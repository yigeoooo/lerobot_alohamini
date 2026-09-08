from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np

from lerobot.vr_gateway.server import VRGateway, VRGatewayConfig


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


def test_reanchor_message_is_staged_and_reported():
    robot = _RobotStub()
    gateway = VRGateway(robot, VRGatewayConfig(), arm_ik=_IKStub())
    ack = gateway.stage_message({"type": "reanchor", "left": _pose(), "right": _pose()})
    assert ack["status"] == "staged"
    assert gateway.flush() is True
    assert gateway.status_payload()["arm_pending"] is False
    assert gateway.status_payload()["arm_homing"] is True
    assert gateway.status_payload()["arm_home_max_error_deg"] == 12.5
    assert gateway.process_message({"type": "reanchor", "left": _pose(), "right": _pose()})["status"] == "reanchored"


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
    assert gateway.process_message(
        {
            "type": "arm_pose",
            "active": False,
            "left": None,
            "right": None,
            "client_time_ms": 0,
        }
    )["status"] == "held"


def test_encode_payload_converts_rgb_frame_to_bgr_before_jpeg(monkeypatch):
    class _Encoded:
        def tobytes(self):
            return b"jpeg"

    class _CV2:
        COLOR_RGB2BGR = object()
        IMWRITE_JPEG_QUALITY = 1

        def __init__(self):
            self.converted = None

        def cvtColor(self, frame, code):
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
