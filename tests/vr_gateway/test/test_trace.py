from __future__ import annotations

import json
from pathlib import Path

import pytest

from lerobot.vr_gateway.server import VRGateway, VRGatewayConfig
from lerobot.vr_gateway.trace import (
    TraceIncompleteError,
    VRTraceRecorder,
    read_trace,
    require_replay_observations,
)


class _TraceRobot:
    """Synthetic robot used only to verify the trace transport contract."""

    is_connected = True

    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []
        self.last_remote_state: dict[str, object] = {}

    def get_observation(self) -> dict[str, object]:
        state = {
            "lift_axis.height_mm": 300.0,
            "base_x.vel": 0.0,
            "base_y.vel": 0.0,
            "base_theta.vel": 0.0,
        }
        for side in ("left", "right"):
            for name in ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_yaw", "wrist_roll"):
                state[f"arm_{side}_{name}.pos"] = 0.0
        self.last_remote_state = state
        return state

    def send_action(self, action: dict[str, object]) -> dict[str, object]:
        self.sent.append(dict(action))
        return {"accepted": True, "action_keys": sorted(action)}


class _TraceIK:
    active = False
    homing = False
    tracking_status = {"state": "ok", "sides": {}}

    def update(self, payload: dict[str, object], state: dict[str, object]) -> dict[str, float]:
        self.active = bool(payload.get("active"))
        if not self.active:
            return {}
        return {"arm_left_shoulder_pan.pos": 4.0, "arm_right_shoulder_pan.pos": -4.0}


def _pose() -> dict[str, list[float]]:
    return {"position": [0.0, 0.0, 0.0], "orientation": [0.0, 0.0, 0.0, 1.0]}


def test_trace_writer_roundtrip_redacts_camera_and_auth_fields(tmp_path: Path) -> None:
    """Synthetic tool test: the opt-in writer is complete and control-only."""
    path = tmp_path / "trace.jsonl"
    recorder = VRTraceRecorder(path, metadata={"evidence": "synthetic_tool_test"}, clock=lambda: 100)
    recorder.record(
        "ws_in",
        message={
            "type": "head_pose",
            "camera": "forward",
            "authorization": "secret",
            "pose": _pose(),
        },
    )
    recorder.record(
        "control_tick",
        tick_seq=1,
        observation_seq=1,
        measured_state={"lift_axis.height_mm": 300.0},
    )
    recorder.record("action_result", tick_seq=1, sent=False, action=None, result=None)
    recorder.close()

    events = read_trace(path)
    assert events[0]["kind"] == "header"
    assert events[-1]["complete"] is True
    raw = json.dumps(events)
    assert "secret" not in raw
    assert '"camera"' not in raw
    assert require_replay_observations(events)[0]["measured_state"]["lift_axis.height_mm"] == 300.0


def test_gateway_trace_captures_ws_tick_observation_and_action_order(tmp_path: Path) -> None:
    """Synthetic protocol test; it does not claim a Quest or hardware symptom repro."""
    path = tmp_path / "gateway.jsonl"
    robot = _TraceRobot()
    gateway = VRGateway(
        robot,
        VRGatewayConfig(trace_path=str(path), trace_max_events=64),
        arm_ik=_TraceIK(),
    )
    gateway.capture_observation()
    gateway.stage_message({"type": "head_pose", "pose": _pose()})
    gateway.stage_message({"type": "base", "x.vel": 0.2, "y.vel": 0.0, "theta.vel": 0.1})
    gateway.stage_message({"type": "lift", "velocity": 5.0, "button": "B"})
    gateway.stage_message(
        {
            "type": "arm_pose",
            "active": True,
            "left_active": True,
            "right_active": True,
            "reanchor": True,
            "left_reanchor": True,
            "right_reanchor": True,
            "left": _pose(),
            "right": _pose(),
            "mode": "telegrip",
            "control_mode": "telegrip",
            "client_time_ms": 1000,
        }
    )
    assert gateway.flush() is True
    gateway.stage_message({"type": "arm_pose", "active": False, "left": None, "right": None})
    gateway.stage_message({"type": "base", "x.vel": 0.0, "y.vel": 0.0, "theta.vel": 0.0})
    assert gateway.flush() is True
    gateway.close_trace()

    events = read_trace(path)
    kinds = [event["kind"] for event in events]
    assert kinds[0] == "header" and kinds[-1] == "footer"
    assert events[0]["metadata"]["control_mode"] == "telegrip"
    assert events[0]["metadata"]["clock"] == "monotonic_ns"
    assert kinds.index("observation") < kinds.index("control_tick") < kinds.index("action_result")
    ws = [event for event in events if event["kind"] == "ws_in"]
    assert [event["message"]["type"] for event in ws] == ["head_pose", "base", "lift", "arm_pose", "arm_pose", "base"]
    ticks = require_replay_observations(events)
    assert len(ticks) == 2
    assert ticks[0]["arm_payload"]["control_mode"] == "telegrip"
    actions = [event for event in events if event["kind"] == "action_result" and event.get("sent") is not False]
    assert actions and actions[0]["action"]["x.vel"] == 0.2
    assert events[1]["kind"] == "observation"
    assert "jpeg_b64" not in json.dumps(events)


def test_replay_rejects_ws_only_or_incomplete_trace(tmp_path: Path) -> None:
    """A WS capture without measured state is insufficient for state-dependent IK."""
    path = tmp_path / "incomplete.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps({"schema": 1, "kind": "header", "seq": 0, "complete": True}),
                json.dumps({"schema": 1, "kind": "control_tick", "seq": 1, "observation_seq": 1, "measured_state": None}),
                json.dumps({"schema": 1, "kind": "footer", "seq": 2, "complete": True, "dropped_events": 0}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(TraceIncompleteError, match="missing measured_state"):
        require_replay_observations(read_trace(path))


def test_per_side_activity_and_reanchor_are_preserved_for_telegrip_trace(tmp_path: Path) -> None:
    """Synthetic protocol test: one hand can release without erasing the other anchor."""
    path = tmp_path / "per-side.jsonl"
    robot = _TraceRobot()
    gateway = VRGateway(
        robot,
        VRGatewayConfig(trace_path=str(path), control_mode="telegrip", trace_max_events=64),
        arm_ik=_TraceIK(),
    )
    gateway.capture_observation()
    gateway.stage_message(
        {
            "type": "arm_pose",
            "active": True,
            "left_active": True,
            "right_active": False,
            "left_reanchor": True,
            "right_reanchor": False,
            "left": _pose(),
            "right": None,
            "control_mode": "telegrip",
        }
    )
    assert gateway.flush() is True
    gateway.close_trace()
    events = read_trace(path)
    tick = require_replay_observations(events)[0]
    payload = tick["arm_payload"]
    assert payload["left_active"] is True
    assert payload["right_active"] is False
    assert payload["left_reanchor"] is True
    assert payload["right_reanchor"] is False
    assert payload["control_mode"] == "telegrip"
    assert tick["control_mode"] == "telegrip"
    assert tick["left_active"] is True and tick["right_active"] is False
    assert tick["left_reanchor"] is True and tick["right_reanchor"] is False


def test_per_side_release_clears_only_released_hand_diagnostic_anchor() -> None:
    """Synthetic state test: release cannot leave a stale hand anchor for re-grip."""
    gateway = VRGateway(_TraceRobot(), VRGatewayConfig(), arm_ik=_TraceIK())
    gateway._arm_hand_position_m["left"] = (0.1, 0.2, 0.3)
    gateway._arm_hand_anchor_m["left"] = (0.0, 0.0, 0.0)
    gateway._arm_hand_position_m["right"] = (0.2, 0.3, 0.4)
    gateway._arm_hand_anchor_m["right"] = (0.0, 0.0, 0.0)
    gateway._remember_arm_hand_pose(
        {
            "active": True,
            "left_active": False,
            "right_active": True,
            "left": None,
            "right": _pose(),
        }
    )
    assert gateway._arm_hand_position_m["left"] is None
    assert gateway._arm_hand_anchor_m["left"] is None
    assert gateway._arm_hand_position_m["right"] == (0.0, 0.0, 0.0)


def test_trace_records_runtime_control_mode_switch(tmp_path: Path) -> None:
    """Synthetic protocol test: a payload mode switch is visible at dispatch/tick."""
    path = tmp_path / "mode-switch.jsonl"
    robot = _TraceRobot()
    gateway = VRGateway(
        robot,
        VRGatewayConfig(trace_path=str(path), control_mode="telegrip", trace_max_events=64),
        arm_ik=_TraceIK(),
    )
    gateway.capture_observation()
    gateway.stage_message(
        {
            "type": "arm_pose",
            "active": True,
            "left_active": True,
            "right_active": True,
            "left": _pose(),
            "right": _pose(),
            "control_mode": "full_pose",
        }
    )
    assert gateway.flush() is True
    gateway.close_trace()
    events = read_trace(path)
    tick = require_replay_observations(events)[0]
    assert tick["control_mode"] == "full_pose"
    assert tick["arm_payload"]["control_mode"] == "full_pose"


def test_trace_overflow_is_marked_incomplete_and_rejected(tmp_path: Path) -> None:
    """Synthetic tool test: bounded capture never blocks and cannot look complete."""
    path = tmp_path / "overflow.jsonl"
    recorder = VRTraceRecorder(path, max_events=8)
    for index in range(100):
        recorder.record("ws_in", message={"type": "ping", "index": index})
    recorder.close(timeout_s=2.0)
    assert recorder.dropped > 0
    with pytest.raises(TraceIncompleteError, match="incomplete|footer"):
        read_trace(path)
