from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from gpx2raw.cli import _collect_gpx, _collect_photos, build_parser
from gpx2raw.core import TrackPoint, find_match
from gpx2raw.exiftool_io import parse_photo_timestamp


def test_collect_gpx_single_file(tmp_path: Path) -> None:
    gpx = tmp_path / "a.gpx"
    gpx.write_bytes(b"x")
    found = _collect_gpx([str(gpx)])
    assert found == [gpx]


def test_collect_gpx_directory(tmp_path: Path) -> None:
    a = tmp_path / "a.gpx"
    b = tmp_path / "b.gpx"
    ignored = tmp_path / "c.txt"
    a.write_bytes(b"x")
    b.write_bytes(b"x")
    ignored.write_bytes(b"x")
    found = _collect_gpx([str(tmp_path)])
    assert found == [a, b]


def test_collect_gpx_mixed_args(tmp_path: Path) -> None:
    sub = tmp_path / "sub"
    sub.mkdir()
    a = tmp_path / "a.gpx"
    b = sub / "b.gpx"
    a.write_bytes(b"x")
    b.write_bytes(b"x")
    found = _collect_gpx([str(a), str(sub)])
    # b.gpx is at top level of sub/, found by glob
    assert found == [a, b]


def test_collect_gpx_directory_non_recursive(tmp_path: Path) -> None:
    sub = tmp_path / "sub"
    sub.mkdir()
    a = tmp_path / "a.gpx"
    b = sub / "b.gpx"
    a.write_bytes(b"x")
    b.write_bytes(b"x")
    found = _collect_gpx([str(tmp_path)])
    # non-recursive: only top-level a.gpx
    assert found == [a]


def test_collect_gpx_directory_recursive(tmp_path: Path) -> None:
    sub = tmp_path / "sub"
    sub.mkdir()
    a = tmp_path / "a.gpx"
    b = sub / "b.gpx"
    a.write_bytes(b"x")
    b.write_bytes(b"x")
    found = _collect_gpx([str(tmp_path)], recursive=True)
    assert found == [a, b]


def test_collect_photos_directory_non_recursive(tmp_path: Path) -> None:
    sub = tmp_path / "sub"
    sub.mkdir()
    a = tmp_path / "a.jpg"
    b = sub / "b.jpg"
    a.write_bytes(b"x")
    b.write_bytes(b"x")
    found = _collect_photos(tmp_path)
    # non-recursive: only top-level
    assert found == [a]


def test_collect_photos_directory_recursive(tmp_path: Path) -> None:
    sub = tmp_path / "sub"
    sub.mkdir()
    a = tmp_path / "a.jpg"
    b = sub / "b.jpg"
    a.write_bytes(b"x")
    b.write_bytes(b"x")
    found = _collect_photos(tmp_path, recursive=True)
    assert found == [a, b]


def test_collect_gpx_rejects_missing_path() -> None:
    with pytest.raises(ValueError):
        _collect_gpx(["/nonexistent/path.gpx"])


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


def test_parse_photo_timestamp_defaults_to_utc8_when_missing_offset() -> None:
    record = {
        "DateTimeOriginal": "2026:07:05 08:00:00",
    }

    parsed = parse_photo_timestamp(record, fallback_timezone=None)
    # 无 OffsetTimeOriginal 且无 --timezone 时默认按 Asia/Shanghai (UTC+8) 处理
    assert parsed.original_utc == datetime(2026, 7, 5, 0, 0, 0, tzinfo=timezone.utc)


def test_parse_photo_timestamp_falls_back_to_create_date() -> None:
    record = {
        "CreateDate": "2026:07:05 08:00:00",
    }

    parsed = parse_photo_timestamp(record, fallback_timezone=None)
    assert parsed.original_utc == datetime(2026, 7, 5, 0, 0, 0, tzinfo=timezone.utc)


def test_parse_photo_timestamp_create_date_with_offset() -> None:
    record = {
        "CreateDate": "2026:07:05 08:00:00+08:00",
    }

    parsed = parse_photo_timestamp(record, fallback_timezone=None)
    assert parsed.original_utc == datetime(2026, 7, 5, 0, 0, 0, tzinfo=timezone.utc)


def test_build_parser_supports_multiple_gpx_args() -> None:
    parser = build_parser()
    args = parser.parse_args(["--photos", "a.NEF", "--gpx", "b.gpx", "c.gpx"])
    assert args.gpx == ["b.gpx", "c.gpx"]


def test_build_parser_supports_recursive_flags() -> None:
    parser = build_parser()
    args = parser.parse_args(["--photos", "a.NEF", "--gpx", "b.gpx", "-rp", "-rg"])
    assert args.recursive_photos is True
    assert args.recursive_gpx is True


def test_build_parser_supports_skip_existing_gps_flag() -> None:
    parser = build_parser()
    args = parser.parse_args(["--photos", "a.NEF", "--gpx", "b.gpx", "--skip-existing-gps"])
    assert args.skip_existing_gps is True


def test_build_parser_supports_manual_coords() -> None:
    parser = build_parser()
    args = parser.parse_args(["--photos", "a.NEF", "--lat", "30.5", "--lon", "120.8", "--ele", "100"])
    assert args.lat == 30.5
    assert args.lon == 120.8
    assert args.ele == 100.0


def test_build_parser_manual_coords_without_ele() -> None:
    parser = build_parser()
    args = parser.parse_args(["--photos", "a.NEF", "--lat", "30.5", "--lon", "120.8"])
    assert args.lat == 30.5
    assert args.lon == 120.8
    assert args.ele is None