#!/usr/bin/env python3

from __future__ import annotations

import argparse
import base64
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
import io
import time
from typing import Any
import numpy as np
import requests
import torch
from PIL import Image

from lerobot.datasets.lerobot_dataset import LeRobotDataset
from lerobot.utils.feature_utils import build_dataset_frame, hw_to_dataset_features
from lerobot.processor import make_default_processors
from lerobot.processor.converters import (
    observation_to_transition,
    transition_to_observation,
)
from lerobot.processor.pipeline import (
    ActionProcessorStep,
    ObservationProcessorStep,
    RobotProcessorPipeline,
)
from lerobot.robots.alohamini import LeKiwiClient, LeKiwiClientConfig
from lerobot.utils.constants import ACTION, OBS_STATE, OBS_STR
from lerobot.common.control_utils import init_keyboard_listener
from lerobot.utils.robot_utils import precise_sleep
from lerobot.utils.utils import log_say
from lerobot.utils.visualization_utils import init_rerun, log_rerun_data


def _expected_api16_state_order() -> list[str]:
    # OpenPI AlohaMini API16 (dataset/robot interface) order.
    return [
        "arm_left_shoulder_pan.pos",
        "arm_left_shoulder_lift.pos",
        "arm_left_elbow_flex.pos",
        "arm_left_wrist_flex.pos",
        "arm_left_wrist_roll.pos",
        "arm_left_gripper.pos",
        "arm_right_shoulder_pan.pos",
        "arm_right_shoulder_lift.pos",
        "arm_right_elbow_flex.pos",
        "arm_right_wrist_flex.pos",
        "arm_right_wrist_roll.pos",
        "arm_right_gripper.pos",
        "x.vel",
        "y.vel",
        "theta.vel",
        "lift_axis.height_mm",
    ]


def _expected_api18_state_order() -> list[str]:
    # OpenPI AlohaMini2Pro API18 order. Must match openpi config alohamini2pro_0604.
    return [
        "arm_left_shoulder_pan.pos",
        "arm_left_shoulder_lift.pos",
        "arm_left_elbow_flex.pos",
        "arm_left_wrist_flex.pos",
        "arm_left_wrist_yaw.pos",
        "arm_left_wrist_roll.pos",
        "arm_left_gripper.pos",
        "arm_right_shoulder_pan.pos",
        "arm_right_shoulder_lift.pos",
        "arm_right_elbow_flex.pos",
        "arm_right_wrist_flex.pos",
        "arm_right_wrist_yaw.pos",
        "arm_right_wrist_roll.pos",
        "arm_right_gripper.pos",
        "x.vel",
        "y.vel",
        "theta.vel",
        "lift_axis.height_mm",
    ]


def _validate_state_action_order(
    dataset_features: dict[str, dict],
    requested_dof: int | None = None,
) -> tuple[list[str], int]:
    expected_api16 = _expected_api16_state_order()
    expected_api18 = _expected_api18_state_order()

    state_ft = dataset_features.get("observation.state")
    action_ft = dataset_features.get("action")
    if not isinstance(state_ft, dict) or not isinstance(action_ft, dict):
        raise ValueError("Missing required dataset features: 'observation.state' and/or 'action'.")

    state_names = list(state_ft.get("names") or [])
    action_names = list(action_ft.get("names") or [])

    if state_names != action_names:
        raise ValueError(
            "State/action name order mismatch.\n"
            f"- observation.state.names: {state_names}\n"
            f"- action.names: {action_names}\n"
        )

    state_dim = int(state_ft.get("shape", (0,))[0])
    action_dim = int(action_ft.get("shape", (0,))[0])

    if requested_dof is not None and requested_dof not in (16, 18):
        raise ValueError(f"requested_dof must be 16 or 18, got {requested_dof}")

    if state_dim != action_dim:
        raise ValueError(f"State/action dim mismatch: state={state_dim}, action={action_dim}")
    if state_dim not in (16, 18):
        raise ValueError(f"Only 16/18-DoF are supported, got dim={state_dim}")
    if requested_dof is not None and state_dim != requested_dof:
        raise ValueError(f"Requested {requested_dof}-DoF but robot/dataset features report {state_dim}-DoF")

    if state_dim == 16 and state_names != expected_api16:
        raise ValueError(
            "State/action order does not match OpenPI AlohaMini API16.\n"
            f"- expected: {expected_api16}\n"
            f"- got:      {state_names}\n"
        )
    if state_dim == 18 and state_names != expected_api18:
        raise ValueError(
            "State/action order does not match OpenPI AlohaMini2Pro API18.\n"
            f"- expected: {expected_api18}\n"
            f"- got:      {state_names}\n"
        )

    if not state_names:
        state_names = [f"joint_{i}" for i in range(state_dim)]

    return state_names, state_dim


def _print_camera_info(
    robot: LeKiwiClient,
    dataset_features: dict[str, dict],
    obs_sample: dict[str, Any],
    camera_mapping: dict[str, str],
) -> None:
    # Dataset feature declared shapes (from robot config).
    for cam in camera_mapping:
        k = f"observation.images.{cam}"
        if k in dataset_features:
            print(f"[camera] feature {k} shape={dataset_features[k].get('shape')} dtype={dataset_features[k].get('dtype')}")
        else:
            print(f"[camera] feature {k} missing in dataset_features")

    # Live frames (from robot observation).
    for cam in camera_mapping:
        v = obs_sample.get(cam)
        if isinstance(v, np.ndarray):
            print(f"[camera] live {cam} shape={v.shape} dtype={v.dtype}")
        else:
            print(f"[camera] live {cam} missing or not ndarray (type={type(v).__name__})")

    # Mapping sanity (LeRobot -> OpenPI expected camera names)
    print(f"[camera] lerobot->openpi mapping: {camera_mapping}")


def _maybe_print_server_metadata(server_url: str, timeout_s: float = 2.0) -> None:
    try:
        resp = requests.get(f"{server_url.rstrip('/')}/metadata", timeout=timeout_s)
        resp.raise_for_status()
        meta = resp.json()
        if isinstance(meta, dict):
            keys = sorted(meta.keys())
            print(f"[server] /metadata keys={keys}")
            # Avoid printing huge blobs.
            for k in ("name", "config", "model", "action_horizon", "action_dim", "robot"):
                if k in meta:
                    print(f"[server] {k}={meta[k]}")
            # Print action normalization info if available
            if "config" in meta and isinstance(meta["config"], dict):
                config = meta["config"]
                if "output_transforms" in config:
                    print(f"[server] output_transforms={config['output_transforms']}")
        else:
            print(f"[server] /metadata returned non-dict: {type(meta).__name__}")
    except Exception as e:
        print(f"[server] failed to fetch /metadata from {server_url!r}: {e}")


def _validate_action_values(
    action_tensor: Any,
    action_dict: dict[str, Any],
    dataset_features: dict[str, dict],
    expected_order: list[str],
    expected_action_dim: int,
    frame_idx: int = 0,
    log_every_n: int = 30,
) -> None:
    """Validate action values: dimension, range, and key matching."""
    import torch

    # Convert to numpy for validation
    if isinstance(action_tensor, torch.Tensor):
        action_array = action_tensor.detach().cpu().numpy()
    else:
        action_array = np.asarray(action_tensor)

    # Flatten if needed
    if action_array.ndim > 1:
        action_array = action_array.flatten()

    # Check dimension
    if len(action_array) != expected_action_dim:
        print(f"[action_validation] ERROR: Action dim mismatch: expected {expected_action_dim}, got {len(action_array)}")
        return

    # Check for NaN/Inf
    if np.any(np.isnan(action_array)) or np.any(np.isinf(action_array)):
        print(f"[action_validation] ERROR: Action contains NaN or Inf values!")
        print(f"[action_validation] action_array={action_array}")

    # Check value ranges (only log periodically to avoid spam)
    if frame_idx % log_every_n == 0:
        action_min = float(np.min(action_array))
        action_max = float(np.max(action_array))
        action_mean = float(np.mean(np.abs(action_array)))

        # Expected ranges (approximate)
        # Joint angles: typically ±π (≈ ±3.14) or ±180°
        # Gripper: typically [0, 1] or specific range
        # Base velocity: typically small (e.g., ±0.5 m/s)
        # Lift: typically in mm, depends on robot

        if expected_action_dim == 16:
            joint_angles = action_array[:12]
            base_vel = action_array[12:15]
            lift = action_array[15:16]
        elif expected_action_dim == 18:
            joint_angles = action_array[:14]
            base_vel = action_array[14:17]
            lift = action_array[17:18]
        else:
            raise ValueError(f"Unsupported action dim for validation: {expected_action_dim}. Expected 16 or 18.")

        warnings = []
        critical_errors = []

        # Check for extremely large values (likely unnormalized or wrong scale)
        if action_max > 100.0 or action_min < -100.0:
            critical_errors.append(
                f"CRITICAL: Action values extremely large (range=[{action_min:.2f}, {action_max:.2f}]). "
                f"This suggests actions may not be properly denormalized or have wrong scale."
            )

        if joint_angles.size and np.any(np.abs(joint_angles) > 10.0):  # > ~3π, clearly abnormal
            warnings.append(f"Joint angles out of range: min={joint_angles.min():.2f}, max={joint_angles.max():.2f}")
        if base_vel.size >= 2 and np.any(np.abs(base_vel[:2]) > 5.0):  # x, y velocity > 5 m/s, clearly abnormal
            warnings.append(f"Base x/y velocity out of range: {base_vel[:2]}")
        if lift.size and np.any(np.abs(lift) > 1000.0):  # Lift > 1000mm, likely abnormal
            warnings.append(f"Lift axis out of range: {lift}")

        if critical_errors:
            print(f"[action_validation] ERROR (frame {frame_idx}):")
            for err in critical_errors:
                print(f"  {err}")
            print(f"  Full action array: {action_array}")
            print(f"  SUGGESTION: Check if server returns normalized actions that need denormalization.")
            print(f"  SUGGESTION: Use --training_dataset_id to load stats for denormalization.")

        if warnings:
            print(f"[action_validation] WARNING (frame {frame_idx}):")
            for w in warnings:
                print(f"  {w}")
            print(f"  Full action: min={action_min:.2f}, max={action_max:.2f}, mean_abs={action_mean:.2f}")

    # Check key matching
    action_names = dataset_features.get("action", {}).get("names", [])
    if len(action_names) == len(expected_order):
        for i, (name, expected) in enumerate(zip(action_names, expected_order)):
            if name != expected:
                if frame_idx == 0:  # Only log once
                    print(f"[action_validation] WARNING: Action name mismatch at index {i}: got '{name}', expected '{expected}'")
    else:
        if frame_idx == 0:
            print(f"[action_validation] WARNING: Action names length mismatch: got {len(action_names)}, expected {len(expected_order)}")

    # Check action_dict keys match robot._state_order
    if frame_idx == 0:
        missing_keys = []
        for key in expected_order:
            if key not in action_dict:
                missing_keys.append(key)
        if missing_keys:
            print(f"[action_validation] WARNING: Missing action keys in dict: {missing_keys}")


def _maybe_bgr_to_rgb(obs: dict[str, Any], camera_keys: tuple[str, ...]) -> dict[str, Any]:
    out = dict(obs)
    for k in camera_keys:
        img = out.get(k)
        if isinstance(img, np.ndarray) and img.ndim == 3 and img.shape[-1] == 3 and img.dtype == np.uint8:
            # OpenCV decode returns BGR by default.
            out[k] = img[..., ::-1].copy()
    return out


class BGRToRGBProcessorStep(ObservationProcessorStep):
    """Convert BGR images to RGB for OpenPI compatibility (training uses RGB from torchvision VideoReader)."""

    def __init__(self, camera_keys: tuple[str, ...] = ("chest", "wrist_left", "wrist_right")):
        self.camera_keys = camera_keys

    def observation(self, observation: dict[str, Any]) -> dict[str, Any]:
        return _maybe_bgr_to_rgb(observation, self.camera_keys)

    def transform_features(
        self, features: dict[str, Any]
    ) -> dict[str, Any]:
        # No feature shape changes, just color channel reordering.
        return features


class ActionDenormalizeProcessorStep(ActionProcessorStep):
    """Denormalize actions using training dataset statistics.

    This step checks if actions appear to be in normalized range (e.g., [-1, 1] or [0, 1])
    and denormalizes them using dataset statistics if training_stats are provided.
    """

    def __init__(
        self,
        training_stats: dict[str, dict[str, Any]] | None = None,
        action_key: str = "action",
    ):
        self.training_stats = training_stats
        self.action_key = action_key
        self._has_warned = False

    def action(self, action: Any) -> Any:
        import torch

        if self.training_stats is None or self.action_key not in self.training_stats:
            return action

        # Convert to numpy
        if isinstance(action, torch.Tensor):
            action_array = action.detach().cpu().numpy()
        else:
            action_array = np.asarray(action)

        # Flatten if needed
        original_shape = action_array.shape
        if action_array.ndim > 1:
            action_array = action_array.flatten()

        # Check if action appears to be in normalized range
        action_min = float(np.min(action_array))
        action_max = float(np.max(action_array))
        action_mean_abs = float(np.mean(np.abs(action_array)))

        # Heuristic: if values are mostly in [-2, 2] range, might be normalized
        # But if values are very large (hundreds/thousands), likely already denormalized or wrong
        is_likely_normalized = (
            action_mean_abs < 2.0
            and action_min > -5.0
            and action_max < 5.0
            and not self._has_warned
        )

        if is_likely_normalized:
            stats = self.training_stats[self.action_key]
            if "mean" in stats and "std" in stats:
                mean = stats["mean"]
                std = stats["std"]

                # Convert to numpy if needed
                if isinstance(mean, torch.Tensor):
                    mean = mean.numpy()
                if isinstance(std, torch.Tensor):
                    std = std.numpy()

                # Ensure compatible shapes
                if mean.ndim > 1:
                    mean = mean.flatten()
                if std.ndim > 1:
                    std = std.flatten()

                # Pad or slice to match action dimension
                action_dim = len(action_array)
                stats_dim = len(mean)
                if action_dim > stats_dim:
                    # Pad with zeros (mean=0, std=1 for extra dims)
                    mean = np.concatenate([mean, np.zeros(action_dim - stats_dim)])
                    std = np.concatenate([std, np.ones(action_dim - stats_dim)])
                elif action_dim < stats_dim:
                    # Slice to match
                    mean = mean[:action_dim]
                    std = std[:action_dim]

                # Denormalize: x = x_norm * std + mean
                action_denorm = action_array * (std + 1e-6) + mean
                action_array = action_denorm

                if not self._has_warned:
                    print(
                        f"[action_denormalize] Detected normalized actions (range=[{action_min:.3f}, {action_max:.3f}]), "
                        f"denormalizing using training stats. "
                        f"After denorm: range=[{action_array.min():.3f}, {action_array.max():.3f}]"
                    )
                    self._has_warned = True

        # Reshape back to original shape
        action_array = action_array.reshape(original_shape)

        # Convert back to tensor if input was tensor
        if isinstance(action, torch.Tensor):
            return torch.from_numpy(action_array).to(action.device).to(action.dtype)
        return action_array

    def transform_features(self, features: dict[str, Any]) -> dict[str, Any]:
        # No feature shape changes, just value scaling.
        return features


def _extract_state_vector(obs: dict[str, Any], state_order: list[str]) -> np.ndarray:
    state = obs.get(OBS_STATE)
    if isinstance(state, np.ndarray):
        arr = np.asarray(state, dtype=np.float32).reshape(-1)
        if arr.shape[0] == len(state_order):
            return arr.copy()

    return np.asarray([obs.get(k, 0.0) for k in state_order], dtype=np.float32)


def _hold_action_from_observation(obs: dict[str, Any], state_order: list[str]) -> np.ndarray:
    action = _extract_state_vector(obs, state_order)
    for stop_key in ("x.vel", "y.vel", "theta.vel"):
        if stop_key in state_order:
            action[state_order.index(stop_key)] = 0.0
    return action


def _action_array_to_dict(action_array: np.ndarray, action_names: list[str]) -> dict[str, float]:
    flat = np.asarray(action_array, dtype=np.float32).reshape(-1)
    if flat.shape[0] != len(action_names):
        raise ValueError(f"Action dim mismatch: expected {len(action_names)}, got {flat.shape[0]}")
    return {name: float(flat[i]) for i, name in enumerate(action_names)}


def _as_hwc_uint8(img: np.ndarray) -> np.ndarray:
    arr = np.asarray(img)
    if arr.ndim == 3 and arr.shape[0] in (1, 3, 4) and arr.shape[-1] not in (1, 3, 4):
        arr = np.transpose(arr, (1, 2, 0))
    if arr.ndim == 2:
        arr = np.repeat(arr[..., None], 3, axis=-1)
    if arr.ndim != 3 or arr.shape[-1] not in (1, 3, 4):
        raise ValueError(f"Expected HWC/CHW image with 1/3/4 channels, got shape={arr.shape}")
    if arr.shape[-1] == 4:
        arr = arr[..., :3]
    if np.issubdtype(arr.dtype, np.floating):
        max_value = float(np.nanmax(arr)) if arr.size else 1.0
        scale = 255.0 if max_value <= 1.5 else 1.0
        arr = np.clip(arr * scale, 0, 255).astype(np.uint8)
    elif arr.dtype != np.uint8:
        arr = np.clip(arr, 0, 255).astype(np.uint8)
    return np.ascontiguousarray(arr)


def _encode_image_payload(img: np.ndarray, mode: str) -> dict[str, Any]:
    arr = _as_hwc_uint8(img)
    if mode == "ndarray":
        return {
            "__ndarray__": True,
            "dtype": str(arr.dtype),
            "shape": list(arr.shape),
            "data": arr.tolist(),
        }
    if mode != "jpeg":
        raise ValueError(f"Unsupported image payload mode: {mode}")

    buffer = io.BytesIO()
    Image.fromarray(arr).save(buffer, format="JPEG", quality=90)
    return {
        "__image_jpeg__": True,
        "b64": base64.b64encode(buffer.getvalue()).decode("ascii"),
    }


class AsyncOpenPIHTTPPolicy:
    """Background HTTP action-chunk client for OpenPI /infer."""

    def __init__(
        self,
        server_url: str,
        task: str,
        state_order: list[str],
        action_dim: int,
        camera_mapping: dict[str, str],
        *,
        timeout_s: float = 10.0,
        refill_threshold: int = 2,
        image_payload: str = "jpeg",
        log_every_n: int = 30,
    ) -> None:
        self.server_url = server_url.rstrip("/")
        self.task = task
        self.state_order = list(state_order)
        self.action_dim = int(action_dim)
        self.camera_mapping = dict(camera_mapping)
        self.timeout_s = float(timeout_s)
        self.refill_threshold = int(refill_threshold)
        self.image_payload = image_payload
        self.log_every_n = int(log_every_n)

        self._actions: deque[np.ndarray] = deque()
        self._pending: Future[np.ndarray] | None = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="openpi-http")
        self._request_count = 0
        self._response_count = 0
        self._last_error: str | None = None

    def reset(self) -> None:
        self._actions.clear()
        if self._pending is not None and not self._pending.done():
            self._pending.cancel()
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="openpi-http")
        self._pending = None
        self._last_error = None

    def close(self) -> None:
        if self._pending is not None and not self._pending.done():
            self._pending.cancel()
        self._executor.shutdown(wait=False, cancel_futures=True)

    def step(self, obs: dict[str, Any]) -> tuple[np.ndarray, str]:
        self._collect_completed()
        if self._pending is None and len(self._actions) <= self.refill_threshold:
            self._submit(obs)

        if self._actions:
            return self._actions.popleft(), "remote"

        return _hold_action_from_observation(obs, self.state_order), "hold"

    def _snapshot_inputs(self, obs: dict[str, Any]) -> dict[str, Any]:
        images: dict[str, np.ndarray] = {}
        missing = []
        for lerobot_key, openpi_key in self.camera_mapping.items():
            img = obs.get(lerobot_key)
            if not isinstance(img, np.ndarray):
                missing.append(lerobot_key)
                continue
            images[openpi_key] = np.asarray(img).copy()
        if missing:
            raise ValueError(f"Missing camera frames for OpenPI HTTP inference: {missing}")
        if "cam_high" not in images:
            raise ValueError(f"OpenPI requires cam_high. Current mapping produced keys={sorted(images)}")

        return {
            "images": images,
            "state": _extract_state_vector(obs, self.state_order),
            "prompt": self.task,
        }

    def _submit(self, obs: dict[str, Any]) -> None:
        try:
            snapshot = self._snapshot_inputs(obs)
        except Exception as e:
            if self._last_error != str(e):
                print(f"[server] cannot submit inference request: {e}")
                self._last_error = str(e)
            return

        self._request_count += 1
        self._pending = self._executor.submit(self._request_actions, snapshot)

    def _collect_completed(self) -> None:
        if self._pending is None or not self._pending.done():
            return

        try:
            actions = self._pending.result()
            self._actions.clear()
            self._actions.extend(actions)
            self._response_count += 1
            self._last_error = None
            if self._response_count == 1 or self._response_count % self.log_every_n == 0:
                print(
                    f"[server] received action chunk #{self._response_count}: "
                    f"shape={actions.shape}, queued={len(self._actions)}"
                )
        except Exception as e:
            msg = str(e)
            if self._last_error != msg:
                print(f"[server] async inference failed: {msg}")
                self._last_error = msg
        finally:
            self._pending = None

    def _request_actions(self, snapshot: dict[str, Any]) -> np.ndarray:
        observation = {
            "images": {
                key: _encode_image_payload(img, self.image_payload)
                for key, img in snapshot["images"].items()
            },
            "state": np.asarray(snapshot["state"], dtype=np.float32).tolist(),
            "prompt": snapshot["prompt"],
        }
        response = requests.post(
            f"{self.server_url}/infer",
            json={"observation": observation, "task": self.task},
            timeout=self.timeout_s,
        )
        response.raise_for_status()
        data = response.json()

        actions_raw = data.get("actions")
        if actions_raw is None:
            actions_raw = [data.get("action")]
        actions = np.asarray(actions_raw, dtype=np.float32)
        if actions.ndim == 1:
            actions = actions[None, :]
        if actions.ndim != 2:
            raise ValueError(f"Expected action chunk shape [horizon, dim], got {actions.shape}")
        if actions.shape[-1] != self.action_dim:
            raise ValueError(
                f"Server action dim mismatch: expected {self.action_dim}, got {actions.shape[-1]}. "
                "Check that OpenPI is serving alohamini2pro_0604 and robot_dof=18."
            )
        return actions


def _run_remote_http_episode(
    *,
    robot: LeKiwiClient,
    events: dict,
    fps: int,
    policy: AsyncOpenPIHTTPPolicy,
    dataset: LeRobotDataset | None,
    dataset_features: dict[str, dict],
    state_order: list[str],
    action_dim: int,
    control_time_s: int,
    task: str,
    robot_action_processor: RobotProcessorPipeline,
    robot_observation_processor: RobotProcessorPipeline,
    debug_actions: bool,
    denormalize_step: ActionDenormalizeProcessorStep | None,
    display_data: bool,
) -> None:
    control_interval = 1.0 / fps
    frame_idx = 0
    timestamp = 0.0
    start_episode_t = time.perf_counter()
    policy.reset()

    while timestamp < control_time_s:
        loop_start = time.perf_counter()
        if events["exit_early"]:
            events["exit_early"] = False
            break
        if events["stop_recording"]:
            break

        obs_raw = robot.get_observation()
        obs_processed = robot_observation_processor(obs_raw)

        action_array, action_source = policy.step(obs_processed)
        action_tensor = torch.as_tensor(action_array, dtype=torch.float32).unsqueeze(0)
        if denormalize_step is not None and action_source == "remote":
            action_tensor = denormalize_step.action(action_tensor)
            action_array = action_tensor.squeeze(0).detach().cpu().numpy()

        action_dict = _action_array_to_dict(action_array, state_order)
        if debug_actions and (frame_idx == 0 or frame_idx % 30 == 0):
            _validate_action_values(
                action_tensor=action_tensor,
                action_dict=action_dict,
                dataset_features=dataset_features,
                expected_order=state_order,
                expected_action_dim=action_dim,
                frame_idx=frame_idx,
                log_every_n=30,
            )
            print(
                f"[action_debug] frame={frame_idx} source={action_source} "
                f"range=[{float(np.min(action_array)):.3f}, {float(np.max(action_array)):.3f}]"
            )

        robot_action_to_send = robot_action_processor((action_dict, obs_raw))
        sent_action = robot.send_action(robot_action_to_send)

        if dataset is not None:
            observation_frame = build_dataset_frame(dataset.features, obs_processed, prefix=OBS_STR)
            action_values = {name: float(sent_action.get(name, action_dict[name])) for name in state_order}
            action_frame = build_dataset_frame(dataset.features, action_values, prefix=ACTION)
            dataset.add_frame({**observation_frame, **action_frame, "task": task})

        if display_data:
            log_rerun_data(observation=obs_processed, action=action_dict)

        frame_idx += 1
        dt_s = time.perf_counter() - loop_start
        if dt_s > control_interval:
            print(
                f"[timing] loop slower than target: {1 / dt_s:.1f} Hz < {fps} Hz "
                f"(source={action_source})"
            )
        precise_sleep(max(control_interval - dt_s, 0.0))
        timestamp = time.perf_counter() - start_episode_t


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate AlohaMini2Pro with an OpenPI HTTP policy server.",
        epilog=(
            "Server:\n"
            "  cd /home/yigeoooo/project/openpi && uv run scripts/serve_policy_http.py \\\n"
            "    --port 8000 --default-prompt \"pickup the rubbish\" policy:checkpoint \\\n"
            "    --policy.config=alohamini2pro_0604 --policy.dir=<checkpoint_dir>\n\n"
            "Robot client:\n"
            "  python examples/alohamini/evaluate_bi_http.py --server_url http://<server-ip>:8000 \\\n"
            "    --task_description \"pickup the rubbish\" --remote_ip <robot-host-ip> --robot_dof 18\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--num_episodes", type=int, default=2, help="Number of episodes to record")
    parser.add_argument("--fps", type=int, default=30, help="Frames per second")
    parser.add_argument("--episode_time", type=int, default=360, help="Duration of each episode in seconds")
    parser.add_argument("--task_description", type=str, default="pickup the rubbish", help="Task prompt")
    parser.add_argument("--server_url", type=str, required=True, help="OpenPI HTTP policy server base URL")
    parser.add_argument("--http_timeout_s", type=float, default=10.0, help="HTTP /infer request timeout")
    parser.add_argument(
        "--async_refill_threshold",
        type=int,
        default=2,
        help="Submit a new async server request when queued actions are at or below this count.",
    )
    parser.add_argument(
        "--image_payload",
        type=str,
        default="jpeg",
        choices=("jpeg", "ndarray"),
        help="HTTP image payload encoding. jpeg is faster; ndarray preserves exact pixels but is much larger.",
    )
    parser.add_argument(
        "--bgr_to_rgb",
        action="store_true",
        default=False,
        help=(
            "Convert OpenCV-decoded BGR images to RGB before inference (default: False). "
            "NOTE: LeRobot datasets recorded with OpenCV (like pick_up_merged) save BGR images "
            "that are incorrectly treated as RGB. Training decodes these as BGR (treated as RGB). "
            "So inference should also send BGR (no conversion) to match training. "
            "Only enable this if your training dataset was recorded with explicit BGR→RGB conversion."
        ),
    )
    parser.add_argument(
        "--hf_dataset_id",
        type=str,
        default="",
        help=(
            "HuggingFace dataset repo id for saving evaluation data (e.g. 'username/eval_dataset'). "
            "If not provided, a local temporary dataset will be created (data saved locally, not pushed to Hub). "
            "Required for policy inference to get dataset features."
        ),
    )
    parser.add_argument("--remote_ip", type=str, default="127.0.0.1", help="LeKiwi host IP address")
    parser.add_argument("--robot_id", type=str, default="lekiwi", help="Robot ID")
    parser.add_argument(
        "--robot_model",
        type=str,
        default="alohamini2pro",
        choices=("alohamini1", "alohamini2", "alohamini2pro"),
        help="Must match the robot_model on the Pi host side.",
    )
    parser.add_argument("--cam_high", type=str, default="chest", help="LeRobot camera key mapped to OpenPI cam_high")
    parser.add_argument(
        "--cam_left_wrist",
        type=str,
        default="wrist_left",
        help="LeRobot camera key mapped to OpenPI cam_left_wrist",
    )
    parser.add_argument(
        "--cam_right_wrist",
        type=str,
        default="wrist_right",
        help="LeRobot camera key mapped to OpenPI cam_right_wrist",
    )
    parser.add_argument(
        "--debug_actions",
        action="store_true",
        default=False,
        help="Enable detailed action debugging: log action values, validate ranges, and check for anomalies.",
    )
    parser.add_argument(
        "--training_dataset_id",
        type=str,
        default="",
        help=(
            "Training dataset repo_id (e.g. 'username/pick_up_merged') for loading action statistics. "
            "Normally not needed for OpenPI HTTP because the server applies output transforms."
        ),
    )
    parser.add_argument(
        "--no_save",
        action="store_true",
        default=False,
        help=(
            "Run inference only without saving evaluation data to disk (no dataset created, no frames/videos written). "
            "Use when disk space is limited or only robot execution is needed."
        ),
    )
    parser.add_argument(
        "--robot_dof",
        type=str,
        default="18",
        choices=("auto", "16", "18"),
        help="Robot action/state DoF. AlohaMini2Pro should be 18.",
    )

    args = parser.parse_args()

    camera_mapping = {
        args.cam_high: "cam_high",
        args.cam_left_wrist: "cam_left_wrist",
        args.cam_right_wrist: "cam_right_wrist",
    }
    if len(camera_mapping) != 3:
        raise ValueError(f"Camera mapping keys must be distinct, got {camera_mapping}")

    # === Robot config ===
    robot_config = LeKiwiClientConfig(remote_ip=args.remote_ip, id=args.robot_id, robot_model=args.robot_model)
    robot = LeKiwiClient(robot_config)
    robot.connect()

    # === Dataset features ===
    action_features = hw_to_dataset_features(robot.action_features, ACTION)
    obs_features = hw_to_dataset_features(robot.observation_features, OBS_STR)
    dataset_features = {**action_features, **obs_features}

    # ---- Readiness checks: state/action order + camera resolution ----
    requested_dof = None if args.robot_dof == "auto" else int(args.robot_dof)
    state_order, action_dim = _validate_state_action_order(dataset_features, requested_dof=requested_dof)
    print(f"[info] Detected robot action/state DoF: {action_dim}")
    if args.robot_model == "alohamini2pro" and action_dim != 18:
        raise ValueError(f"AlohaMini2Pro must use 18-DoF, got action_dim={action_dim}")

    dataset = None
    if not args.no_save:
        # Create dataset: use provided repo_id or a local temporary path
        if args.hf_dataset_id:
            dataset_repo_id = args.hf_dataset_id
            dataset_root = None  # Use default HF_LEROBOT_HOME location
        else:
            # Use a local temporary dataset path (not pushed to Hub)
            from datetime import datetime
            from pathlib import Path
            dataset_repo_id = f"local_eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            dataset_root = Path.cwd() / "eval_data" / dataset_repo_id
            print(f"[info] No --hf_dataset_id provided, using local temporary dataset: {dataset_repo_id}")
            print(f"[info] Evaluation data will be saved locally at: {dataset_root}")
            print(f"[info] Data will NOT be pushed to HuggingFace Hub.")

        dataset = LeRobotDataset.create(
            repo_id=dataset_repo_id,
            root=dataset_root,
            fps=args.fps,
            features=dataset_features,
            robot_type=robot.name,
            use_videos=True,
            image_writer_threads=4,
        )
    else:
        print(f"[info] --no_save: inference only, no evaluation data will be written to disk.")

    # Grab a sample observation for camera logging (and optional color conversion sanity).
    obs0 = robot.get_observation()
    if args.bgr_to_rgb:
        obs0 = _maybe_bgr_to_rgb(obs0, tuple(camera_mapping))
    _print_camera_info(robot, dataset_features, obs0, camera_mapping)
    for camera_key in camera_mapping:
        if not isinstance(obs0.get(camera_key), np.ndarray):
            raise ValueError(
                f"Remote HTTP 推理要求提供 {camera_key!r} 相机帧，但当前 obs0[{camera_key!r}] "
                f"缺失或不是 ndarray。当前可用 keys={sorted(obs0.keys())}"
            )

    _maybe_print_server_metadata(args.server_url)

    training_stats = None
    if args.training_dataset_id:
        try:
            print(f"[info] Loading training dataset stats from: {args.training_dataset_id}")
            training_dataset = LeRobotDataset(args.training_dataset_id)
            training_stats = training_dataset.meta.stats
            if "action" in training_stats:
                action_stats = training_stats["action"]
                mean = action_stats.get("mean")
                std = action_stats.get("std")
                if isinstance(mean, torch.Tensor):
                    mean = mean.numpy()
                if isinstance(std, torch.Tensor):
                    std = std.numpy()
                print(
                    f"[info] Training action stats: "
                    f"mean range=[{float(np.min(mean)):.3f}, {float(np.max(mean)):.3f}], "
                    f"std range=[{float(np.min(std)):.3f}, {float(np.max(std)):.3f}]"
                )
            else:
                print("[warning] Training dataset has no action stats, skipping denormalization setup.")
                training_stats = None
        except Exception as e:
            print(f"[warning] Failed to load training dataset stats: {e}")
            training_stats = None

    teleop_action_processor, robot_action_processor, robot_observation_processor = make_default_processors()
    _ = teleop_action_processor
    if args.bgr_to_rgb:
        bgr_to_rgb_step = BGRToRGBProcessorStep(camera_keys=tuple(camera_mapping))
        robot_observation_processor = RobotProcessorPipeline[dict[str, Any], dict[str, Any]](
            steps=[*robot_observation_processor.steps, bgr_to_rgb_step],
            to_transition=observation_to_transition,
            to_output=transition_to_observation,
        )

    denormalize_step = ActionDenormalizeProcessorStep(training_stats=training_stats) if training_stats else None
    if denormalize_step is not None:
        print("[warning] Action denormalization enabled from --training_dataset_id. OpenPI usually already denormalizes.")

    policy = AsyncOpenPIHTTPPolicy(
        server_url=args.server_url,
        task=args.task_description,
        state_order=state_order,
        action_dim=action_dim,
        camera_mapping=camera_mapping,
        timeout_s=args.http_timeout_s,
        refill_threshold=args.async_refill_threshold,
        image_payload=args.image_payload,
    )

    listener, events = init_keyboard_listener()
    init_rerun(session_name="lekiwi_evaluate")

    if not robot.is_connected:
        raise ValueError("Robot is not connected!")

    # Print diagnostic summary
    print("\n" + "=" * 80)
    print("DIAGNOSTIC SUMMARY")
    print("=" * 80)
    print("Policy mode: remote_http_async")
    print(f"Server URL: {args.server_url}")
    print(f"Robot model: {args.robot_model}")
    print(f"Camera mapping: {camera_mapping}")
    print(f"Action denormalization: {'ENABLED' if denormalize_step is not None else 'DISABLED'}")
    print(f"Action debugging: {'ENABLED' if args.debug_actions else 'DISABLED'}")
    print(f"BGR→RGB conversion: {'ENABLED' if args.bgr_to_rgb else 'DISABLED'}")
    print(f"Image payload: {args.image_payload}")
    print(f"Async refill threshold: {args.async_refill_threshold}")
    print("=" * 80 + "\n")

    print("Starting evaluate loop...")
    recorded_episodes = 0

    try:
        while recorded_episodes < args.num_episodes and not events["stop_recording"]:
            log_say(f"Running OpenPI HTTP inference, eval episode {recorded_episodes + 1} of {args.num_episodes}")

            _run_remote_http_episode(
                robot=robot,
                events=events,
                fps=args.fps,
                policy=policy,
                dataset=dataset,
                dataset_features=dataset_features,
                state_order=state_order,
                action_dim=action_dim,
                control_time_s=args.episode_time,
                task=args.task_description,
                robot_action_processor=robot_action_processor,
                robot_observation_processor=robot_observation_processor,
                debug_actions=args.debug_actions,
                denormalize_step=denormalize_step,
                display_data=True,
            )

            if not events["stop_recording"] and dataset is not None:
                dataset.save_episode()
                recorded_episodes += 1
            elif not events["stop_recording"] and args.no_save:
                recorded_episodes += 1
    finally:
        log_say("Stop recording")
        policy.close()
        if robot.is_connected:
            robot.disconnect()
        listener.stop()
        if dataset is not None:
            dataset.finalize()
            if args.hf_dataset_id:
                dataset.push_to_hub()
                print(f"[info] Evaluation data pushed to HuggingFace Hub: {dataset.repo_id}")
            else:
                print(f"[info] Evaluation data saved locally at: {dataset.root}")
                print("[info] To push to Hub later, use: dataset.push_to_hub()")
        else:
            print("[info] --no_save: no evaluation data was saved.")


if __name__ == "__main__":
    main()
