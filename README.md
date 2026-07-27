# gpx2raw

将照片拍摄时间与 GPX 轨迹时间对齐，匹配坐标并写入照片 GPS 元数据。

当前支持媒体格式：
- NEF
- JPG/JPEG
- MOV

## 特性

- `--photos` 同时支持目录和单文件。
- `--gpx` 通过 GPX 时间点匹配照片时间。支持传入多个文件或目录。与 `--lat/--lon` 互斥。
- `--lat/--lon` 手动指定坐标，直接写入所有照片。与 `--gpx` 互斥。
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

多 GPX 文件或目录:

```bash
uv run gpx2raw --photos ./photos --gpx ./track1.gpx ./track2.gpx
uv run gpx2raw --photos ./photos --gpx ./gpx_folder/
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

递归搜索子目录:

```bash
uv run gpx2raw --photos ./photos -rp --gpx ./gpx_folder -rg
```

手动指定坐标写入（无需 GPX）:

```bash
uv run gpx2raw --photos ./photos --lat 30.5 --lon 120.8 --ele 100 -w
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

- `--photos` 必填。目录或单个媒体文件（.NEF/.JPG/.JPEG/.MOV）。
- `--gpx` 可选（与 --lat/--lon 互斥）。GPX 文件或目录，可传入多个。
- `--lat` 可选。手动指定纬度（需同时指定 --lon）。
- `--lon` 可选。手动指定经度（需同时指定 --lat）。
- `--ele` 可选。手动指定海拔，配合 --lat/--lon 使用。
- `--max-delta-sec` 可选。最大允许时间差，默认 300。
- `--clock-offset-sec` 可选。对照片时间加减秒数，默认 0。
- `--timezone` 可选。照片缺失 `OffsetTimeOriginal` 时使用。
- `-w, --write` 可选。实际写入；未指定时仅预览。
- `-N, --no-backup` 可选。写入时不保留 exiftool 备份。
- `--skip-existing-gps` 可选。照片已有 GPS 信息时直接跳过。
- `-rp, --recursive-photos` 可选。递归搜索照片子目录。
- `-rg, --recursive-gpx` 可选。递归搜索 GPX 子目录。