#!/usr/bin/env python

# Copyright 2026 The HuggingFace Inc. team. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("datasets", reason="datasets is required (install lerobot[dataset])")

from lerobot.scripts.lerobot_curate_dataset import CuratorState


class FakeMeta:
    def __init__(self, episodes: list[dict], features: dict | None = None) -> None:
        self.episodes = episodes
        self.features = features or {}
        self.total_episodes = len(episodes)
        self.total_frames = sum(int(ep["length"]) for ep in episodes)
        self.fps = 30
        self.camera_keys = ["observation.images.front"]
        self.video_keys = ["observation.video.front"]

    def ensure_readable(self) -> None:
        pass


class FakeHfDataset:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.selected_indices = None

    def select(self, indices):
        self.selected_indices = list(indices)
        return [self.rows[index] for index in self.selected_indices]


class FakeDataset:
    def __init__(self, meta: FakeMeta, hf_dataset: FakeHfDataset | None = None) -> None:
        self.meta = meta
        self.hf_dataset = hf_dataset
        self.repo_id = "test/repo"
        self.root = Path("/tmp/fake-lerobot-dataset")


def make_state(episode_lengths: list[int] | None = None) -> CuratorState:
    episode_lengths = episode_lengths or [10, 12, 14]
    episodes = [
        {
            "length": length,
            "dataset_from_index": sum(episode_lengths[:episode_index]),
            "tasks": [],
        }
        for episode_index, length in enumerate(episode_lengths)
    ]
    return CuratorState(FakeDataset(FakeMeta(episodes)), repo_id="test/repo", video_backend=None)


def capture_rewrite_call(monkeypatch, state: CuratorState) -> dict:
    captured = {}

    def fake_rewrite_source(**kwargs):
        captured.update(kwargs)
        return {"total_episodes": state.dataset.meta.total_episodes}

    monkeypatch.setattr(state, "_rewrite_source", fake_rewrite_source)
    return captured


def test_delete_range_only_passes_current_episode_delete_range(monkeypatch):
    state = make_state()
    captured = capture_rewrite_call(monkeypatch, state)

    state.update_edit({"episode": 1, "delete_start": 2, "delete_end": 5})

    assert captured == {
        "episode_delete_ranges": {1: (2, 5)},
        "selected_episode": 1,
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"episode": 1, "delete": True},
        {"episode": 1, "delete_start": 0, "delete_end": 12},
    ],
)
def test_delete_episode_only_passes_current_episode_index(monkeypatch, payload):
    state = make_state()
    captured = capture_rewrite_call(monkeypatch, state)

    state.update_edit(payload)

    assert captured == {
        "delete_episode_indices": [1],
        "selected_episode": 1,
    }


def test_keep_range_only_passes_current_episode_range(monkeypatch):
    state = make_state()
    captured = capture_rewrite_call(monkeypatch, state)

    state.update_edit({"episode": 2, "start": 3, "end": 9})

    assert captured == {
        "episode_ranges": {2: (3, 9)},
        "selected_episode": 2,
    }


def test_rewrite_source_uses_delete_episodes_for_whole_episode_delete(monkeypatch, tmp_path):
    state = make_state()
    calls = []

    def fake_delete_episodes(*args, **kwargs):
        calls.append(("delete", args, kwargs))

    def fake_trim_episodes(*args, **kwargs):
        calls.append(("trim", args, kwargs))

    monkeypatch.setattr("lerobot.scripts.lerobot_curate_dataset.delete_episodes", fake_delete_episodes)
    monkeypatch.setattr("lerobot.scripts.lerobot_curate_dataset.trim_episodes", fake_trim_episodes)

    state._rewrite_source_with_tool(
        state.dataset,
        tmp_path,
        delete_episode_indices=[1],
    )

    assert [call[0] for call in calls] == ["delete"]
    assert calls[0][2]["episode_indices"] == [1]
    assert calls[0][2]["output_dir"] == tmp_path
    assert calls[0][2]["repo_id"] == state.dataset.repo_id


def test_rewrite_source_keeps_trim_episodes_for_frame_range_delete(monkeypatch, tmp_path):
    state = make_state()
    calls = []

    def fake_delete_episodes(*args, **kwargs):
        calls.append(("delete", args, kwargs))

    def fake_trim_episodes(*args, **kwargs):
        calls.append(("trim", args, kwargs))

    monkeypatch.setattr("lerobot.scripts.lerobot_curate_dataset.delete_episodes", fake_delete_episodes)
    monkeypatch.setattr("lerobot.scripts.lerobot_curate_dataset.trim_episodes", fake_trim_episodes)

    state._rewrite_source_with_tool(
        state.dataset,
        tmp_path,
        episode_delete_ranges={1: (2, 5)},
    )

    assert [call[0] for call in calls] == ["trim"]
    assert calls[0][2]["episode_delete_ranges"] == {1: (2, 5)}
    assert calls[0][2]["delete_episode_indices"] is None
    assert calls[0][2]["output_dir"] == tmp_path
    assert calls[0][2]["repo_id"] == state.dataset.repo_id


def test_frame_data_returns_low_dimensional_alignment_fields_without_visual_payloads():
    features = {
        "timestamp": {"dtype": "float32", "shape": None, "names": None},
        "frame_index": {"dtype": "int64", "shape": None, "names": None},
        "index": {"dtype": "int64", "shape": None, "names": None},
        "action": {"dtype": "float32", "shape": (2,), "names": ["left", "right"]},
        "observation.state": {"dtype": "float32", "shape": (3,), "names": {"x": 0, "y": 1, "z": 2}},
        "observation.images.front": {"dtype": "image", "shape": (480, 640, 3), "names": None},
        "observation.video.front": {"dtype": "video", "shape": None, "names": None},
    }
    episodes = [
        {"length": 1, "dataset_from_index": 0, "tasks": []},
        {"length": 2, "dataset_from_index": 1, "tasks": []},
    ]
    rows = [
        {
            "timestamp": np.float32(0.0),
            "frame_index": 0,
            "index": 0,
            "action": np.array([0.0, 0.1], dtype=np.float32),
            "observation.state": np.array([1.0, 2.0, 3.0], dtype=np.float32),
            "observation.images.front": "ignored image",
            "observation.video.front": "ignored video",
        },
        {
            "timestamp": np.float32(0.1),
            "frame_index": 0,
            "index": 1,
            "action": np.array([1.0, 1.1], dtype=np.float32),
            "observation.state": np.array([4.0, 5.0, 6.0], dtype=np.float32),
            "observation.images.front": "ignored image",
            "observation.video.front": "ignored video",
        },
        {
            "timestamp": np.float32(0.2),
            "frame_index": 1,
            "index": 2,
            "action": np.array([2.0, 2.1], dtype=np.float32),
            "observation.state": np.array([7.0, 8.0, 9.0], dtype=np.float32),
            "observation.images.front": "ignored image",
            "observation.video.front": "ignored video",
        },
    ]
    hf_dataset = FakeHfDataset(rows)
    state = CuratorState(
        FakeDataset(FakeMeta(episodes, features=features), hf_dataset=hf_dataset),
        repo_id="test/repo",
        video_backend=None,
    )

    payload = state.frame_data(1)

    assert hf_dataset.selected_indices == [1, 2]
    assert payload["episode"] == 1
    assert payload["frame_count"] == 2
    field_keys = [field["key"] for field in payload["fields"]]
    assert field_keys == ["timestamp", "frame_index", "index", "action", "observation.state"]
    assert "observation.images.front" not in field_keys
    assert "observation.video.front" not in field_keys
    assert payload["fields"][3]["shape"] == [2]
    assert payload["fields"][4]["names"] == {"x": 0, "y": 1, "z": 2}
    assert len(payload["frames"]) == 2
    assert payload["frames"][0]["timestamp"] == pytest.approx(0.1)
    assert payload["frames"][0]["frame_index"] == 0
    assert payload["frames"][0]["index"] == 1
    assert payload["frames"][0]["action"] == pytest.approx([1.0, 1.1])
    assert payload["frames"][0]["observation.state"] == pytest.approx([4.0, 5.0, 6.0])
    assert payload["frames"][1]["timestamp"] == pytest.approx(0.2)
    assert payload["frames"][1]["frame_index"] == 1
    assert payload["frames"][1]["index"] == 2
    assert payload["frames"][1]["action"] == pytest.approx([2.0, 2.1])
    assert payload["frames"][1]["observation.state"] == pytest.approx([7.0, 8.0, 9.0])
