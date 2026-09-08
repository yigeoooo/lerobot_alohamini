from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("placo")

from lerobot.vr_gateway.arm_ik import (  # noqa: E402
    ARM_JOINTS,
    DEFAULT_HOME_POSTURE_DEG,
    SIDES,
    VR_TO_ROBOT,
    AlohaMiniDualArmIK,
    pose_difference,
    rotation_exp,
)
from lerobot.vr_gateway.server import ALOHAMINI_ROBOT_TO_URDF_JOINT_SIGNS  # noqa: E402

URDF_PATH = Path(__file__).parents[3] / "src/lerobot/vr_gateway/assets/alohamini2pro/urdf/alohamini2pro.urdf"


def _engaged_ik(**kwargs: object) -> AlohaMiniDualArmIK:
    ik = AlohaMiniDualArmIK(
        URDF_PATH,
        fixed_dt=0.04,
        smooth=1.0,
        max_joint_speed_deg_s=1000.0,
        max_state_deviation_deg=None,
        solver_iterations=60,
        **kwargs,
    )
    state = {"lift_axis.height_mm": 300.0}
    payload = {"active": True}
    for side in SIDES:
        for name in ARM_JOINTS:
            state[f"arm_{side}_{name}.pos"] = DEFAULT_HOME_POSTURE_DEG[side][name]
        payload[side] = {
            "position": [0.0, 0.0, 0.0],
            "orientation": [0.0, 0.0, 0.0, 1.0],
        }
    assert ik.update(payload, state)
    return ik


def _tcp_z_from_robot_degrees(
    ik: AlohaMiniDualArmIK, side: str, robot_degrees: dict[str, float]
) -> float:
    state = {f"arm_{side}_{name}.pos": robot_degrees[name] for name in ARM_JOINTS}
    ik._write_joints(side, ik._state_to_urdf_deg(side, state))
    ik.robot.update_kinematics()
    return float(ik.robot.get_T_world_frame(ik.tip_frames[side])[2, 3])


@pytest.mark.parametrize(
    "side,before,after",
    (
        (
            "right",
            (-7.3, -41.6, 41.8, 0.9, 0.0, 0.0),
            (-7.3, -43.0, 59.6, 25.8, 0.0, 0.0),
        ),
        (
            "left",
            (-7.5, -37.1, 37.4, 3.0, 0.0, 0.0),
            (-7.5, -38.3, 50.8, 21.3, 0.0, 0.0),
        ),
    ),
)
def test_robot_joint_log_snapshot_reproduces_downward_tcp_motion(side, before, after):
    """The reported bad commands lower both model TCPs under the hardware sign profile."""
    ik = AlohaMiniDualArmIK(
        URDF_PATH,
        joint_signs=ALOHAMINI_ROBOT_TO_URDF_JOINT_SIGNS,
    )
    before_deg = dict(zip(ARM_JOINTS, before, strict=True))
    after_deg = dict(zip(ARM_JOINTS, after, strict=True))

    before_z = _tcp_z_from_robot_degrees(ik, side, before_deg)
    after_z = _tcp_z_from_robot_degrees(ik, side, after_deg)

    assert after_z < before_z - 0.05


def test_webxr_up_produces_upward_robot_command_fk_for_both_arms():
    """A WebXR +Y request must raise the TCP after robot/URDF sign conversion."""
    ik = AlohaMiniDualArmIK(
        URDF_PATH,
        fixed_dt=0.04,
        smooth=1.0,
        max_joint_speed_deg_s=10_000.0,
        max_state_deviation_deg=None,
        solver_iterations=100,
        joint_signs=ALOHAMINI_ROBOT_TO_URDF_JOINT_SIGNS,
    )
    state = _home_state()
    payload = _controller_payload()
    initial = ik.update(payload, state)
    state.update(initial)
    for side in SIDES:
        payload[side]["position"][1] = 0.04

    raised = ik.update(payload, state)

    assert ik.tracking_status["state"] == "ok"
    for side in SIDES:
        initial_deg = {name: initial[f"arm_{side}_{name}.pos"] for name in ARM_JOINTS}
        raised_deg = {name: raised[f"arm_{side}_{name}.pos"] for name in ARM_JOINTS}
        initial_z = _tcp_z_from_robot_degrees(ik, side, initial_deg)
        raised_z = _tcp_z_from_robot_degrees(ik, side, raised_deg)
        assert raised_z > initial_z + 0.035


def _home_state() -> dict[str, float]:
    state = {"lift_axis.height_mm": 300.0}
    for side in SIDES:
        for name in ARM_JOINTS:
            state[f"arm_{side}_{name}.pos"] = DEFAULT_HOME_POSTURE_DEG[side][name]
    return state


def _controller_payload() -> dict[str, object]:
    return {
        "active": True,
        **{
            side: {
                "position": [0.0, 0.0, 0.0],
                "orientation": [0.0, 0.0, 0.0, 1.0],
            }
            for side in SIDES
        },
    }


@pytest.mark.parametrize(
    "delta_m",
    (
        (0.08, 0.0, 0.0),
        (-0.08, 0.0, 0.0),
        (0.0, -0.10, 0.0),
        (0.0, 0.08, 0.0),
        (0.0, 0.0, 0.10),
        (0.0, 0.0, -0.10),
    ),
)
def test_real_placo_reaches_cartesian_translation_in_all_directions(delta_m):
    ik = _engaged_ik()
    for side in SIDES:
        ik._target[side][:3, 3] += delta_m
        ik.tasks[side].T_world_frame = ik._target[side]

    converged = ik._solve()
    ik._update_tracking_status(converged)

    assert converged
    assert ik.tracking_status["state"] == "ok"
    assert all(ik.tracking_status["sides"][side]["position_error_mm"] < 1.0 for side in SIDES)


# Representative AlohaMini 2 Pro Feetech ROM converted to robot/action degrees, with
# a 2-degree safety margin.  Production still loads the exact per-unit calibration at
# runtime; these values make the offline FK/IK contract exercise both ends of every
# physical joint rather than the URDF's overly broad +/-180-degree limits.
PRO_CALIBRATION_LIMITS_DEG = {
    "left": {
        "shoulder_pan": (-125.34, 125.34),
        "shoulder_lift": (-99.32, 99.32),
        "elbow_flex": (-94.84, 94.84),
        "wrist_flex": (-92.37, 92.37),
        "wrist_yaw": (-83.63, 83.63),
        "wrist_roll": (-178.0, 178.0),
    },
    "right": {
        "shoulder_pan": (-125.74, 125.74),
        "shoulder_lift": (-100.20, 100.20),
        "elbow_flex": (-92.86, 92.86),
        "wrist_flex": (-92.24, 92.24),
        "wrist_yaw": (-83.23, 83.23),
        "wrist_roll": (-178.0, 178.0),
    },
}

WORKSPACE_OFFSETS_M = tuple(
    (x, y, z)
    for x in (-0.06, 0.0, 0.06)
    for y in (-0.06, 0.0, 0.06)
    for z in (-0.06, 0.0, 0.06)
)


@pytest.mark.parametrize("delta_m", WORKSPACE_OFFSETS_M)
def test_real_placo_reaches_three_dimensional_workspace_grid(delta_m):
    """The calibrated home branch must cover the central 3-D workspace volume."""
    ik = _engaged_ik()
    for side in SIDES:
        ik._target[side][:3, 3] += delta_m
        ik.tasks[side].T_world_frame = ik._target[side]

    converged = ik._solve()
    ik._update_tracking_status(converged)

    assert converged
    for side in SIDES:
        status = ik.tracking_status["sides"][side]
        assert status["state"] == "ok"
        assert status["position_error_mm"] < 1.0
        assert status["orientation_error_deg"] < 0.5


@pytest.mark.parametrize("side", SIDES)
@pytest.mark.parametrize("joint_name", ARM_JOINTS)
@pytest.mark.parametrize("requested_fraction", (0.0, 0.5, 1.0))
def test_calibrated_min_mid_max_of_every_pro_joint_reaches_fk_target(side, joint_name, requested_fraction):
    """Every Pro joint's calibrated min/mid/max remains usable through FK and IK."""
    ik = _engaged_ik(joint_limits_deg=PRO_CALIBRATION_LIMITS_DEG)
    joint_index = ARM_JOINTS.index(joint_name)
    lower, upper = PRO_CALIBRATION_LIMITS_DEG[side][joint_name]
    requested_deg = lower + requested_fraction * (upper - lower)
    current = ik._read_joints(side)
    requested = current.copy()
    requested[joint_index] = requested_deg
    ik._write_joints(side, requested)
    ik.robot.update_kinematics()
    target = np.array(ik.robot.get_T_world_frame(ik.tip_frames[side]))
    ik._write_joints(side, current)
    ik.robot.update_kinematics()
    ik._target[side] = target
    ik.tasks[side].T_world_frame = target

    assert ik._solve(), f"{side} {joint_name} at {requested_deg} deg did not converge"
    solved = ik._read_joints(side)
    actual = np.array(ik.robot.get_T_world_frame(ik.tip_frames[side]))
    position_error_m, orientation_error_rad = pose_difference(actual, target)

    lower, upper = PRO_CALIBRATION_LIMITS_DEG[side][joint_name]
    assert lower - 1e-6 <= solved[joint_index] <= upper + 1e-6
    assert solved[joint_index] == pytest.approx(requested_deg, abs=0.25)
    assert position_error_m < 1e-3
    assert orientation_error_rad < 1e-2


@pytest.mark.parametrize("side", SIDES)
def test_all_six_joints_straight_configuration_is_reachable(side):
    """The all-zero, fully straight chain is a valid coordinated target."""
    ik = _engaged_ik(joint_limits_deg=PRO_CALIBRATION_LIMITS_DEG)
    current = ik._read_joints(side)
    ik._write_joints(side, np.zeros(len(ARM_JOINTS)))
    ik.robot.update_kinematics()
    target = np.array(ik.robot.get_T_world_frame(ik.tip_frames[side]))
    ik._write_joints(side, current)
    ik.robot.update_kinematics()
    ik._target[side] = target
    ik.tasks[side].T_world_frame = target

    assert ik._solve()
    solved = ik._read_joints(side)
    actual = np.array(ik.robot.get_T_world_frame(ik.tip_frames[side]))
    position_error_m, orientation_error_rad = pose_difference(actual, target)
    limits = np.array([PRO_CALIBRATION_LIMITS_DEG[side][name] for name in ARM_JOINTS])
    assert np.all(solved >= limits[:, 0] - 1e-6)
    assert np.all(solved <= limits[:, 1] + 1e-6)
    assert position_error_m < 1e-3
    assert orientation_error_rad < 1e-2


@pytest.mark.parametrize(
    "joint_pose",
    (
        {"shoulder_pan": -50.0, "shoulder_lift": -35.0},
        {"shoulder_pan": 50.0, "shoulder_lift": -35.0},
        {"shoulder_lift": -55.0, "elbow_flex": 55.0, "wrist_flex": -35.0},
        {"shoulder_pan": 35.0, "shoulder_lift": -50.0, "elbow_flex": 30.0, "wrist_flex": 25.0},
    ),
)
def test_multi_joint_linkage_and_dual_arm_coordination(joint_pose):
    """Shoulder/elbow/wrist changes solve together on both arms, not one axis at a time."""
    ik = _engaged_ik(joint_limits_deg=PRO_CALIBRATION_LIMITS_DEG)
    targets = {}
    for side in SIDES:
        targets[side] = _target_from_joint_pose(ik, side, joint_pose)
        ik._target[side] = targets[side]
        ik.tasks[side].T_world_frame = targets[side]

    assert ik._solve()
    for side in SIDES:
        position_error_m, orientation_error_rad = pose_difference(
            np.array(ik.robot.get_T_world_frame(ik.tip_frames[side])), targets[side]
        )
        assert position_error_m < 1e-3
        assert orientation_error_rad < 1e-2
        solved = ik._read_joints(side)
        limits = np.array([PRO_CALIBRATION_LIMITS_DEG[side][name] for name in ARM_JOINTS])
        assert np.all(solved >= limits[:, 0] - 1e-6)
        assert np.all(solved <= limits[:, 1] + 1e-6)


@pytest.mark.parametrize("side", SIDES)
@pytest.mark.parametrize("direction", (-1.0, 1.0))
def test_shoulder_pan_and_horizontal_wrist_rotation_each_follow_both_directions(side, direction):
    """Regression coverage for the two rotations reported as ineffective by operators."""
    ik = _engaged_ik(joint_limits_deg=PRO_CALIBRATION_LIMITS_DEG)
    start = ik._read_joints(side)
    changes = {"shoulder_pan": direction * 50.0, "wrist_yaw": direction * 50.0}
    target = _target_from_joint_pose(ik, side, changes)
    ik._target[side] = target
    ik.tasks[side].T_world_frame = target

    assert ik._solve()
    solved = ik._read_joints(side)
    pan_index = ARM_JOINTS.index("shoulder_pan")
    yaw_index = ARM_JOINTS.index("wrist_yaw")
    assert direction * (solved[pan_index] - start[pan_index]) > 35.0
    assert direction * (solved[yaw_index] - start[yaw_index]) > 35.0
    position_error_m, orientation_error_rad = pose_difference(
        np.array(ik.robot.get_T_world_frame(ik.tip_frames[side])), target
    )
    assert position_error_m < 1e-3
    assert orientation_error_rad < 1e-2


def test_unreachable_workspace_target_reports_diagnostic_state():
    ik = _engaged_ik(joint_limits_deg=PRO_CALIBRATION_LIMITS_DEG)
    for side in SIDES:
        ik._target[side][1, 3] -= 0.5
        ik.tasks[side].T_world_frame = ik._target[side]

    converged = ik._solve()
    ik._update_tracking_status(converged)

    assert not converged
    assert ik.tracking_status["state"] in {"ik_unreachable", "joint_limit"}
    for side in SIDES:
        status = ik.tracking_status["sides"][side]
        assert status["converged"] is False
        assert status["position_error_mm"] > 10.0
        assert status["state"] in {"ik_unreachable", "joint_limit"}


def test_public_update_never_emits_commands_outside_calibrated_limits():
    ik = _engaged_ik(
        joint_limits_deg=PRO_CALIBRATION_LIMITS_DEG,
    )
    state = _home_state()
    payload = _controller_payload()
    first = ik.update(payload, state)
    state.update(first)
    for side in SIDES:
        payload[side]["position"] = [0.08, 0.08, -0.08]
        payload[side]["orientation"] = [0.0, 0.0, 0.3826834, 0.9238795]

    output = ik.update(payload, state)
    for side in SIDES:
        for name in ARM_JOINTS:
            value = output[f"arm_{side}_{name}.pos"]
            lower, upper = PRO_CALIBRATION_LIMITS_DEG[side][name]
            assert lower - 1e-6 <= value <= upper + 1e-6


@pytest.mark.parametrize("axis", np.eye(3))
def test_real_placo_reaches_cartesian_rotation_about_every_axis(axis):
    ik = _engaged_ik()
    rotation = rotation_exp(axis * np.deg2rad(20.0))
    for side in SIDES:
        ik._target[side][:3, :3] = rotation @ ik._target[side][:3, :3]
        ik.tasks[side].T_world_frame = ik._target[side]

    converged = ik._solve()
    ik._update_tracking_status(converged)

    assert converged
    assert ik.tracking_status["state"] == "ok"
    assert all(ik.tracking_status["sides"][side]["orientation_error_deg"] < 0.5 for side in SIDES)


def test_level_hand_yaw_is_driven_mainly_by_wrist_yaw():
    ik = _engaged_ik()
    start = ik._read_joints("left")
    rotation = rotation_exp(np.array([0.0, 0.0, np.deg2rad(20.0)]))
    for side in SIDES:
        ik._target[side][:3, :3] = rotation @ ik._target[side][:3, :3]
        ik.tasks[side].T_world_frame = ik._target[side]

    assert ik._solve()
    delta = ik._read_joints("left") - start

    wrist_yaw = ARM_JOINTS.index("wrist_yaw")
    shoulder_pan = ARM_JOINTS.index("shoulder_pan")
    assert abs(delta[wrist_yaw]) > 20.0
    assert abs(delta[wrist_yaw]) > 3.0 * abs(delta[shoulder_pan])


def _pose_from_target(home: np.ndarray, target: np.ndarray) -> dict[str, list[float]]:
    """Encode a robot-frame target as the equivalent WebXR controller delta."""
    basis = np.asarray(VR_TO_ROBOT)
    rotation = basis.T @ target[:3, :3] @ home[:3, :3].T @ basis
    rotation = np.asarray(rotation)
    trace = float(np.trace(rotation))
    if trace > 0.0:
        scale = np.sqrt(trace + 1.0) * 2.0
        quaternion = [
            (rotation[2, 1] - rotation[1, 2]) / scale,
            (rotation[0, 2] - rotation[2, 0]) / scale,
            (rotation[1, 0] - rotation[0, 1]) / scale,
            0.25 * scale,
        ]
    else:
        raise AssertionError("test target rotation must not be near 180 degrees")
    return {
        "position": (basis.T @ (target[:3, 3] - home[:3, 3])).tolist(),
        "orientation": quaternion,
    }


def _target_from_joint_pose(ik: AlohaMiniDualArmIK, side: str, changes: dict[str, float]) -> np.ndarray:
    current = ik._read_joints(side)
    requested = current.copy()
    for name, value in changes.items():
        requested[ARM_JOINTS.index(name)] = value
    ik._write_joints(side, requested)
    ik.robot.update_kinematics()
    target = np.array(ik.robot.get_T_world_frame(ik.tip_frames[side]))
    ik._write_joints(side, current)
    ik.robot.update_kinematics()
    return target


def test_forearm_rotates_to_point_fingers_at_sky_without_elbow_motion():
    """A held elbow plus forearm rotation must be solved as a wrist pose."""
    ik = _engaged_ik()
    side = "left"
    start = ik._read_joints(side)
    target = _target_from_joint_pose(ik, side, {"wrist_flex": 55.0})
    ik._target[side] = target
    ik.tasks[side].T_world_frame = target

    assert ik._solve()
    solved = ik._read_joints(side)
    position_error_m, orientation_error_rad = pose_difference(
        np.array(ik.robot.get_T_world_frame(ik.tip_frames[side])), target
    )
    assert solved[ARM_JOINTS.index("wrist_flex")] - start[ARM_JOINTS.index("wrist_flex")] > 50.0
    assert abs(solved[ARM_JOINTS.index("elbow_flex")] - start[ARM_JOINTS.index("elbow_flex")]) < 1.0
    assert position_error_m < 5e-4
    assert orientation_error_rad < 5e-3


def test_straight_forward_reach_requires_shoulder_and_elbow_coordination():
    """A forward-pointing hand must extend the whole arm, not only drop the wrist."""
    ik = _engaged_ik()
    side = "left"
    start = ik._read_joints(side)
    target = _target_from_joint_pose(ik, side, {"shoulder_lift": -70.0, "elbow_flex": 0.0})
    ik._target[side] = target
    ik.tasks[side].T_world_frame = target

    assert ik._solve()
    solved = ik._read_joints(side)
    position_error_m, orientation_error_rad = pose_difference(
        np.array(ik.robot.get_T_world_frame(ik.tip_frames[side])), target
    )
    shoulder_delta = abs(solved[ARM_JOINTS.index("shoulder_lift")] - start[ARM_JOINTS.index("shoulder_lift")])
    elbow_delta = abs(solved[ARM_JOINTS.index("elbow_flex")] - start[ARM_JOINTS.index("elbow_flex")])
    wrist_delta = abs(solved[ARM_JOINTS.index("wrist_flex")] - start[ARM_JOINTS.index("wrist_flex")])
    assert shoulder_delta > 20.0
    assert elbow_delta > 20.0
    assert shoulder_delta + elbow_delta > 2.0 * wrist_delta
    assert position_error_m < 5e-4
    assert orientation_error_rad < 5e-3


def test_public_update_reaches_combined_forward_and_up_target():
    """The controller path must preserve both translation and orientation together."""
    ik = _engaged_ik()
    state = _home_state()
    payload = _controller_payload()
    first = ik.update(payload, state)
    state.update(first)
    side = "left"
    target = _target_from_joint_pose(
        ik, side, {"shoulder_lift": -62.0, "elbow_flex": 8.0, "wrist_flex": 35.0}
    )
    pose = _pose_from_target(ik._robot0[side], target)
    for current_side in SIDES:
        payload[current_side] = pose
    output = ik.update(payload, state)
    assert ik.tracking_status["state"] == "ok"
    current = np.array(ik.robot.get_T_world_frame(ik.tip_frames[side]))
    position_error_m, orientation_error_rad = pose_difference(current, ik._target[side])
    assert position_error_m < 1e-3
    assert orientation_error_rad < 1e-2
    changed = np.abs(
        np.array([output[f"arm_{side}_{name}.pos"] for name in ARM_JOINTS])
        - np.array([first[f"arm_{side}_{name}.pos"] for name in ARM_JOINTS])
    )
    assert np.count_nonzero(changed[:4] > 5.0) >= 3


@pytest.mark.parametrize("side", SIDES)
@pytest.mark.parametrize("joint_index,joint_name", tuple(enumerate(ARM_JOINTS)))
@pytest.mark.parametrize("direction", (-1.0, 1.0))
def test_each_joint_can_reach_its_positive_and_negative_fk_pose(side, joint_index, joint_name, direction):
    """Every physical joint must remain usable in the full six-DoF IK chain."""
    ik = _engaged_ik()
    start = ik._read_joints(side)

    requested = start.copy()
    requested[joint_index] += direction * 8.0
    ik._write_joints(side, requested)
    ik.robot.update_kinematics()
    target = np.array(ik.robot.get_T_world_frame(ik.tip_frames[side]))

    ik._write_joints(side, start)
    ik.robot.update_kinematics()
    ik._target[side] = target
    ik.tasks[side].T_world_frame = target

    assert ik._solve(), f"{side} {joint_name} did not converge"
    solved = ik._read_joints(side)
    current = np.array(ik.robot.get_T_world_frame(ik.tip_frames[side]))
    position_error_m, orientation_error_rad = pose_difference(current, target)

    assert direction * (solved[joint_index] - start[joint_index]) > 6.0
    assert position_error_m < 5e-4
    assert orientation_error_rad < 5e-3


def test_public_update_homes_loaded_posture_before_tracking():
    """Regression: a newly gripped loaded posture homes before tracking."""
    ik = AlohaMiniDualArmIK(
        URDF_PATH,
        fixed_dt=0.04,
        smooth=1.0,
        max_joint_speed_deg_s=10_000.0,
        max_state_deviation_deg=None,
        solver_iterations=100,
    )
    state = _home_state()
    payload = _controller_payload()
    state["arm_left_shoulder_lift.pos"] = -39.0

    homing = ik.update(payload, state)
    assert homing
    assert ik.homing is True
    assert ik.active is False
    state["arm_left_shoulder_lift.pos"] = -41.5
    engaged = ik.update(payload, state)
    assert engaged
    assert ik.active is True
    state.update(engaged)

    before = {side: np.array([engaged[f"arm_{side}_{name}.pos"] for name in ARM_JOINTS]) for side in SIDES}
    for side in SIDES:
        payload[side]["position"][2] = -0.06
    followed = ik.update(payload, state)

    assert ik.tracking_status["state"] == "ok"
    for side in SIDES:
        after = np.array([followed[f"arm_{side}_{name}.pos"] for name in ARM_JOINTS])
        delta = np.abs(after - before[side])
        assert np.count_nonzero(delta[:5] > 0.5) >= 3
        assert delta[ARM_JOINTS.index("shoulder_lift")] > 5.0
        assert delta[ARM_JOINTS.index("elbow_flex")] > 5.0
        assert ik.tracking_status["sides"][side]["position_error_mm"] < 1.0


def test_public_update_tracks_multi_point_path_with_multi_joint_coordination():
    ik = AlohaMiniDualArmIK(
        URDF_PATH,
        fixed_dt=0.04,
        smooth=1.0,
        max_joint_speed_deg_s=10_000.0,
        max_state_deviation_deg=None,
        solver_iterations=100,
    )
    state = _home_state()
    payload = _controller_payload()
    previous = ik.update(payload, state)
    state.update(previous)

    path = (
        (0.0, 0.0, -0.06),
        (0.04, 0.03, -0.06),
        (-0.04, 0.05, -0.03),
        (-0.03, -0.03, 0.02),
    )
    for point in path:
        for side in SIDES:
            payload[side]["position"] = list(point)
        current = ik.update(payload, state)
        assert ik.tracking_status["state"] == "ok"
        for side in SIDES:
            old_joints = np.array([previous[f"arm_{side}_{name}.pos"] for name in ARM_JOINTS])
            new_joints = np.array([current[f"arm_{side}_{name}.pos"] for name in ARM_JOINTS])
            assert np.count_nonzero(np.abs(new_joints - old_joints) > 0.5) >= 3
            assert ik.tracking_status["sides"][side]["position_error_mm"] < 1.0
        state.update(current)
        previous = current


def test_payload_mode_switch_reanchors_without_command_jump():
    """Changing orientation priority keeps the current measured pose as the anchor."""
    ik = AlohaMiniDualArmIK(
        URDF_PATH,
        fixed_dt=0.04,
        smooth=1.0,
        max_joint_speed_deg_s=10_000.0,
        max_state_deviation_deg=None,
        solver_iterations=100,
    )
    state = _home_state()
    payload = _controller_payload()
    first = ik.update(payload, state)
    assert first and ik.control_mode == "full_pose"
    state.update(first)

    # Hold the controller still while changing only the task priority.  Re-anchoring
    # from measured FK should make this a continuity-preserving mode switch.
    payload["control_mode"] = "telegrip"
    switched = ik.update(payload, state)
    assert switched
    assert ik.control_mode == "telegrip"
    # Placo's FrameTask does not expose its configured weights; the IK keeps the
    # effective value explicitly so runtime diagnostics and replay can verify it.
    assert ik._task_orientation_weight == pytest.approx(ik.orientation_weight * 0.25)
    for side in SIDES:
        deltas = np.array(
            [switched[f"arm_{side}_{name}.pos"] - first[f"arm_{side}_{name}.pos"] for name in ARM_JOINTS]
        )
        assert np.max(np.abs(deltas)) < 1.0
    assert ik.active_sides == {"left": True, "right": True}


def _solve_forward_offset(
    distance_m: float,
    joint_limits_deg: dict[str, dict[str, tuple[float, float]]] | None = None,
) -> tuple[AlohaMiniDualArmIK, bool]:
    """Solve a fresh home target translated along the robot's forward (-y) axis."""
    ik = AlohaMiniDualArmIK(
        URDF_PATH,
        fixed_dt=0.04,
        smooth=1.0,
        max_joint_speed_deg_s=10_000.0,
        max_state_deviation_deg=None,
        solver_iterations=100,
        joint_limits_deg=joint_limits_deg,
    )
    state = _home_state()
    ik.update(_controller_payload(), state)
    for side in SIDES:
        ik._target[side][1, 3] -= distance_m
        ik.tasks[side].T_world_frame = ik._target[side]
    converged = ik._solve()
    ik._update_tracking_status(converged)
    return ik, converged


def test_forward_reach_capacity_with_raw_urdf_limits():
    """The URDF chain reaches 16 cm forward but is near its geometric limit at 18 cm."""
    reachable, converged = _solve_forward_offset(0.16)
    assert converged
    for side in SIDES:
        status = reachable.tracking_status["sides"][side]
        assert status["position_error_mm"] < 1.0
        assert status["limited_joints"] == []

    beyond, converged = _solve_forward_offset(0.18)
    assert not converged
    for side in SIDES:
        status = beyond.tracking_status["sides"][side]
        assert status["position_error_mm"] > 1.0


def test_forward_reach_capacity_respects_example_calibrated_joint_limits():
    """A representative +-90 deg calibration stops forward reach at shoulder lift."""
    limits = {side: dict.fromkeys(ARM_JOINTS, (-90.0, 90.0)) for side in SIDES}

    reachable, converged = _solve_forward_offset(0.10, limits)
    assert converged
    for side in SIDES:
        assert reachable.tracking_status["sides"][side]["position_error_mm"] < 1.0

    beyond, converged = _solve_forward_offset(0.11, limits)
    assert not converged
    for side in SIDES:
        status = beyond.tracking_status["sides"][side]
        assert status["position_error_mm"] > 1.0
        assert "shoulder_lift" in status["limited_joints"]
