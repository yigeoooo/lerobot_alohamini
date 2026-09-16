from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from lerobot.vr_gateway.calibration import calibrate_arms as module


@dataclass
class Calibration:
    id: int
    drive_mode: int
    homing_offset: int
    range_min: int
    range_max: int


def arm(side):
    return {
        f"arm_{side}_{joint}": Calibration(index, 0, index, 100, 3000)
        for index, joint in enumerate(module.ARM_JOINTS, start=1)
    }


def test_merge_replaces_arms_and_preserves_base_lift():
    template = {
        "base_left_wheel": {"marker": "unchanged"},
        "lift_axis": {"marker": "unchanged"},
        **{name: {"old": True} for name in (*arm("left"), *arm("right"))},
    }

    result = module.merge_arm_calibrations(template, arm("left"), arm("right"))

    assert result["base_left_wheel"] == {"marker": "unchanged"}
    assert result["lift_axis"] == {"marker": "unchanged"}
    assert result["arm_left_shoulder_pan"]["homing_offset"] == 1
    assert result["arm_right_gripper"]["id"] == 7


class FakeBus:
    def __init__(self, names):
        self.motors = {name: SimpleNamespace(id=index) for index, name in enumerate(names, start=1)}
        self.homing_calls = 0
        self.written = None

    def disable_torque(self, names):
        self.disabled = list(names)

    def write(self, register, name, value):
        pass

    def set_half_turn_homings(self, names):
        self.homing_calls += 1
        return {name: 200 + index for index, name in enumerate(names)}

    def record_ranges_of_motion(self, names):
        return (
            {name: 100 + index for index, name in enumerate(names)},
            {name: 3000 + index for index, name in enumerate(names)},
        )

    def write_calibration(self, calibration, cache=False):
        self.written = calibration


class PositionMode:
    value = 0


class OperatingMode:
    POSITION = PositionMode()


def test_default_range_capture_preserves_homing_offsets():
    names = [f"arm_left_{joint}" for joint in module.ARM_JOINTS]
    previous = {
        name: Calibration(index, 0, -500 - index, 0, 4095) for index, name in enumerate(names, start=1)
    }
    bus = FakeBus(names)

    result = module.calibrate_one_arm(bus, "left", names, previous, False, Calibration, OperatingMode)

    assert bus.homing_calls == 0
    assert {name: calibration.homing_offset for name, calibration in result.items()} == {
        name: calibration.homing_offset for name, calibration in previous.items()
    }


def test_explicit_ports_must_exist_and_be_distinct(tmp_path):
    left = tmp_path / "ttyACM-left"
    right = tmp_path / "ttyACM-right"
    left.touch()
    right.touch()

    assert module.resolve_arm_ports(str(left), str(right)) == (str(left), str(right))
    with pytest.raises(ValueError, match="different"):
        module.resolve_arm_ports(str(left), str(left))
    with pytest.raises(ValueError, match="both"):
        module.resolve_arm_ports(str(left), None)
