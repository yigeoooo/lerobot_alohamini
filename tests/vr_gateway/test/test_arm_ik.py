from __future__ import annotations

import importlib
import importlib.machinery
import sys
import types
from pathlib import Path

import numpy as np
import pytest


URDF_PATH = (
    Path(__file__).parents[2]
    / "src/lerobot/vr_gateway/assets/alohamini2pro/urdf/alohamini2pro.urdf"
)


class _FakeFrameTask:
    def __init__(self, robot, frame_name, target):
        self.robot = robot
        self.frame_name = frame_name
        self.T_world_frame = target
        self.position_weight = 1.0
        self.orientation_weight = 0.5

    def configure(self, *args, **kwargs):
        return None


class _FakePostureTask:
    def __init__(self):
        self.joints = {}

    def set_joints(self, joints):
        self.joints = dict(joints)

    def configure(self, *args, **kwargs):
        return None


class _FakeSolver:
    def __init__(self, robot):
        self.robot = robot
        self.dt = 0.04
        self._frame_tasks = {}

    def mask_fbase(self, *args, **kwargs):
        return None

    def mask_dof(self, *args, **kwargs):
        return None

    def enable_joint_limits(self, *args, **kwargs):
        return None

    def enable_velocity_limits(self, *args, **kwargs):
        return None

    def add_regularization_task(self, *args, **kwargs):
        return None

    def add_frame_task(self, frame_name, target):
        task = _FakeFrameTask(self.robot, frame_name, target)
        self._frame_tasks[frame_name] = task
        return task

    def add_joints_task(self):
        return _FakePostureTask()

    def solve(self, *args, **kwargs):
        return True


class _FakeRobot:
    def __init__(self, *_args, **_kwargs):
        self._joint_names = [
            "left_shoulder_pan",
            "left_shoulder_lift",
            "left_elbow_flex",
            "left_wrist_flex",
            "left_wrist_yaw_joint",
            "left_wrist_roll",
            "right_shoulder_pan",
            "right_shoulder_lift",
            "right_elbow_flex",
            "right_wrist_flex",
            "right_wrist_yaw_joint",
            "right_wrist_roll",
            "vertical_move",
            "left_gripper",
            "right_gripper",
            "base_x",
        ]
        self._frames = ["left_Moving_Jaw", "right_Moving_Jaw"]
        self._joint_values = {name: 0.0 for name in self._joint_names}
        self.state = types.SimpleNamespace(q=np.zeros(len(self._joint_names), dtype=float))

    def joint_names(self):
        return list(self._joint_names)

    def frame_names(self):
        return list(self._frames)

    def get_joint_limits(self, name):
        return (-np.pi, np.pi)

    def set_joint(self, name, value):
        self._joint_values[name] = float(value)

    def get_joint(self, name):
        return float(self._joint_values[name])

    def update_kinematics(self):
        return None

    def get_T_world_frame(self, frame_name):
        idx = 0 if frame_name.startswith("left") else 1
        T = np.eye(4)
        T[0, 3] = 0.2 + 0.01 * idx
        T[1, 3] = 0.1 * idx
        T[2, 3] = 0.3
        T[:3, :3] = np.eye(3)
        return T


@pytest.fixture
def fake_placo(monkeypatch):
    from lerobot.utils import import_utils

    fake = types.ModuleType("placo")
    fake.RobotWrapper = _FakeRobot
    fake.KinematicsSolver = _FakeSolver
    fake.__spec__ = importlib.machinery.ModuleSpec("placo", loader=None)
    monkeypatch.setitem(sys.modules, "placo", fake)
    monkeypatch.setattr(import_utils, "is_package_available", lambda *args, **kwargs: True)
    import_utils._require_package_cache.clear()
    return fake


@pytest.fixture
def arm_ik_module(fake_placo):
    import lerobot.vr_gateway.arm_ik as arm_ik

    return importlib.reload(arm_ik)


def _make_pose(x=0.0, y=0.0, z=0.0):
    return {
        "position": [x, y, z],
        "orientation": [0.0, 0.0, 0.0, 1.0],
    }


def test_pose_to_matrix_uses_xyzw_quaternion_order(arm_ik_module):
    pose = {
        "position": [1.0, 2.0, 3.0],
        "orientation": [0.0, 0.0, 1.0, 0.0],
    }
    T = arm_ik_module.pose_to_matrix(pose)
    assert T is not None
    np.testing.assert_allclose(T[:3, 3], [1.0, 2.0, 3.0])
    np.testing.assert_allclose(T[:3, :3], np.diag([-1.0, -1.0, 1.0]), atol=1e-7)


def test_compose_target_applies_relative_delta_from_origin(arm_ik_module):
    home = np.eye(4)
    home[:3, 3] = [0.4, -0.2, 0.7]
    origin = np.eye(4)
    origin[:3, 3] = [0.1, 0.2, 0.3]
    current = np.eye(4)
    current[:3, 3] = [0.6, 0.7, 0.8]
    target = arm_ik_module.compose_target(home, origin, current, np.eye(3), position_scale=0.5)
    np.testing.assert_allclose(target[:3, 3], [0.65, 0.05, 0.95])
    np.testing.assert_allclose(target[:3, :3], np.eye(3))


def test_compose_target_composes_relative_rotation_onto_home(arm_ik_module):
    """The orientation mapping matches ``current * inverse(origin) * home``."""
    def z_rotation(angle):
        c, s = np.cos(angle), np.sin(angle)
        return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])

    home = np.eye(4)
    home[:3, :3] = z_rotation(-0.3)
    origin = np.eye(4)
    origin[:3, :3] = z_rotation(0.4)
    current = np.eye(4)
    current[:3, :3] = z_rotation(1.1)

    target = arm_ik_module.compose_target(home, origin, current, np.eye(3))
    expected = current[:3, :3] @ origin[:3, :3].T @ home[:3, :3]
    np.testing.assert_allclose(target[:3, :3], expected, atol=1e-7)


def test_compose_target_maps_translation_and_rotation_through_robot_basis(arm_ik_module):
    """The shared WebXR delta is rotated once into the robot base frame."""
    basis = arm_ik_module.VR_TO_ROBOT
    home = np.eye(4)
    home[:3, 3] = [0.3, -0.2, 0.5]
    origin = np.eye(4)
    current = np.eye(4)
    current[:3, 3] = [0.1, 0.2, 0.3]

    target = arm_ik_module.compose_target(home, origin, current, basis, position_scale=0.5)
    np.testing.assert_allclose(target[:3, 3], home[:3, 3] + 0.5 * basis @ current[:3, 3])
    np.testing.assert_allclose(target[:3, :3], basis @ basis.T)


def test_robot_basis_maps_vr_right_to_robot_negative_x(arm_ik_module):
    """The robot's own +x axis points left (URDF: left_Base at x=+0.187, right_Base at x=-0.187),
    so a vr +x (right) hand motion must map to robot -x, not robot +x."""
    np.testing.assert_allclose(arm_ik_module.VR_TO_ROBOT @ np.array([1.0, 0.0, 0.0]), [-1.0, 0.0, 0.0])


def test_robot_basis_maps_vr_up_to_robot_positive_z(arm_ik_module):
    """Lifting the controller (vr +y) must raise the gripper (robot +z), not lower it."""
    np.testing.assert_allclose(arm_ik_module.VR_TO_ROBOT @ np.array([0.0, 1.0, 0.0]), [0.0, 0.0, 1.0])


def test_robot_basis_maps_vr_forward_to_robot_forward(arm_ik_module):
    """vr forward is -z; the robot's own forward is -y, so vr -z must map to robot -y."""
    np.testing.assert_allclose(arm_ik_module.VR_TO_ROBOT @ np.array([0.0, 0.0, -1.0]), [0.0, -1.0, 0.0])


def test_smoothing_deadband_and_joint_rate_limit_are_pure_and_accumulative(arm_ik_module):
    candidate = np.eye(4)
    committed = np.eye(4)
    candidate[0, 3] = 0.001
    assert not arm_ik_module.should_commit_target(candidate, committed, 0.002, 0.01)
    candidate[0, 3] = 0.002
    assert arm_ik_module.should_commit_target(candidate, committed, 0.002, 0.01)

    np.testing.assert_allclose(
        arm_ik_module.clamp_joint_step(np.zeros(2), np.array([100.0, -100.0]), 0.5, 10.0),
        [10.0, -10.0],
    )
    assert arm_ik_module.rate_compensated_smoothing(0.5, 0.08, 0.04) == pytest.approx(0.75)


def _make_state(arm_ik):
    state = {"lift_axis.height_mm": 120.0}
    for side in arm_ik.SIDES:
        for name in arm_ik.ARM_JOINTS:
            state[f"arm_{side}_{name}.pos"] = 0.0
    return state


def _move_state_to_home(arm_ik, state):
    for side in arm_ik.SIDES:
        for name in arm_ik.ARM_JOINTS:
            state[f"arm_{side}_{name}.pos"] = arm_ik.DEFAULT_HOME_POSTURE_DEG[side][name]


def test_update_rejects_missing_state_on_first_engage(arm_ik_module, tmp_path):
    ik = arm_ik_module.AlohaMiniDualArmIK(URDF_PATH, fixed_dt=0.04, state_blend=0.1)
    state = _make_state(arm_ik_module)
    state.pop("arm_left_wrist_roll.pos")
    payload = {
        "active": True,
        "left": _make_pose(),
        "right": _make_pose(0.1),
    }
    assert ik.update(payload, state) == {}
    assert ik.active is False
    assert "missing_state" in (ik.engage_reason or "")


def test_update_engages_and_reanchors(arm_ik_module):
    ik = arm_ik_module.AlohaMiniDualArmIK(URDF_PATH, fixed_dt=0.04, state_blend=0.1)
    state = _make_state(arm_ik_module)
    _move_state_to_home(arm_ik_module, state)
    payload = {
        "active": True,
        "left": _make_pose(),
        "right": _make_pose(0.1),
    }
    assert ik.update(payload, state)
    payload2 = {
        "active": True,
        "left": _make_pose(0.02),
        "right": _make_pose(0.12),
        "reanchor": True,
    }
    assert ik.update(payload2, state)
    assert ik.active is True
    assert ik.engage_reason is None


def test_update_homes_before_engage_and_engages_as_soon_as_home_is_measured(arm_ik_module):
    ik = arm_ik_module.AlohaMiniDualArmIK(URDF_PATH, fixed_dt=0.04)
    state = _make_state(arm_ik_module)
    payload = {
        "active": True,
        "left": _make_pose(),
        "right": _make_pose(0.1),
    }

    first = ik.update(payload, state)

    assert first
    assert ik.active is False
    assert ik.homing is True
    assert ik.engage_reason == "homing"
    assert first["arm_left_shoulder_lift.pos"] == pytest.approx(-0.8)
    assert ik.home_max_error_deg == pytest.approx(85.5)

    _move_state_to_home(arm_ik_module, state)

    second = ik.update(payload, state)

    assert second
    assert ik.active is True
    assert ik.homing is False
    assert ik.engage_reason is None
    assert ik.home_max_error_deg == 0.0


def test_initial_reanchor_request_does_not_bypass_homing(arm_ik_module):
    ik = arm_ik_module.AlohaMiniDualArmIK(URDF_PATH, fixed_dt=0.04)
    state = _make_state(arm_ik_module)
    payload = {
        "active": True,
        "left": _make_pose(),
        "right": _make_pose(0.1),
        "reanchor": True,
    }

    out = ik.update(payload, state)

    assert out
    assert ik.active is False
    assert ik.homing is True
    assert ik.engage_reason == "homing"


def test_homing_command_accumulates_past_loaded_joint_deadband(arm_ik_module):
    ik = arm_ik_module.AlohaMiniDualArmIK(
        URDF_PATH,
        fixed_dt=0.04,
        home_max_state_deviation_deg=5.0,
    )
    state = _make_state(arm_ik_module)
    payload = {
        "active": True,
        "left": _make_pose(),
        "right": _make_pose(0.1),
    }

    outputs = [ik.update(payload, state) for _ in range(8)]

    assert outputs[0]["arm_left_shoulder_lift.pos"] == pytest.approx(-0.8)
    assert outputs[1]["arm_left_shoulder_lift.pos"] == pytest.approx(-1.6)
    assert outputs[-1]["arm_left_shoulder_lift.pos"] == pytest.approx(-5.0)
    assert ik.active is False
    assert ik.homing is True


def test_update_holds_on_short_pose_drop(arm_ik_module):
    ik = arm_ik_module.AlohaMiniDualArmIK(URDF_PATH, fixed_dt=0.04, state_blend=0.1)
    state = _make_state(arm_ik_module)
    payload = {
        "active": True,
        "left": _make_pose(),
        "right": _make_pose(0.1),
    }
    out1 = ik.update(payload, state)
    payload["left"] = None
    assert ik.update(payload, state) == {}
    assert out1
