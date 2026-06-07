#!/usr/bin/env python3

import argparse

from lerobot.common.control_utils import init_keyboard_listener
from lerobot.datasets.lerobot_dataset import LeRobotDataset
from lerobot.processor import make_default_processors
from lerobot.robots.alohamini.config_lekiwi import LeKiwiClientConfig
from lerobot.robots.alohamini.lekiwi_client import LeKiwiClient
from lerobot.scripts.lerobot_record import record_loop
from lerobot.teleoperators.bi_so_leader import BiSOLeader, BiSOLeaderConfig
from lerobot.teleoperators.keyboard import KeyboardTeleop, KeyboardTeleopConfig
from lerobot.teleoperators.so_leader import SOLeaderConfig
from lerobot.utils.constants import ACTION, HF_LEROBOT_HOME, OBS_STR
from lerobot.utils.feature_utils import hw_to_dataset_features
from lerobot.utils.utils import log_say
from lerobot.utils.visualization_utils import init_rerun


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Record AlohaMini bi-arm episodes until a key is pressed. "
            "Right arrow finishes the current episode, left arrow rerecords it, Esc stops recording."
        )
    )
    parser.add_argument(
        "--dataset",
        type=str,
        required=True,
        help="Dataset repo_id, e.g. liyitenga/record_20250914225057",
    )
    parser.add_argument("--num_episodes", type=int, default=1, help="Number of episodes to record")
    parser.add_argument("--fps", type=int, default=30, help="Frames per second")
    parser.add_argument("--task_description", type=str, default="My task description4", help="Task description")
    parser.add_argument("--remote_ip", type=str, default="127.0.0.1", help="Robot host IP")
    parser.add_argument("--robot_id", type=str, default="lekiwi_host", help="Robot ID")
    parser.add_argument("--leader_id", type=str, default="so101_leader_bi", help="Leader arm device ID")
    parser.add_argument(
        "--arm_profile",
        type=str,
        default="so-arm-5dof",
        choices=["so-arm-5dof", "am-leader-6dof"],
        help="Leader arm profile selector.",
    )
    parser.add_argument("--resume", action="store_true", help="Resume recording on existing dataset")
    return parser.parse_args()


def main():
    args = parse_args()

    robot_config = LeKiwiClientConfig(remote_ip=args.remote_ip, id=args.robot_id)
    leader_arm_config = BiSOLeaderConfig(
        left_arm_config=SOLeaderConfig(
            port="/dev/ttyACM0",
            arm_profile=args.arm_profile,
        ),
        right_arm_config=SOLeaderConfig(
            port="/dev/ttyACM1",
            arm_profile=args.arm_profile,
        ),
        id=args.leader_id,
    )
    keyboard_config = KeyboardTeleopConfig()

    robot = LeKiwiClient(robot_config)
    leader_arm = BiSOLeader(leader_arm_config)
    keyboard = KeyboardTeleop(keyboard_config)
    dataset = None
    listener = None

    teleop_action_processor, robot_action_processor, robot_observation_processor = make_default_processors()

    action_features = hw_to_dataset_features(robot.action_features, ACTION)
    obs_features = hw_to_dataset_features(robot.observation_features, OBS_STR)
    dataset_features = {**action_features, **obs_features}

    try:
        if args.resume:
            print("Resuming existing dataset:", args.dataset)
            dataset = LeRobotDataset.resume(
                repo_id=args.dataset,
                root=HF_LEROBOT_HOME / args.dataset,
                image_writer_threads=4,
            )
        else:
            dataset = LeRobotDataset.create(
                repo_id=args.dataset,
                fps=args.fps,
                features=dataset_features,
                robot_type=robot.name,
                use_videos=True,
                image_writer_threads=4,
            )
            print(f"Dataset created with id: {dataset.repo_id}")

        robot.connect()
        leader_arm.connect()
        keyboard.connect()

        listener, events = init_keyboard_listener()
        if listener is None:
            raise RuntimeError("Keyboard listener is required for manual-stop recording.")

        init_rerun(session_name="lekiwi_record_until_key")

        if not robot.is_connected or not leader_arm.is_connected or not keyboard.is_connected:
            raise ValueError("Robot or teleop is not connected!")

        print("Starting record loop...")
        print("Controls: RIGHT=finish episode, LEFT=rerecord episode, ESC=stop recording.")
        recorded_episodes = 0

        while recorded_episodes < args.num_episodes and not events["stop_recording"]:
            log_say(f"Recording episode {recorded_episodes + 1} of {args.num_episodes}")
            print("Recording... press RIGHT to finish this episode.")

            record_loop(
                robot=robot,
                events=events,
                fps=args.fps,
                dataset=dataset,
                teleop=[leader_arm, keyboard],
                control_time_s=None,
                single_task=args.task_description,
                display_data=True,
                teleop_action_processor=teleop_action_processor,
                robot_action_processor=robot_action_processor,
                robot_observation_processor=robot_observation_processor,
            )

            if not events["stop_recording"] and (
                (recorded_episodes < args.num_episodes - 1) or events["rerecord_episode"]
            ):
                log_say("Reset the environment")
                print("Resetting... press RIGHT when the environment is ready.")
                record_loop(
                    robot=robot,
                    events=events,
                    fps=args.fps,
                    teleop=[leader_arm, keyboard],
                    control_time_s=None,
                    single_task=args.task_description,
                    display_data=True,
                    teleop_action_processor=teleop_action_processor,
                    robot_action_processor=robot_action_processor,
                    robot_observation_processor=robot_observation_processor,
                )

            if events["rerecord_episode"]:
                log_say("Re-record episode")
                events["rerecord_episode"] = False
                events["exit_early"] = False
                dataset.clear_episode_buffer()
                continue

            dataset.save_episode()
            recorded_episodes += 1

    finally:
        log_say("Stop recording")
        if robot.is_connected:
            robot.disconnect()
        if leader_arm.is_connected:
            leader_arm.disconnect()
        if keyboard.is_connected:
            keyboard.disconnect()
        if listener is not None:
            listener.stop()
        if dataset is not None:
            dataset.finalize()

    dataset.push_to_hub()


if __name__ == "__main__":
    main()
