#!/usr/bin/env python3
"""Pure gesture helpers for the phone-touch control experiment.

This module deliberately knows nothing about Bluetooth, Android, OCR, or offer
state.  It converts physical pointer samples into normalized coordinates and a
small set of manual gestures.  Keeping that boundary narrow makes it impossible
for scanner output to become a phone click by importing this module alone.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Optional


@dataclass(frozen=True)
class Sample:
    x: float
    y: float
    when: float


@dataclass(frozen=True)
class Gesture:
    kind: str
    x: float
    y: float
    dx: float = 0.0
    dy: float = 0.0


def normalized(x: float, y: float, left: float, top: float,
               width: float, height: float) -> tuple[float, float]:
    """Return coordinates in [0, 1] relative to the visible phone image."""
    if width <= 0 or height <= 0:
        raise ValueError('phone image width and height must be positive')
    nx = (x - left) / width
    ny = (y - top) / height
    return max(0.0, min(1.0, nx)), max(0.0, min(1.0, ny))


class GestureTracker:
    """Classify one physical pointer sequence as tap or drag.

    Coordinates supplied here are already normalized to the phone image.  The
    tracker emits movement while a drag is active and exactly one tap on a
    short, sufficiently stationary press.  cancel() never emits a click.
    """

    def __init__(self, tap_seconds: float = 0.35, drag_distance: float = 0.018):
        if tap_seconds <= 0 or drag_distance <= 0:
            raise ValueError('gesture thresholds must be positive')
        self.tap_seconds = tap_seconds
        self.drag_distance = drag_distance
        self._start: Optional[Sample] = None
        self._last: Optional[Sample] = None
        self._dragged = False

    @property
    def active(self) -> bool:
        return self._start is not None

    def down(self, x: float, y: float, when: float) -> None:
        point = Sample(x, y, when)
        self._start = point
        self._last = point
        self._dragged = False

    def move(self, x: float, y: float, when: float) -> Optional[Gesture]:
        if self._start is None or self._last is None:
            return None
        point = Sample(x, y, when)
        total = math.hypot(point.x - self._start.x, point.y - self._start.y)
        if total >= self.drag_distance:
            self._dragged = True
        previous = self._last
        self._last = point
        if not self._dragged:
            return None
        return Gesture('move', point.x, point.y,
                       point.x - previous.x, point.y - previous.y)

    def up(self, x: float, y: float, when: float) -> Optional[Gesture]:
        if self._start is None:
            return None
        start = self._start
        distance = math.hypot(x - start.x, y - start.y)
        elapsed = max(0.0, when - start.when)
        was_drag = self._dragged or distance >= self.drag_distance
        self.cancel()
        if not was_drag and elapsed <= self.tap_seconds:
            return Gesture('tap', x, y)
        return Gesture('release', x, y)

    def cancel(self) -> None:
        self._start = None
        self._last = None
        self._dragged = False
