#!/usr/bin/env python3
"""Record VR teleoperation episodes from a Pi gateway into a local dataset.

The Quest and robot stay on the Pi.  This process is the only component that owns
the local :class:`LeRobotDataset`: it receives canonical state/action samples and
JPEG camera frames from ``/record``, decodes them to RGB, and writes standard
LeRobot videos/parquet files on the PC.

Start this process before entering VR.  The left Quest thumbstick click then toggles
one episode at a time; the gateway refuses to start an episode until this connection
has completed its metadata/status handshake.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from lerobot.datasets import LeRobotDataset
from lerobot.utils.constants import ACTION, HF_LEROBOT_HOME, OBS_STR
from lerobot.utils.feature_utils import build_dataset_frame

LOGGER = logging.getLogger("lerobot.record_vr")
PROTOCOL = 2


def _dataset_path(args: argparse.Namespace) -> Path:
    return Path(args.dataset_root).expanduser() if args.dataset_root else HF_LEROBOT_HOME / args.repo_id


def _existing_dataset(path: Path) -> bool:
    return (path / "meta" / "info.json").is_file()


def _pending_frames(dataset: LeRobotDataset) -> int:
    writer = dataset.writer
    buffer = writer.episode_buffer if writer is not None else None
    return 0 if buffer is None else int(buffer["size"])


def _saved_dataset_counts(root: Path) -> tuple[int, int]:
    """Count committed episodes/frames from local parquet and cross-check metadata.

    This is called before opening a writer and after finalizing one, never while
    parquet files are being written. Do not trust a cached dataset object's totals
    or repair inconsistent files silently.
    """
    import pyarrow.parquet as pq

    info = json.loads((root / "meta" / "info.json").read_text())
    video_keys = [key for key, feature in info["features"].items() if feature["dtype"] == "video"]
    lengths: dict[int, int] = {}
    columns = ["episode_index", "length"]
    for key in video_keys:
        columns.extend((f"videos/{key}/chunk_index", f"videos/{key}/file_index"))
    for path in sorted((root / "meta" / "episodes").rglob("*.parquet")):
        for row in pq.ParquetFile(path).read(columns=columns).to_pylist():
            episode = int(row["episode_index"])
            if episode in lengths or int(row["length"]) <= 0:
                raise ValueError(f"数据集校验失败：episode {episode} 重复或为空")
            lengths[episode] = int(row["length"])
            for key in video_keys:
                video = root / info["video_path"].format(
                    video_key=key,
                    chunk_index=int(row[f"videos/{key}/chunk_index"]),
                    file_index=int(row[f"videos/{key}/file_index"]),
                )
                if not video.is_file() or video.stat().st_size == 0:
                    raise ValueError(f"数据集校验失败：episode {episode} 缺少视频 {video}")

    actual: Counter[int] = Counter()
    for path in sorted((root / "data").rglob("*.parquet")):
        for batch in pq.ParquetFile(path).iter_batches(columns=["episode_index"]):
            indices, counts = np.unique(batch.column(0).to_numpy(), return_counts=True)
            actual.update({int(index): int(count) for index, count in zip(indices, counts, strict=True)})
    if dict(actual) != lengths:
        raise ValueError("数据集校验失败：episode 索引与实际数据帧数不一致（可能缺少数据文件）")
    episodes, frames = len(lengths), sum(actual.values())
    if set(lengths) != set(range(episodes)):
        raise ValueError("数据集校验失败：episode 编号不连续")
    if (episodes, frames) != (int(info["total_episodes"]), int(info["total_frames"])):
        raise ValueError(
            f"数据集校验失败：磁盘实际 {episodes} 条 / {frames} 帧，"
            f"info.json 记录 {info['total_episodes']} 条 / {info['total_frames']} 帧"
        )
    return frames, episodes


def _normalise_features(features: dict[str, dict]) -> dict[str, dict]:
    """Restore tuple shapes after JSON transport while preserving the schema."""
    result = {}
    for key, feature in features.items():
        value = dict(feature)
        if isinstance(value.get("shape"), list):
            value["shape"] = tuple(value["shape"])
        result[key] = value
    return result


def _decode_jpeg(encoded: str, camera_name: str) -> np.ndarray:
    try:
        raw = base64.b64decode(encoded, validate=True)
        image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    except Exception as exc:  # pragma: no cover - codec errors depend on camera data
        raise RuntimeError(f"invalid JPEG for camera {camera_name}: {exc}") from exc
    if image is None:
        raise RuntimeError(f"failed to decode JPEG for camera {camera_name}")
    # Gateway JPEGs are encoded from RGB after converting to BGR for OpenCV.
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


def _build_frame(dataset: LeRobotDataset, sample: dict[str, Any], task: str) -> dict[str, Any]:
    state = sample.get("state")
    action = sample.get("action")
    frames = sample.get("frames")
    if not isinstance(state, dict) or not isinstance(action, dict) or not isinstance(frames, dict):
        raise ValueError("sample must contain state, action and frames dictionaries")
    camera_names = [
        key.removeprefix(f"{OBS_STR}.images.")
        for key, feature in dataset.features.items()
        if key.startswith(f"{OBS_STR}.images.") and feature.get("dtype") in {"video", "image"}
    ]
    decoded = {name: _decode_jpeg(frames[name]["jpeg_b64"], name) for name in camera_names if name in frames}
    missing = [name for name in camera_names if name not in decoded]
    if missing:
        raise ValueError(f"sample is missing cameras: {', '.join(missing)}")
    values = {**state, **decoded}
    observation_frame = build_dataset_frame(dataset.features, values, prefix=OBS_STR)
    action_frame = build_dataset_frame(dataset.features, action, prefix=ACTION)
    expected = {
        key
        for key, feature in dataset.features.items()
        if key.startswith((f"{OBS_STR}.", f"{ACTION}."))
        and feature.get("dtype") in {"float32", "video", "image"}
    }
    actual = set(observation_frame) | set(action_frame)
    missing_features = expected - actual
    if missing_features:
        raise ValueError(f"sample is missing dataset features: {', '.join(sorted(missing_features))}")
    return {**observation_frame, **action_frame, "task": task}


async def _send_json(websocket: Any, payload: dict[str, Any], lock: asyncio.Lock) -> None:
    async with lock:
        await websocket.send(json.dumps(payload, separators=(",", ":")))


async def _dataset_io(function, *args, **kwargs):
    """Keep heartbeats running, and finish writer work before cancellation cleanup."""
    work = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(work)
    except asyncio.CancelledError:
        await work
        raise


async def _run(args: argparse.Namespace) -> None:
    try:
        import websockets
        from websockets.exceptions import ConnectionClosed
    except ImportError as exc:  # pragma: no cover - optional PC transport dependency
        raise RuntimeError(
            "Install the VR recorder dependencies: uv sync --extra vr --extra dataset"
        ) from exc

    root = _dataset_path(args)
    root.parent.mkdir(parents=True, exist_ok=True)
    if root.exists() and not _existing_dataset(root):
        raise RuntimeError(
            f"dataset root exists without LeRobot metadata: {root}; "
            "choose a new path or remove the empty directory"
        )
    uri = args.gateway_url.rstrip("/") + "/record"
    send_lock = asyncio.Lock()
    dataset: LeRobotDataset | None = None
    active_episode: int | None = None
    recorder_phase = "checking"
    dataset_verified = False
    dataset_episode_index: int | None = None
    received_frames = 0
    saved_episode: int | None = None
    saved_episode_frames = 0
    saved_dataset_episode: int | None = None
    dataset_closed = False
    last_status_error: str | None = None
    known_frames = 0
    known_episodes = 0

    async with websockets.connect(
        uri, max_size=args.max_message_mb * 1024 * 1024, ping_interval=10
    ) as websocket:
        await _send_json(
            websocket,
            {
                "type": "hello",
                "protocol": PROTOCOL,
                "dataset_repo_id": args.repo_id,
                "dataset_root": str(root.resolve()),
                "dataset_exists": _existing_dataset(root),
                "dataset_frames": 0,
                "dataset_episodes": 0,
            },
            send_lock,
        )
        metadata = json.loads(await websocket.recv())
        if metadata.get("type") != "record_metadata":
            raise RuntimeError(f"gateway did not return metadata: {metadata}")
        if int(metadata.get("protocol", -1)) != PROTOCOL:
            raise RuntimeError(f"unsupported recorder protocol: {metadata.get('protocol')}")
        fps = int(metadata["fps"])
        if fps != args.fps:
            raise RuntimeError(f"gateway recording fps is {fps}, but PC requested {args.fps}")

        async def send_status() -> None:
            await _send_json(
                websocket,
                {
                    "type": "recorder_status",
                    "protocol": PROTOCOL,
                    "dataset_repo_id": args.repo_id,
                    "dataset_root": str(root.resolve()),
                    "dataset_exists": _existing_dataset(root),
                    "dataset_frames": known_frames,
                    "dataset_episodes": known_episodes,
                    "dataset_verified": dataset_verified,
                    "dataset_episode_index": dataset_episode_index,
                    "recorder_phase": recorder_phase,
                    "episode": active_episode,
                    "episode_frames": received_frames,
                    "saved_episode": saved_episode,
                    "saved_episode_frames": saved_episode_frames,
                    "saved_dataset_episode": saved_dataset_episode,
                    "error": last_status_error,
                },
                send_lock,
            )

        async def save_pending_episode() -> None:
            nonlocal known_frames, known_episodes, recorder_phase, saved_episode, saved_episode_frames
            nonlocal dataset_closed, dataset_verified, saved_dataset_episode
            assert dataset is not None
            recorder_phase = "saving"
            dataset_verified = False
            # A broken connection must not prevent local data from being saved.
            with contextlib.suppress(ConnectionClosed):
                await send_status()
            count = _pending_frames(dataset)
            if count == 0:
                raise RuntimeError("本段未收到有效样本，没有生成 episode")
            await _dataset_io(dataset.save_episode, None, True)
            # save_episode alone leaves parquet writers/metadata buffers open.
            # Confirm success only once videos AND readable parquet are on disk.
            await _dataset_io(dataset.finalize)
            dataset_closed = True
            frames, episodes = await _dataset_io(_saved_dataset_counts, root)
            if (frames, episodes) != (known_frames + count, known_episodes + 1):
                raise RuntimeError("数据集校验失败：本次保存后的条数或帧数增量不正确")
            known_frames, known_episodes = frames, episodes
            dataset_verified = True
            saved_episode = active_episode
            saved_episode_frames = count
            saved_dataset_episode = known_episodes - 1
            recorder_phase = "saved"
            LOGGER.info(
                "episode %s 保存成功: %d 帧，数据集共 %d 集 / %d 帧，%s",
                active_episode,
                count,
                known_episodes,
                known_frames,
                root,
            )
            with contextlib.suppress(ConnectionClosed):
                await send_status()

        async def heartbeat() -> None:
            while True:
                await asyncio.sleep(1.0)
                await send_status()

        async def receive_samples() -> None:
            nonlocal dataset, active_episode, recorder_phase, received_frames, dataset_closed
            nonlocal known_frames, known_episodes, dataset_episode_index, dataset_verified
            assert dataset is not None
            async for raw in websocket:
                message = json.loads(raw)
                kind = message.get("type")
                if kind == "record_state":
                    if bool(message.get("recording")):
                        episode = int(message["episode"])
                        if active_episode == episode:
                            continue
                        active_episode = episode
                        if dataset_closed:
                            dataset_verified = False
                            known_frames, known_episodes = await _dataset_io(_saved_dataset_counts, root)
                            dataset = await _dataset_io(
                                LeRobotDataset.resume,
                                repo_id=args.repo_id,
                                root=root,
                                image_writer_threads=args.image_writer_threads,
                            )
                            dataset_closed = False
                        dataset_verified = True
                        dataset_episode_index = known_episodes
                        received_frames = 0
                        recorder_phase = "recording"
                        await send_status()
                        LOGGER.info("recording episode %d", active_episode)
                    elif message.get("phase") == "saving":
                        episode = int(message["episode"])
                        if active_episode == episode and recorder_phase in {"saved", "error"}:
                            continue
                        active_episode = episode
                        expected = int(message.get("frames", received_frames))
                        if received_frames != expected:
                            raise RuntimeError(
                                f"样本数量不一致: 网关 {expected} 帧，PC 收到 {received_frames} 帧"
                            )
                        await save_pending_episode()
                elif kind == "sample":
                    episode = int(message.get("episode", -1))
                    if active_episode != episode or recorder_phase != "recording":
                        # A stop/start transition can race one in-flight sample. Drop
                        # it instead of mixing episode boundaries.
                        continue
                    if int(message.get("sequence", received_frames)) != received_frames:
                        raise RuntimeError("录制样本序号不连续")
                    await _dataset_io(
                        lambda dataset=dataset, message=message: dataset.add_frame(
                            _build_frame(dataset, message, args.task)
                        )
                    )
                    received_frames += 1
                elif kind == "error":
                    raise RuntimeError(message.get("error", "gateway recorder error"))

        heartbeat_task = asyncio.create_task(heartbeat())
        receive_task = None
        try:
            await send_status()
            if _existing_dataset(root):
                # Check files before opening a writer, so inconsistent metadata
                # cannot make resume overwrite existing episodes.
                known_frames, known_episodes = await _dataset_io(_saved_dataset_counts, root)
                dataset = await _dataset_io(
                    LeRobotDataset.resume,
                    repo_id=args.repo_id,
                    root=root,
                    image_writer_threads=args.image_writer_threads,
                )
                if dataset.fps != fps:
                    raise RuntimeError(f"existing dataset fps is {dataset.fps}, gateway is {fps}")
            else:
                dataset = await _dataset_io(
                    LeRobotDataset.create,
                    repo_id=args.repo_id,
                    root=root,
                    fps=fps,
                    features=_normalise_features(metadata["dataset_features"]),
                    robot_type=metadata.get("robot_type"),
                    use_videos=True,
                    image_writer_threads=args.image_writer_threads,
                )
                known_frames, known_episodes = await _dataset_io(_saved_dataset_counts, root)
            dataset_verified = True
            recorder_phase = "ready"
            await send_status()
            LOGGER.info("PC 录制端已核对磁盘: %s (%d 条 / %d 帧)", root, known_episodes, known_frames)
            receive_task = asyncio.create_task(receive_samples())
            done, _ = await asyncio.wait((heartbeat_task, receive_task), return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except ConnectionClosed:
            pass  # The cleanup below saves pending frames even if the gateway went away.
        except Exception as exc:
            last_status_error = str(exc)
            recorder_phase = "error"
            dataset_verified = False
            with contextlib.suppress(ConnectionClosed):
                await send_status()
            raise
        finally:
            heartbeat_task.cancel()
            tasks = [heartbeat_task]
            if receive_task is not None:
                receive_task.cancel()
                tasks.append(receive_task)
            await asyncio.gather(*tasks, return_exceptions=True)
            if dataset is not None:
                try:
                    if recorder_phase == "recording" and dataset.has_pending_frames():
                        await save_pending_episode()
                finally:
                    if not dataset_closed:
                        await _dataset_io(dataset.finalize)
                LOGGER.info("local VR dataset finalized at %s (%d frames)", root, dataset.num_frames)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Record Quest VR teleoperation into a local LeRobot dataset")
    parser.add_argument("--gateway-url", default="ws://127.0.0.1:8000", help="Pi gateway WebSocket base URL")
    parser.add_argument("--dataset.repo_id", "--dataset", dest="repo_id", required=True)
    parser.add_argument("--dataset.root", "--root", dest="dataset_root", default=None)
    parser.add_argument("--dataset.single_task", "--task", dest="task", required=True)
    parser.add_argument("--dataset.fps", "--fps", dest="fps", type=int, default=25)
    parser.add_argument("--image-writer-threads", type=int, default=4)
    parser.add_argument("--max-message-mb", type=int, default=32)
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level), format="%(asctime)s %(levelname)s %(message)s"
    )
    try:
        asyncio.run(_run(args))
    except KeyboardInterrupt:
        LOGGER.info("VR recorder stopped")


if __name__ == "__main__":
    main()
