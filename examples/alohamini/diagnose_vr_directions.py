"""Offline VR hand-pose direction diagnostics for AlohaMini 2 Pro.

The harness generates controller poses from known URDF joint perturbations, then feeds
those poses through the real ``AlohaMiniDualArmIK.update`` path.  It reports the
controller payload, robot-frame target displacement, FK displacement, and final action
delta for both arms and all six joints.  No robot hardware is opened.

Run with the ``lerobot_alohamini`` conda environment:

    python examples/alohamini/diagnose_vr_directions.py

For the same boundary logs used by the gateway, add ``--verbose``.  This sets
``LEROBOT_VR_DIAGNOSTICS=1`` and enables the ``[VR-DIAG]`` records from ``arm_ik.py``.
"""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

import numpy as np

from lerobot.vr_gateway.arm_ik import (
    ARM_JOINTS,
    DEFAULT_HOME_POSTURE_DEG,
    SIDES,
    VR_TRANSLATION_DIRECTION,
    AlohaMiniDualArmIK,
)
from lerobot.vr_gateway.server import ALOHAMINI_ROBOT_TO_URDF_JOINT_SIGNS

LOGGER = logging.getLogger("vr_direction_diagnostics")
URDF_PATH = Path(__file__).parents[2] / "src/lerobot/vr_gateway/assets/alohamini2pro/urdf/alohamini2pro.urdf"


def _state() -> dict[str, float]:
    state: dict[str, float] = {"lift_axis.height_mm": 300.0}
    for side in SIDES:
        for name in ARM_JOINTS:
            state[f"arm_{side}_{name}.pos"] = DEFAULT_HOME_POSTURE_DEG[side][name]
    return state


def _payload() -> dict[str, object]:
    return {
        "active": True,
        "left_active": True,
        "right_active": True,
        "left": {"position": [0.0, 0.0, 0.0], "orientation": [0.0, 0.0, 0.0, 1.0]},
        "right": {"position": [0.0, 0.0, 0.0], "orientation": [0.0, 0.0, 0.0, 1.0]},
    }


def _matrix_to_quaternion(rotation: np.ndarray) -> list[float]:
    """Convert a proper rotation matrix to WebXR XYZW quaternion order."""
    r = np.asarray(rotation, dtype=float)
    trace = float(np.trace(r))
    if trace > 0.0:
        scale = np.sqrt(trace + 1.0) * 2.0
        q = np.array(
            [(r[2, 1] - r[1, 2]) / scale, (r[0, 2] - r[2, 0]) / scale, (r[1, 0] - r[0, 1]) / scale, 0.25 * scale]
        )
    else:
        index = int(np.argmax(np.diag(r)))
        if index == 0:
            scale = np.sqrt(1.0 + r[0, 0] - r[1, 1] - r[2, 2]) * 2.0
            q = np.array([0.25 * scale, (r[0, 1] + r[1, 0]) / scale, (r[0, 2] + r[2, 0]) / scale, (r[2, 1] - r[1, 2]) / scale])
        elif index == 1:
            scale = np.sqrt(1.0 - r[0, 0] + r[1, 1] - r[2, 2]) * 2.0
            q = np.array([(r[0, 1] + r[1, 0]) / scale, 0.25 * scale, (r[1, 2] + r[2, 1]) / scale, (r[0, 2] - r[2, 0]) / scale])
        else:
            scale = np.sqrt(1.0 - r[0, 0] - r[1, 1] + r[2, 2]) * 2.0
            q = np.array([(r[0, 2] + r[2, 0]) / scale, (r[1, 2] + r[2, 1]) / scale, 0.25 * scale, (r[1, 0] - r[0, 1]) / scale])
    return (q / np.linalg.norm(q)).tolist()


def _controller_pose_for_target(ik: AlohaMiniDualArmIK, home: np.ndarray, target: np.ndarray) -> dict[str, object]:
    basis = ik._body_basis
    position = VR_TRANSLATION_DIRECTION @ (basis.T @ (target[:3, 3] - home[:3, 3]))
    rotation = basis.T @ target[:3, :3] @ home[:3, :3].T @ basis
    return {"position": position.tolist(), "orientation": _matrix_to_quaternion(rotation)}


def _fk(ik: AlohaMiniDualArmIK, side: str) -> np.ndarray:
    ik.robot.update_kinematics()
    return np.array(ik.robot.get_T_world_frame(ik.tip_frames[side]))


def _new_ik() -> AlohaMiniDualArmIK:
    return AlohaMiniDualArmIK(
        URDF_PATH,
        fixed_dt=0.04,
        smooth=1.0,
        max_joint_speed_deg_s=10_000.0,
        max_state_deviation_deg=None,
        solver_iterations=100,
        joint_signs=ALOHAMINI_ROBOT_TO_URDF_JOINT_SIGNS,
        home_before_engage=False,
    )


def run_joint_matrix() -> int:
    failures = 0
    for side in SIDES:
        for joint in ARM_JOINTS:
            for requested_delta in (-10.0, 10.0):
                ik = _new_ik()
                state = _state()
                initial = ik.update(_payload(), state)
                state.update(initial)
                home = ik._robot0[side].copy()
                desired = ik._read_joints(side).copy()
                desired[ARM_JOINTS.index(joint)] += requested_delta
                ik._write_joints(side, desired)
                target = _fk(ik, side)
                sample = _payload()
                sample[side] = _controller_pose_for_target(ik, home, target)
                output = ik.update(sample, state)
                command = np.array([output[f"arm_{side}_{name}.pos"] for name in ARM_JOINTS])
                ik._write_joints(side, ik._state_to_urdf_deg(side, {f"arm_{side}_{name}.pos": value for name, value in zip(ARM_JOINTS, command, strict=True)}))
                actual = _fk(ik, side)
                target_delta = target[:3, 3] - home[:3, 3]
                actual_delta = actual[:3, 3] - home[:3, 3]
                direction_ok = float(np.dot(target_delta, actual_delta)) > 0.0
                if not direction_ok:
                    failures += 1
                print(
                    f"JOINT side={side} joint={joint} request={requested_delta:+.1f}deg "
                    f"hand={np.round(sample[side]['position'], 4).tolist()} "
                    f"target_delta_m={np.round(target_delta, 4).tolist()} "
                    f"fk_delta_m={np.round(actual_delta, 4).tolist()} "
                    f"direction={'OK' if direction_ok else 'FAIL'} "
                    f"action_deg={np.round(command, 2).tolist()}"
                )
    return failures


def run_forward_backward_and_up() -> int:
    failures = 0
    for label, hand_delta in (("forward", [0.0, 0.0, -0.04]), ("backward", [0.0, 0.0, 0.04]), ("up", [0.0, 0.04, 0.0])):
        ik = _new_ik()
        state = _state()
        initial = ik.update(_payload(), state)
        state.update(initial)
        before = {side: _fk(ik, side) for side in SIDES}
        moved = _payload()
        for side in SIDES:
            moved[side]["position"] = hand_delta  # type: ignore[index]
        output = ik.update(moved, state)
        state.update(output)
        after = {side: _fk(ik, side) for side in SIDES}
        expected = ik._body_basis @ (VR_TRANSLATION_DIRECTION @ np.asarray(hand_delta))
        print(f"AXIS case={label} hand_delta_m={hand_delta} expected_robot_delta_m={np.round(expected, 4).tolist()}")
        for side in SIDES:
            delta = after[side][:3, 3] - before[side][:3, 3]
            ok = float(np.dot(expected, delta)) > 0.0
            failures += not ok
            print(f"AXIS side={side} fk_delta_m={np.round(delta, 4).tolist()} direction={'OK' if ok else 'FAIL'}")
    return failures


def run_perpendicular_forearm_up() -> int:
    """Use an approximately 90-degree elbow configuration and move the forearm up."""
    failures = 0
    for side in SIDES:
        ik = _new_ik()
        state = _state()
        state[f"arm_{side}_elbow_flex.pos"] = 105.0
        payload = _payload()
        initial = ik.update(payload, state)
        state.update(initial)
        upper = np.array(ik.robot.get_T_world_frame(f"{side}_Upper_Arm"))[:3, 3]
        lower = np.array(ik.robot.get_T_world_frame(f"{side}_Lower_Arm"))[:3, 3]
        wrist = np.array(ik.robot.get_T_world_frame(f"{side}_Wrist_Pitch_Roll"))[:3, 3]
        upper_vec, forearm_vec = lower - upper, wrist - lower
        elbow_angle = np.degrees(np.arccos(np.dot(upper_vec, forearm_vec) / np.linalg.norm(upper_vec) / np.linalg.norm(forearm_vec)))
        before = _fk(ik, side)
        moved = _payload()
        moved["left_active"] = side == "left"
        moved["right_active"] = side == "right"
        moved[side]["position"] = [0.0, 0.04, 0.0]  # type: ignore[index]
        output = ik.update(moved, state)
        ik._write_joints(side, ik._state_to_urdf_deg(side, {f"arm_{side}_{name}.pos": output[f"arm_{side}_{name}.pos"] for name in ARM_JOINTS}))
        after = _fk(ik, side)
        delta = after[:3, 3] - before[:3, 3]
        ok = delta[2] > 0.0
        failures += not ok
        print(f"PERP side={side} elbow_angle_deg={elbow_angle:.2f} hand_delta_m=[0, 0.04, 0] fk_delta_m={np.round(delta, 4).tolist()} direction={'OK' if ok else 'FAIL'}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action="store_true", help="enable [VR-DIAG] input/state/target/action logs")
    args = parser.parse_args()
    if args.verbose:
        os.environ["LEROBOT_VR_DIAGNOSTICS"] = "1"
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
            force=True,
        )
    if not URDF_PATH.is_file():
        raise FileNotFoundError(URDF_PATH)
    failures = run_forward_backward_and_up() + run_perpendicular_forearm_up() + run_joint_matrix()
    print(f"RESULT {'PASS' if failures == 0 else 'FAIL'} failures={failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
