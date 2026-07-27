from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

from .core import TrackPoint, find_match, load_gpx_points
from .exiftool_io import ExifToolError, ensure_exiftool_installed, read_photo_metadata, write_gps_metadata


PHOTO_EXTENSIONS = {".nef", ".jpg", ".jpeg", ".mov"}
GPX_EXTENSIONS = {".gpx"}


def _collect_gpx(gpx_args: list[str], recursive: bool = False) -> list[Path]:
    paths: list[Path] = []
    for raw in gpx_args:
        p = Path(raw).expanduser().resolve()
        if p.is_file():
            if p.suffix.lower() in GPX_EXTENSIONS:
                paths.append(p)
        elif p.is_dir():
            iterator = p.rglob("*") if recursive else p.glob("*")
            for item in sorted(iterator):
                if item.is_file() and item.suffix.lower() in GPX_EXTENSIONS:
                    paths.append(item)
        else:
            raise ValueError(f"--gpx 路径不存在: {raw}")

    if not paths:
        raise ValueError("未发现 .gpx 文件。")
    return paths


DISPLAY_TZ = ZoneInfo("Asia/Shanghai")


def _fmt_time(utc_dt: datetime) -> str:
    return utc_dt.astimezone(DISPLAY_TZ).isoformat()


@dataclass(frozen=True)
class RunStats:
    total: int = 0
    written: int = 0
    skipped: int = 0
    failed: int = 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gpx2raw",
        description="按拍摄时间将 GPX 坐标匹配并写入 NEF/JPG/MOV GPS 元数据。",
    )
    parser.add_argument(
        "--photos",
        required=True,
        help="照片输入路径，支持目录或单个 .NEF/.JPG/.JPEG/.MOV 文件。",
    )
    parser.add_argument("--gpx", nargs="+", help="GPX 轨迹文件或目录，可传入多个。与 --lat/--lon 互斥。")
    parser.add_argument("--lat", type=float, help="手动指定纬度（需同时指定 --lon）。")
    parser.add_argument("--lon", type=float, help="手动指定经度（需同时指定 --lat）。")
    parser.add_argument("--ele", type=float, default=None, help="手动指定海拔（可选，配合 --lat/--lon 使用）。")
    parser.add_argument("--max-delta-sec", type=float, default=300.0, help="最大允许匹配时间差（秒），默认 300。")
    parser.add_argument("--clock-offset-sec", type=float, default=0.0, help="对照片时间应用的全局偏移（秒）。")
    parser.add_argument("--timezone", help="当照片缺少 OffsetTimeOriginal 时使用的时区，如 Asia/Shanghai。")
    parser.add_argument("-w", "--write", action="store_true", help="执行写入。未指定时仅 dry-run 预览。")
    parser.add_argument("-N", "--no-backup", action="store_true", help="写入时不保留 exiftool 备份文件。")
    parser.add_argument("--skip-existing-gps", action="store_true", help="如果照片已包含 GPS 信息则跳过。")
    parser.add_argument("-rp", "--recursive-photos", action="store_true", help="递归搜索照片子目录。")
    parser.add_argument("-rg", "--recursive-gpx", action="store_true", help="递归搜索 GPX 子目录。")
    return parser


def _collect_photos(photos_path: Path, recursive: bool = False) -> list[Path]:
    if photos_path.is_file():
        if photos_path.suffix.lower() not in PHOTO_EXTENSIONS:
            raise ValueError("--photos 为单文件时必须是 .NEF/.JPG/.JPEG/.MOV 文件。")
        return [photos_path]

    if photos_path.is_dir():
        iterator = photos_path.rglob("*") if recursive else photos_path.glob("*")
        files = sorted(
            item
            for item in iterator
            if item.is_file() and item.suffix.lower() in PHOTO_EXTENSIONS
        )
        return files

    raise ValueError("--photos 路径不存在，或既不是文件也不是目录。")


def _print_row(columns: Iterable[str]) -> None:
    print(" | ".join(columns))


def _run(args: argparse.Namespace) -> int:
    photos_path = Path(args.photos).expanduser().resolve()

    # Validate: either --gpx or (--lat + --lon)
    manual_mode = args.lat is not None or args.lon is not None
    gpx_mode = args.gpx is not None

    if manual_mode and gpx_mode:
        raise ValueError("--gpx 与 --lat/--lon 不能同时使用。")
    if not manual_mode and not gpx_mode:
        raise ValueError("请指定 --gpx 或 --lat/--lon。")
    if manual_mode and (args.lat is None or args.lon is None):
        raise ValueError("--lat 和 --lon 必须同时指定。")

    photos = _collect_photos(photos_path, recursive=args.recursive_photos)
    if not photos:
        raise ValueError("未发现 .NEF/.JPG/.JPEG/.MOV 文件。")

    ensure_exiftool_installed()

    all_track_points: list[TrackPoint] = []
    if gpx_mode:
        gpx_files = _collect_gpx(args.gpx, recursive=args.recursive_gpx)
        for gpx_path in gpx_files:
            all_track_points.extend(load_gpx_points(gpx_path))
        all_track_points.sort(key=lambda item: item.time_utc)
        if not all_track_points:
            raise ValueError("GPX 中没有可用的带时间轨迹点。")

    offset = timedelta(seconds=args.clock_offset_sec)
    stats = RunStats(total=len(photos))
    action = "WRITE" if args.write else "DRYRUN"
    _print_row(["file", "photo_time", "delta_sec", "source", "lat", "lon", "action"])

    manual_lat: float | None = args.lat
    manual_lon: float | None = args.lon
    manual_ele: float | None = args.ele

    for photo in photos:
        try:
            photo_metadata = read_photo_metadata(photo, args.timezone)
            photo_time = photo_metadata.original_utc + offset

            if args.skip_existing_gps and photo_metadata.has_existing_gps:
                stats = RunStats(
                    total=stats.total,
                    written=stats.written,
                    skipped=stats.skipped + 1,
                    failed=stats.failed,
                )
                _print_row([photo.name, _fmt_time(photo_time), "-", "existing-gps", "-", "-", "SKIP"])
                continue

            if manual_mode:
                matched_lat = manual_lat
                matched_lon = manual_lon
                matched_ele = manual_ele
                source = "manual"
                delta = "-"
            else:
                matched = find_match(photo_time, all_track_points, args.max_delta_sec)
                if matched is None:
                    stats = RunStats(
                        total=stats.total,
                        written=stats.written,
                        skipped=stats.skipped + 1,
                        failed=stats.failed,
                    )
                    _print_row([photo.name, _fmt_time(photo_time), "-", "skip", "-", "-", "SKIP"])
                    continue
                matched_lat = matched.latitude
                matched_lon = matched.longitude
                matched_ele = matched.elevation
                source = matched.source
                delta = f"{matched.nearest_delta_seconds:.3f}"

            if args.write:
                write_gps_metadata(
                    photo,
                    matched_lat,
                    matched_lon,
                    matched_ele,
                    photo_time,
                    keep_backup=not args.no_backup,
                )
                stats = RunStats(
                    total=stats.total,
                    written=stats.written + 1,
                    skipped=stats.skipped,
                    failed=stats.failed,
                )
            else:
                stats = RunStats(
                    total=stats.total,
                    written=stats.written,
                    skipped=stats.skipped,
                    failed=stats.failed,
                )

            _print_row(
                [
                    photo.name,
                    _fmt_time(photo_time),
                    delta,
                    source,
                    f"{matched_lat:.7f}",
                    f"{matched_lon:.7f}",
                    action,
                ]
            )
        except Exception as exc:  # noqa: BLE001
            stats = RunStats(
                total=stats.total,
                written=stats.written,
                skipped=stats.skipped,
                failed=stats.failed + 1,
            )
            _print_row([photo.name, "-", "-", "error", "-", "-", str(exc)])

    print(
        f"summary: total={stats.total} written={stats.written} skipped={stats.skipped} failed={stats.failed} mode={action}"
    )
    return 0 if stats.failed == 0 else 1


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return _run(args)
    except (ValueError, ExifToolError) as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())