"""Encoder/URDF conversions ported from alohamini_ros2's JointMapper.

This module has no ROS or ZMQ dependency. The installed motor ranges select the
encoder branch; the profile binds those encoder ticks to the CAD reference pose.
"""

from __future__ import annotations

import math
from typing import Any

ARM_JOINTS = (
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_yaw",
    "wrist_roll",
    "gripper",
)


def signed_tick_delta(tick: int, reference_tick: int, period: int) -> int:
    return int((int(tick) - int(reference_tick) + period // 2) % period - period // 2)


class JointMapper:
    """Convert between Host motor normalization and authoritative URDF space."""

    def __init__(self, calibration: dict[str, Any], lift_calibration: dict[str, Any] | None = None) -> None:
        if "ticks_per_revolution" in calibration:
            calibrations = dict.fromkeys(("left", "right"), calibration)
        else:
            calibrations = calibration
        if set(calibrations) != {"left", "right"}:
            raise ValueError("arm calibration must provide left and right mappings")
        periods = {int(calibrations[side]["ticks_per_revolution"]) for side in ("left", "right")}
        if len(periods) != 1:
            raise ValueError("left/right ticks_per_revolution must match")
        self.period = periods.pop()
        self.joints_by_side = {side: calibrations[side]["joints"] for side in ("left", "right")}
        self.joints = self.joints_by_side["right"]
        self.lift_calibration = lift_calibration
        self.previous: dict[str, float] = {}

    def _entry(self, side: str, joint: str) -> dict[str, Any]:
        try:
            return self.joints_by_side[side][joint]
        except KeyError as error:
            raise ValueError(f"missing calibration for {side}_{joint}") from error

    def lift_height_to_urdf(self, height_mm: float) -> float:
        if not isinstance(self.lift_calibration, dict):
            raise ValueError("lift-axis calibration is required")
        mechanism = self.lift_calibration["mechanism"]
        urdf = self.lift_calibration["urdf"]
        physical_min = float(mechanism["physical_min_mm"])
        physical_max = float(mechanism["physical_max_mm"])
        q_min = float(urdf["q_at_physical_min_m"])
        q_max = float(urdf["q_at_physical_max_m"])
        if physical_max <= physical_min or q_max <= q_min:
            raise ValueError("invalid lift-axis calibration range")
        height = float(height_mm)
        if bool(urdf.get("clamp_to_physical_range", True)):
            height = min(physical_max, max(physical_min, height))
        ratio = (height - physical_min) / (physical_max - physical_min)
        return q_min + ratio * (q_max - q_min)

    def lift_urdf_to_height(self, position_m: float) -> float:
        if not isinstance(self.lift_calibration, dict):
            raise ValueError("lift-axis calibration is required")
        mechanism = self.lift_calibration["mechanism"]
        urdf = self.lift_calibration["urdf"]
        physical_min = float(mechanism["physical_min_mm"])
        physical_max = float(mechanism["physical_max_mm"])
        q_min = float(urdf["q_at_physical_min_m"])
        q_max = float(urdf["q_at_physical_max_m"])
        position = finite_number(position_m, "vertical_move")
        if physical_max <= physical_min or q_max <= q_min:
            raise ValueError("invalid lift-axis calibration range")
        if position < q_min or position > q_max:
            raise ValueError(f"vertical_move {position:.6f} is outside [{q_min:.6f}, {q_max:.6f}]")
        ratio = (position - q_min) / (q_max - q_min)
        return physical_min + ratio * (physical_max - physical_min)

    def lerobot_to_tick(self, value: float, metadata: dict[str, Any]) -> int:
        lower = int(metadata["range_min"])
        upper = int(metadata["range_max"])
        if upper <= lower:
            raise ValueError("Host motor range_max must exceed range_min")
        mode = metadata["normalization"]
        drive_mode = int(metadata["drive_mode"])
        if mode == "range_m100_100":
            normalized = -value if drive_mode else value
            normalized = min(100.0, max(-100.0, normalized))
            return int(((normalized + 100.0) / 200.0) * (upper - lower) + lower)
        if mode == "range_0_100":
            normalized = 100.0 - value if drive_mode else value
            normalized = min(100.0, max(0.0, normalized))
            return int((normalized / 100.0) * (upper - lower) + lower)
        if mode == "degrees":
            midpoint = (lower + upper) / 2.0
            return round(value * (self.period - 1) / 360.0 + midpoint)
        raise ValueError(f"Unsupported Host normalization: {mode!r}")

    def tick_to_lerobot(self, tick: int, metadata: dict[str, Any]) -> float:
        lower = int(metadata["range_min"])
        upper = int(metadata["range_max"])
        if upper <= lower:
            raise ValueError("Host motor range_max must exceed range_min")
        mode = metadata["normalization"]
        drive_mode = int(metadata["drive_mode"])
        tick = min(upper, max(lower, int(tick)))
        if mode == "range_m100_100":
            normalized = (tick - lower) * 200.0 / (upper - lower) - 100.0
            return -normalized if drive_mode else normalized
        if mode == "range_0_100":
            normalized = (tick - lower) * 100.0 / (upper - lower)
            return 100.0 - normalized if drive_mode else normalized
        if mode == "degrees":
            midpoint = (lower + upper) / 2.0
            return (tick - midpoint) * 360.0 / (self.period - 1)
        raise ValueError(f"Unsupported Host normalization: {mode!r}")

    def tick_to_urdf(self, joint: str, tick: int, state_key: str, side: str | None = None) -> float:
        parsed_side, parsed_joint = self._joint_from_urdf_name(state_key)
        side = parsed_side if side is None else side
        if parsed_side != side or parsed_joint != joint:
            raise ValueError(f"state key {state_key} does not match {side}_{joint}")
        entry = self._entry(side, joint)
        delta = signed_tick_delta(tick, int(entry["reference_tick"]), self.period)
        ratio = float(entry.get("joint_per_encoder_ratio", 1.0))
        value = (
            float(entry["reference_q_rad"]) + int(entry["sign"]) * delta * 2.0 * math.pi / self.period * ratio
        )
        period_rad = 2.0 * math.pi * ratio
        if entry.get("safe_q_min_rad") is not None and entry.get("safe_q_max_rad") is not None:
            # Several calibrated arm ranges cross the encoder's periodic
            # branch.  On the first observation choose the unique equivalent
            # angle inside the installed robot's calibrated URDF interval. Keep
            # this branch on later samples too: single-turn position commands
            # cannot safely wrap from encoder 4095 to 0.
            lower = float(entry["safe_q_min_rad"])
            upper = float(entry["safe_q_max_rad"])
            midpoint = (lower + upper) / 2.0
            candidates = [
                value + turns * period_rad
                for turns in range(-2, 3)
                if lower - 1e-9 <= value + turns * period_rad <= upper + 1e-9
            ]
            if not candidates:
                raise ValueError(f"{state_key} encoder position has no branch inside calibrated limits")
            previous = self.previous.get(state_key, midpoint)
            value = min(candidates, key=lambda candidate: abs(candidate - previous))
            value = min(upper, max(lower, value))
        elif state_key in self.previous:
            value += round((self.previous[state_key] - value) / period_rad) * period_rad
        self.previous[state_key] = value
        return value

    @staticmethod
    def _joint_from_urdf_name(urdf_name: str) -> tuple[str, str]:
        side, separator, suffix = urdf_name.partition("_")
        if side not in ("left", "right") or not separator:
            raise ValueError(f"Unsupported arm joint: {urdf_name}")
        joint = "wrist_yaw" if suffix == "wrist_yaw_joint" else suffix
        if joint not in ARM_JOINTS:
            raise ValueError(f"Unsupported arm joint: {urdf_name}")
        return side, joint

    def urdf_to_lerobot(self, urdf_name: str, position: float, metadata: dict[str, Any]) -> tuple[str, float]:
        side, joint = self._joint_from_urdf_name(urdf_name)
        entry = self._entry(side, joint)
        q = finite_number(position, urdf_name)
        calibrated_limits = [
            float(entry[key]) for key in ("safe_q_min_rad", "safe_q_max_rad") if entry.get(key) is not None
        ]
        if joint == "wrist_roll" and not calibrated_limits:
            calibrated_limits = [-math.pi, math.pi]
        if joint == "gripper" and not calibrated_limits:
            calibrated_limits = [
                float(entry["urdf_open_rad"]),
                float(entry["urdf_closed_rad"]),
            ]
        if calibrated_limits:
            lower = min(calibrated_limits)
            upper = max(calibrated_limits)
            if q < lower or q > upper:
                # The measured folded Home sits exactly on the calibrated
                # boundary and small encoder drift pushes it a few epsilons
                # over; accept and clamp such marginal overflows instead of
                # rejecting every goal while the robot rests at Home.
                tolerance = 1.0e-4
                if q < lower - tolerance or q > upper + tolerance:
                    raise ValueError(f"{urdf_name} {q:.6f} is outside calibrated [{lower:.6f}, {upper:.6f}]")
                q = max(lower, min(upper, q))
        ratio = float(entry.get("joint_per_encoder_ratio", 1.0))
        sign = int(entry["sign"])
        if ratio == 0.0 or sign not in (-1, 1):
            raise ValueError(f"invalid calibration for {joint}")
        delta = (q - float(entry["reference_q_rad"])) * self.period
        delta /= sign * 2.0 * math.pi * ratio
        tick = (int(entry["reference_tick"]) + round(delta)) % self.period
        motor_name = f"arm_{side}_{joint}"
        motor_metadata = metadata.get("motors", {}).get(motor_name)
        if not isinstance(motor_metadata, dict):
            raise ValueError(f"Host metadata lacks {motor_name}")
        range_min = int(motor_metadata["range_min"])
        range_max = int(motor_metadata["range_max"])
        if tick < range_min or tick > range_max:
            raise ValueError(
                f"{urdf_name} maps to tick {tick}, outside Host range [{range_min}, {range_max}]"
            )
        return f"{motor_name}.pos", self.tick_to_lerobot(tick, motor_metadata)

    def observation_to_joint_positions(
        self, observation: dict[str, Any], metadata: dict[str, Any]
    ) -> dict[str, float]:
        motors = metadata.get("motors", {})
        positions: dict[str, float] = {}
        for side in ("left", "right"):
            for joint in ARM_JOINTS:
                motor_name = f"arm_{side}_{joint}"
                observation_key = f"{motor_name}.pos"
                motor_metadata = motors.get(motor_name)
                if observation_key not in observation or not isinstance(motor_metadata, dict):
                    continue
                tick = self.lerobot_to_tick(float(observation[observation_key]), motor_metadata)
                suffix = "wrist_yaw_joint" if joint == "wrist_yaw" else joint
                urdf_name = f"{side}_{suffix}"
                positions[urdf_name] = self.tick_to_urdf(joint, tick, urdf_name, side=side)
        if "lift_axis.height_mm" in observation:
            positions["vertical_move"] = self.lift_height_to_urdf(float(observation["lift_axis.height_mm"]))
        return positions


def finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field} must be finite")
    return result
