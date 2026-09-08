from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

from lerobot.vr_gateway.arm_ik import AlohaMiniDualArmIK
from lerobot.vr_gateway.server import VRGateway, VRGatewayConfig


@dataclass
class FakeRobot:
    is_connected: bool = True
    last_remote_state: dict[str, object] | None = None

    def connect(self) -> None:
        self.is_connected = True

    def disconnect(self) -> None:
        self.is_connected = False

    def get_observation(self) -> dict[str, object]:
        return {}

    def send_action(self, action: dict[str, object]) -> dict[str, object]:
        return action


class FakeArmIK:
    def __init__(self) -> None:
        self.reanchor_calls = 0
        self.updates: list[dict[str, object]] = []

    def update(self, payload: dict[str, object], state: dict[str, object]) -> dict[str, float]:
        self.updates.append(payload)
        if payload.get("reanchor"):
            self.reanchor_calls += 1
        if not payload.get("active"):
            return {}
        return {"arm_left_shoulder_pan.pos": 1.0}


def test_gateway_reanchor_ack_and_follow_up_active_pose():
    robot = FakeRobot()
    arm_ik = FakeArmIK()
    gateway = VRGateway(robot, VRGatewayConfig(), arm_ik=arm_ik)

    ack = gateway.stage_message({"type": "arm_pose", "reanchor": True, "active": False})

    assert ack["status"] == "staged"
    assert ack["reanchor"] is True

    gateway.stage_message({"type": "arm_pose", "active": True, "left": {}, "right": {}, "reanchor": True})
    gateway.flush()

    assert arm_ik.reanchor_calls == 1
    assert arm_ik.updates[-1]["active"] is True
    assert arm_ik.updates[-1]["reanchor"] is True


def test_aloha_mini_ik_reanchor_resets_internal_state():
    ik = AlohaMiniDualArmIK.__new__(AlohaMiniDualArmIK)
    ik._reset = MagicMock()
    ik._engage = MagicMock(return_value=True)
    ik.active = True
    ik._target = {"left": object(), "right": object()}
    ik._last_time = 123.0

    poses = {"left": object(), "right": object()}
    state = {"arm_left_shoulder_pan.pos": 0.0}

    assert AlohaMiniDualArmIK.reanchor(ik, poses, state) is True
    ik._reset.assert_not_called()
    ik._engage.assert_called_once_with(poses, state)
