"""The legacy entry point must use the captured mechanical zero and motor travel."""

import copy

import numpy as np
import pytest

from lerobot.vr_gateway.arm_ik import ARM_JOINTS
from lerobot.vr_gateway.server import make_vr_arm_ik


def test_legacy_requires_home_before_model_or_hardware_start(mapping, tmp_path):
    with pytest.raises(FileNotFoundError, match="Arm mapping missing"):
        make_vr_arm_ik(mapping.calibration, mapping_dir=tmp_path / "missing")


def test_legacy_rejects_home_bound_to_old_motor_calibration(mapping, mapping_dir):
    stale = copy.deepcopy(mapping.calibration)
    stale["arm_left_shoulder_lift"]["homing_offset"] += 1
    with pytest.raises(ValueError, match="calibration differs"):
        make_vr_arm_ik(stale, mode="legacy", mapping_dir=mapping_dir)


def test_legacy_home_and_straight_arm_share_the_same_motor_mapping(legacy_ik_factory, mapping):
    ik = legacy_ik_factory(fixed_dt=0.04)
    for side in ("left", "right"):
        expected_home = np.rad2deg(
            [mapping.mappings[side]["joints"][joint]["reference_q_rad"] for joint in ARM_JOINTS]
        )
        state = {}
        for joint in ARM_JOINTS:
            motor = mapping.calibration[f"arm_{side}_{joint}"]
            tick = mapping.mappings[side]["joints"][joint]["reference_tick"]
            state[f"arm_{side}_{joint}.pos"] = (
                (tick - (motor["range_min"] + motor["range_max"]) / 2) * 360 / 4095
            )
        np.testing.assert_allclose(ik._state_to_urdf_deg(side, state), expected_home, atol=1e-9)
        for joint, bounds in zip(ik.joints[side], mapping.limits_deg[side], strict=True):
            np.testing.assert_allclose(np.rad2deg(ik.robot.get_joint_limits(joint)), bounds)
        # CAD elbow straightening must be executable without enlarging motor travel.
        for shoulder in (-162.237, -72.237):
            q = np.array([0.0, shoulder, 163.163, 0.0, 0.0, 0.0])
            assert np.all(q >= ik.joint_limits_deg[side][:, 0])
            assert np.all(q <= ik.joint_limits_deg[side][:, 1])
            command = ik._urdf_deg_to_robot_deg(q, side)
            for joint, value in zip(ARM_JOINTS, command, strict=True):
                motor = mapping.calibration[f"arm_{side}_{joint}"]
                tick = value * 4095 / 360 + (motor["range_min"] + motor["range_max"]) / 2
                assert motor["range_min"] - 1e-8 <= tick <= motor["range_max"] + 1e-8


def test_legacy_home_keeps_legacy_control_defaults_and_current_pose(legacy_ik_factory, mapping):
    ik = legacy_ik_factory(fixed_dt=0.04)
    assert ik.mode == "legacy"
    assert ik.arm_mapping is not None
    assert ik.home_before_engage is False
    assert ik.position_scale == 0.5
    assert ik.posture_weight == 5e-4
    assert ik.orientation_weight == 1.0
    assert ik.retry_budget_s == 0.0
    assert ik.tip_frames == {side: f"{side}_Moving_Jaw" for side in ("left", "right")}
    state = {"lift_axis.height_mm": 0.0}
    for side in ("left", "right"):
        q = np.array([10.0, -80.0, 100.0, 20.0, -10.0, 15.0])
        state.update(
            zip((f"arm_{side}_{j}.pos" for j in ARM_JOINTS), mapping.to_robot_deg(side, q), strict=True)
        )
    pose = {"position": [0, 0, 0], "orientation": [0, 0, 0, 1]}
    output = ik.update({"left_active": True, "left": pose}, state)
    assert not ik.homing
    for key, value in output.items():
        assert value == pytest.approx(state[key], abs=360 / 4095)


@pytest.mark.parametrize("side", ["left", "right"])
@pytest.mark.parametrize("gesture,max_error_mm", [("straight_forward", 15), ("straight_up", 8)])
def test_legacy_home_improves_known_reachable_path(legacy_ik_factory, mapping, side, gesture, max_error_mm):
    from tests.vr_gateway.benchmark_legacy_home import replay

    result = replay(legacy_ik_factory(fixed_dt=0.04), mapping, side, gesture)
    # Default posture/attitude priorities still leave a measurable bend. This
    # guards the mapping improvement, not an unsupported full-extension claim.
    assert result["position_error_mm"] < max_error_mm, result
    assert result["orientation_error_deg"] < 0.5
    assert result["max_motor_step_deg"] <= 3.6 + 360 / 4095


def test_home_reference_geometry_matches_both_cad_chains(legacy_ik_factory, mapping):
    from lerobot.vr_gateway.calibrated_ik import make_calibrated_ik
    from lerobot.vr_gateway.calibration.verify_arm_mapping import arm_points

    legacy = legacy_ik_factory()
    reference = make_calibrated_ik(mapping)
    for side in ("left", "right"):
        q = np.rad2deg([mapping.mappings[side]["joints"][j]["reference_q_rad"] for j in ARM_JOINTS])
        # Only the tip frames differ; the same Home must bind the same arm chain.
        np.testing.assert_allclose(
            arm_points(legacy, side, q)[:-1], arm_points(reference, side, q)[:-1], atol=1e-8
        )
