"""Construct VR IK from the ROS2 model and this machine's reference capture."""

from __future__ import annotations

import numpy as np

from .arm_ik import AlohaMiniDualArmIK
from .calibration.profile import ASSET_DIR, ArmMapping
from .coordinates import XR_TO_BASE

# ROS2's base_cad_joint rotates the CAD frame +90 degrees about Z into the
# standard base frame (+X forward, +Y left, +Z up). Only legacy clients send CAD bases.
CAD_TO_BASE = np.array([[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])


def make_calibrated_ik(mapping: ArmMapping, **options) -> AlohaMiniDualArmIK:
    # Folded Home is the operator's clutch anchor. A 1:1 gain keeps the known
    # 0.47-0.68 m straight-arm TCP travel inside normal controller reach.
    options.setdefault("position_scale", 1.0)
    # Match the ROS position-priority controller: orientation remains active for
    # wrist motion, but yields when keeping it would prevent the TCP reaching the hand.
    options.setdefault("position_weight", 100.0)
    options.setdefault("orientation_weight", 0.001)
    options.setdefault("orientation_motion_weight", 0.35)
    options.setdefault("posture_weight", 1e-4)
    # Advance the Cartesian target only as the measured arm follows it. This bounds
    # recovery frames and prevents a distant unreachable target from driving joints
    # to their limits while the physical arm is still near Home.
    options.setdefault("max_target_position_lead_m", 0.025)
    options.setdefault("max_target_orientation_lead_rad", np.deg2rad(15.0))
    ik = AlohaMiniDualArmIK(
        ASSET_DIR / "urdf/alohamini2pro_kinematic.urdf",
        arm_mapping=mapping,
        tip_frame_template="{side}_tcp",
        vr_to_robot=CAD_TO_BASE.T @ XR_TO_BASE,
        body_basis_rotation=CAD_TO_BASE,
        translation_direction=np.eye(3),
        home_before_engage=False,
        **options,
    )
    ik.mode = "calibrated"
    return ik
