"""Read arm states directly without whole-robot connect/configure side effects."""

from __future__ import annotations

import time
from contextlib import ExitStack
from pathlib import Path


def read_arm_states(calibration: dict, left_port: str, right_port: str, samples: int = 10) -> list[dict]:
    """Read current EEPROM and stable-position samples; never write motor registers."""
    from lerobot.motors import MotorCalibration, MotorNormMode
    from lerobot.motors.feetech import FeetechMotorsBus
    from lerobot.robots.alohamini.alohamini import _make_arm_motors

    if Path(left_port).resolve() == Path(right_port).resolve():
        raise ValueError("Left and right arm ports must be different")
    metadata = {"schema_version": 1, "robot_model": "alohamini2pro", "motors": {}}
    buses = {}
    with ExitStack() as stack:
        for side, port in (("left", left_port), ("right", right_port)):
            motors = _make_arm_motors(f"arm_{side}", "am-follower-6dof-hd", MotorNormMode.DEGREES)
            bus = FeetechMotorsBus(
                port=port,
                motors=motors,
                calibration={name: MotorCalibration(**calibration[name]) for name in motors},
            )
            stack.callback(close_bus, bus)
            bus.connect()
            buses[side] = bus
            for register, field in (
                ("Homing_Offset", "homing_offset"),
                ("Min_Position_Limit", "range_min"),
                ("Max_Position_Limit", "range_max"),
            ):
                values = bus.sync_read(register, normalize=False)
                for name in motors:
                    if values[name] != calibration[name][field]:
                        raise ValueError(f"EEPROM and calibration JSON disagree: {name}.{field}")
            for name, motor in motors.items():
                metadata["motors"][name] = {
                    **calibration[name],
                    "normalization": motor.norm_mode.value,
                    "model": motor.model,
                }
        observations = []
        for _ in range(samples):
            observation = {"_robot_metadata": metadata, "_images": [], "_raw_positions": {}}
            for bus in buses.values():
                raw = bus.sync_read("Present_Position", normalize=False)
                observation["_raw_positions"].update(raw)
                for name, tick in raw.items():
                    meta = metadata["motors"][name]
                    lo, hi = meta["range_min"], meta["range_max"]
                    if name.endswith("_gripper"):
                        value = (tick - lo) * 100.0 / (hi - lo)
                        if meta["drive_mode"]:
                            value = 100.0 - value
                    else:
                        value = (tick - (lo + hi) / 2) * 360.0 / 4095
                    observation[f"{name}.pos"] = value
            observations.append(observation)
            time.sleep(0.04)
    return observations


def close_bus(bus) -> None:
    if bus.is_connected:
        bus.disconnect(disable_torque=False)
