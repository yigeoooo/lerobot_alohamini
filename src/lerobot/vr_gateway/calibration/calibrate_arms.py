#!/usr/bin/env python3
"""Interactively calibrate both AlohaMini follower arms for LeRobot.

This tool deliberately bypasses AlohaMini.connect/configure and lift.home. It
opens only the existing arm buses, disables torque on arm motors 1..7, and
never emits a goal position or touches base/lift calibration registers.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

CONFIRMATION = "CALIBRATE BOTH ARMS"
ARM_JOINTS = (
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_yaw",
    "wrist_roll",
    "gripper",
)


def calibration_to_dict(calibration) -> dict[str, int]:
    return {
        "id": int(calibration.id),
        "drive_mode": int(calibration.drive_mode),
        "homing_offset": int(calibration.homing_offset),
        "range_min": int(calibration.range_min),
        "range_max": int(calibration.range_max),
    }


def merge_arm_calibrations(
    template: dict,
    left: dict,
    right: dict,
) -> dict:
    """Replace arm entries while preserving base/lift entries byte-for-byte."""
    result = {name: dict(entry) for name, entry in template.items()}
    expected = {f"arm_{side}_{joint}" for side in ("left", "right") for joint in ARM_JOINTS}
    captured = set(left) | set(right)
    if captured != expected:
        missing = sorted(expected - captured)
        extra = sorted(captured - expected)
        raise ValueError(f"arm capture mismatch; missing={missing}, extra={extra}")
    for name, calibration in {**left, **right}.items():
        result[name] = calibration_to_dict(calibration)
    return result


def read_selected_calibration(bus, motor_names, calibration_type):
    calibration = {}
    for name in motor_names:
        motor = bus.motors[name]
        calibration[name] = calibration_type(
            id=motor.id,
            drive_mode=0,
            homing_offset=int(bus.read("Homing_Offset", name, normalize=False)),
            range_min=int(bus.read("Min_Position_Limit", name, normalize=False)),
            range_max=int(bus.read("Max_Position_Limit", name, normalize=False)),
        )
    return calibration


def calibrate_one_arm(
    bus,
    side,
    motor_names,
    previous,
    rehome,
    calibration_type,
    operating_mode,
):
    bus.disable_torque(motor_names)

    if rehome:
        for name in motor_names:
            bus.write("Operating_Mode", name, operating_mode.POSITION.value)
        input(
            f"Move the {side.upper()} arm to the middle of every joint's usable "
            "range, then press ENTER to rewrite homing offsets: "
        )
        homings = bus.set_half_turn_homings(motor_names)
    else:
        homings = {name: int(previous[name].homing_offset) for name in motor_names}

    full_turn_name = f"arm_{side}_wrist_roll"
    ranged_names = [name for name in motor_names if name != full_turn_name]
    print(
        f"Move every {side.upper()} arm joint through its complete safe range. "
        "Include the gripper; wrist_roll is treated as a full turn. Press ENTER to finish."
    )
    mins, maxes = bus.record_ranges_of_motion(ranged_names)
    mins[full_turn_name] = 0
    maxes[full_turn_name] = 4095

    result = {}
    for name in motor_names:
        motor = bus.motors[name]
        result[name] = calibration_type(
            id=motor.id,
            drive_mode=0,
            homing_offset=int(homings[name]),
            range_min=int(mins[name]),
            range_max=int(maxes[name]),
        )
    bus.write_calibration(result, cache=False)
    return result


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Torque-disabled, manual dual-arm calibration. Writes arm EEPROM "
            "homing offsets/ranges and generates a LeRobot AlohaMiniRobot JSON."
        )
    )
    parser.add_argument(
        "--robot-model", default="alohamini2pro", choices=("alohamini1", "alohamini2", "alohamini2pro")
    )
    parser.add_argument("--left-port", help="Left arm serial device, for example /dev/ttyACM0")
    parser.add_argument("--right-port", help="Right arm serial device, for example /dev/ttyACM1")
    parser.add_argument(
        "--list-ports",
        action="store_true",
        help="List likely arm serial devices without opening them, then exit",
    )
    parser.add_argument("--id", default="AlohaMiniRobot")
    parser.add_argument(
        "--rehome",
        action="store_true",
        help=(
            "Also rewrite half-turn homing offsets. By default only min/max "
            "ranges are captured and existing homing offsets are preserved."
        ),
    )
    parser.add_argument(
        "--template",
        type=Path,
        help="Existing full-robot JSON whose untouched base/lift entries are preserved",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path.cwd() / "AlohaMiniRobot.candidate.json",
    )
    return parser.parse_args()


def serial_candidates() -> list[Path]:
    candidates = list(Path("/dev/serial/by-id").glob("*"))
    candidates.extend(Path("/dev").glob("ttyACM*"))
    return sorted(set(candidates), key=str)


def resolve_arm_ports(left: str | None, right: str | None) -> tuple[str, str]:
    if (left is None) != (right is None):
        raise ValueError("provide both --left-port and --right-port")
    if left is not None and right is not None:
        if left == right:
            raise ValueError("left and right ports must be different")
        missing = [port for port in (left, right) if not Path(port).exists()]
        if missing:
            raise FileNotFoundError(f"serial devices do not exist: {missing}")
        return left, right

    aliases = ("/dev/am_arm_follower_left", "/dev/am_arm_follower_right")
    if all(Path(port).exists() for port in aliases):
        return aliases
    found = [str(path) for path in serial_candidates()]
    raise ValueError(
        "left/right arm ports are not identified. Available candidates: "
        f"{found}. ttyACM numbering is not a stable side identity; pass both "
        "--left-port and --right-port explicitly"
    )


def default_template(robot_id: str = "AlohaMiniRobot") -> Path:
    from lerobot.utils.constants import HF_LEROBOT_CALIBRATION

    return HF_LEROBOT_CALIBRATION / f"robots/alohamini/{robot_id}.json"


def main() -> int:
    args = parse_args()
    if args.list_ports:
        candidates = serial_candidates()
        if candidates:
            print("\n".join(str(path) for path in candidates))
        else:
            print("No /dev/serial/by-id/* or /dev/ttyACM* devices found.")
        return 0
    if importlib.util.find_spec("lerobot") is None:
        print(
            "ERROR: LeRobot is not importable in the current Python environment. "
            "Use the project's LeRobot Python environment.",
            file=sys.stderr,
        )
        return 2
    try:
        left_port, right_port = resolve_arm_ports(args.left_port, args.right_port)
    except (FileNotFoundError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    template_path = args.template or default_template(args.id)
    with template_path.open(encoding="utf-8") as stream:
        template = json.load(stream)

    operation = (
        "rewrites Homing_Offset and position limits"
        if args.rehome
        else "preserves Homing_Offset and rewrites only position limits"
    )
    print(
        f"DANGER: this is a real EEPROM calibration. It {operation} on arm "
        "motors 1..7.\n"
        "Stop LeRobot Host, teleoperation, and every other serial-bus owner first.\n"
        "The tool will NOT enable torque, command motion, home the lift, or modify "
        "base/lift calibration.",
        file=sys.stderr,
    )
    if input(f"Type exactly '{CONFIRMATION}' to continue: ").strip() != CONFIRMATION:
        print("Calibration cancelled; no serial port was opened.", file=sys.stderr)
        return 2

    if args.output.exists():
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        backup = args.output.with_name(f"{args.output.name}.backup-{stamp}")
        shutil.copy2(args.output, backup)
        print(f"Backed up existing calibration to {backup}")

    # Import LeRobot only after explicit confirmation so a missing environment or
    # cancelled run cannot instantiate hardware objects.
    from lerobot.motors import MotorCalibration
    from lerobot.motors.feetech import OperatingMode
    from lerobot.robots.alohamini.alohamini import AlohaMini
    from lerobot.robots.alohamini.config_alohamini import AlohaMiniConfig

    config = AlohaMiniConfig()
    config.id = args.id
    config.robot_model = args.robot_model
    config.left_port = left_port
    config.right_port = right_port
    config.no_follower = False
    config.cameras = {}
    robot = AlohaMini(config)

    left_connected = False
    right_connected = False
    previous_left = None
    previous_right = None
    success = False
    try:
        robot.left_bus.connect()
        left_connected = True
        robot.right_bus.connect()
        right_connected = True

        left_names = list(robot.left_arm_motors)
        right_names = list(robot.right_arm_motors)
        previous_left = read_selected_calibration(robot.left_bus, left_names, MotorCalibration)
        previous_right = read_selected_calibration(robot.right_bus, right_names, MotorCalibration)
        print("Read Homing_Offset directly from connected motor EEPROM:")
        for side, calibration in (("LEFT", previous_left), ("RIGHT", previous_right)):
            print(f"  {side}")
            for name, entry in calibration.items():
                print(
                    f"    {name}: homing_offset={entry.homing_offset} "
                    f"range=[{entry.range_min}, {entry.range_max}]"
                )

        left = calibrate_one_arm(
            robot.left_bus,
            "left",
            left_names,
            previous_left,
            args.rehome,
            MotorCalibration,
            OperatingMode,
        )
        right = calibrate_one_arm(
            robot.right_bus,
            "right",
            right_names,
            previous_right,
            args.rehome,
            MotorCalibration,
            OperatingMode,
        )
        document = merge_arm_calibrations(template, left, right)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", dir=args.output.parent, delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(document, stream, indent=4)
                stream.write("\n")
            temporary.replace(args.output)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        success = True
        print(f"Wrote dual-arm LeRobot calibration: {args.output}")
        print(
            "Arm torque remains disabled. If this is a candidate path, install it "
            "in the LeRobot calibration cache. Next capture a new folded-Home mapping."
        )
        return 0
    except BaseException:
        if success:
            raise
        if left_connected and previous_left is not None:
            try:
                robot.left_bus.write_calibration(previous_left, cache=False)
                print("Restored previous LEFT arm EEPROM calibration.", file=sys.stderr)
            except Exception as error:
                print(f"FAILED to restore LEFT arm calibration: {error}", file=sys.stderr)
        if right_connected and previous_right is not None:
            try:
                robot.right_bus.write_calibration(previous_right, cache=False)
                print("Restored previous RIGHT arm EEPROM calibration.", file=sys.stderr)
            except Exception as error:
                print(f"FAILED to restore RIGHT arm calibration: {error}", file=sys.stderr)
        raise
    finally:
        # Never call robot.disconnect(): its implementation may apply whole-robot
        # lifecycle behavior. Close the two buses without further torque writes.
        if robot.right_bus and robot.right_bus.is_connected:
            robot.right_bus.disconnect(disable_torque=False)
        if robot.left_bus.is_connected:
            robot.left_bus.disconnect(disable_torque=False)
        if not success:
            print("Calibration did not complete; do not deploy a partial output.", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
