# gpx2raw

将照片拍摄时间与 GPX 轨迹时间对齐，匹配坐标并写入照片 GPS 元数据。

当前支持照片格式：
- NEF
- JPG/JPEG

## 特性

- `--photos` 同时支持目录和单文件。
- `--gpx` 必填，通过 GPX 时间点匹配照片时间。
- 默认 `dry-run`，只有加 `--write` 才会写入。
- 匹配策略为线性插值，超出最大时间差窗口会跳过。
- 可选跳过已存在 GPS 信息的照片。

## 依赖

1. Python 3.10+
2. uv
2. exiftool（读写照片 EXIF/GPS）

macOS 安装 uv:

```bash
brew install uv
```

macOS 安装 exiftool:

```bash
brew install exiftool
```

同步项目依赖:

```bash
uv sync --dev
```

## 用法

目录输入（默认 dry-run）:

```bash
uv run gpx2raw --photos ./testdata --gpx ./track.gpx
```

单文件输入并实际写入:

```bash
uv run gpx2raw --photos ./testdata/_DSC1657.NEF --gpx ./track.gpx --write
```

使用短参数写入且不保留备份:

```bash
uv run gpx2raw --photos ./testdata --gpx ./track.gpx -w -N
```

跳过已经写有 GPS 的照片:

```bash
uv run gpx2raw --photos ./photos --gpx ./track.gpx --skip-existing-gps
```

指定时间偏移与匹配窗口:

```bash
uv run gpx2raw \
  --photos ./photos \
  --gpx ./track.gpx \
  --clock-offset-sec 12 \
  --max-delta-sec 300 \
  --timezone Asia/Shanghai
```

## 参数

- `--photos` 必填。目录或单个照片文件（.NEF/.JPG/.JPEG）。
- `--gpx` 必填。GPX 文件路径。
- `--max-delta-sec` 可选。最大允许时间差，默认 300。
- `--clock-offset-sec` 可选。对照片时间加减秒数，默认 0。
- `--timezone` 可选。照片缺失 `OffsetTimeOriginal` 时使用。
- `-w, --write` 可选。实际写入；未指定时仅预览。
- `-N, --no-backup` 可选。写入时不保留 exiftool 备份。
- `--skip-existing-gps` 可选。照片已有 GPS 信息时直接跳过。