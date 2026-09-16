"""The capture path must read encoders without configuring or moving motors."""

from types import SimpleNamespace

import pytest

from lerobot.vr_gateway.calibration.hardware import read_arm_states
from lerobot.vr_gateway.calibration.joint_mapping import ARM_JOINTS


@pytest.mark.parametrize("mismatch", [False, True])
def test_serial_capture_checks_eeprom_and_closes_without_writes(monkeypatch, mismatch):
    from lerobot.motors import feetech
    from lerobot.vr_gateway.calibration import hardware

    calibration = {
        f"arm_{side}_{joint}": {
            "id": i,
            "drive_mode": 0,
            "homing_offset": 0,
            "range_min": 500,
            "range_max": 3500,
        }
        for side in ("left", "right")
        for i, joint in enumerate(ARM_JOINTS, 1)
    }
    buses = []

    class ReadOnlyBus:
        def __init__(self, port, motors, calibration):
            self.motors = motors
            self.is_connected = False
            self.closed = False
            buses.append(self)

        def connect(self):
            self.is_connected = True

        def sync_read(self, register, *, normalize):
            assert normalize is False
            values = {
                "Homing_Offset": 1 if mismatch else 0,
                "Min_Position_Limit": 500,
                "Max_Position_Limit": 3500,
                "Present_Position": 2048,
            }
            return dict.fromkeys(self.motors, values[register])

        def disconnect(self, *, disable_torque):
            assert disable_torque is False
            self.closed = True
            self.is_connected = False

    monkeypatch.setattr(feetech, "FeetechMotorsBus", ReadOnlyBus)
    monkeypatch.setattr(hardware.time, "sleep", lambda _: None)
    if mismatch:
        with pytest.raises(ValueError, match="EEPROM and calibration JSON disagree"):
            read_arm_states(calibration, "/dev/left", "/dev/right", samples=3)
    else:
        observations = read_arm_states(calibration, "/dev/left", "/dev/right", samples=3)
        assert len(observations) == 3
        assert observations[0]["_raw_positions"] == dict.fromkeys(calibration, 2048)
    assert buses and all(bus.closed for bus in buses)


def test_vr_connection_rejects_eeprom_mismatch_before_configure():
    from lerobot.robots.alohamini.alohamini import AlohaMini

    calls = []
    bus = SimpleNamespace(
        connect=lambda: calls.append("connect"),
        disconnect=lambda **kwargs: calls.append(("disconnect", kwargs)),
    )
    robot = SimpleNamespace(
        left_bus=bus,
        right_bus=bus,
        is_connected=False,
        is_calibrated=False,
        config=SimpleNamespace(require_calibration_match=True),
    )
    with pytest.raises(ValueError, match="EEPROM calibration differs"):
        AlohaMini.connect(robot)
    assert calls == [
        "connect",
        "connect",
        ("disconnect", {"disable_torque": False}),
        ("disconnect", {"disable_torque": False}),
    ]
