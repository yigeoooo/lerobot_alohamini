"""Per-hand clutch events retained while high-rate poses are coalesced.

The gateway protects this mailbox with its staging lock. The control worker takes
a snapshot: a release/re-grip between two control ticks must still re-anchor.
"""

from __future__ import annotations

from typing import Any

SIDES = ("left", "right")


class ArmSessions:
    def __init__(self):
        self.requested = dict.fromkeys(SIDES, False)
        self.blocked: dict[str, str | None] = dict.fromkeys(SIDES)
        self.reset_sides: set[str] = set()
        self.last_pose_at: dict[str, float | None] = dict.fromkeys(SIDES)
        self._epochs: dict[str, int | None] = dict.fromkeys(SIDES)

    def stage(self, payload: dict[str, Any], now: float) -> dict[str, Any]:
        from .arm_ik import pose_to_matrix

        result = dict(payload)
        for side in SIDES:
            pressed = bool(payload.get(f"{side}_active", payload.get("active", False)))
            tracked = pose_to_matrix(payload.get(side)) is not None
            if not pressed:
                self.blocked[side] = None
            elif not tracked:
                self.blocked[side] = "tracking_lost"
            active = pressed and tracked and self.blocked[side] is None
            epoch = payload.get(f"{side}_epoch")
            if epoch is not None:
                if not isinstance(epoch, int) or epoch < 0:
                    raise ValueError("arm epoch must be a nonnegative integer")
                if self._epochs[side] is not None and epoch != self._epochs[side]:
                    self.reset_sides.add(side)
                self._epochs[side] = epoch
            if self.requested[side] != active or payload.get("reanchor"):
                self.reset_sides.add(side)
            self.requested[side] = active
            result[f"{side}_active"] = active
            if active:
                self.last_pose_at[side] = now
        result["active"] = any(self.requested.values())
        return result

    def stop(self, reason: str, sides=SIDES) -> None:
        for side in sides:
            self.reset_sides.add(side)
            self.requested[side] = False
            self.blocked[side] = reason
            self.last_pose_at[side] = None

    def take_resets(self) -> set[str]:
        resets, self.reset_sides = self.reset_sides, set()
        return resets

    def expired(self, now: float, timeout: float) -> set[str]:
        return {
            side
            for side in SIDES
            if self.requested[side]
            and self.last_pose_at[side] is not None
            and now - self.last_pose_at[side] > timeout
        }
