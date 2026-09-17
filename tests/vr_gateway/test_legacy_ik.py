"""Legacy direction, timing and travel after binding the mechanical Home."""

import json
from pathlib import Path

import numpy as np
import pytest

FIXTURES = Path(__file__).parent / "fixtures"
ORACLE = json.loads((FIXTURES / "legacy_ik_d569ef96.json").read_text())
CALIBRATION = json.loads((FIXTURES / "ros2_reference_calibration.json").read_text())


@pytest.mark.parametrize(
    "case",
    ORACLE["cases"],
    ids=lambda case: f"{case['yaw_deg']}-{case['axis']}",
)
def test_legacy_target_direction_after_alignment(case, legacy_ik_factory):
    pytest.importorskip("placo")
    ik = legacy_ik_factory(fixed_dt=0.04, deadband_m=0.0, deadband_rad=0.0)
    assert ik.arm_mapping is not None
    assert ik.home_before_engage is False
    assert ik.position_scale == 0.5
    yaw = np.deg2rad(case["yaw_deg"])
    c, s = np.cos(yaw), np.sin(yaw)
    heading = np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
    ik.align({"position": [0, 0, 0], "orientation": [0, np.sin(yaw / 2), 0, np.cos(yaw / 2)]})
    state = dict(ORACLE["state"])
    start = {"position": [0, 0, 0], "orientation": [0, 0, 0, 1]}
    payload = {"active": True, "left": start, "right": start}
    state.update(ik.update(payload, state))
    origins = {side: ik._robot0[side].copy() for side in ("left", "right")}
    for frame in range(50):
        fraction = min((frame + 1) / 25.0, 1.0)
        angle = np.deg2rad(5) * fraction if case["axis"] == "rotation" else 0.0
        pose = {
            "position": (heading @ np.array(case["delta"]) * fraction).tolist(),
            "orientation": [0, np.sin(angle / 2), 0, np.cos(angle / 2)],
        }
        payload.update(left=pose, right=pose)
        output = ik.update(payload, state)
        state.update(output)
        ik.accept_action(output)
        if frame in (24, 49):
            # Home removes the old empirical forward reflection. Motor angles
            # now change with Home, so old joint-output snapshots do not apply.
            delta = np.array(case["delta"])
            expected_position = np.array([-delta[0], delta[2], delta[1]]) * 0.5
            expected_rotation = np.array(
                [[np.cos(angle), -np.sin(angle), 0], [np.sin(angle), np.cos(angle), 0], [0, 0, 1]]
            )
            # Horizontal yaw is about world Y; align rotates only the horizontal axes.
            side = "left"
            np.testing.assert_allclose(
                ik._target[side][:3, 3] - origins[side][:3, 3], expected_position, atol=1e-8
            )
            np.testing.assert_allclose(
                ik._target[side][:3, :3] @ origins[side][:3, :3].T, expected_rotation, atol=1e-8
            )


def test_legacy_solver_respects_current_motor_ranges(legacy_ik_factory, mapping):
    pytest.importorskip("placo")
    ik = legacy_ik_factory(fixed_dt=0.04)
    from lerobot.vr_gateway.arm_ik import ARM_JOINTS

    state = dict(ORACLE["state"])
    pose = {"position": [0, 0, 0], "orientation": [0, 0, 0, 1]}
    payload = {"active": True, "left": pose, "right": pose}
    state.update(ik.update(payload, state))
    pose["position"] = [0, 1.0, -1.0]
    for _ in range(60):
        output = ik.update(payload, state)
        for side in ("left", "right"):
            for index, (joint, name) in enumerate(zip(ARM_JOINTS, ik.joints[side], strict=True)):
                motor = CALIBRATION[f"arm_{side}_{joint}"]
                bound = (motor["range_max"] - motor["range_min"]) * 180 / 4095
                assert abs(output[f"arm_{side}_{joint}.pos"]) <= bound + 1e-6
                np.testing.assert_allclose(
                    np.rad2deg(ik.robot.get_joint_limits(name)), mapping.limits_deg[side][index]
                )
        state.update(output)


def test_legacy_motion_budget_tracks_normal_control_period(monkeypatch, legacy_ik_factory):
    pytest.importorskip("placo")
    ik = legacy_ik_factory()
    monkeypatch.setattr("lerobot.vr_gateway.legacy_ik.time.monotonic", lambda: 1.0)
    ik._last_time = 0.9
    assert ik._tick_dt() == pytest.approx(0.1)
    # A stall cannot accumulate an unbounded movement budget.
    ik._last_time = 0.0
    assert ik._tick_dt() == pytest.approx(0.2)


@pytest.mark.parametrize("side", ["left", "right"])
@pytest.mark.parametrize("bound,index", [("lower", 0), ("upper", 1)])
def test_limit_warning_uses_installed_limits_and_motor_signs(side, bound, index, legacy_ik_factory):
    pytest.importorskip("placo")
    ik = legacy_ik_factory(fixed_dt=0.04)
    from lerobot.vr_gateway.arm_ik import ARM_JOINTS

    state = dict(ORACLE["state"])
    assert ik.joint_limit_warnings(state) == []
    q = ik._state_to_urdf_deg(side, state)
    q[5] = ik.joint_limits_deg[side][5, index]
    state.update(
        zip((f"arm_{side}_{j}.pos" for j in ARM_JOINTS), ik._urdf_deg_to_robot_deg(q, side), strict=True)
    )
    assert ik.joint_limit_warnings(state) == [{"side": side, "joint": "wrist_roll", "bound": bound}]
    q[5] += 2 if index == 0 else -2
    state.update(
        zip((f"arm_{side}_{j}.pos" for j in ARM_JOINTS), ik._urdf_deg_to_robot_deg(q, side), strict=True)
    )
    assert ik.joint_limit_warnings(state) == []
