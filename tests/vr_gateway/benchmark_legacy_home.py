"""Offline before/after Home replay using archived paired fixtures, never hardware.

Run from the repo root: uv run python tests/vr_gateway/benchmark_legacy_home.py
The baseline deliberately reconstructs the pre-Home factory only in this probe.
Both controllers are evaluated against the same Home-bound CAD forward model.
"""

from __future__ import annotations

import argparse
import copy
import json
import tempfile
from pathlib import Path

import numpy as np
import yaml

from lerobot.vr_gateway.arm_ik import ARM_JOINTS, pose_difference, rotation_exp, rotation_log
from lerobot.vr_gateway.calibration.profile import ASSET_DIR, ArmMapping
from lerobot.vr_gateway.calibration.sync_arm_mapping import build_side_mapping
from lerobot.vr_gateway.legacy_ik import LegacyArmIK, make_legacy_ik
from lerobot.vr_gateway.server import ALOHAMINI_ROBOT_TO_URDF_JOINT_SIGNS, make_vr_arm_ik


def rotation_vector_quaternion(vector):
    """XYZW input without requiring SciPy on the robot's runtime environment."""
    vector = np.asarray(vector, dtype=float)
    angle = np.linalg.norm(vector)
    xyz = vector * (0.5 if angle < 1e-12 else np.sin(angle / 2) / angle)
    return [*xyz.tolist(), float(np.cos(angle / 2))]


def fixture_mapping() -> ArmMapping:
    calibration = json.loads((Path(__file__).parent / "fixtures/ros2_reference_calibration.json").read_text())
    templates = {
        side: yaml.safe_load((ASSET_DIR / f"calibration/hardware_joint_map_{side}.yaml").read_text())
        for side in ("left", "right")
    }
    ticks = {
        f"arm_{side}_{joint}": entry["reference_tick"]
        for side, template in templates.items()
        for joint, entry in template["joints"].items()
    }
    return ArmMapping(
        {
            side: build_side_mapping(
                template, calibration, ticks, side, {"captured_at": "offline fixture", "host": "offline"}
            )
            for side, template in templates.items()
        },
        calibration,
    )


def unmapped_baseline(calibration, **options):
    ik = LegacyArmIK(
        ASSET_DIR / "urdf/alohamini2pro.urdf",
        joint_signs=ALOHAMINI_ROBOT_TO_URDF_JOINT_SIGNS,
        home_before_engage=False,
        posture_weight=5e-4,
        retry_budget_s=0.0,
        **options,
    )
    for side in ("left", "right"):
        for index, joint in enumerate(ARM_JOINTS):
            motor = calibration[f"arm_{side}_{joint}"]
            half = (motor["range_max"] - motor["range_min"]) * 180 / 4095
            bounds = ik.joint_limits_deg[side][index]
            bounds[:] = [max(bounds[0], -half), min(bounds[1], half)]
            ik.robot.set_joint_limits(ik.joints[side][index], *np.deg2rad(bounds))
    return ik


def replay(ik, mapping, side, gesture):
    plant = make_legacy_ik(copy.deepcopy(mapping))
    state = {"lift_axis.height_mm": 0.0}
    for arm in ("left", "right"):
        state.update(
            zip(
                (f"arm_{arm}_{j}.pos" for j in ARM_JOINTS),
                mapping.to_robot_deg(arm, [0, -95, 95, 0, 0, 0]),
                strict=True,
            )
        )
    plant._sync_lift_joint(state)
    keys = [f"arm_{side}_{j}.pos" for j in ARM_JOINTS]

    def fk(q):
        plant._write_joints(side, q)
        plant.robot.update_kinematics()
        return np.array(plant.robot.get_T_world_frame(plant.tip_frames[side]))

    start = np.asarray(mapping.to_urdf_deg(side, [state[key] for key in keys]))
    origin = fk(start)
    pose = {"position": [0, 0, 0], "orientation": [0, 0, 0, 1]}
    ik.align(pose)
    payload = {f"{side}_active": True, side: pose}
    state.update(ik.update(payload, state))
    first_limit = None
    samples = []
    max_step = 0.0
    for frame in range(201):
        fraction = min(frame / 150, 1.0)
        if gesture in ("straight_forward", "straight_up"):
            shoulder = -162.237 if gesture == "straight_forward" else -72.237
            finish = np.array([0, shoulder, 163.163, 0, 0, 0])
            desired = fk(start + fraction * (finish - start))
            # This planar reach needs only swing, no roll/twist correction.
            pose["position"] = np.linalg.solve(
                ik._translation_direction,
                ik._body_basis.T @ (desired[:3, 3] - origin[:3, 3]) / ik.position_scale,
            ).tolist()
            pose["orientation"] = rotation_vector_quaternion(
                ik._body_basis.T @ rotation_log(desired[:3, :3] @ origin[:3, :3].T)
            )
        else:
            desired = origin.copy()
            if gesture in ("up", "forward"):
                pose["position"] = (
                    fraction * np.array([0, 0.4, 0] if gesture == "up" else [0, 0, -0.4])
                ).tolist()
                # Physical CAD +Z is up and -Y is forward, independently of the
                # controller's historical empirical forward compensation.
                desired[:3, 3] += fraction * np.array([0, 0, 0.2] if gesture == "up" else [0, -0.2, 0])
            else:
                angle = fraction * (90 if gesture == "yaw_positive" else -90)
                pose["orientation"] = rotation_vector_quaternion([0, np.deg2rad(angle), 0])
                desired[:3, :3] = rotation_exp([0, 0, np.deg2rad(angle)]) @ origin[:3, :3]
        output = ik.update(payload, state)
        assert all(key in output for key in keys)
        max_step = max(max_step, max(abs(output[key] - state[key]) for key in keys))
        for key in keys:
            motor = mapping.calibration[key.removesuffix(".pos")]
            tick = output[key] * 4095 / 360 + (motor["range_min"] + motor["range_max"]) / 2
            assert motor["range_min"] - 1e-6 <= tick <= motor["range_max"] + 1e-6
        state.update(output)
        ik.accept_action(output)
        q = np.asarray(mapping.to_urdf_deg(side, [state[key] for key in keys]))
        actual = fk(q)
        warnings = [item for item in ik.joint_limit_warnings(state) if item["side"] == side]
        if warnings and first_limit is None:
            first_limit = {"fraction": fraction, "joints": warnings}
        if frame % 10 == 0:
            samples.append(
                {
                    "fraction": fraction,
                    "actual_xyz_m": actual[:3, 3].tolist(),
                    "target_xyz_m": desired[:3, 3].tolist(),
                }
            )
    error, rotation_error = pose_difference(actual, desired)
    elbow_bend = abs((163.161935 - q[2] + 180) % 360 - 180)
    return {
        "side": side,
        "gesture": gesture,
        "position_error_mm": 1000 * error,
        "orientation_error_deg": float(np.rad2deg(rotation_error)),
        "elbow_bend_deg": elbow_bend,
        "pan_change_deg": q[0] - start[0],
        "actual_tcp_delta_m": (actual[:3, 3] - origin[:3, 3]).tolist(),
        "final_cad_deg": q.tolist(),
        "first_limit": first_limit,
        "max_motor_step_deg": max_step,
        "samples": samples,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("/tmp/legacy_home_replay.json"))
    parser.add_argument("--arm-mapping-dir", type=Path, help="optional captured profile, still offline")
    parser.add_argument(
        "--calibration-json", type=Path, help="verify a captured profile against current calibration"
    )
    args = parser.parse_args()
    if args.calibration_json is not None and args.arm_mapping_dir is None:
        parser.error("--calibration-json requires --arm-mapping-dir")
    if args.arm_mapping_dir is None:
        mapping = fixture_mapping()
    else:
        calibration_path = args.calibration_json or args.arm_mapping_dir / "AlohaMiniRobot.json"
        mapping = ArmMapping.load(args.arm_mapping_dir, json.loads(calibration_path.read_text()))
    rows = []
    with tempfile.TemporaryDirectory(prefix="legacy_home_offline_") as temporary:
        directory = Path(temporary)
        (directory / "AlohaMiniRobot.json").write_text(json.dumps(mapping.calibration))
        for side, profile in mapping.mappings.items():
            (directory / f"hardware_joint_map_{side}.yaml").write_text(yaml.safe_dump(profile))
        for variant in ("before_home", "home_only", "legacy_home"):
            for side in ("left", "right"):
                for gesture in (
                    "straight_forward",
                    "straight_up",
                    "up",
                    "forward",
                    "yaw_positive",
                    "yaw_negative",
                ):
                    options = {"fixed_dt": 0.04}
                    if variant == "home_only":
                        options["translation_direction"] = np.diag([1.0, 1.0, -1.0])
                    ik = (
                        unmapped_baseline(mapping.calibration, **options)
                        if variant == "before_home"
                        else make_vr_arm_ik(
                            mapping.calibration, mode="legacy", mapping_dir=directory, **options
                        )
                    )
                    row = {"variant": variant, **replay(ik, mapping, side, gesture)}
                    rows.append(row)
                    print(
                        variant,
                        side,
                        gesture,
                        f"error={row['position_error_mm']:.2f}mm",
                        f"orientation={row['orientation_error_deg']:.2f}deg",
                        f"bend={row['elbow_bend_deg']:.2f}deg",
                        flush=True,
                    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "evidence": "Synthetic trajectories; ideal feedback; no hardware",
                "mapping_source": str(args.arm_mapping_dir or "archived paired fixture"),
                "physical_geometry_confirmed": False,
                "rows": rows,
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
