from unittest.mock import MagicMock, call

from lerobot.robots.alohamini.alohamini import AlohaMini


def _bus(motors: list[str]) -> MagicMock:
    bus = MagicMock()
    bus.motors = dict.fromkeys(motors)
    positions = {name: float(index) for index, name in enumerate(motors)}
    bus.sync_read.side_effect = lambda _register, names: {name: positions[name] for name in names}
    bus.read.return_value = 1
    return bus


def test_configure_seeds_safe_targets_before_enabling_torque():
    left_arm = ["arm_left_shoulder_pan", "arm_left_shoulder_lift"]
    base = ["base_left_wheel", "base_right_wheel"]
    right_arm = ["arm_right_shoulder_pan", "arm_right_shoulder_lift"]
    left = _bus([*left_arm, *base, "lift_axis"])
    right = _bus(right_arm)

    robot = AlohaMini.__new__(AlohaMini)
    robot.left_bus = left
    robot.right_bus = right
    robot.left_arm_motors = left_arm
    robot.right_arm_motors = right_arm
    robot.base_motors = base
    robot.lift = MagicMock(enabled=True)
    robot.lift.cfg.name = "lift_axis"

    robot.configure()

    left.sync_write.assert_has_calls(
        [
            call("Goal_Position", {left_arm[0]: 0.0, left_arm[1]: 1.0}),
            call("Goal_Velocity", dict.fromkeys(base, 0)),
        ]
    )
    right.sync_write.assert_called_once_with(
        "Goal_Position", {right_arm[0]: 0.0, right_arm[1]: 1.0}
    )
    left.enable_torque.assert_called_once_with(list(left.motors))
    right.enable_torque.assert_called_once_with(list(right.motors))
    assert left.method_calls.index(call.sync_write("Goal_Position", {left_arm[0]: 0.0, left_arm[1]: 1.0})) \
        < left.method_calls.index(call.enable_torque(list(left.motors)))


def test_enable_and_verify_torque_rejects_a_disabled_motor():
    bus = _bus(["joint_a", "joint_b"])
    bus.read.side_effect = [1, 0]

    try:
        AlohaMini._enable_and_verify_torque(bus, list(bus.motors))
    except RuntimeError as exc:
        assert "joint_b" in str(exc)
    else:
        raise AssertionError("disabled motor was not rejected")
