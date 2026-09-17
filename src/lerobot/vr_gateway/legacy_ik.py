"""Legacy hand gestures on the original CAD model, bound to captured Folded Home."""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np

from .arm_ik import AlohaMiniDualArmIK, pose_to_matrix, rotation_exp, rotation_log
from .calibration.profile import ArmMapping


class LegacyArmIK(AlohaMiniDualArmIK):
    """CAD hand gestures and legacy timing, with hand-axis wrist roll."""

    mode = "legacy"

    def __init__(self, *args, **options):
        super().__init__(*args, **options)
        self._wrist_origin: dict[str, np.ndarray] = {}
        self._wrist_tip_offset: dict[str, np.ndarray] = {}
        self._roll_origin: dict[str, float] = {}
        self._roll_twist: dict[str, float] = {}

    def _engage_side(self, side: str, pose: np.ndarray, state: dict) -> bool:
        if not super()._engage_side(side, pose, state):
            return False
        self._latch_wrist(side)
        return True

    def _engage(self, poses: dict, state: dict) -> bool:
        if not super()._engage(poses, state):
            return False
        for side in self.active_sides:
            self._latch_wrist(side)
        return True

    def _latch_wrist(self, side: str) -> None:
        wrist = np.array(self.robot.get_T_world_frame(f"{side}_Fixed_Jaw"))
        self._wrist_origin[side] = wrist
        self._wrist_tip_offset[side] = np.linalg.inv(wrist) @ self._robot0[side]
        self._roll_origin[side] = float(self._last_output[side][5])
        self._roll_twist[side] = 0.0

    def _target_from_delta(self, side: str, ctrl: np.ndarray) -> np.ndarray:
        target = super()._target_from_delta(side, ctrl)
        anchor = self._ctrl0[side][:3, :3]
        local = anchor.T @ ctrl[:3, :3]
        # Swing/twist decomposition about the controller's LOCAL long axis Z.
        # atan2 avoids Euler pitch/yaw coupling; unwrap only across successive
        # tracked samples, so crossing +/-180 degrees cannot reverse the wrist.
        sine = local[1, 0] - local[0, 1]
        cosine = local[0, 0] + local[1, 1]
        twist = self._roll_twist[side]
        if np.hypot(sine, cosine) > 1e-8:
            wrapped = np.arctan2(sine, cosine)
            twist += (wrapped - twist + np.pi) % (2 * np.pi) - np.pi
        self._roll_twist[side] = twist
        swing = local @ rotation_exp([0.0, 0.0, -twist])

        world_swing = rotation_log(anchor @ swing @ anchor.T)
        # Preserve d569ef96's world-yaw direction. A second yaw inversion here
        # reverses horizontal hand turns; long-axis twist is handled separately.
        mapped_swing = rotation_exp(self._body_basis @ world_swing * self.orientation_scale)

        # Controller forward is -Z; Fixed_Jaw's roll axis is +Z. The existing
        # motor sign conversion remains responsible for the encoder direction.
        origin = self._roll_origin[side]
        roll_deg = np.clip(
            origin - np.rad2deg(twist) * self.orientation_scale,
            *self.joint_limits_deg[side][5],
        )
        roll = rotation_exp([0.0, 0.0, np.deg2rad(roll_deg - origin)])
        wrist_rotation = self._wrist_origin[side][:3, :3]
        offset = self._wrist_tip_offset[side]
        target[:3, :3] = mapped_swing @ wrist_rotation @ roll @ offset[:3, :3]
        # The moving-jaw origin is off the roll bearing's axis. Let it trace its
        # physical arc during a twist; fixing that point would force shoulder,
        # elbow and wrist-yaw compensation instead of independent gripper roll.
        target[:3, 3] += mapped_swing @ wrist_rotation @ (roll - np.eye(3)) @ offset[:3, 3]
        return target

    def align(self, head_pose: dict) -> None:
        pose = pose_to_matrix(head_pose)
        if pose is None:
            raise ValueError("alignment requires a valid current head pose")
        rotation = pose[:3, :3]
        # Same yaw extraction and CAD basis as d569ef96's handleAlignment in JS.
        yaw = np.arctan2(rotation[0, 2], rotation[0, 0])
        c, s = np.cos(yaw), np.sin(yaw)
        heading = np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]])
        self._body_basis = self._vr_to_robot @ heading.T
        self.release()

    def _tick_dt(self) -> float:
        if self.fixed_dt is not None:
            return self.fixed_dt
        now = time.monotonic()
        previous, self._last_time = self._last_time, now
        if previous is None:
            return self.nominal_dt
        # Restore the old elapsed-time budget, bounded to 200 ms by max_dt.
        return float(np.clip(now - previous, self.min_dt, self.max_dt))


def make_legacy_ik(mapping: ArmMapping, **options) -> LegacyArmIK:
    options.setdefault("position_scale", 0.5)
    options.setdefault("posture_weight", 5e-4)
    options.setdefault("retry_budget_s", 0.0)
    # With the physical zero restored, CAD -Y is forward. The old XR-Z
    # reflection compensated for the incorrect zero and now reverses reach.
    options.setdefault("translation_direction", np.eye(3))
    # Home binds encoder positions to this CAD chain's joint angles. The shared
    # IK installs its asymmetric per-side limits in Placo and output protection;
    # intersecting with midpoint-centred motor degrees would exclude straight arms.
    return LegacyArmIK(
        Path(__file__).parent / "assets/alohamini2pro/urdf/alohamini2pro.urdf",
        arm_mapping=mapping,
        home_before_engage=False,
        **options,
    )
