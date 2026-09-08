"""Offline benchmark for the AlohaMini Pro VR IK modes.

Run with::

    uv run python tests/vr_gateway/test/benchmark_ik_modes.py

The benchmark drives the same sanitized URDF and representative calibrated ROM for
all modes.  It is deliberately synthetic: no Quest packets, robot observations, or
motor commands are involved, so the numbers are useful for regression comparison but
must not be presented as a reproduction of hardware behaviour.
"""

from __future__ import annotations

import json
import math
import statistics
import time
from pathlib import Path
from typing import Any

import numpy as np

from lerobot.vr_gateway.arm_ik import (
    ARM_JOINTS,
    SIDES,
    AlohaMiniDualArmIK,
    pose_difference,
)

URDF_PATH = Path(__file__).parents[3] / "src/lerobot/vr_gateway/assets/alohamini2pro/urdf/alohamini2pro.urdf"

# Limits obtained from the AlohaMini 2 Pro Feetech calibration ranges, converted to
# robot/action degrees with a 2-degree safety margin.  They are only an offline model
# contract; deployments still load their own calibration at runtime.
CALIBRATED_LIMITS_DEG: dict[str, dict[str, tuple[float, float]]] = {
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

PRODUCTION_IK_CONFIG = {
    "fixed_dt": 0.04,
    "smooth": 0.7,
    "max_joint_speed_deg_s": 180.0,
    "max_state_deviation_deg": 45.0,
    "solver_iterations": 20,
}


def _home_state() -> dict[str, float]:
    state: dict[str, float] = {"lift_axis.height_mm": 300.0}
    for side in SIDES:
        for name in ARM_JOINTS:
            state[f"arm_{side}_{name}.pos"] = float(
                {"shoulder_pan": -7.5, "shoulder_lift": -45.0, "elbow_flex": 45.0,
                 "wrist_flex": 0.0, "wrist_yaw": 0.0, "wrist_roll": 0.0}[name]
            )
        state[f"arm_{side}_gripper.pos"] = 0.0
    return state


def _identity_pose(x: float, y: float, z: float) -> dict[str, list[float]]:
    return {"position": [float(x), float(y), float(z)], "orientation": [0.0, 0.0, 0.0, 1.0]}


def _payload(point: tuple[float, float, float], angle: float = 0.0) -> dict[str, Any]:
    # A small orientation sweep makes the full-pose and telegrip weighting observable
    # while preserving the same Cartesian position path in all three modes.
    half = angle * 0.5
    orientation = [0.0, math.sin(half), 0.0, math.cos(half)]
    pose = {
        "position": [float(v) for v in point],
        "orientation": orientation,
    }
    return {
        "left_active": True,
        "right_active": True,
        "active": True,
        "left": dict(pose),
        "right": dict(pose),
        "left_gripper": 0.0,
        "right_gripper": 0.0,
    }


def _trajectory() -> list[tuple[tuple[float, float, float], float]]:
    points: list[tuple[tuple[float, float, float], float]] = []
    # Forward reach, then a downward grasp-like move (WebXR +y maps to robot +z).
    points.extend([((0.0, 0.0, 0.0), 0.0), ((0.0, 0.0, -0.05), 0.10), ((0.0, -0.04, -0.05), 0.20)])
    # Horizontal positive and negative circles in the controller x/z plane.
    radius = 0.045
    for direction in (1.0, -1.0):
        for index in range(1, 17):
            theta = direction * 2.0 * math.pi * index / 16.0
            points.append(((radius * math.cos(theta), -0.02, radius * math.sin(theta)), 0.15 * math.sin(theta)))
    return points


def _run_mode(mode: str, orientation_weight: float) -> dict[str, Any]:
    ik = AlohaMiniDualArmIK(
        URDF_PATH,
        control_mode=mode,
        orientation_weight=orientation_weight,
        joint_limits_deg=CALIBRATED_LIMITS_DEG,
        **PRODUCTION_IK_CONFIG,
    )
    state = _home_state()
    trajectory = _trajectory()
    solve_ms: list[float] = []
    position_errors_mm: list[float] = []
    joint_steps_deg: list[float] = []
    branch_jumps = 0
    command_branch_jumps = 0
    previous_solution: dict[str, np.ndarray] = {}
    previous_command: dict[str, np.ndarray] = {}
    previous_output: dict[str, float] | None = None

    for point, angle in trajectory:
        payload = _payload(point, angle)
        started = time.perf_counter()
        output = ik.update(payload, state)
        solve_ms.append((time.perf_counter() - started) * 1000.0)
        if not output:
            continue
        # Apply the generated action as the next synthetic measured state.  This keeps
        # the replay closed-loop while retaining deterministic 40 ms control ticks.
        state.update(output)
        for side in SIDES:
            target = ik._target[side]
            if target is None:
                continue
            actual = np.asarray(ik.robot.get_T_world_frame(ik.tip_frames[side]), dtype=float)
            position_error_m, _ = pose_difference(actual, target)
            position_errors_mm.append(position_error_m * 1000.0)
            solution = ik._read_joints(side)
            if side in previous_solution:
                delta_norm = float(np.linalg.norm(solution - previous_solution[side]))
                # Branch flip proxy: a discontinuous adjacent six-joint jump larger
                # than 30 degrees in one 40 ms tick.
                if delta_norm > 30.0:
                    branch_jumps += 1
            if previous_output is not None:
                values = np.array([output[f"arm_{side}_{name}.pos"] for name in ARM_JOINTS])
                old = np.array([previous_output[f"arm_{side}_{name}.pos"] for name in ARM_JOINTS])
                joint_steps_deg.extend(np.abs(values - old).tolist())
                if side in previous_command and float(np.linalg.norm(values - previous_command[side])) > 30.0:
                    command_branch_jumps += 1
                previous_command[side] = values.copy()
            else:
                previous_command[side] = np.array(
                    [output[f"arm_{side}_{name}.pos"] for name in ARM_JOINTS]
                )
            previous_solution[side] = solution.copy()
        previous_output = output

    def summary(values: list[float]) -> dict[str, float]:
        if not values:
            return {"mean": float("nan"), "max": float("nan"), "p50": float("nan"), "p95": float("nan")}
        return {
            "mean": float(statistics.fmean(values)),
            "max": float(max(values)),
            "p50": float(np.percentile(values, 50)),
            "p95": float(np.percentile(values, 95)),
        }

    return {
        "mode": "position_only" if orientation_weight == 0.0 else mode,
        "ik_config": PRODUCTION_IK_CONFIG,
        "configured_orientation_weight": orientation_weight,
        "effective_orientation_weight": orientation_weight
        * (0.25 if mode == "telegrip" else 1.0),
        "ticks": len(trajectory),
        "solve_wall_ms": summary(solve_ms),
        "tcp_position_error_mm": summary(position_errors_mm),
        "joint_step_deg": summary(joint_steps_deg),
        "branch_jump_count": branch_jumps,
        "command_branch_jump_count": command_branch_jumps,
        "branch_jump_definition": "adjacent six-joint solution L2 norm > 30 deg per 40 ms tick",
        "command_branch_jump_definition": "adjacent emitted six-joint command L2 norm > 30 deg per 40 ms tick",
    }


def main() -> None:
    # Position-only is the explicit orientation_weight=0 baseline.  telegrip uses the
    # production 0.25 scale while full_pose keeps the configured weight unchanged.
    results = [
        _run_mode("full_pose", 1.0),
        _run_mode("telegrip", 1.0),
        _run_mode("full_pose", 0.0),
    ]
    print(json.dumps({"synthetic": True, "results": results}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
