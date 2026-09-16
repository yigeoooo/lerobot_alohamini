"""Check mappings and display Home/measured arm geometry without ROS or motion."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from .joint_mapping import ARM_JOINTS
from .profile import ASSET_DIR, DEFAULT_MAPPING_DIR, ArmMapping


def check_round_trip(mapping: ArmMapping) -> None:
    """Exercise each arm's complete executable range, including periodic branches."""
    for side in ("left", "right"):
        limits = np.asarray(mapping.limits_deg[side])
        for fraction in np.linspace(0.0, 1.0, 101):
            expected = limits[:, 0] + fraction * (limits[:, 1] - limits[:, 0])
            actual = mapping.to_urdf_deg(side, mapping.to_robot_deg(side, expected))
            if not np.allclose(actual, expected, atol=360.0 / 4096):
                raise ValueError(f"{side} encoder/URDF round trip failed at fraction {fraction}")


def arm_points(ik, side: str, joints_deg) -> np.ndarray:
    ik._write_joints(side, np.asarray(joints_deg))
    ik.robot.update_kinematics()
    frames = ("Base", "Upper_Arm", "Lower_Arm", "Wrist_Pitch_Roll", "Fixed_Jaw", "tcp")
    return np.array([ik.robot.get_T_world_frame(f"{side}_{frame}")[:3, 3] for frame in frames])


def write_figure(home: dict, measured: dict | None, destination: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 3, figsize=(15, 6))
    for ax, (x, y, title) in zip(
        axes,
        ((0, 2, "Side: forward / up"), (1, 2, "Front: left / up"), (0, 1, "Top: forward / left")),
        strict=True,
    ):
        for side, color in (("left", "tab:blue"), ("right", "tab:orange")):
            points = home[side]
            ax.plot(points[:, x], points[:, y], "o--", color=color, alpha=0.5, label=f"{side} Home")
            if measured is not None:
                points = measured[side]
                ax.plot(points[:, x], points[:, y], "o-", color=color, label=f"{side} measured")
        ax.set_title(title)
        ax.set_xlabel("XYZ"[x] + " (m)")
        ax.set_ylabel("XYZ"[y] + " (m)")
        ax.axis("equal")
        ax.grid(True)
        ax.legend()
    fig.suptitle("AlohaMini CAD reference / measured FK — joint axes and TCP, no collision geometry")
    fig.tight_layout()
    fig.savefig(destination)
    fig.savefig(destination.with_suffix(".png"), dpi=140)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm-mapping-dir", type=Path, default=DEFAULT_MAPPING_DIR)
    parser.add_argument("--calibration-json", type=Path)
    parser.add_argument("--show-home", action="store_true", help="render packaged CAD Home before capture")
    parser.add_argument("--read-hardware", action="store_true", help="read only the two arm serial buses")
    parser.add_argument(
        "--expect-home", action="store_true", help="require measured joints within 2 degrees of Home"
    )
    parser.add_argument("--left-port", default="/dev/am_arm_follower_left")
    parser.add_argument("--right-port", default="/dev/am_arm_follower_right")
    parser.add_argument(
        "--lift-height-mm", type=float, default=0.0, help="displayed lift height, does not move lift"
    )
    parser.add_argument("--output-dir", type=Path, default=Path.cwd() / "arm_mapping_check")
    args = parser.parse_args()
    if args.show_home and (args.read_hardware or args.expect_home):
        parser.error("--show-home is an offline reference preview")
    if args.expect_home and not args.read_hardware:
        parser.error("--expect-home requires --read-hardware")

    from lerobot.vr_gateway.arm_ik import AlohaMiniDualArmIK
    from lerobot.vr_gateway.calibrated_ik import make_calibrated_ik

    if args.show_home:
        import yaml

        mappings = {
            side: yaml.safe_load((ASSET_DIR / f"calibration/hardware_joint_map_{side}.yaml").read_text())
            for side in ("left", "right")
        }
        ik = AlohaMiniDualArmIK(
            ASSET_DIR / "urdf/alohamini2pro_kinematic.urdf",
            tip_frame_template="{side}_tcp",
            home_before_engage=False,
        )
    else:
        cal_path = args.calibration_json or args.arm_mapping_dir / "AlohaMiniRobot.json"
        if args.read_hardware and args.calibration_json is None:
            from lerobot.utils.constants import HF_LEROBOT_CALIBRATION

            cal_path = HF_LEROBOT_CALIBRATION / "robots/alohamini/AlohaMiniRobot.json"
        calibration = json.loads(cal_path.read_text())
        mapping = ArmMapping.load(args.arm_mapping_dir, calibration)
        check_round_trip(mapping)
        mappings = mapping.mappings
        ik = make_calibrated_ik(mapping)

    ik._sync_lift_joint({"lift_axis.height_mm": args.lift_height_mm})
    home_q = {
        side: np.rad2deg([mappings[side]["joints"][name]["reference_q_rad"] for name in ARM_JOINTS[:-1]])
        for side in ("left", "right")
    }
    home = {side: arm_points(ik, side, home_q[side]) for side in ("left", "right")}
    measured = None
    report = {
        "source": "CAD reference preview" if args.show_home else "mapping numerical checks",
        "lift_height_mm_for_display": args.lift_height_mm,
        "collision_checked": False,
        "physical_geometry_confirmed": False,
        "home_q_deg": {side: q.tolist() for side, q in home_q.items()},
    }
    home_ok = True
    if args.read_hardware:
        from .hardware import read_arm_states
        from .sync_arm_mapping import median_stable_ticks

        observations = read_arm_states(calibration, args.left_port, args.right_port)
        ticks = median_stable_ticks(observations, calibration, max_spread=4)
        measured = {}
        report["measured_q_deg"] = {}
        for side in ("left", "right"):
            values = [
                mapping.mapper.tick_to_lerobot(
                    ticks[f"arm_{side}_{name}"], mapping.metadata["motors"][f"arm_{side}_{name}"]
                )
                for name in ARM_JOINTS[:-1]
            ]
            q = np.asarray(mapping.to_urdf_deg(side, values))
            report["measured_q_deg"][side] = q.tolist()
            measured[side] = arm_points(ik, side, q)
            home_ok &= bool(np.max(np.abs(q - home_q[side])) <= 2.0)
        report["within_2deg_of_captured_home"] = home_ok
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_figure(home, measured, args.output_dir / "arm_reference.svg")
    (args.output_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    print(f"Geometry view: {args.output_dir / 'arm_reference.svg'}")
    print(
        "Compare the displayed upper arm, forearm and wrist with the physical arms; a numerical check cannot establish the physical zero."
    )
    if args.expect_home and not home_ok:
        raise SystemExit("Measured arms differ from captured Home by more than 2 degrees")


if __name__ == "__main__":
    main()
