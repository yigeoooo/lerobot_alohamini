"""Operator gestures must drive the requested wrist axis and pan direction."""

import json
from pathlib import Path

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from lerobot.vr_gateway.arm_ik import ARM_JOINTS, DEFAULT_HOME_POSTURE_DEG, rotation_exp
from lerobot.vr_gateway.server import make_vr_arm_ik

CALIBRATION = json.loads((Path(__file__).parent / "fixtures/ros2_reference_calibration.json").read_text())


def state_and_pose():
    state = {"lift_axis.height_mm": 0.0}
    for side, joints in DEFAULT_HOME_POSTURE_DEG.items():
        state.update({f"arm_{side}_{joint}.pos": value for joint, value in joints.items()})
    return state, {"position": [0.0, 0.0, 0.0], "orientation": [0.0, 0.0, 0.0, 1.0]}


@pytest.mark.parametrize("side", ["left", "right"])
@pytest.mark.parametrize("angle", [-30.0, 30.0])
@pytest.mark.parametrize("anchor_angles", [(0, 0, 0), (40, -25, 15)])
def test_twisting_controller_only_rotates_gripper_long_axis(side, angle, anchor_angles):
    pytest.importorskip("placo")
    ik = make_vr_arm_ik(CALIBRATION, fixed_dt=0.04)
    state, pose = state_and_pose()
    anchor = Rotation.from_euler("yxz", anchor_angles, degrees=True)
    pose["orientation"] = anchor.as_quat().tolist()
    payload = {f"{side}_active": True, side: pose}
    state.update(ik.update(payload, state))
    initial = np.array([state[f"arm_{side}_{joint}.pos"] for joint in ARM_JOINTS])

    for frame in range(50):
        twist = Rotation.from_euler("z", angle * min((frame + 1) / 25, 1), degrees=True)
        pose["orientation"] = (anchor * twist).as_quat().tolist()
        output = ik.update(payload, state)
        state.update(output)
        ik.accept_action(output)
    delta = np.array([state[f"arm_{side}_{joint}.pos"] for joint in ARM_JOINTS]) - initial
    assert delta[5] == pytest.approx(angle, abs=1.0)
    assert np.max(np.abs(delta[:5])) < 1.0, delta


@pytest.mark.parametrize("side", ["left", "right"])
@pytest.mark.parametrize("angle", [-20.0, 20.0])
def test_horizontal_hand_turn_preserves_original_git_direction(side, angle):
    pytest.importorskip("placo")
    ik = make_vr_arm_ik(CALIBRATION, fixed_dt=0.04)
    state, pose = state_and_pose()
    ik.align(pose)
    payload = {f"{side}_active": True, side: pose}
    state.update(ik.update(payload, state))
    initial_pan = state[f"arm_{side}_shoulder_pan.pos"]
    origin_rotation = ik._robot0[side][:3, :3].copy()
    pose["orientation"] = Rotation.from_euler("y", angle, degrees=True).as_quat().tolist()
    for _ in range(40):
        output = ik.update(payload, state)
        state.update(output)
        ik.accept_action(output)
    # d569ef96 maps positive XR Y yaw to positive model Z; no extra inversion.
    assert (state[f"arm_{side}_shoulder_pan.pos"] - initial_pan) * angle > 1
    np.testing.assert_allclose(
        ik._target[side][:3, :3] @ origin_rotation.T,
        rotation_exp([0, 0, np.deg2rad(angle)]),
        atol=1e-6,
    )


def test_roll_across_180_degrees_keeps_continuous_targets_and_respects_joint_limits():
    pytest.importorskip("placo")
    ik = make_vr_arm_ik(CALIBRATION, fixed_dt=0.04)
    state, pose = state_and_pose()
    state["arm_left_wrist_roll.pos"] = -90.0
    payload = {"left_active": True, "left": pose}
    state.update(ik.update(payload, state))
    previous = state["arm_left_wrist_roll.pos"]
    for angle in range(1, 301):
        pose["orientation"] = Rotation.from_euler("z", angle, degrees=True).as_quat().tolist()
        output = ik.update(payload, state)
        current = output["arm_left_wrist_roll.pos"]
        assert current >= previous - 0.2
        assert abs(current - previous) <= 3.6 + 1e-6
        assert -180 <= current <= 180
        state.update(output)
        previous = current
    assert previous > 175


def test_regrip_resets_twist_without_a_wrist_jump():
    pytest.importorskip("placo")
    ik = make_vr_arm_ik(CALIBRATION, fixed_dt=0.04)
    state, pose = state_and_pose()
    payload = {"left_active": True, "left": pose}
    state.update(ik.update(payload, state))
    pose["orientation"] = Rotation.from_euler("z", 30, degrees=True).as_quat().tolist()
    for _ in range(20):
        state.update(ik.update(payload, state))
    before = state["arm_left_wrist_roll.pos"]
    ik.release(["left"])
    pose["orientation"] = Rotation.from_euler("z", 100, degrees=True).as_quat().tolist()
    state.update(ik.update(payload, state))
    assert state["arm_left_wrist_roll.pos"] == pytest.approx(before, abs=0.1)
    pose["orientation"] = Rotation.from_euler("z", 110, degrees=True).as_quat().tolist()
    for _ in range(15):
        state.update(ik.update(payload, state))
    assert state["arm_left_wrist_roll.pos"] - before == pytest.approx(10, abs=0.5)
