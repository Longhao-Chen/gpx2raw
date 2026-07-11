from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from gpx2raw.cli import _collect_photos
from gpx2raw.core import TrackPoint, find_match
from gpx2raw.exiftool_io import ExifToolError, parse_photo_timestamp, read_photo_metadata
from gpx2raw.cli import build_parser


def test_collect_photos_supports_single_jpg(tmp_path: Path) -> None:
    photo = tmp_path / "a.JPG"
    photo.write_bytes(b"x")

    found = _collect_photos(photo)
    assert found == [photo]


def test_collect_photos_supports_directory_mixed_ext(tmp_path: Path) -> None:
    photo_nef = tmp_path / "a.NEF"
    photo_jpeg = tmp_path / "b.jpeg"
    video_mov = tmp_path / "c.MOV"
    ignored = tmp_path / "d.png"
    photo_nef.write_bytes(b"x")
    photo_jpeg.write_bytes(b"x")
    video_mov.write_bytes(b"x")
    ignored.write_bytes(b"x")

    found = _collect_photos(tmp_path)
    assert found == [photo_nef, photo_jpeg, video_mov]


def test_collect_photos_rejects_invalid_single_file(tmp_path: Path) -> None:
    invalid = tmp_path / "a.png"
    invalid.write_bytes(b"x")

    with pytest.raises(ValueError):
        _collect_photos(invalid)


def test_find_match_interpolates_between_points() -> None:
    base = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    points = [
        TrackPoint(time_utc=base, latitude=30.0, longitude=120.0, elevation=10.0),
        TrackPoint(time_utc=base + timedelta(seconds=10), latitude=40.0, longitude=130.0, elevation=30.0),
    ]

    target = base + timedelta(seconds=5)
    result = find_match(target, points, max_delta_seconds=300)
    assert result is not None
    assert result.source == "interpolated"
    assert result.latitude == pytest.approx(35.0)
    assert result.longitude == pytest.approx(125.0)
    assert result.elevation == pytest.approx(20.0)


def test_parse_photo_timestamp_with_offset() -> None:
    record = {
        "DateTimeOriginal": "2026:07:05 08:00:00",
        "SubSecTimeOriginal": "12",
        "OffsetTimeOriginal": "+08:00",
    }

    parsed = parse_photo_timestamp(record, fallback_timezone=None)
    assert parsed.original_utc == datetime(2026, 7, 5, 0, 0, 0, 120000, tzinfo=timezone.utc)


def test_parse_photo_timestamp_with_int_subsec() -> None:
    record = {
        "DateTimeOriginal": "2026:07:05 08:00:00",
        "SubSecTimeOriginal": 2,
        "OffsetTimeOriginal": "+08:00",
    }

    parsed = parse_photo_timestamp(record, fallback_timezone=None)
    assert parsed.original_utc == datetime(2026, 7, 5, 0, 0, 0, 200000, tzinfo=timezone.utc)


def test_parse_photo_timestamp_requires_tz_when_missing_offset() -> None:
    record = {
        "DateTimeOriginal": "2026:07:05 08:00:00",
    }

    with pytest.raises(ExifToolError):
        parse_photo_timestamp(record, fallback_timezone=None)


def test_build_parser_supports_skip_existing_gps_flag() -> None:
    parser = build_parser()
    args = parser.parse_args(["--photos", "a.NEF", "--gpx", "b.gpx", "--skip-existing-gps"])
    assert args.skip_existing_gps is True