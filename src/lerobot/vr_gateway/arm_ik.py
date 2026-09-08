"""Quest 3 (WebXR) controller poses -> AlohaMini 2 Pro dual-arm joint targets.

The gateway feeds :meth:`AlohaMiniDualArmIK.update` a WebXR payload and the latest
robot state; it returns absolute joint targets in **degrees** (the robot is built
with ``use_degrees=True``, so ``arm_*.pos`` values are degrees, except the gripper
which is always ``RANGE_0_100``).

Coordinate conventions used throughout:

* WebXR reference space: ``+x`` right, ``+y`` up, ``-z`` forward (away from the user).
* AlohaMini ``base_link`` (verified against the URDF: ``front_camera`` sits at
  ``y = -0.055``, ``left_Base`` at ``x = +0.187``): ``-y`` forward, ``+x`` left,
  ``+z`` up.

Both the clutch reference and the live controller pose live in the *same* WebXR
reference space, so relative motion is composed in that shared world frame and then
rotated once into the robot base frame by :data:`VR_TO_ROBOT`.
"""

from __future__ import annotations

import logging
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import numpy as np

from lerobot.utils.import_utils import require_package

logger = logging.getLogger(__name__)

SIDES: tuple[str, str] = ("left", "right")

# Robot-side joint keys, in the order the arm chain is traversed. These are the
# suffixes used by the robot state/action dicts (``arm_left_shoulder_pan.pos`` ...).
ARM_JOINTS: tuple[str, ...] = (
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_yaw",
    "wrist_roll",
)

# URDF joint names are ``{side}_{suffix}`` except for wrist_yaw, which the CAD export
# named ``{side}_wrist_yaw_joint``. Verified against the shipped URDF.
_URDF_JOINT_SUFFIX_OVERRIDES = {"wrist_yaw": "wrist_yaw_joint"}

# The mobile lift column that the shoulders are mounted on. Its URDF joint
# (``vertical_move``, a prismatic torso lift with a +-0.3 m / 600 mm range) was
# previously frozen at 0 regardless of the robot's actual lift height, so the IK
# model's idea of "where the shoulders are" could be off by up to +-300 mm from
# reality -- enough to push the arm's shoulder/elbow/wrist chain into a different
# posture than the one that actually reaches a given world-frame target, which
# looks like the vertical/wrist axes responding backwards. Both spans are exactly
# 600 mm (robot: ``lift_axis.height_mm`` in [0, 600]; URDF: vertical_move in
# [-0.3, 0.3]), so the two are rescaled 1:1.
LIFT_JOINT_NAME = "vertical_move"
LIFT_HEIGHT_STATE_KEY = "lift_axis.height_mm"

# A physically verified "gripper forward" posture (robot-frame degrees, i.e. the
# same space as ``arm_{side}_{name}.pos``): confirmed by photo + FK cross-check to
# be a stable, safe elbow-up configuration that matches the URDF's own kinematic
# branch (see arm_ik_development notes). The IK model can only track correctly
# once the real arm is in the same branch the model assumes; if the operator
# clutches in from an arbitrary pose (e.g. hanging straight down, which sits in
# the *opposite* branch), the differential solver fights the real arm and the
# vertical/wrist axes appear to move backwards. Ramping to this posture before
# every engage removes that ambiguity.
DEFAULT_HOME_POSTURE_DEG: dict[str, dict[str, float]] = {
    "left": {
        "shoulder_pan": -7.5,
        "shoulder_lift": -82.8,
        "elbow_flex": 80.0,
        "wrist_flex": 22.7,
        "wrist_yaw": 6.3,
        "wrist_roll": -3.4,
    },
    "right": {
        "shoulder_pan": -7.3,
        "shoulder_lift": -85.5,
        "elbow_flex": 83.1,
        "wrist_flex": 18.6,
        "wrist_yaw": 2.4,
        "wrist_roll": -8.0,
    },
}

# Maps a WebXR vector into the robot base frame. The robot's own +x axis points
# *left*, not right (see the module docstring: verified against the URDF, where
# left_Base sits at x = +0.187 and right_Base at x = -0.187), so:
#   vr +x (right)    -> robot -x (right is the robot's -x, since its +x is left)
#   vr +y (up)       -> robot +z (up)
#   vr -z (forward)  -> robot -y (forward, since the robot's +y is backward)
# det(+1), so this is a proper rotation.
VR_TO_ROBOT: np.ndarray = np.array(
    [
        [-1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0],
        [0.0, 1.0, 0.0],
    ],
    dtype=float,
)


# --------------------------------------------------------------------------------------
# Pure geometry helpers (no placo needed -- kept module level so they stay unit testable)
# --------------------------------------------------------------------------------------
def quaternion_to_matrix(quaternion: np.ndarray) -> np.ndarray | None:
    """Convert a WebXR ``(x, y, z, w)`` quaternion to a rotation matrix, or ``None`` if invalid."""
    q = np.asarray(quaternion, dtype=float)
    if q.shape != (4,) or not np.isfinite(q).all():
        return None
    norm = float(np.linalg.norm(q))
    if norm < 1e-8:
        return None
    x, y, z, w = q / norm
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def pose_to_matrix(pose: dict[str, Any] | None) -> np.ndarray | None:
    """Build a 4x4 homogeneous transform from a ``{"position", "orientation"}`` payload.

    WebXR controller poses arrive as position plus XYZW quaternion. The matrix is a
    standard homogeneous transform in that same world frame.
    """
    if not pose:
        return None
    position = np.asarray(pose.get("position", [0.0, 0.0, 0.0]), dtype=float)
    if position.shape != (3,) or not np.isfinite(position).all():
        return None
    rotation = quaternion_to_matrix(pose.get("orientation", [0.0, 0.0, 0.0, 1.0]))
    if rotation is None:
        return None
    transform = np.eye(4)
    transform[:3, :3] = rotation
    transform[:3, 3] = position
    return transform


def rotation_log(rotation: np.ndarray) -> np.ndarray:
    """Rotation matrix -> rotation vector (axis * angle)."""
    r = np.asarray(rotation, dtype=float)
    cos_angle = float(np.clip((np.trace(r) - 1.0) / 2.0, -1.0, 1.0))
    angle = float(np.arccos(cos_angle))
    if angle < 1e-9:
        # Near identity the first-order term is exact enough and numerically stable.
        return np.array([r[2, 1] - r[1, 2], r[0, 2] - r[2, 0], r[1, 0] - r[0, 1]]) / 2.0
    if np.pi - angle < 1e-6:
        # Near pi the skew part vanishes; recover the axis from the symmetric part.
        axis_squared = np.clip(np.diag(r) - cos_angle, 0.0, None) / (1.0 - cos_angle)
        axis = np.sqrt(axis_squared)
        major = int(np.argmax(axis))
        # Fix the relative signs from the (small but non-zero) skew part.
        skew = np.array([r[2, 1] - r[1, 2], r[0, 2] - r[2, 0], r[1, 0] - r[0, 1]])
        if skew[major] < 0:
            axis = -axis
        for i in range(3):
            if i != major and skew[i] * axis[major] * axis[i] < 0:
                axis[i] = -axis[i]
        norm = float(np.linalg.norm(axis))
        if norm < 1e-12:
            return np.zeros(3)
        return axis / norm * angle
    skew = np.array([r[2, 1] - r[1, 2], r[0, 2] - r[2, 0], r[1, 0] - r[0, 1]])
    return skew * (angle / (2.0 * np.sin(angle)))


def rotation_exp(rotation_vector: np.ndarray) -> np.ndarray:
    """Rotation vector (axis * angle) -> rotation matrix (Rodrigues)."""
    v = np.asarray(rotation_vector, dtype=float)
    angle = float(np.linalg.norm(v))
    if angle < 1e-12:
        return np.eye(3)
    axis = v / angle
    k = np.array(
        [
            [0.0, -axis[2], axis[1]],
            [axis[2], 0.0, -axis[0]],
            [-axis[1], axis[0], 0.0],
        ]
    )
    return np.eye(3) + np.sin(angle) * k + (1.0 - np.cos(angle)) * (k @ k)


def rotation_angle(rotation: np.ndarray) -> float:
    """Geodesic angle of a rotation matrix, in radians."""
    return float(np.linalg.norm(rotation_log(rotation)))


def scale_rotation(rotation: np.ndarray, scale: float) -> np.ndarray:
    """Interpolate a rotation towards identity: ``exp(scale * log(R))``."""
    if abs(scale - 1.0) < 1e-12:
        return np.asarray(rotation, dtype=float)
    return rotation_exp(scale * rotation_log(rotation))


def orthonormalize(rotation: np.ndarray) -> np.ndarray:
    """Project a nearly-orthonormal matrix back onto SO(3) (nearest rotation)."""
    u, _, vt = np.linalg.svd(np.asarray(rotation, dtype=float))
    r = u @ vt
    if np.linalg.det(r) < 0:
        u[:, -1] *= -1.0
        r = u @ vt
    return r


def compose_target(
    robot0: np.ndarray,
    ctrl0: np.ndarray,
    ctrl: np.ndarray,
    basis: np.ndarray,
    position_scale: float = 1.0,
    orientation_scale: float = 1.0,
) -> np.ndarray:
    """Retarget the current controller pose relative to the clutch-time origin.

    The mapping is the same idea as IsaacTeleop's clutch retargeting, but implemented
    locally: keep the robot's latched home pose, then apply the controller delta
    relative to the latched origin.

    In math form:

    - ``home`` = ``robot0``
    - ``origin`` = ``ctrl0``
    - ``current`` = ``ctrl``
    - ``delta`` = ``current * inverse(origin)``
    - ``target`` = ``delta * home``

    The WebXR pose payloads use XYZW quaternions; the controller translation delta is
    composed explicitly as ``home + scale * (current - origin)`` so the hand moves in
    the shared reference space rather than in the controller's local frame.
    """
    home = np.asarray(robot0, dtype=float)
    origin = np.asarray(ctrl0, dtype=float)
    current = np.asarray(ctrl, dtype=float)
    position_delta = current[:3, 3] - origin[:3, 3]
    rotation_delta = current[:3, :3] @ origin[:3, :3].T
    rotation_delta = scale_rotation(rotation_delta, orientation_scale)

    target = np.eye(4)
    target[:3, 3] = home[:3, 3] + position_scale * (basis @ position_delta)
    # Re-project onto SO(3): the solver is handed this matrix directly, and a chain of
    # products must not be allowed to drift off the manifold.
    target[:3, :3] = orthonormalize((basis @ rotation_delta @ basis.T) @ home[:3, :3])
    return target


def pose_difference(a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    """Return ``(translation_m, rotation_rad)`` between two 4x4 transforms."""
    translation = float(np.linalg.norm(a[:3, 3] - b[:3, 3]))
    rotation = rotation_angle(a[:3, :3].T @ b[:3, :3])
    return translation, rotation


def should_commit_target(
    candidate: np.ndarray,
    committed: np.ndarray,
    deadband_m: float,
    deadband_rad: float,
) -> bool:
    """Deadband test against the last *committed* target rather than the previous frame.

    Comparing frame to frame would reject any motion slower than
    ``deadband_m / tick_period`` forever (2 mm at 25 Hz == 5 cm/s, i.e. every deliberate
    manipulation move). Comparing against the committed target lets slow motion
    accumulate until it clears the threshold, and then applies all of it at once, which
    also gives the hysteresis: right after a commit the residual is zero again.
    """
    translation, rotation = pose_difference(candidate, committed)
    return translation >= deadband_m or rotation >= deadband_rad


def clamp_joint_step(
    previous_deg: np.ndarray,
    target_deg: np.ndarray,
    smoothing: float,
    max_delta_deg: float,
) -> np.ndarray:
    """Blend towards ``target_deg`` then clamp the per-tick travel.

    ``smoothing`` is the (already rate-compensated) EMA factor in ``[0, 1]``;
    ``max_delta_deg`` is the absolute per-joint travel budget for this tick.
    """
    previous = np.asarray(previous_deg, dtype=float)
    step = smoothing * (np.asarray(target_deg, dtype=float) - previous)
    return previous + np.clip(step, -max_delta_deg, max_delta_deg)


def rate_compensated_smoothing(smoothing: float, dt: float, nominal_dt: float) -> float:
    """Rescale an EMA factor tuned for ``nominal_dt`` so it behaves the same at ``dt``.

    Keeps the effective time constant fixed when the browser's frame rate wanders.
    """
    smoothing = float(np.clip(smoothing, 0.0, 1.0))
    if smoothing >= 1.0 or nominal_dt <= 0.0 or dt <= 0.0:
        return smoothing
    return float(np.clip(1.0 - (1.0 - smoothing) ** (dt / nominal_dt), 0.0, 1.0))


# --------------------------------------------------------------------------------------
# URDF preparation
# --------------------------------------------------------------------------------------
def _sanitize_urdf(source: Path, velocity_limit_rad_s: float) -> str:
    """Return URDF XML text stripped of meshes and made safe for pinocchio/placo.

    Two things happen here:

    1. ``visual``/``collision`` elements are dropped so no mesh files have to resolve.
    2. ``continuous`` joints are rewritten as bounded ``revolute`` joints. A continuous
       joint occupies two ``q`` slots (cos/sin) in pinocchio, but placo's
       name -> ``q`` index lookup assumes one slot per joint, so **every joint declared
       after a continuous joint gets addressed one slot too early**. On this URDF that
       silently redirected ``set_joint("left_shoulder_pan", ...)`` onto ``vertical_move``.

    ``velocity`` limits are also filled in: the export ships ``velocity="0"``, which
    would freeze the solver once velocity limits are enabled.
    """
    root = ET.fromstring(source.read_text(encoding="utf-8"))
    for element in list(root):
        if element.tag not in ("link", "joint"):
            continue
        for tag in ("visual", "collision"):
            for child in element.findall(tag):
                element.remove(child)
        if element.tag != "joint":
            continue
        limit = element.find("limit")
        if element.get("type") == "continuous":
            element.set("type", "revolute")
            if limit is None:
                limit = ET.SubElement(element, "limit")
            limit.set("lower", f"{-np.pi:.6f}")
            limit.set("upper", f"{np.pi:.6f}")
        if limit is not None:
            if float(limit.get("effort", "0") or 0.0) <= 0.0:
                limit.set("effort", "100")
            if float(limit.get("velocity", "0") or 0.0) <= 0.0:
                limit.set("velocity", f"{velocity_limit_rad_s:.6f}")
    return ET.tostring(root, encoding="unicode")


# --------------------------------------------------------------------------------------
# Main controller
# --------------------------------------------------------------------------------------
class AlohaMiniDualArmIK:
    """Differential-IK retargeting of two Quest controllers onto the AlohaMini arms."""

    def __init__(
        self,
        urdf_path: str | Path,
        smooth: float = 0.7,
        max_step_deg: float | None = None,
        *,
        position_scale: float = 0.5,
        orientation_scale: float = 1.0,
        position_weight: float = 1.0,
        orientation_weight: float = 1.0,
        posture_weight: float = 5e-4,
        regularization: float = 1e-5,
        solver_dt: float = 0.04,
        solver_iterations: int = 20,
        position_tolerance_m: float = 5e-4,
        orientation_tolerance_rad: float = 5e-3,
        max_joint_speed_deg_s: float = 180.0,
        max_state_deviation_deg: float | None = 45.0,
        joint_limits_deg: dict[str, tuple[float, float]] | None = None,
        deadband_m: float = 0.0015,
        deadband_rad: float = 0.01,
        nominal_dt: float = 0.04,
        min_dt: float = 0.005,
        max_dt: float = 0.2,
        fixed_dt: float | None = None,
        state_blend: float = 0.0,
        tip_frame_template: str = "{side}_Moving_Jaw",
        vr_to_robot: np.ndarray | None = None,
        joint_signs: dict[str, float] | None = None,
        joint_offsets_deg: dict[str, float] | None = None,
        lift_height_mm_range: tuple[float, float] = (0.0, 600.0),
        home_posture_deg: dict[str, dict[str, float]] | None = None,
        home_speed_deg_s: float = 20.0,
        home_tolerance_deg: float = 2.0,
        home_max_state_deviation_deg: float = 5.0,
    ):
        """
        Args:
            urdf_path: Path to the AlohaMini 2 Pro URDF.
            smooth: EMA factor applied to the IK result, expressed at ``nominal_dt``.
                1.0 means "no smoothing"; it is rate-compensated against the real tick.
            max_step_deg: Legacy fixed per-tick degree cap. ``None`` (default) uses the
                rate-correct ``max_joint_speed_deg_s`` budget instead.
            position_scale: Hand displacement -> gripper displacement gain. The arm's
                full reach measured from the URDF is ~0.54 m (comfortable radius
                ~0.30 m) while a seated human sweeps ~0.7 m, so 0.5 maps a full human
                sweep onto roughly the usable robot workspace.
            orientation_scale: Same idea for wrist rotation; 1.0 keeps rotation 1:1.
            position_weight: placo frame-task weight on the position sub-task.
            orientation_weight: placo frame-task weight on the orientation sub-task.
                Must be > 0 or the commanded wrist orientation is ignored entirely.
            posture_weight: Weight of the low-priority shoulder/elbow posture task that
                pins non-wrist joints to their clutch-time posture. Wrist joints are
                deliberately excluded so rotation remains responsive.
            regularization: placo regularization task weight (keeps the QP well posed).
            solver_dt: Integration step handed to placo, used by its joint/velocity
                limit constraints.
            solver_iterations: Max differential-IK iterations per tick.
            position_tolerance_m: Early-exit translation tolerance for the solve loop.
            orientation_tolerance_rad: Early-exit rotation tolerance for the solve loop.
            max_joint_speed_deg_s: Output velocity clamp, applied as ``speed * dt``.
            max_state_deviation_deg: Hard cap on how far a commanded joint may run away
                from the *measured* joint, applied only when the state actually reports
                that joint. This is the IK-side equivalent of the robot's
                ``max_relative_target`` (which the gateway currently leaves disabled) and
                bounds the damage from an open-loop runaway or a current-limited /
                stalled servo. ``None`` disables it.
            joint_limits_deg: Per-joint ``(lower, upper)`` override in URDF degrees. The
                shipped URDF declares a uniform +-180 deg, which is far wider than the
                real servo travel, so this should be narrowed once measured on hardware.
            deadband_m: Translation deadband measured against the last *committed*
                target (not frame to frame), so slow motion still accumulates through.
            deadband_rad: Rotation deadband, same accumulate-then-commit semantics.
            nominal_dt: Tick period ``smooth`` was tuned at.
            min_dt / max_dt: Clamp on the measured wall-clock tick period.
            fixed_dt: Bypass the wall clock and assume this tick period. Use when the
                caller drives ``update`` at a known fixed rate, or for reproducible
                tests; ``None`` (default) measures the real period.
            state_blend: Fraction of the *measured* joint state blended into the IK
                seed each tick. 0.0 (default) seeds purely from the last command, which
                is smooth but open loop: if a servo stalls, the model and the hardware
                drift apart. A small value (0.05-0.2) closes that loop at the cost of
                feeding servo jitter back into the solver.
            tip_frame_template: URDF frame driven by the controller, per side.
            vr_to_robot: Override for the WebXR -> robot base rotation.
            joint_signs: Per-joint ``+1/-1`` correction if the servo direction disagrees
                with the URDF axis. Keys are entries of :data:`ARM_JOINTS`.
            joint_offsets_deg: Per-joint zero offset, ``robot_deg = sign * urdf_deg + offset``.
            lift_height_mm_range: The robot's real ``lift_axis.height_mm`` span
                (``LiftAxisConfig.soft_min_mm``/``soft_max_mm``), rescaled 1:1 onto the
                URDF's ``vertical_move`` joint limits every tick so the model's shoulder
                height matches reality instead of being frozen at the URDF's zero.
            home_posture_deg: Per-side, per-joint robot-frame degrees (same units as
                ``arm_{side}_{name}.pos``) the arm ramps to before every engage.
                ``None`` (default) uses :data:`DEFAULT_HOME_POSTURE_DEG`. This exists
                because the arm's shoulder/elbow/wrist chain is kinematically
                redundant: clutching in from an arbitrary posture (e.g. hanging
                straight down) can land the model in the URDF's *other* branch for
                that same tip position, where the differential solver's steering
                direction disagrees with the real servo response -- symptomatically
                indistinguishable from a sign error, but not fixable by one. Starting
                every session from the same verified posture removes the ambiguity.
            home_speed_deg_s: Per-joint angular speed budget for the homing ramp.
                Deliberately much slower than ``max_joint_speed_deg_s`` -- homing
                moves the arm without the operator's hand controlling it, so it must
                be conservative regardless of how fast normal teleop is tuned.
            home_tolerance_deg: Per-joint slack (in degrees) below which the arm is
                considered "at" the home posture and engage may proceed.
            home_max_state_deviation_deg: Maximum lead of the homing command over the
                measured joint. The command ramp must accumulate independently of the
                measured position to overcome loaded-joint static friction, but this
                bound prevents it from running away if a joint is obstructed.
        """
        require_package("placo", extra="placo-dep")
        import placo

        self.smooth = float(smooth)
        self.max_step_deg = None if max_step_deg is None else float(max_step_deg)
        self.position_scale = float(position_scale)
        self.orientation_scale = float(orientation_scale)
        self.position_weight = float(position_weight)
        self.orientation_weight = float(orientation_weight)
        self.posture_weight = float(posture_weight)
        self.solver_iterations = max(1, int(solver_iterations))
        self.position_tolerance_m = float(position_tolerance_m)
        self.orientation_tolerance_rad = float(orientation_tolerance_rad)
        self.max_joint_speed_deg_s = float(max_joint_speed_deg_s)
        self.max_state_deviation_deg = (
            None if max_state_deviation_deg is None else float(max_state_deviation_deg)
        )
        self.deadband_m = float(deadband_m)
        self.deadband_rad = float(deadband_rad)
        self.nominal_dt = float(nominal_dt)
        self.min_dt = float(min_dt)
        self.max_dt = float(max_dt)
        self.fixed_dt = None if fixed_dt is None else float(fixed_dt)
        self._lift_height_mm_range = (
            float(lift_height_mm_range[0]),
            float(lift_height_mm_range[1]),
        )
        self.state_blend = float(np.clip(state_blend, 0.0, 1.0))
        self.active = False

        home_posture = home_posture_deg if home_posture_deg is not None else DEFAULT_HOME_POSTURE_DEG
        unknown_home = {
            side: sorted(set(joints) - set(ARM_JOINTS))
            for side, joints in home_posture.items()
            if set(joints) - set(ARM_JOINTS)
        }
        if set(home_posture) - set(SIDES) or unknown_home:
            raise ValueError(f"home_posture_deg has unexpected sides/joints: {home_posture}")
        self._home_posture_deg = {
            side: {**DEFAULT_HOME_POSTURE_DEG[side], **home_posture.get(side, {})} for side in SIDES
        }
        self.home_speed_deg_s = float(home_speed_deg_s)
        self.home_tolerance_deg = float(home_tolerance_deg)
        self.home_max_state_deviation_deg = float(home_max_state_deviation_deg)
        self._homing = False
        self._homing_command_deg: dict[str, np.ndarray | None] = dict.fromkeys(SIDES)
        self._home_max_error_deg: float | None = None

        self._vr_to_robot = (
            VR_TO_ROBOT.copy() if vr_to_robot is None else np.asarray(vr_to_robot, dtype=float)
        )
        if self._vr_to_robot.shape != (3, 3) or not np.isclose(np.linalg.det(self._vr_to_robot), 1.0):
            raise ValueError("vr_to_robot must be a 3x3 proper rotation matrix (det == +1)")

        self._signs = dict.fromkeys(ARM_JOINTS, 1.0)
        self._signs.update({k: float(v) for k, v in (joint_signs or {}).items()})
        self._offsets = dict.fromkeys(ARM_JOINTS, 0.0)
        self._offsets.update({k: float(v) for k, v in (joint_offsets_deg or {}).items()})
        unknown = (set(joint_signs or {}) | set(joint_offsets_deg or {})) - set(ARM_JOINTS)
        if unknown:
            raise ValueError(f"Unknown joint name(s) in sign/offset override: {sorted(unknown)}")

        self.tip_frames = {side: tip_frame_template.format(side=side) for side in SIDES}
        self.joints = {
            side: [f"{side}_{_URDF_JOINT_SUFFIX_OVERRIDES.get(name, name)}" for name in ARM_JOINTS]
            for side in SIDES
        }

        urdf = Path(urdf_path).resolve()
        if not urdf.is_file():
            raise FileNotFoundError(f"URDF not found: {urdf}")
        xml_text = _sanitize_urdf(urdf, np.deg2rad(self.max_joint_speed_deg_s))
        # placo only reads the file during construction, so a scratch copy is enough.
        with tempfile.TemporaryDirectory(prefix="alohamini_vr_ik_") as tmp:
            scratch = Path(tmp) / urdf.name
            scratch.write_text(xml_text, encoding="utf-8")
            self.robot = placo.RobotWrapper(str(scratch))

        self._validate_model()

        self.solver = placo.KinematicsSolver(self.robot)
        self.solver.mask_fbase(True)
        self.solver.dt = float(solver_dt)
        self.solver.enable_joint_limits(True)
        self.solver.enable_velocity_limits(True)

        # Everything that is not an arm joint (mobile base, lift, gripper jaws) must be
        # frozen: otherwise the solver happily satisfies the frame task by driving the
        # base or the lift, and the arm joints we read back barely move.
        arm_joints = {name for side in SIDES for name in self.joints[side]}
        self.frozen_joints = [name for name in self.robot.joint_names() if name not in arm_joints]
        for name in self.frozen_joints:
            self.robot.set_joint(name, 0.0)
            self.solver.mask_dof(name)

        # The lift is frozen (never solved) like the other non-arm joints above, but
        # unlike them its value must track reality every tick: it is not close enough
        # to a fixed constant for the arm chain to ignore (see LIFT_JOINT_NAME above).
        self._lift_urdf_range: tuple[float, float] | None = None
        if LIFT_JOINT_NAME in self.frozen_joints:
            lo, hi = self.robot.get_joint_limits(LIFT_JOINT_NAME)
            self._lift_urdf_range = (float(lo), float(hi))

        unknown_limits = set(joint_limits_deg or {}) - set(ARM_JOINTS)
        if unknown_limits:
            raise ValueError(f"Unknown joint name(s) in joint_limits_deg: {sorted(unknown_limits)}")
        self.joint_limits_deg = {}
        for side in SIDES:
            limits = np.rad2deg(
                np.array([self.robot.get_joint_limits(n) for n in self.joints[side]], dtype=float)
            )
            for index, name in enumerate(ARM_JOINTS):
                override = (joint_limits_deg or {}).get(name)
                if override is not None:
                    limits[index] = [float(override[0]), float(override[1])]
            self.joint_limits_deg[side] = limits

        self.solver.add_regularization_task(float(regularization))
        self.tasks = {}
        self.posture_tasks = {}
        for side in SIDES:
            task = self.solver.add_frame_task(self.tip_frames[side], np.eye(4))
            # FrameTask.configure(name, priority, position_weight, orientation_weight).
            task.configure(f"{side}_tip", "soft", self.position_weight, self.orientation_weight)
            self.tasks[side] = task
            posture = self.solver.add_joints_task()
            # Keep the redundant shoulder/elbow configuration near engage posture,
            # while leaving every wrist DOF available to satisfy orientation tracking.
            posture.set_joints({
                self.joints[side][index]: 0.0
                for index in range(3)
            })
            posture.configure(f"{side}_posture", "soft", self.posture_weight)
            self.posture_tasks[side] = posture

        self._ctrl0: dict[str, np.ndarray | None] = dict.fromkeys(SIDES)
        self._robot0: dict[str, np.ndarray | None] = dict.fromkeys(SIDES)
        self._target: dict[str, np.ndarray | None] = dict.fromkeys(SIDES)
        self._last_output: dict[str, np.ndarray | None] = dict.fromkeys(SIDES)
        self._last_time: float | None = None
        self._warned_invalid_pose = False
        self._engage_reason: str | None = None

    @staticmethod
    def required_state_keys() -> tuple[str, ...]:
        """State keys needed to safely seed the IK on first engage."""
        keys = ["lift_axis.height_mm"]
        for side in SIDES:
            keys.extend(f"arm_{side}_{name}.pos" for name in ARM_JOINTS)
        return tuple(keys)

    def _missing_state_keys(self, state: dict[str, Any]) -> list[str]:
        return [key for key in self.required_state_keys() if key not in state]

    def _state_is_fresh_and_complete(self, state: dict[str, Any]) -> tuple[bool, str | None]:
        missing = self._missing_state_keys(state)
        if missing:
            return False, f"missing_state:{','.join(missing)}"
        invalid = []
        for key in self.required_state_keys():
            try:
                value = float(state[key])
            except (TypeError, ValueError):
                invalid.append(key)
                continue
            if not np.isfinite(value):
                invalid.append(key)
        if invalid:
            return False, f"invalid_state:{','.join(invalid)}"
        return True, None

    @property
    def engage_reason(self) -> str | None:
        """Latest engage/reanchor rejection reason, if any."""
        return self._engage_reason

    @property
    def homing(self) -> bool:
        return self._homing

    @property
    def home_max_error_deg(self) -> float | None:
        return self._home_max_error_deg

    # -- model checks ------------------------------------------------------------------
    def _validate_model(self) -> None:
        """Fail loudly at construction if the URDF does not match our expectations."""
        joint_names = set(self.robot.joint_names())
        frame_names = set(self.robot.frame_names())
        missing_joints = sorted({n for side in SIDES for n in self.joints[side]} - joint_names)
        missing_frames = sorted(set(self.tip_frames.values()) - frame_names)
        if missing_joints or missing_frames:
            raise ValueError(
                "URDF does not expose the expected AlohaMini arm model. "
                f"Missing joints: {missing_joints or 'none'}. "
                f"Missing frames: {missing_frames or 'none'}. "
                f"Available joints: {sorted(joint_names)}."
            )
        # placo indexes joints by name assuming exactly one configuration slot each.
        # A free flyer adds 7. Anything else means some joint has nq != 1 and every
        # later set_joint()/get_joint() would address the wrong joint.
        extra = int(self.robot.state.q.shape[0]) - len(joint_names)
        if extra not in (0, 7):
            raise ValueError(
                f"Unexpected URDF configuration size (nq={self.robot.state.q.shape[0]}, "
                f"{len(joint_names)} joints): a joint with more than one configuration "
                "slot would silently misalign placo's joint-name lookup."
            )

    # -- unit conversion ---------------------------------------------------------------
    def _state_to_urdf_deg(self, side: str, state: dict[str, Any]) -> np.ndarray:
        """Read measured joint positions (degrees, ``use_degrees=True``) into URDF degrees."""
        values = []
        for name in ARM_JOINTS:
            raw = state.get(f"arm_{side}_{name}.pos", 0.0)
            try:
                robot_deg = float(raw)
            except (TypeError, ValueError):
                robot_deg = 0.0
            if not np.isfinite(robot_deg):
                robot_deg = 0.0
            values.append((robot_deg - self._offsets[name]) * self._signs[name])
        return np.array(values, dtype=float)

    def _measured_urdf_deg(self, side: str, state: dict[str, Any]) -> np.ndarray | None:
        """Measured joints in URDF degrees, or ``None`` if the state does not report them.

        Used for the runaway clamp: silently treating a missing key as 0 deg there would
        clamp every command towards the arm's zero pose.
        """
        if not all(f"arm_{side}_{name}.pos" in state for name in ARM_JOINTS):
            return None
        return self._state_to_urdf_deg(side, state)

    def _urdf_deg_to_robot_deg(self, values: np.ndarray) -> np.ndarray:
        return np.array(
            [v * self._signs[name] + self._offsets[name] for name, v in zip(ARM_JOINTS, values, strict=True)],
            dtype=float,
        )

    def _sync_lift_joint(self, state: dict[str, Any]) -> None:
        """Move the model's frozen ``vertical_move`` joint to match the real lift height.

        Rescales ``lift_axis.height_mm`` (real robot span) onto the URDF's own
        ``vertical_move`` limits 1:1, since both spans are the same 600 mm travel.
        Falls back to the URDF's own zero if the state key is missing/invalid, matching
        the previous behaviour rather than guessing.
        """
        if self._lift_urdf_range is None:
            return
        mm_lo, mm_hi = self._lift_height_mm_range
        urdf_lo, urdf_hi = self._lift_urdf_range
        value = urdf_lo
        if mm_hi > mm_lo:
            try:
                height_mm = float(state.get(LIFT_HEIGHT_STATE_KEY, mm_lo))
            except (TypeError, ValueError):
                height_mm = mm_lo
            if np.isfinite(height_mm):
                frac = float(np.clip((height_mm - mm_lo) / (mm_hi - mm_lo), 0.0, 1.0))
                value = urdf_lo + frac * (urdf_hi - urdf_lo)
        self.robot.set_joint(LIFT_JOINT_NAME, value)

    # -- kinematics helpers ------------------------------------------------------------
    def _write_joints(self, side: str, urdf_deg: np.ndarray) -> None:
        for name, value in zip(self.joints[side], np.deg2rad(urdf_deg), strict=True):
            self.robot.set_joint(name, float(value))

    def _read_joints(self, side: str) -> np.ndarray:
        return np.rad2deg(np.array([self.robot.get_joint(n) for n in self.joints[side]], dtype=float))

    def _target_from_delta(self, side: str, ctrl: np.ndarray) -> np.ndarray:
        """Retarget the current controller pose ``ctrl`` onto side ``side``'s gripper."""
        return compose_target(
            self._robot0[side],
            self._ctrl0[side],
            ctrl,
            self._vr_to_robot,
            self.position_scale,
            self.orientation_scale,
        )

    def _tick_dt(self) -> float:
        if self.fixed_dt is not None:
            return self.fixed_dt
        now = time.monotonic()
        previous, self._last_time = self._last_time, now
        if previous is None:
            return self.nominal_dt
        return float(np.clip(now - previous, self.min_dt, self.max_dt))

    def _reset(self) -> None:
        self.active = False
        self._ctrl0 = dict.fromkeys(SIDES)
        self._robot0 = dict.fromkeys(SIDES)
        self._target = dict.fromkeys(SIDES)
        self._last_output = dict.fromkeys(SIDES)
        self._last_time = None
        self._engage_reason = None
        self._homing = False
        self._homing_command_deg = dict.fromkeys(SIDES)
        self._home_max_error_deg = None

    def _is_at_home_posture(self, state: dict[str, Any]) -> bool:
        for side in SIDES:
            measured = self._measured_urdf_deg(side, state)
            if measured is None:
                return False
            target = np.array(
                [self._home_posture_deg[side][name] for name in ARM_JOINTS], dtype=float
            )
            # Compare in robot-frame degrees (the space home_posture_deg is authored
            # in), not URDF degrees, so joint_signs/joint_offsets_deg don't need to be
            # accounted for twice.
            current = self._urdf_deg_to_robot_deg(measured)
            if np.any(np.abs(current - target) > self.home_tolerance_deg):
                return False
        return True

    def _step_homing(self, state: dict[str, Any], dt: float) -> dict[str, float] | None:
        """Advance one ramp step towards the home posture.

        Returns the next commanded joint dict, or ``None`` if the state is missing
        (nothing safe to command -- caller should hold).
        """
        max_delta_deg = self.home_speed_deg_s * dt
        out: dict[str, float] = {}
        at_home = True
        max_error_deg = 0.0
        for side in SIDES:
            measured = self._measured_urdf_deg(side, state)
            if measured is None:
                return None
            current = self._urdf_deg_to_robot_deg(measured)
            target = np.array(
                [self._home_posture_deg[side][name] for name in ARM_JOINTS], dtype=float
            )
            error = np.abs(current - target)
            max_error_deg = max(max_error_deg, float(np.max(error)))
            if np.any(error > self.home_tolerance_deg):
                at_home = False
            previous = self._homing_command_deg[side]
            if previous is None:
                previous = current.copy()
            step = np.clip(target - previous, -max_delta_deg, max_delta_deg)
            command = previous + step
            if self.home_max_state_deviation_deg > 0:
                command = np.clip(
                    command,
                    current - self.home_max_state_deviation_deg,
                    current + self.home_max_state_deviation_deg,
                )
            self._homing_command_deg[side] = command
            for name, value in zip(ARM_JOINTS, command, strict=True):
                out[f"arm_{side}_{name}.pos"] = float(value)
            # Grippers are not part of the home posture; hold whatever the operator
            # last commanded rather than snapping them shut/open.
            gripper_key = f"arm_{side}_gripper.pos"
            if gripper_key in state:
                try:
                    out[gripper_key] = float(state[gripper_key])
                except (TypeError, ValueError):
                    pass
        self._homing = not at_home
        self._home_max_error_deg = max_error_deg
        return out

    def _engage(self, poses: dict[str, np.ndarray], state: dict[str, Any]) -> bool:
        """Latch the clutch reference: current hand poses <-> current gripper poses."""
        ok, reason = self._state_is_fresh_and_complete(state)
        if not ok:
            self._engage_reason = reason
            logger.warning("VR IK engage rejected: %s", reason)
            return False
        for name in self.frozen_joints:
            self.robot.set_joint(name, 0.0)
        self._sync_lift_joint(state)
        for side in SIDES:
            measured = self._state_to_urdf_deg(side, state)
            self._write_joints(side, measured)
            self._last_output[side] = measured
        self.robot.update_kinematics()
        for side in SIDES:
            self._robot0[side] = np.array(self.robot.get_T_world_frame(self.tip_frames[side]))
            self._ctrl0[side] = poses[side].copy()
            self._target[side] = self._robot0[side].copy()
            # Pin the nullspace to the posture we clutched in at.
            self.posture_tasks[side].set_joints({
                name: float(np.deg2rad(value))
                for name, value in zip(self.joints[side][:3], self._last_output[side][:3], strict=True)
            })
        self._last_time = time.monotonic()
        self.active = True
        self._homing = False
        self._homing_command_deg = dict.fromkeys(SIDES)
        self._engage_reason = None
        self._home_max_error_deg = 0.0
        logger.info("VR IK engaged with fresh robot state")
        return True

    def reanchor(self, poses: dict[str, np.ndarray], state: dict[str, Any]) -> bool:
        """Reset the clutch reference to the current controller and robot pose."""
        if not poses:
            self._engage_reason = "missing_controller_pose"
            logger.warning("VR IK reanchor rejected: missing controller pose")
            return False
        self.active = False
        self._target = dict.fromkeys(SIDES)
        self._last_time = None
        ok = self._engage(poses, state)
        if ok:
            logger.info("VR IK reanchored to current controller pose")
        return ok

    def _solve(self) -> bool:
        """Iterate the differential IK until both frame tasks converge (or we run out)."""
        for _ in range(self.solver_iterations):
            self.solver.solve(True)
            self.robot.update_kinematics()
            converged = True
            for side in SIDES:
                current = np.array(self.robot.get_T_world_frame(self.tip_frames[side]))
                translation, rotation = pose_difference(current, self._target[side])
                if translation > self.position_tolerance_m or rotation > self.orientation_tolerance_rad:
                    converged = False
                    break
            if converged:
                return True
        return False

    # -- public API --------------------------------------------------------------------
    @staticmethod
    def _T(pose: dict[str, Any] | None) -> np.ndarray | None:  # noqa: N802  (kept for API compat)
        """Backwards-compatible alias for :func:`pose_to_matrix`."""
        return pose_to_matrix(pose)

    def _q(self, side: str, state: dict[str, Any]) -> np.ndarray:
        """Backwards-compatible alias for the measured-joint reader."""
        return self._state_to_urdf_deg(side, state)

    def update(self, payload: dict[str, Any], state: dict[str, Any]) -> dict[str, float]:
        """Map one WebXR ``arm_pose`` message to absolute joint targets in degrees.

        Returns an empty dict when the operator is not clutched in, when the payload is
        unusable, or when the solve fails -- the gateway treats that as "hold".
        """
        state = state or {}
        want = bool(payload.get("active")) and bool(payload.get("left")) and bool(payload.get("right"))
        if not want:
            self._reset()
            return {}

        poses: dict[str, np.ndarray] = {}
        for side in SIDES:
            pose = pose_to_matrix(payload.get(side))
            if pose is None:
                # Hold without touching any latched state: a dropped/garbled frame must
                # not desynchronise the clutch reference.
                if not self._warned_invalid_pose:
                    logger.warning("Ignoring VR arm payload with unusable %s controller pose", side)
                    self._warned_invalid_pose = True
                return {}
            poses[side] = pose
        self._warned_invalid_pose = False

        reanchor_requested = bool(
            payload.get("reanchor") or payload.get("align") or payload.get("calibrate")
        )
        if self.active and reanchor_requested:
            if not self.reanchor(poses, state):
                return {}
        elif not self.active:
            ok, reason = self._state_is_fresh_and_complete(state)
            if not ok:
                self._engage_reason = reason
                return {}
            if self._homing or not self._is_at_home_posture(state):
                # Ramp towards the verified home posture before latching a clutch
                # reference, so every session starts from the same kinematic branch
                # (see DEFAULT_HOME_POSTURE_DEG) instead of wherever the arm happened
                # to be left. This is an open-loop joint-space move, independent of
                # the differential-IK solver below.
                self._homing = True
                self._engage_reason = "homing"
                homing_dt = self._tick_dt()
                out = self._step_homing(state, homing_dt)
                if self._homing:
                    return out if out is not None else {}
            if not self._engage(poses, state):
                return {}

        dt = self._tick_dt()
        smoothing = rate_compensated_smoothing(self.smooth, dt, self.nominal_dt)
        max_delta_deg = self.max_joint_speed_deg_s * dt
        if self.max_step_deg is not None:
            max_delta_deg = min(max_delta_deg, self.max_step_deg)

        # The lift can move mid-session (base/lift controls run concurrently with arm
        # IK), so keep the model's shoulder height current every tick, not just at
        # engage time. The target frame stays a fixed world-frame pose regardless.
        self._sync_lift_joint(state)

        # Seed the model from the last command, optionally corrected towards reality.
        for side in SIDES:
            seed = self._last_output[side]
            measured = self._measured_urdf_deg(side, state)
            if self.state_blend > 0.0 and measured is not None:
                seed = (1.0 - self.state_blend) * seed + self.state_blend * measured
            self._write_joints(side, seed)
        self.robot.update_kinematics()

        for side in SIDES:
            candidate = self._target_from_delta(side, poses[side])
            if should_commit_target(candidate, self._target[side], self.deadband_m, self.deadband_rad):
                self._target[side] = candidate
            self.tasks[side].T_world_frame = self._target[side]

        try:
            if not self._solve():
                # Not fatal: the target is simply out of reach or near a singularity, and
                # the output clamps below keep the partial solution safe.
                logger.debug("VR IK did not converge within %d iterations", self.solver_iterations)
        except Exception:
            logger.exception("VR IK solve failed; holding previous joint targets")
            # Restore the model to the seed so the next tick starts from a sane state.
            for side in SIDES:
                self._write_joints(side, self._last_output[side])
            self.robot.update_kinematics()
            return {}

        solution: dict[str, np.ndarray] = {}
        for side in SIDES:
            raw = self._read_joints(side)
            if not np.isfinite(raw).all():
                logger.warning("VR IK produced a non-finite solution for %s arm; holding", side)
                for other in SIDES:
                    self._write_joints(other, self._last_output[other])
                self.robot.update_kinematics()
                return {}
            limits = self.joint_limits_deg[side]
            raw = np.clip(raw, limits[:, 0], limits[:, 1])
            command = clamp_joint_step(self._last_output[side], raw, smoothing, max_delta_deg)
            # Bound open-loop runaway: the robot ships with max_relative_target disabled
            # and the DEGREES write path does no clamping of its own.
            if self.max_state_deviation_deg is not None:
                measured = self._measured_urdf_deg(side, state)
                if measured is not None:
                    command = np.clip(
                        command,
                        measured - self.max_state_deviation_deg,
                        measured + self.max_state_deviation_deg,
                    )
            solution[side] = command

        out: dict[str, float] = {}
        for side in SIDES:
            self._last_output[side] = solution[side]
            for name, value in zip(ARM_JOINTS, self._urdf_deg_to_robot_deg(solution[side]), strict=True):
                out[f"arm_{side}_{name}.pos"] = float(value)
            trigger = payload.get(f"{side}_gripper", 0.0)
            try:
                trigger = float(trigger)
            except (TypeError, ValueError):
                trigger = 0.0
            if not np.isfinite(trigger):
                trigger = 0.0
            # Gripper motors are RANGE_0_100 regardless of use_degrees.
            out[f"arm_{side}_gripper.pos"] = float(np.clip(trigger, 0.0, 1.0) * 100.0)
        return out
