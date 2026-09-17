"""Regression paths for Home mapping, servo limits and straight-arm reach."""

import copy
import math

import numpy as np
import pytest
import yaml

from lerobot.vr_gateway.calibration.profile import ASSET_DIR, ArmMapping
from lerobot.vr_gateway.calibration.verify_arm_mapping import check_round_trip


def test_ros2_home_and_complete_range_round_trip(mapping):
    check_round_trip(mapping)
    for side in ("left", "right"):
        entries = mapping.mappings[side]["joints"]
        expected = []
        degrees = []
        for name, entry in list(entries.items())[:6]:
            meta = mapping.metadata["motors"][f"arm_{side}_{name}"]
            expected.append(math.degrees(entry["reference_q_rad"]))
            degrees.append(
                (entry["reference_tick"] - (meta["range_min"] + meta["range_max"]) / 2) * 360 / 4095
            )
        np.testing.assert_allclose(mapping.to_urdf_deg(side, degrees), expected, atol=1e-9)


def test_mapping_rejects_changed_eeprom_and_unbound_templates(mapping):
    stale = copy.deepcopy(mapping.calibration)
    stale["arm_left_shoulder_lift"]["homing_offset"] += 1
    with pytest.raises(ValueError, match="Stale or unbound"):
        ArmMapping(mapping.mappings, stale)
    templates = {
        side: yaml.safe_load((ASSET_DIR / f"calibration/hardware_joint_map_{side}.yaml").read_text())
        for side in ("left", "right")
    }
    with pytest.raises(ValueError, match="Stale or unbound"):
        ArmMapping(templates, mapping.calibration)


def test_mapping_rejects_out_of_range_targets(mapping):
    for side in ("left", "right"):
        q = np.mean(mapping.limits_deg[side], axis=1)
        q[1] = mapping.limits_deg[side][1][0] - 1
        with pytest.raises(ValueError, match="outside calibrated"):
            mapping.to_robot_deg(side, q)


def real_ik(mapping, **kwargs):
    pytest.importorskip("placo")
    from lerobot.vr_gateway.calibrated_ik import make_calibrated_ik

    kwargs.setdefault("fixed_dt", 0.04)
    return make_calibrated_ik(mapping, **kwargs)


def test_solver_uses_current_per_side_motor_limits(mapping):
    ik = real_ik(mapping)
    for side in ("left", "right"):
        for name, limits in zip(ik.joints[side], mapping.limits_deg[side], strict=True):
            np.testing.assert_allclose(np.rad2deg(ik.robot.get_joint_limits(name)), limits)
    assert ik.joint_limits_deg["left"][1, 0] != ik.joint_limits_deg["right"][1, 0]


def initial_state(mapping):
    from lerobot.vr_gateway.arm_ik import ARM_JOINTS

    state = {"lift_axis.height_mm": 0.0}
    for side in ("left", "right"):
        q = np.rad2deg([mapping.mappings[side]["joints"][name]["reference_q_rad"] for name in ARM_JOINTS])
        state.update(
            {
                f"arm_{side}_{name}.pos": value
                for name, value in zip(ARM_JOINTS, mapping.to_robot_deg(side, q), strict=True)
            }
        )
    return state


def test_folded_home_maps_straight_arm_targets_into_normal_hand_travel(mapping):
    from lerobot.vr_gateway.arm_ik import ARM_JOINTS

    ik = real_ik(mapping)
    state = initial_state(mapping)
    assert ik.position_scale == 1.0

    for side in ("left", "right"):
        home = mapping.to_urdf_deg(side, [state[f"arm_{side}_{name}.pos"] for name in ARM_JOINTS])
        ik._write_joints(side, home)
        ik.robot.update_kinematics()
        origin = np.array(ik.robot.get_T_world_frame(ik.tip_frames[side]))

        for shoulder in (-162.237, -72.237):
            straight = np.array([0.0, shoulder, 163.163, 0.0, 0.0, 0.0])
            ik._write_joints(side, straight)
            ik.robot.update_kinematics()
            target = np.array(ik.robot.get_T_world_frame(ik.tip_frames[side]))
            hand_travel_m = np.linalg.norm(target[:3, 3] - origin[:3, 3]) / ik.position_scale
            assert hand_travel_m < 0.75


def test_folded_home_is_the_operation_anchor_without_runtime_homing(mapping):
    from lerobot.vr_gateway.arm_ik import ARM_JOINTS

    ik = real_ik(mapping)
    state = initial_state(mapping)
    pose = {"position": [0.0, 0.0, 0.0], "orientation": [0.0, 0.0, 0.0, 1.0]}
    payload = {"left_active": True, "left": pose}

    output = ik.update(payload, state)

    assert ik.home_before_engage is False
    assert ik.homing is False
    assert ik.active_sides == {"left"}
    for name in ARM_JOINTS:
        assert output[f"arm_left_{name}.pos"] == pytest.approx(
            state[f"arm_left_{name}.pos"], abs=360.0 / 4095.0
        )


def test_resumed_tick_uses_one_nominal_motion_budget(mapping):
    from lerobot.vr_gateway.arm_ik import ARM_JOINTS
    from lerobot.vr_gateway.calibrated_ik import make_calibrated_ik

    ik = make_calibrated_ik(
        copy.deepcopy(mapping),
        smooth=1.0,
        max_joint_speed_deg_s=90.0,
        state_blend=0.0,
        deadband_m=0.0,
        deadband_rad=0.0,
    )
    state = initial_state(mapping)
    pose = {"position": [0.0, 0.0, 0.0], "orientation": [0.0, 0.0, 0.0, 1.0]}
    payload = {"left_active": True, "left": pose}
    first = ik.update(payload, state)
    state.update(first)
    before = np.asarray(mapping.to_urdf_deg("left", [first[f"arm_left_{name}.pos"] for name in ARM_JOINTS]))

    ik._last_time -= 1.0
    payload["left"]["position"] = [0.0, 0.0, -0.3]
    resumed = ik.update(payload, state)
    after = np.asarray(mapping.to_urdf_deg("left", [resumed[f"arm_left_{name}.pos"] for name in ARM_JOINTS]))

    one_encoder_tick_deg = 360.0 / 4095.0
    assert np.max(np.abs(after - before)) <= 90.0 * ik.nominal_dt + one_encoder_tick_deg


def test_world_rotation_about_tcp_roll_axis_drives_wrist_roll(mapping):
    from scipy.spatial.transform import Rotation

    from lerobot.vr_gateway.arm_ik import ARM_JOINTS

    ik = real_ik(
        copy.deepcopy(mapping),
        deadband_m=0.0,
        deadband_rad=0.0,
        solver_iterations=80,
    )
    state = initial_state(mapping)
    anchor = Rotation.from_euler("zyx", [35.0, -25.0, 15.0], degrees=True)
    pose = {
        "position": [0.0, 0.0, 0.0],
        "orientation": anchor.as_quat().tolist(),
    }
    payload = {"left_active": True, "left": pose}
    first = ik.update(payload, state)
    state.update(first)
    start = np.asarray(mapping.to_urdf_deg("left", [first[f"arm_left_{name}.pos"] for name in ARM_JOINTS]))

    # Rotate around the TCP's physical roll axis, expressed in the XR world.
    # The controller can start in any orientation; its local X is not the TCP X.
    tcp_axis = ik._robot0["left"][:3, 0]
    xr_axis = ik._body_basis.T @ tcp_axis
    pose["orientation"] = (Rotation.from_rotvec(xr_axis * np.deg2rad(45.0)) * anchor).as_quat().tolist()
    current = first
    for _ in range(40):
        current = ik.update(payload, state)
        state.update(current)
    finish = np.asarray(mapping.to_urdf_deg("left", [current[f"arm_left_{name}.pos"] for name in ARM_JOINTS]))
    delta = finish - start

    roll_index = ARM_JOINTS.index("wrist_roll")
    assert delta[roll_index] > 35.0
    assert np.max(np.abs(np.delete(delta, roll_index))) < 8.0


def test_calibrated_target_lead_is_bounded_from_measured_tcp(mapping):
    from scipy.spatial.transform import Rotation

    from lerobot.vr_gateway.arm_ik import ARM_JOINTS, pose_difference

    ik = real_ik(
        copy.deepcopy(mapping),
        deadband_m=0.0,
        deadband_rad=0.0,
        solver_iterations=80,
    )
    state = initial_state(mapping)
    pose = {"position": [0.0, 0.0, 0.0], "orientation": [0.0, 0.0, 0.0, 1.0]}
    payload = {"left_active": True, "left": pose}
    state.update(ik.update(payload, state))

    measured = np.asarray(mapping.to_urdf_deg("left", [state[f"arm_left_{name}.pos"] for name in ARM_JOINTS]))
    ik._write_joints("left", measured)
    ik.robot.update_kinematics()
    measured_tcp = np.array(ik.robot.get_T_world_frame(ik.tip_frames["left"]))

    pose["position"] = [0.0, 0.0, -0.3]
    pose["orientation"] = Rotation.from_rotvec([np.deg2rad(90.0), 0.0, 0.0]).as_quat().tolist()
    ik.update(payload, state)
    position_lead_m, orientation_lead_rad = pose_difference(measured_tcp, ik._target["left"])

    assert position_lead_m <= 0.025 + 1e-9
    assert orientation_lead_rad <= np.deg2rad(15.0) + 1e-9


@pytest.mark.parametrize("side", ["left", "right"])
@pytest.mark.parametrize("shoulder", [-162.237, -72.237], ids=["forward", "up"])
def test_position_priority_reaches_straight_arm_with_fixed_hand_orientation(mapping, side, shoulder):
    from lerobot.vr_gateway.arm_ik import ARM_JOINTS

    ik = real_ik(
        copy.deepcopy(mapping),
        deadband_m=0.0,
        deadband_rad=0.0,
        solver_iterations=80,
    )
    plant = real_ik(copy.deepcopy(mapping))
    state = initial_state(mapping)
    pose = {"position": [0.0, 0.0, 0.0], "orientation": [0.0, 0.0, 0.0, 1.0]}
    payload = {f"{side}_active": True, side: pose}
    state.update(ik.update(payload, state))

    home = np.asarray(mapping.to_urdf_deg(side, [state[f"arm_{side}_{name}.pos"] for name in ARM_JOINTS]))
    plant._write_joints(side, home)
    plant.robot.update_kinematics()
    origin = np.array(plant.robot.get_T_world_frame(plant.tip_frames[side]))
    straight = np.array([0.0, shoulder, 163.163, 0.0, 0.0, 0.0])
    plant._write_joints(side, straight)
    plant.robot.update_kinematics()
    desired = np.array(plant.robot.get_T_world_frame(plant.tip_frames[side]))
    pose["position"] = (ik._body_basis.T @ (desired[:3, 3] - origin[:3, 3]) / ik.position_scale).tolist()

    current = {}
    for _ in range(160):
        current = ik.update(payload, state)
        state.update(current)
    solved = np.asarray(mapping.to_urdf_deg(side, [current[f"arm_{side}_{name}.pos"] for name in ARM_JOINTS]))
    plant._write_joints(side, solved)
    plant.robot.update_kinematics()
    actual = np.array(plant.robot.get_T_world_frame(plant.tip_frames[side]))

    assert np.linalg.norm(actual[:3, 3] - desired[:3, 3]) < 0.015


def test_calibrated_client_axes_and_yaw_alignment(mapping):
    from scipy.spatial.transform import Rotation

    ik = real_ik(mapping)
    state = initial_state(mapping)
    pose = {"position": [0.0, 0.0, 0.0], "orientation": [0.0, 0.0, 0.0, 1.0]}
    payload = {"left_active": True, "left": pose}
    ik.update(payload, state)
    origin = ik._target["left"].copy()
    for hand, expected in (
        ([0, 0, -0.02], [0.02, 0, 0]),
        ([0.02, 0, 0], [0, -0.02, 0]),
        ([0, 0.02, 0], [0, 0, 0.02]),
    ):
        moved = np.eye(4)
        moved[:3, 3] = hand
        np.testing.assert_allclose(
            ik._target_from_delta("left", moved)[:3, 3] - origin[:3, 3], expected, atol=1e-9
        )
    # Operator yaw +90 degrees: hand travel follows the same body-relative axes.
    yaw = np.array([[0, 0, 1], [0, 1, 0], [-1, 0, 0]])
    ik.align({"position": [0, 0, 0], "orientation": Rotation.from_matrix(yaw).as_quat().tolist()})
    ik.update(payload, state)
    moved = np.eye(4)
    moved[:3, 3] = yaw @ np.array([0.0, 0.0, -0.02])
    np.testing.assert_allclose(
        ik._target_from_delta("left", moved)[:3, 3] - ik._robot0["left"][:3, 3], [0.02, 0, 0], atol=1e-9
    )


@pytest.mark.parametrize("side", ["left", "right"])
@pytest.mark.parametrize("direction,shoulder", [("forward", -162.237), ("up", -72.237)])
def test_reachable_straight_arm_targets(mapping, side, direction, shoulder):
    from scipy.spatial.transform import Rotation

    from lerobot.vr_gateway.arm_ik import ARM_JOINTS, pose_difference

    ik = real_ik(mapping, deadband_m=0.0, deadband_rad=0.0)
    plant = real_ik(copy.deepcopy(mapping))
    state = initial_state(mapping)
    start = np.array([0.0, -95.0, 95.0, 0.0, 0.0, 0.0])
    finish = np.array([0.0, shoulder, 163.163, 0.0, 0.0, 0.0])
    keys = [f"arm_{side}_{name}.pos" for name in ARM_JOINTS]
    state.update(dict(zip(keys, mapping.to_robot_deg(side, start), strict=True)))

    def fk(q):
        plant._write_joints(side, q)
        plant.robot.update_kinematics()
        return np.array(plant.robot.get_T_world_frame(plant.tip_frames[side]))

    origin = fk(start)
    payload = {f"{side}_active": True, side: {"position": [0, 0, 0], "orientation": [0, 0, 0, 1]}}
    ik.update(payload, state)
    bounds = np.array(mapping.limits_deg[side])
    for fraction in [*np.linspace(0.0, 1.0, 151), *np.ones(50)]:
        expected = start + fraction * (finish - start)
        assert np.all(expected >= bounds[:, 0]) and np.all(expected <= bounds[:, 1])
        target = fk(expected)
        basis = ik._body_basis
        hand = basis.T @ (target[:3, 3] - origin[:3, 3]) / ik.position_scale
        rotation = basis.T @ target[:3, :3] @ origin[:3, :3].T @ basis
        payload[side] = {
            "position": hand.tolist(),
            "orientation": Rotation.from_matrix(rotation).as_quat().tolist(),
        }
        out = ik.update(payload, state)
        assert all(key in out for key in keys)
        q = np.array(mapping.to_urdf_deg(side, [out[key] for key in keys]))
        assert np.all(q >= bounds[:, 0] - 1e-8) and np.all(q <= bounds[:, 1] + 1e-8)
        state.update(out)
    error, rotation_error = pose_difference(fk(q), target)
    # The production controller retains a weak Home-branch posture preference and
    # round-trips through 4095-tick motor coordinates; sub-millimetre agreement is
    # not observable at this boundary. Keep a 5 mm Cartesian acceptance threshold.
    assert error < 0.005, (direction, side, error)
    assert rotation_error < np.deg2rad(1.0)


@pytest.mark.parametrize("side", ["left", "right"])
def test_unreachable_target_retries_are_bounded_and_output_stays_near_feedback(mapping, side):
    from lerobot.vr_gateway.arm_ik import ARM_JOINTS

    # Bypass the upstream Cartesian lead clamp to exercise the solver's own
    # unreachable-target/retry path. Production lead limits have separate coverage.
    ik = real_ik(mapping, retry_after_frames=2, retry_budget_s=0.003, max_target_position_lead_m=None)
    state = initial_state(mapping)
    pose = {"position": [0, 0, 0], "orientation": [0, 0, 0, 1]}
    payload = {f"{side}_active": True, side: pose}
    first = ik.update(payload, state)
    state.update(first)
    keys = [f"arm_{side}_{name}.pos" for name in ARM_JOINTS]
    measured = np.array(mapping.to_urdf_deg(side, [state[key] for key in keys]))
    previous = measured.copy()
    pose["position"] = [10.0, 10.0, -10.0]
    for _ in range(12):
        # A stalled robot: feedback stays fixed while the desired target is unreachable.
        output = ik.update(payload, state)
        q = np.array(mapping.to_urdf_deg(side, [output[key] for key in keys]))
        assert np.isfinite(q).all()
        assert np.max(np.abs(q - previous)) <= 90 * 0.04 + 360 / 4095
        assert np.max(np.abs(q - measured)) <= ik.max_state_deviation_deg + 360 / 4095
        limits = ik.joint_limits_deg[side]
        assert np.all(q >= limits[:, 0] - 1e-6) and np.all(q <= limits[:, 1] + 1e-6)
        assert not any(key.startswith(f"arm_{'right' if side == 'left' else 'left'}_") for key in output)
        assert "lift_axis.height_mm" not in output
        previous = q
    assert 0 < ik.retry_attempts <= 6


def test_ik_itself_rejects_expired_sampling_timestamp(mapping):
    import time

    ik = real_ik(mapping)
    state = initial_state(mapping)
    state["_vr_state_sampled_at"] = time.monotonic() - 5.0
    pose = {"position": [0, 0, 0], "orientation": [0, 0, 0, 1]}
    assert ik.update({"left_active": True, "left": pose}, state) == {}
    assert ik.engage_reason == "stale_feedback"
    assert not ik.active
