from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


class ExifToolError(RuntimeError):
    pass


@dataclass(frozen=True)
class PhotoTimestamp:
    original_utc: datetime


@dataclass(frozen=True)
class PhotoMetadata:
    original_utc: datetime
    has_existing_gps: bool


def ensure_exiftool_installed() -> None:
    if shutil.which("exiftool"):
        return
    raise ExifToolError(
        "exiftool 未安装。请先安装 exiftool（macOS 可执行: brew install exiftool），然后重试。"
    )


def _run_exiftool(args: list[str]) -> str:
    command = ["exiftool", *args]
    proc = subprocess.run(command, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        raise ExifToolError(stderr or f"exiftool 执行失败: {' '.join(command)}")
    return proc.stdout


def _offset_to_tz(offset_text: str) -> timezone:
    sign = 1 if offset_text[0] == "+" else -1
    hours = int(offset_text[1:3])
    minutes = int(offset_text[4:6])
    seconds = sign * (hours * 3600 + minutes * 60)
    return timezone(timedelta(seconds=seconds))


def _subsec_to_microsecond(value: Any) -> int | None:
    if value is None:
        return None

    if isinstance(value, int):
        digits = str(abs(value))
    elif isinstance(value, str):
        digits = "".join(ch for ch in value if ch.isdigit())
    else:
        return None

    if not digits:
        return None
    return int(digits[:6].ljust(6, "0"))


def _has_existing_gps(record: dict[str, Any]) -> bool:
    gps_keys = (
        "GPSLatitude",
        "GPSLongitude",
        "GPSAltitude",
        "GPSPosition",
        "GPSLatitudeRef",
        "GPSLongitudeRef",
    )
    for key in gps_keys:
        value = record.get(key)
        if value not in (None, "", [], {}):
            return True
    return False


def parse_photo_timestamp(record: dict[str, Any], fallback_timezone: str | None, photo_path: Path | None = None) -> PhotoTimestamp:
    date_str = record.get("DateTimeOriginal") or record.get("CreateDate") or record.get("MediaCreateDate")
    if not date_str:
        raise ExifToolError("缺少 DateTimeOriginal / CreateDate，无法匹配轨迹。")

    date_str = str(date_str)

    # QuickTime CreateDate may look like "2026:07:05 08:00:00+08:00"
    # Extract base datetime and optional embedded timezone offset
    tz_info: timezone | None = None
    clean = date_str.strip()

    # Try to extract embedded timezone (+HH:MM or -HH:MM) at the end
    if len(clean) > 19 and clean[19] in "+-":
        base_str = clean[:19]
        tz_part = clean[19:].replace(":", "")  # +08:00 → +0800
        # Handle sign
        sign = 1 if tz_part[0] == "+" else -1
        try:
            hours = int(tz_part[1:3])
            minutes = int(tz_part[3:5]) if len(tz_part) >= 5 else 0
            seconds = sign * (hours * 3600 + minutes * 60)
            tz_info = timezone(timedelta(seconds=seconds))
        except (ValueError, IndexError):
            pass
    else:
        base_str = clean[:19]

    base = datetime.strptime(base_str, "%Y:%m:%d %H:%M:%S")
    if tz_info is not None:
        base = base.replace(tzinfo=tz_info)

    microsecond = _subsec_to_microsecond(record.get("SubSecTimeOriginal"))
    if microsecond is not None:
        base = base.replace(microsecond=microsecond)

    # Determine timezone: embedded in date > OffsetTimeOriginal > fallback_timezone > UTC (with warning)
    offset_str = record.get("OffsetTimeOriginal")
    if base.tzinfo is not None:
        # Already had timezone from CreateDate
        aware = base
    elif offset_str and len(str(offset_str)) == 6 and str(offset_str)[0] in "+-" and str(offset_str)[3] == ":":
        aware = base.replace(tzinfo=_offset_to_tz(str(offset_str)))
    elif fallback_timezone:
        aware = base.replace(tzinfo=ZoneInfo(fallback_timezone))
    else:
        name = photo_path.name if photo_path else "未知文件"
        print(f"[WARN] {name}: 缺少 OffsetTimeOriginal，默认按 Asia/Shanghai (UTC+8) 处理。可通过 --timezone 指定时区。")
        aware = base.replace(tzinfo=ZoneInfo("Asia/Shanghai"))

    return PhotoTimestamp(original_utc=aware.astimezone(timezone.utc))


def read_photo_metadata(photo_path: Path, fallback_timezone: str | None) -> PhotoMetadata:
    stdout = _run_exiftool(
        [
            "-j",
            "-DateTimeOriginal",
            "-SubSecTimeOriginal",
            "-OffsetTimeOriginal",
            "-CreateDate",
            "-MediaCreateDate",
            "-GPSLatitude",
            "-GPSLongitude",
            "-GPSAltitude",
            "-GPSPosition",
            str(photo_path),
        ]
    )
    payload = json.loads(stdout)
    if not payload:
        raise ExifToolError(f"未读取到 EXIF 数据: {photo_path}")
    record = payload[0]
    timestamp = parse_photo_timestamp(record, fallback_timezone, photo_path=photo_path)
    return PhotoMetadata(original_utc=timestamp.original_utc, has_existing_gps=_has_existing_gps(record))


def read_photo_timestamp(photo_path: Path, fallback_timezone: str | None) -> PhotoTimestamp:
    metadata = read_photo_metadata(photo_path, fallback_timezone)
    return PhotoTimestamp(original_utc=metadata.original_utc)


def write_gps_metadata(
    photo_path: Path,
    latitude: float,
    longitude: float,
    elevation: float | None,
    gps_time_utc: datetime,
    keep_backup: bool,
) -> None:
    lat_ref = "N" if latitude >= 0 else "S"
    lon_ref = "E" if longitude >= 0 else "W"
    args = [
        "-P",
        f"-GPSLatitude={abs(latitude)}",
        f"-GPSLatitudeRef={lat_ref}",
        f"-GPSLongitude={abs(longitude)}",
        f"-GPSLongitudeRef={lon_ref}",
        f"-GPSDateStamp={gps_time_utc.strftime('%Y:%m:%d')}",
        f"-GPSTimeStamp={gps_time_utc.strftime('%H:%M:%S.%f')[:-3]}",
    ]

    if elevation is not None:
        altitude_ref = 0 if elevation >= 0 else 1
        args.extend(
            [
                f"-GPSAltitude={abs(elevation)}",
                f"-GPSAltitudeRef={altitude_ref}",
            ]
        )

    if not keep_backup:
        args.append("-overwrite_original")

    args.append(str(photo_path))
    _run_exiftool(args)