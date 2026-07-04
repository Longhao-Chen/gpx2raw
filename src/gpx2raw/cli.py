from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Iterable

from .core import find_match, load_gpx_points
from .exiftool_io import ExifToolError, ensure_exiftool_installed, read_photo_metadata, write_gps_metadata


PHOTO_EXTENSIONS = {".nef", ".jpg", ".jpeg"}


@dataclass(frozen=True)
class RunStats:
    total: int = 0
    written: int = 0
    skipped: int = 0
    failed: int = 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gpx2raw",
        description="按拍摄时间将 GPX 坐标匹配并写入 NEF/JPG GPS 元数据。",
    )
    parser.add_argument(
        "--photos",
        required=True,
        help="照片输入路径，支持目录或单个 .NEF/.JPG/.JPEG 文件。",
    )
    parser.add_argument("--gpx", required=True, help="GPX 轨迹文件路径。")
    parser.add_argument("--max-delta-sec", type=float, default=300.0, help="最大允许匹配时间差（秒），默认 300。")
    parser.add_argument("--clock-offset-sec", type=float, default=0.0, help="对照片时间应用的全局偏移（秒）。")
    parser.add_argument("--timezone", help="当照片缺少 OffsetTimeOriginal 时使用的时区，如 Asia/Shanghai。")
    parser.add_argument("-w", "--write", action="store_true", help="执行写入。未指定时仅 dry-run 预览。")
    parser.add_argument("-N", "--no-backup", action="store_true", help="写入时不保留 exiftool 备份文件。")
    parser.add_argument("--skip-existing-gps", action="store_true", help="如果照片已包含 GPS 信息则跳过。")
    return parser


def _collect_photos(photos_path: Path) -> list[Path]:
    if photos_path.is_file():
        if photos_path.suffix.lower() not in PHOTO_EXTENSIONS:
            raise ValueError("--photos 为单文件时必须是 .NEF/.JPG/.JPEG 文件。")
        return [photos_path]

    if photos_path.is_dir():
        files = sorted(
            item
            for item in photos_path.rglob("*")
            if item.is_file() and item.suffix.lower() in PHOTO_EXTENSIONS
        )
        return files

    raise ValueError("--photos 路径不存在，或既不是文件也不是目录。")


def _print_row(columns: Iterable[str]) -> None:
    print(" | ".join(columns))


def _run(args: argparse.Namespace) -> int:
    photos_path = Path(args.photos).expanduser().resolve()
    gpx_path = Path(args.gpx).expanduser().resolve()
    if not gpx_path.is_file():
        raise ValueError("--gpx 路径不存在或不是文件。")

    photos = _collect_photos(photos_path)
    if not photos:
        raise ValueError("未发现 .NEF/.JPG/.JPEG 文件。")

    ensure_exiftool_installed()
    track_points = load_gpx_points(gpx_path)
    if not track_points:
        raise ValueError("GPX 中没有可用的带时间轨迹点。")

    offset = timedelta(seconds=args.clock_offset_sec)
    stats = RunStats(total=len(photos))
    action = "WRITE" if args.write else "DRYRUN"
    _print_row(["file", "photo_utc", "delta_sec", "source", "lat", "lon", "action"])

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
                _print_row([photo.name, photo_time.isoformat(), "-", "existing-gps", "-", "-", "SKIP"])
                continue

            matched = find_match(photo_time, track_points, args.max_delta_sec)
            if matched is None:
                stats = RunStats(
                    total=stats.total,
                    written=stats.written,
                    skipped=stats.skipped + 1,
                    failed=stats.failed,
                )
                _print_row([photo.name, photo_time.isoformat(), "-", "skip", "-", "-", "SKIP"])
                continue

            if args.write:
                write_gps_metadata(
                    photo,
                    matched.latitude,
                    matched.longitude,
                    matched.elevation,
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
                    photo_time.isoformat(),
                    f"{matched.nearest_delta_seconds:.3f}",
                    matched.source,
                    f"{matched.latitude:.7f}",
                    f"{matched.longitude:.7f}",
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