from __future__ import annotations

import asyncio
import base64
import json
import threading
from types import SimpleNamespace

import av
import cv2
import numpy as np
import pyarrow.parquet as pq
import pytest
import websockets

from examples.alohamini import record_vr
from lerobot.utils.feature_utils import hw_to_dataset_features


class RecorderSocket:
    def __init__(self, features):
        self.incoming = asyncio.Queue()
        self.outgoing = asyncio.Queue()
        self.sent = []
        self.feed({"type": "record_metadata", "protocol": 2, "fps": 25, "dataset_features": features})

    def feed(self, message):
        self.incoming.put_nowait(None if message is None else json.dumps(message))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def send(self, raw):
        message = json.loads(raw)
        self.sent.append(message)
        self.outgoing.put_nowait(message)

    async def recv(self):
        return await self.incoming.get()

    def __aiter__(self):
        return self

    async def __anext__(self):
        raw = await self.recv()
        if raw is None:
            raise StopAsyncIteration
        return raw

    async def status(self, phase):
        async def receive():
            while True:
                message = await self.outgoing.get()
                if message.get("recorder_phase") == phase:
                    return message

        return await asyncio.wait_for(receive(), timeout=20)


def features(cameras=()):
    joints = {"joint.pos": float, "second_joint.pos": float}
    return {
        **hw_to_dataset_features(joints, "action"),
        **hw_to_dataset_features({**joints, **dict.fromkeys(cameras, (32, 32, 3))}, "observation"),
    }


def sample(episode=1, sequence=0, frames=None):
    return {
        "type": "sample",
        "episode": episode,
        "sequence": sequence,
        "state": {"joint.pos": 0.0, "second_joint.pos": 0.5},
        "action": {"joint.pos": 1.0, "second_joint.pos": 2.0},
        "frames": frames or {},
    }


def args(root):
    return SimpleNamespace(
        dataset_root=str(root),
        repo_id="vr_test",
        gateway_url="ws://test",
        fps=25,
        task="test",
        max_message_mb=32,
        image_writer_threads=1,
    )


@pytest.mark.parametrize("failure", [None, "save", "finalize", "verify"])
def test_pc_confirms_only_after_save_and_finalize_and_reports_failures(monkeypatch, tmp_path, failure):
    release = threading.Event()

    class Dataset:
        def __init__(self):
            self.writer = SimpleNamespace(episode_buffer={"size": 0})
            self.features = features()
            self.num_frames = 0
            self.num_episodes = 0
            self.finalized = False
            self.save_calls = 0
            self.resume_calls = 0

        def add_frame(self, frame):
            assert not self.finalized
            self.writer.episode_buffer["size"] += 1

        def has_pending_frames(self):
            return bool(self.writer.episode_buffer.get("size", 0))

        def save_episode(self, *args):
            self.save_calls += 1
            count = self.writer.episode_buffer.pop("size")
            assert release.wait(5), "test did not release save"
            if failure == "save":
                raise OSError("disk full")
            self.num_frames += count
            self.num_episodes += 1
            self.writer.episode_buffer = {"size": 0}

        def finalize(self):
            if failure == "finalize":
                raise OSError("parquet footer failed")
            self.finalized = True

    dataset = Dataset()

    def resume(**kwargs):
        dataset.resume_calls += 1
        dataset.finalized = False
        return dataset

    monkeypatch.setattr(
        record_vr, "LeRobotDataset", SimpleNamespace(create=lambda **k: dataset, resume=resume)
    )

    def verified_counts(root):
        if failure == "verify" and dataset.num_episodes:
            raise OSError("dataset counts inconsistent")
        return dataset.num_frames, dataset.num_episodes

    monkeypatch.setattr(record_vr, "_saved_dataset_counts", verified_counts)

    async def scenario():
        socket = RecorderSocket(features())
        monkeypatch.setattr(websockets, "connect", lambda *a, **k: socket)
        task = asyncio.create_task(record_vr._run(args(tmp_path / "dataset")))
        try:
            await socket.status("ready")
            socket.feed({"type": "record_state", "recording": True, "phase": "recording", "episode": 1})
            await socket.status("recording")
            socket.feed(sample())
            socket.feed(
                {"type": "record_state", "recording": False, "phase": "saving", "episode": 1, "frames": 1}
            )
            saving = await socket.status("saving")
            assert saving["dataset_frames"] == 0
            # The saver is blocked in a worker; the one-second heartbeat still runs.
            await socket.status("saving")
            assert not any(message.get("recorder_phase") == "saved" for message in socket.sent)
            release.set()
            if failure:
                error = await socket.status("error")
                assert error["episode"] == 1
                assert (
                    error["error"]
                    == {
                        "save": "disk full",
                        "finalize": "parquet footer failed",
                        "verify": "dataset counts inconsistent",
                    }[failure]
                )
                assert error["dataset_verified"] is False
                with pytest.raises(OSError):
                    await task
                assert dataset.save_calls == 1  # Never retry a partially mutated buffer.
                assert not any(message.get("recorder_phase") == "saved" for message in socket.sent)
            else:
                saved = await socket.status("saved")
                assert dataset.finalized
                assert saved["saved_episode"] == 1
                assert saved["saved_episode_frames"] == 1
                assert saved["dataset_frames"] == saved["dataset_episodes"] == 1
                # A duplicate stop cannot save twice; the next start must reopen the writer.
                socket.feed(
                    {"type": "record_state", "recording": False, "phase": "saving", "episode": 1, "frames": 1}
                )
                socket.feed({"type": "record_state", "recording": True, "phase": "recording", "episode": 2})
                await socket.status("recording")
                socket.feed(sample(episode=2))
                socket.feed(
                    {"type": "record_state", "recording": False, "phase": "saving", "episode": 2, "frames": 1}
                )
                saved = await socket.status("saved")
                assert saved["saved_episode"] == 2
                assert saved["dataset_frames"] == 2
                assert dataset.save_calls == 2
                assert dataset.resume_calls == 1
                socket.feed(None)
                await task
        finally:
            release.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


def _make_saved_dataset(root):
    dataset = record_vr.LeRobotDataset.create("vr_test", root=root, fps=25, features=features())
    for _ in range(2):
        dataset.add_frame(record_vr._build_frame(dataset, sample(), "test"))
        dataset.save_episode()
    dataset.finalize()


@pytest.mark.parametrize("damage", ["info", "data", "episode_index"])
def test_saved_dataset_counts_detects_inconsistent_disk_files(tmp_path, damage):
    root = tmp_path / "dataset"
    _make_saved_dataset(root)
    assert record_vr._saved_dataset_counts(root) == (2, 2)
    if damage == "info":
        path = root / "meta" / "info.json"
        info = json.loads(path.read_text())
        info["total_episodes"] = 9
        path.write_text(json.dumps(info))
    elif damage == "data":
        next((root / "data").rglob("*.parquet")).unlink()
    else:
        next((root / "meta" / "episodes").rglob("*.parquet")).unlink()
    with pytest.raises(ValueError, match="数据集校验失败"):
        record_vr._saved_dataset_counts(root)


def test_pc_restart_rechecks_counts_and_appends_to_actual_episode(monkeypatch, tmp_path):
    root = tmp_path / "dataset"
    _make_saved_dataset(root)

    async def scenario():
        for restart in range(2):
            socket = RecorderSocket(features())
            monkeypatch.setattr(websockets, "connect", lambda *a, socket=socket, **k: socket)
            task = asyncio.create_task(record_vr._run(args(root)))
            try:
                ready = await socket.status("ready")
                assert ready["dataset_verified"] is True
                assert ready["dataset_episodes"] == ready["dataset_frames"] == 2 + restart
                assert ready["saved_dataset_episode"] is None
                if restart == 0:
                    socket.feed(
                        {"type": "record_state", "recording": True, "phase": "recording", "episode": 1}
                    )
                    recording = await socket.status("recording")
                    assert recording["dataset_episode_index"] == 2
                    socket.feed(sample())
                    socket.feed(
                        {
                            "type": "record_state",
                            "recording": False,
                            "phase": "saving",
                            "episode": 1,
                            "frames": 1,
                        }
                    )
                    saved = await socket.status("saved")
                    assert saved["saved_dataset_episode"] == 2
                    assert saved["dataset_verified"] is True
                    assert saved["dataset_episodes"] == 3
                socket.feed(None)
                await task
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


def test_pc_startup_rejects_missing_data_instead_of_reporting_cached_totals(monkeypatch, tmp_path):
    root = tmp_path / "dataset"
    _make_saved_dataset(root)
    next((root / "data").rglob("*.parquet")).unlink()

    async def scenario():
        socket = RecorderSocket(features())
        monkeypatch.setattr(websockets, "connect", lambda *a, **k: socket)
        task = asyncio.create_task(record_vr._run(args(root)))
        try:
            error = await socket.status("error")
            assert error["dataset_verified"] is False
            assert "校验失败" in error["error"]
            with pytest.raises(ValueError, match="校验失败"):
                await task
            assert not any(message.get("recorder_phase") == "ready" for message in socket.sent)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


def test_pc_saved_ack_means_three_videos_and_parquet_are_readable(monkeypatch, tmp_path):
    cameras = ("forward", "wrist_left", "wrist_right")
    ok, jpeg = cv2.imencode(".jpg", np.full((32, 32, 3), 100, np.uint8))
    assert ok
    frames = {name: {"jpeg_b64": base64.b64encode(jpeg).decode()} for name in cameras}
    root = tmp_path / "dataset"

    async def scenario():
        socket = RecorderSocket(features(cameras))
        monkeypatch.setattr(websockets, "connect", lambda *a, **k: socket)
        task = asyncio.create_task(record_vr._run(args(root)))
        try:
            await socket.status("ready")
            socket.feed({"type": "record_state", "recording": True, "phase": "recording", "episode": 1})
            await socket.status("recording")
            for sequence in range(2):
                socket.feed(sample(sequence=sequence, frames=frames))
            socket.feed(
                {"type": "record_state", "recording": False, "phase": "saving", "episode": 1, "frames": 2}
            )
            saved = await socket.status("saved")
            assert saved["saved_episode_frames"] == 2
            # Read before disconnect/final cleanup: success must already mean usable files.
            parquet = list((root / "data").rglob("*.parquet"))
            assert sum(pq.read_table(path).num_rows for path in parquet) == 2
            episodes = list((root / "meta" / "episodes").rglob("*.parquet"))
            assert sum(pq.read_table(path).num_rows for path in episodes) == 1
            videos = list((root / "videos").rglob("*.mp4"))
            assert len(videos) == 3
            for path in videos:
                with av.open(str(path)) as video:
                    assert len(list(video.decode(video=0))) == 2
            reader = record_vr.LeRobotDataset("vr_test", root=root, episodes=[0])
            assert reader.num_frames == 2
            assert reader[0]["action"].tolist() == [1.0, 2.0]
            for name in cameras:
                assert reader[0][f"observation.images.{name}"].shape == (3, 32, 32)
            # Resume the finalized dataset and ensure both episodes remain readable.
            socket.feed({"type": "record_state", "recording": True, "phase": "recording", "episode": 2})
            await socket.status("recording")
            socket.feed(sample(episode=2, frames=frames))
            socket.feed(
                {"type": "record_state", "recording": False, "phase": "saving", "episode": 2, "frames": 1}
            )
            saved = await socket.status("saved")
            assert saved["dataset_episodes"] == 2
            assert saved["dataset_frames"] == 3
            for episode, count in ((0, 2), (1, 1)):
                reader = record_vr.LeRobotDataset("vr_test", root=root, episodes=[episode])
                assert reader.num_frames == count
                assert reader[0]["action"].tolist() == [1.0, 2.0]
                for name in cameras:
                    assert reader[0][f"observation.images.{name}"].shape == (3, 32, 32)
            socket.feed(None)
            await task
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())
