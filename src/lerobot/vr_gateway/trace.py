"""Opt-in, bounded VR gateway trace recording and validation helpers.

The trace format is deliberately JSONL so an operator can copy it off a Pi without
special tooling.  Recording is never on the control thread: callers enqueue small,
JSON-safe dictionaries and a daemon writer performs the file I/O.  A dropped event or
writer failure marks the stream incomplete; consumers must reject such a stream rather
than silently treating a partial trajectory as a real replay.

Only control data is recorded.  Camera frames, HTTP headers and authentication-like
fields are removed before an event enters the queue.
"""

from __future__ import annotations

import hashlib
import json
import queue
import threading
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Iterable

TRACE_SCHEMA = 1
_SENTINEL = object()
_REDACT_KEYS = {
    "authorization",
    "cookie",
    "headers",
    "jpeg_b64",
    "frame",
    "image",
    "camera",
    "token",
    "password",
}


class TraceIncompleteError(ValueError):
    """Raised when a trace cannot prove that all control events were preserved."""


def _json_safe(value: Any, *, key: str | None = None) -> Any:
    """Convert values to JSON while dropping image/credential-bearing fields."""
    if key is not None and key.lower() in _REDACT_KEYS:
        return None
    if isinstance(value, dict):
        return {
            str(k): safe
            for k, raw in value.items()
            if (safe := _json_safe(raw, key=str(k))) is not None
        }
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "tolist"):
        return _json_safe(value.tolist())
    if hasattr(value, "item"):
        return value.item()
    if is_dataclass(value):
        return _json_safe(asdict(value))
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return repr(value)
    return value


def file_sha256(path: str | Path) -> str | None:
    """Return a file digest, or ``None`` when the runtime asset is unavailable."""
    candidate = Path(path)
    if not candidate.is_file():
        return None
    digest = hashlib.sha256()
    with candidate.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def runtime_metadata(robot: Any, config: Any, arm_ik: Any = None) -> dict[str, Any]:
    """Build a trace header from runtime assets without reading camera data.

    Calibration values are copied from the robot's already-loaded validation result;
    this keeps the header tied to the actual six-joint runtime calibration rather than
    a test fixture or a hand-entered range.
    """
    try:
        from lerobot import __version__
    except Exception:  # pragma: no cover - import metadata is optional
        __version__ = "unknown"
    urdf = getattr(arm_ik, "urdf_path", None)
    calibration_path = getattr(robot, "calibration_fpath", None)
    arm_calibration = getattr(robot, "vr_arm_calibration", None)
    # Keep the exact raw ROM, drive mode and model resolution for all twelve arm
    # motors. This is read-only metadata from the already-loaded bus calibration.
    runtime_calibration: dict[str, Any] = {}
    for side in ("left", "right"):
        bus = getattr(robot, f"{side}_bus", None)
        for name, cal in getattr(bus, "calibration", {}).items() if bus is not None else ():
            if not str(name).startswith(f"arm_{side}_"):
                continue
            motor = getattr(bus, "motors", {}).get(name)
            model = getattr(motor, "model", None)
            resolution = getattr(bus, "model_resolution_table", {}).get(model)
            runtime_calibration[str(name)] = {
                "id": getattr(cal, "id", None),
                "drive_mode": getattr(cal, "drive_mode", None),
                "homing_offset": getattr(cal, "homing_offset", None),
                "range_min": getattr(cal, "range_min", None),
                "range_max": getattr(cal, "range_max", None),
                "motor_model": model,
                "resolution": resolution,
            }
    metadata = {
        "runtime_version": __version__,
        "gateway_config": _json_safe(config),
        "robot_model": getattr(getattr(robot, "config", None), "robot_model", None),
        "urdf_path": None if urdf is None else str(urdf),
        "urdf_sha256": None if urdf is None else file_sha256(urdf),
        "calibration_path": None if calibration_path is None else str(calibration_path),
        "calibration_sha256": None if calibration_path is None else file_sha256(calibration_path),
        "arm_calibration": _json_safe(arm_calibration),
        "runtime_arm_calibration": _json_safe(runtime_calibration),
        "joint_signs": _json_safe(getattr(arm_ik, "_signs", None)),
        "joint_offsets_deg": _json_safe(getattr(arm_ik, "_offsets", None)),
        "control_mode": getattr(config, "control_mode", None)
        or getattr(arm_ik, "control_mode", None),
        "clock": "monotonic_ns",
        "control_hz": getattr(config, "control_hz", None),
        "poll_hz": getattr(config, "poll_hz", None),
    }
    return metadata


class VRTraceRecorder:
    """Bounded, non-blocking JSONL writer used by the gateway control path."""

    def __init__(
        self,
        path: str | Path,
        *,
        metadata: dict[str, Any] | None = None,
        max_events: int = 4096,
        clock: Any = time.monotonic_ns,
    ) -> None:
        if max_events < 8:
            raise ValueError("max_events must be at least 8")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._queue: queue.Queue[object] = queue.Queue(maxsize=max_events)
        self._clock = clock
        self._seq = 0
        self._dropped = 0
        self._write_error: str | None = None
        self._closed = False
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, name="vr-trace-writer", daemon=True)
        header = {
            "schema": TRACE_SCHEMA,
            "kind": "header",
            "seq": 0,
            "monotonic_ns": int(self._clock()),
            "metadata": _json_safe(metadata or {}),
            "complete": False,
        }
        self.path.write_text(json.dumps(header, separators=(",", ":")) + "\n", encoding="utf-8")
        self._thread.start()

    @property
    def dropped(self) -> int:
        return self._dropped

    @property
    def complete(self) -> bool:
        return self._closed and self._dropped == 0 and self._write_error is None

    def clock_ns(self) -> int:
        """Read the recorder clock for correlating an observation with a tick."""
        return int(self._clock())

    def record(self, kind: str, **fields: Any) -> bool:
        """Enqueue one event without waiting for disk I/O."""
        with self._lock:
            if self._closed:
                return False
            self._seq += 1
            event = {
                "schema": TRACE_SCHEMA,
                "kind": str(kind),
                "seq": self._seq,
                "monotonic_ns": int(self._clock()),
                **_json_safe(fields),
            }
            try:
                self._queue.put_nowait(event)
            except queue.Full:
                self._dropped += 1
                return False
            return True

    def close(self, *, timeout_s: float = 2.0) -> None:
        """Drain queued events and append a completeness footer."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
        try:
            self._queue.put_nowait(_SENTINEL)
        except queue.Full:
            # A full queue means events were dropped; never block shutdown waiting for
            # a failed writer to drain it. Mark the stream incomplete instead.
            with self._lock:
                self._dropped += 1
        self._thread.join(timeout=max(0.0, timeout_s))
        if self._thread.is_alive():
            with self._lock:
                self._write_error = self._write_error or "writer_join_timeout"
        footer = {
            "schema": TRACE_SCHEMA,
            "kind": "footer",
            "seq": self._seq + 1,
            "monotonic_ns": int(self._clock()),
            "complete": self.complete,
            "dropped_events": self._dropped,
            "write_error": self._write_error,
        }
        try:
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(footer, separators=(",", ":")) + "\n")
        except OSError as exc:
            with self._lock:
                self._write_error = str(exc)

    def _run(self) -> None:
        try:
            with self.path.open("a", encoding="utf-8") as stream:
                while True:
                    event = self._queue.get()
                    if event is _SENTINEL:
                        return
                    stream.write(json.dumps(event, separators=(",", ":")) + "\n")
                    stream.flush()
        except (OSError, TypeError, ValueError) as exc:
            with self._lock:
                self._write_error = str(exc)


def read_trace(path: str | Path) -> list[dict[str, Any]]:
    """Read and validate a complete trace before a caller uses its events."""
    events: list[dict[str, Any]] = []
    with Path(path).open(encoding="utf-8") as stream:
        for line_no, line in enumerate(stream, 1):
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise TraceIncompleteError(f"invalid JSON at line {line_no}: {exc}") from exc
            if not isinstance(value, dict) or value.get("schema") != TRACE_SCHEMA:
                raise TraceIncompleteError(f"unsupported trace event at line {line_no}")
            events.append(value)
    if len(events) < 2 or events[0].get("kind") != "header" or events[-1].get("kind") != "footer":
        raise TraceIncompleteError("trace must contain header and footer")
    footer = events[-1]
    if not footer.get("complete") or footer.get("dropped_events", 0) or footer.get("write_error"):
        raise TraceIncompleteError(
            f"trace is incomplete (dropped={footer.get('dropped_events')}, error={footer.get('write_error')})"
        )
    body = events[1:-1]
    expected = 1
    for event in body:
        if event.get("seq") != expected:
            raise TraceIncompleteError(f"non-contiguous event sequence at {event.get('seq')}, expected {expected}")
        expected += 1
    return events


def require_replay_observations(events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reject WS-only captures that cannot reproduce measured-state-dependent IK."""
    all_events = list(events)
    ticks = [event for event in all_events if event.get("kind") == "control_tick"]
    if not ticks:
        raise TraceIncompleteError("trace has no control_tick events")
    missing = [
        event.get("seq")
        for event in ticks
        if not isinstance(event.get("measured_state"), dict)
        or not isinstance(event.get("observation_seq"), int)
    ]
    if missing:
        raise TraceIncompleteError(
            f"control ticks missing measured_state/observation_seq: {missing[:5]}"
        )
    tick_ids = {event.get("tick_seq") for event in ticks}
    action_ids = {
        event.get("tick_seq")
        for event in all_events
        if event.get("kind") == "action_result" and event.get("tick_seq") is not None
    }
    missing_actions = sorted(tick_ids - action_ids)
    if missing_actions:
        raise TraceIncompleteError(f"control ticks missing action_result: {missing_actions[:5]}")
    return ticks
