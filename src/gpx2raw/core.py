from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import gpxpy


@dataclass(frozen=True)
class TrackPoint:
    time_utc: datetime
    latitude: float
    longitude: float
    elevation: float | None


@dataclass(frozen=True)
class MatchResult:
    source: str
    latitude: float
    longitude: float
    elevation: float | None
    nearest_delta_seconds: float


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def load_gpx_points(gpx_path: Path) -> list[TrackPoint]:
    with gpx_path.open("r", encoding="utf-8") as handle:
        gpx = gpxpy.parse(handle)

    points: list[TrackPoint] = []
    for track in gpx.tracks:
        for segment in track.segments:
            for point in segment.points:
                if point.time is None:
                    continue
                points.append(
                    TrackPoint(
                        time_utc=_as_utc(point.time),
                        latitude=point.latitude,
                        longitude=point.longitude,
                        elevation=point.elevation,
                    )
                )

    points.sort(key=lambda item: item.time_utc)
    return points


def _lerp(start: float, end: float, ratio: float) -> float:
    return start + (end - start) * ratio


def _pick_elevation(first: float | None, second: float | None, ratio: float) -> float | None:
    if first is not None and second is not None:
        return _lerp(first, second, ratio)
    if first is not None:
        return first
    return second


def find_match(target_time_utc: datetime, points: list[TrackPoint], max_delta_seconds: float) -> MatchResult | None:
    if not points:
        return None

    target = _as_utc(target_time_utc)
    times = [point.time_utc for point in points]
    idx = bisect_left(times, target)

    if idx == 0:
        nearest = points[0]
        delta = abs((target - nearest.time_utc).total_seconds())
        if delta > max_delta_seconds:
            return None
        return MatchResult(
            source="nearest",
            latitude=nearest.latitude,
            longitude=nearest.longitude,
            elevation=nearest.elevation,
            nearest_delta_seconds=delta,
        )

    if idx == len(points):
        nearest = points[-1]
        delta = abs((target - nearest.time_utc).total_seconds())
        if delta > max_delta_seconds:
            return None
        return MatchResult(
            source="nearest",
            latitude=nearest.latitude,
            longitude=nearest.longitude,
            elevation=nearest.elevation,
            nearest_delta_seconds=delta,
        )

    prev_point = points[idx - 1]
    next_point = points[idx]
    prev_delta = abs((target - prev_point.time_utc).total_seconds())
    next_delta = abs((next_point.time_utc - target).total_seconds())
    nearest_delta = min(prev_delta, next_delta)
    if nearest_delta > max_delta_seconds:
        return None

    segment_seconds = (next_point.time_utc - prev_point.time_utc).total_seconds()
    if segment_seconds == 0:
        return MatchResult(
            source="nearest",
            latitude=prev_point.latitude,
            longitude=prev_point.longitude,
            elevation=prev_point.elevation,
            nearest_delta_seconds=nearest_delta,
        )

    ratio = (target - prev_point.time_utc).total_seconds() / segment_seconds
    return MatchResult(
        source="interpolated",
        latitude=_lerp(prev_point.latitude, next_point.latitude, ratio),
        longitude=_lerp(prev_point.longitude, next_point.longitude, ratio),
        elevation=_pick_elevation(prev_point.elevation, next_point.elevation, ratio),
        nearest_delta_seconds=nearest_delta,
    )