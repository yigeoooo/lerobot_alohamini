"""Bind ROS2 arm mapping files to the current LeRobot motor calibration."""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path

from .joint_mapping import ARM_JOINTS, JointMapper, finite_number
from .sync_arm_mapping import safe_q_range, validate_calibration

DEFAULT_MAPPING_DIR = Path.home() / ".config/lerobot/alohamini/arm_mapping"
ASSET_DIR = Path(__file__).parents[1] / "assets/alohamini2pro"


class ArmMapping:
    """Validated, per-side degree↔URDF mapping with executable motor limits.

    The files retain the ROS2 schema. A fresh Home capture must include the motor
    calibration fingerprint so a rehome or range calibration invalidates it.
    """

    def __init__(self, mappings: dict, calibration: dict):
        validate_calibration(calibration)
        self.calibration = copy.deepcopy(calibration)
        self.mappings = copy.deepcopy(mappings)
        self.metadata = {"motors": {}}
        self.limits_deg: dict[str, list[tuple[float, float]]] = {}
        for side in ("left", "right"):
            mapping = self.mappings.get(side, {})
            if (
                mapping.get("schema_version") != 1
                or mapping.get("side") != side
                or mapping.get("robot_model") != "alohamini2pro"
                or mapping.get("ticks_per_revolution") != 4096
            ):
                raise ValueError(f"Invalid {side} arm mapping schema/model/encoder period")
            limits = []
            for joint in ARM_JOINTS:
                motor_name = f"arm_{side}_{joint}"
                motor = calibration[motor_name]
                entry = mapping.get("joints", {}).get(joint, {})
                fingerprint = {
                    key: motor[key] for key in ("homing_offset", "range_min", "range_max", "drive_mode")
                }
                if entry.get("id") != motor["id"] or entry.get("lerobot_calibration") != fingerprint:
                    raise ValueError(
                        f"Stale or unbound mapping for {motor_name}; run sync_arm_mapping with "
                        "the current calibration and a confirmed physical folded Home"
                    )
                reference = finite_number(entry.get("reference_tick"), f"{motor_name}.reference_tick")
                finite_number(entry.get("reference_q_rad"), f"{motor_name}.reference_q_rad")
                ratio = finite_number(entry.get("joint_per_encoder_ratio", 1.0), motor_name)
                if ratio <= 0 or entry.get("sign") not in (-1, 1):
                    raise ValueError(f"Invalid sign or encoder ratio for {motor_name}")
                if int(reference) != reference or not motor["range_min"] <= reference <= motor["range_max"]:
                    raise ValueError(f"Home reference outside current motor range for {motor_name}")
                self.metadata["motors"][motor_name] = {
                    **motor,
                    "normalization": "range_0_100" if joint == "gripper" else "degrees",
                }
                if joint == "gripper":
                    continue
                lo, hi = safe_q_range(entry, motor, int(reference), 4096)
                # Respect a narrower ROS2 range, and derive a bounded branch for
                # wrist_roll too: these servos run in single-turn position mode.
                lo = max(lo, finite_number(entry.get("safe_q_min_rad", lo), motor_name))
                hi = min(hi, finite_number(entry.get("safe_q_max_rad", hi), motor_name))
                if lo >= hi:
                    raise ValueError(f"Empty URDF range for {motor_name}")
                entry["safe_q_min_rad"], entry["safe_q_max_rad"] = lo, hi
                limits.append((math.degrees(lo), math.degrees(hi)))
            self.limits_deg[side] = limits
        self.mapper = JointMapper(self.mappings)

    @classmethod
    def load(cls, directory: str | Path, calibration: dict) -> ArmMapping:
        import yaml

        directory = Path(directory).expanduser()
        if not directory.is_dir():
            raise FileNotFoundError(
                f"Arm mapping missing: {directory}. Run python -m "
                "lerobot.vr_gateway.calibration.sync_arm_mapping --help to capture folded Home."
            )
        saved = json.loads((directory / "AlohaMiniRobot.json").read_text())
        for name, motor in calibration.items():
            if name.startswith("arm_") and saved.get(name) != motor:
                raise ValueError(f"Arm mapping calibration differs from current robot: {name}")
        mappings = {
            side: yaml.safe_load((directory / f"hardware_joint_map_{side}.yaml").read_text())
            for side in ("left", "right")
        }
        return cls(mappings, calibration)

    def to_urdf_deg(self, side: str, values) -> list[float]:
        result = []
        for joint, value in zip(ARM_JOINTS[:-1], values, strict=True):
            name = f"arm_{side}_{joint}"
            meta = self.metadata["motors"][name]
            value = finite_number(float(value), name)
            tick = self.mapper.lerobot_to_tick(value, meta)
            if not meta["range_min"] <= tick <= meta["range_max"]:
                raise ValueError(f"Measured {name} outside calibrated encoder range")
            suffix = "wrist_yaw_joint" if joint == "wrist_yaw" else joint
            q = self.mapper.tick_to_urdf(joint, tick, f"{side}_{suffix}", side=side)
            result.append(math.degrees(q))
        return result

    def to_robot_deg(self, side: str, values) -> list[float]:
        result = []
        for joint, value in zip(ARM_JOINTS[:-1], values, strict=True):
            suffix = "wrist_yaw_joint" if joint == "wrist_yaw" else joint
            _, degrees = self.mapper.urdf_to_lerobot(
                f"{side}_{suffix}", math.radians(float(value)), self.metadata
            )
            result.append(degrees)
        return result
