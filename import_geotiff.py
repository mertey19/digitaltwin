#!/usr/bin/env python3
"""
import_geotiff.py — WebODM/ODM GeoTIFF çıktılarını data_real/ formatına dönüştürür.

Girdi:
    orthophoto.tif  (RGB veya RGBA orthomosaic)
    dsm.tif         (DSM, metre cinsinden)

Çıktı (data_real/):
    orthomosaic.jpg, heightmap.png, normalmap.png, buildings.json, site_meta.json

Bağımlılık: rasterio (tercih) veya Pillow + numpy fallback (sınırlı georef).

Usage:
    python import_geotiff.py --ortho orthophoto.tif --dsm dsm.tif
    python import_geotiff.py --ortho ortho.tif --dsm dsm.tif --out data_real --gsd 0.1
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import numpy as np
from PIL import Image, ImageFilter

import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DEFAULT = os.path.join(HERE, "data_real")


def _try_rasterio_read(path: str) -> tuple[np.ndarray, dict | None]:
    try:
        import rasterio
        from rasterio.enums import Resampling
    except ImportError:
        return None, None

    with rasterio.open(path) as src:
        if src.count >= 3:
            data = src.read([1, 2, 3], out_shape=(
                3, min(src.height, 8192), min(src.width, 8192)
            ), resampling=Resampling.bilinear)
            arr = np.transpose(data, (1, 2, 0))
        else:
            band = src.read(1, out_shape=(
                min(src.height, 8192), min(src.width, 8192)
            ), resampling=Resampling.bilinear)
            arr = np.stack([band, band, band], axis=-1)

        transform = src.transform
        crs = str(src.crs) if src.crs else None
        meta = {
            "width_px": arr.shape[1],
            "height_px": arr.shape[0],
            "transform": list(transform)[:6] if transform else None,
            "crs": crs,
            "bounds": list(src.bounds) if src.bounds else None,
        }
        if arr.dtype != np.uint8:
            lo, hi = np.percentile(arr, [1, 99])
            arr = np.clip((arr - lo) / max(1e-6, hi - lo) * 255, 0, 255).astype(np.uint8)
        return arr, meta


def _pil_read_rgb(path: str) -> tuple[np.ndarray, dict | None]:
    img = Image.open(path)
    if hasattr(img, "n_frames") and img.n_frames > 1:
        img.seek(0)
    rgb = np.asarray(img.convert("RGB"))
    meta = {"width_px": rgb.shape[1], "height_px": rgb.shape[0], "crs": None, "bounds": None}
    return rgb, meta


def read_ortho(path: str) -> tuple[np.ndarray, dict | None]:
    arr, meta = _try_rasterio_read(path)
    if arr is not None:
        print(f"  Ortho: rasterio ({arr.shape[1]}x{arr.shape[0]})")
        return arr, meta
    print("  Ortho: Pillow fallback (georef sınırlı)")
    return _pil_read_rgb(path)


def read_dsm(path: str) -> tuple[np.ndarray, dict | None]:
    try:
        import rasterio
        from rasterio.enums import Resampling
        with rasterio.open(path) as src:
            dsm = src.read(1, out_shape=(
                min(src.height, 8192), min(src.width, 8192)
            ), resampling=Resampling.bilinear).astype(np.float64)
            nodata = src.nodata
            if nodata is not None:
                dsm[dsm == nodata] = np.nan
            meta = {"crs": str(src.crs) if src.crs else None,
                    "bounds": list(src.bounds) if src.bounds else None}
            return dsm, meta
    except ImportError:
        pass

    img = Image.open(path).convert("L")
    dsm = np.asarray(img).astype(np.float64)
    print("  DSM: Pillow fallback — değerler 0..255 olarak yorumlanır (metre değil!)")
    return dsm, None


def build_normalmap(elev_m: np.ndarray, cell_size_m: float, strength: float = 1.0) -> np.ndarray:
    gy, gx = np.gradient(elev_m * strength, cell_size_m)
    nx, ny = -gx, -gy
    nz = np.ones_like(elev_m)
    length = np.sqrt(nx * nx + ny * ny + nz * nz)
    nx, ny, nz = nx / length, ny / length, nz / length
    rgb = np.stack([nx * 0.5 + 0.5, ny * 0.5 + 0.5, nz * 0.5 + 0.5], axis=-1)
    return (np.clip(rgb, 0, 1) * 255).astype(np.uint8)


def resize_dsm_to_ortho(dsm: np.ndarray, ow: int, oh: int) -> np.ndarray:
    dsm_img = Image.fromarray(np.nan_to_num(dsm, nan=0.0).astype(np.float32), mode="F")
    dsm_img = dsm_img.resize((ow, oh), Image.BILINEAR)
    return np.asarray(dsm_img)


def extract_buildings_simple(ortho_rgb: np.ndarray, max_buildings: int = 60) -> list[dict]:
    """Minimal building extraction for GeoTIFF imports."""
    from ingest_real_dataset import extract_buildings
    return extract_buildings(ortho_rgb, scene=None, mosaic_meta={"method": "exif_gps"})


def enrich_buildings(buildings: list[dict]) -> list[dict]:
    import random
    rng = random.Random(42)
    types = ["konut", "ofis", "depo", "sosyal", "teknik"]
    out = []
    for i, b in enumerate(buildings):
        out.append({
            **b,
            "id": f"B-{i + 1:03d}",
            "type": types[i % len(types)],
            "capacity": int(20 + b.get("height_m", 5) * 8 + rng.randint(0, 40)),
            "last_maintenance": f"2025-{rng.randint(1,12):02d}-{rng.randint(1,28):02d}",
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="GeoTIFF ortho+DSM → data_real/")
    ap.add_argument("--ortho", required=True, help="Orthophoto GeoTIFF yolu")
    ap.add_argument("--dsm", default=None, help="DSM GeoTIFF yolu (opsiyonel; yoksa duz)")
    ap.add_argument("--out", default=OUT_DEFAULT, help="Çıktı klasörü")
    ap.add_argument("--gsd", type=float, default=None,
                    help="m/piksel (bilinmiyorsa piksel boyutundan tahmin)")
    ap.add_argument("--origin-lat", type=float, default=41.0082)
    ap.add_argument("--origin-lon", type=float, default=28.9784)
    ap.add_argument("--height-res", type=int, default=1024)
    args = ap.parse_args()

    if not os.path.isfile(args.ortho):
        print(f"HATA: Ortho bulunamadı: {args.ortho}", file=sys.stderr)
        return 1
    if args.dsm and not os.path.isfile(args.dsm):
        print(f"HATA: DSM bulunamadı: {args.dsm}", file=sys.stderr)
        return 1

    os.makedirs(args.out, exist_ok=True)

    print("[1/5] Orthophoto okunuyor…")
    ortho_rgb, ortho_meta = read_ortho(args.ortho)
    ow, oh = ortho_rgb.shape[1], ortho_rgb.shape[0]

    print("[2/5] DSM okunuyor…")
    if args.dsm:
        dsm, dsm_meta = read_dsm(args.dsm)
        dsm = resize_dsm_to_ortho(dsm, ow, oh)
    else:
        print("  DSM yok -> duz yukseklik (3B icerik bina+agac nesnelerinden).")
        dsm = np.zeros((oh, ow), dtype=np.float64)
        dsm_meta = None

    valid = dsm[np.isfinite(dsm)]
    if valid.size == 0:
        print("HATA: DSM boş", file=sys.stderr)
        return 1

    min_e = float(np.nanpercentile(valid, 1))
    max_e = float(np.nanpercentile(valid, 99))
    if max_e <= min_e:
        max_e = min_e + 1.0

    # GSD from georef bounds if available
    gsd = args.gsd
    if gsd is None and ortho_meta and ortho_meta.get("bounds"):
        b = ortho_meta["bounds"]
        width_m_geo = abs(b[2] - b[0])
        height_m_geo = abs(b[3] - b[1])
        if width_m_geo > 0 and height_m_geo > 0:
            width_m = width_m_geo
            height_m = height_m_geo
            gsd = width_m / ow
        else:
            gsd = 0.15
            width_m = ow * gsd
            height_m = oh * gsd
    else:
        gsd = gsd or 0.15
        width_m = ow * gsd
        height_m = oh * gsd

    print(f"  Saha: {width_m:.1f}×{height_m:.1f} m, elev {min_e:.1f}..{max_e:.1f} m, GSD {gsd:.4f}")

    print("[3/5] Heightmap + normal map…")
    hw = args.height_res
    hh = max(2, int(round(hw * oh / ow)))
    dsm_img = Image.fromarray(dsm.astype(np.float32), mode="F")
    dsm_img = dsm_img.resize((hw, hh), Image.BILINEAR)
    dsm_r = np.asarray(dsm_img)
    h_norm = np.clip((dsm_r - min_e) / max(1e-6, max_e - min_e), 0, 1)
    h16 = (h_norm * 65535).astype(np.uint16)
    Image.fromarray(h16, mode="I;16").save(os.path.join(args.out, "heightmap.png"))

    cell_size_m = width_m / hw
    elev_m = min_e + h_norm * (max_e - min_e)
    nmap = build_normalmap(elev_m, cell_size_m)
    Image.fromarray(nmap, mode="RGB").save(os.path.join(args.out, "normalmap.png"))

    print("[4/5] Orthomosaic JPG…")
    Image.fromarray(ortho_rgb, mode="RGB").save(
        os.path.join(args.out, "orthomosaic.jpg"), quality=92
    )

    print("[5/5] Binalar + site_meta…")
    buildings = extract_buildings_simple(ortho_rgb)
    buildings = enrich_buildings(buildings)
    with open(os.path.join(args.out, "buildings.json"), "w", encoding="utf-8") as f:
        json.dump({"count": len(buildings), "buildings": buildings}, f, indent=2)

    from ingest_real_dataset import extract_trees
    trees = extract_trees(ortho_rgb, scene=None, mosaic_meta={"method": "exif_gps"})
    with open(os.path.join(args.out, "trees.json"), "w", encoding="utf-8") as f:
        json.dump({"count": len(trees), "trees": trees}, f, indent=2)
    print(f"  {len(trees)} agac")

    meta = {
        "site_name": "GeoTIFF Sahası (WebODM/ODM)",
        "twin_version": "2.0.0",
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "asset_summary": {
            "building_count": len(buildings),
            "has_water": False,
            "dataset_type": "geotiff",
            "elevation_range_m": round(max_e - min_e, 3),
            "site_area_m2": round(width_m * height_m, 1),
        },
        "description": "Imported from GeoTIFF via import_geotiff.py",
        "synthetic": False,
        "source": {
            "orthomosaic_tif": os.path.basename(args.ortho),
            "dsm_tif": os.path.basename(args.dsm) if args.dsm else None,
            "import_tool": "import_geotiff.py",
            "ortho_meta": ortho_meta,
            "dsm_meta": dsm_meta,
        },
        "resolution_px": ow,
        "width_m": round(width_m, 3),
        "height_m": round(height_m, 3),
        "min_elev_m": round(min_e, 3),
        "max_elev_m": round(max_e, 3),
        "ground_sample_distance_m": round(gsd, 4),
        "heightmap": "heightmap.png",
        "heightmap_bits": 16,
        "orthomosaic": "orthomosaic.jpg",
        "normalmap": "normalmap.png",
        "buildings": "buildings.json",
        "trees": "trees.json",
        "has_water": False,
        "water_level_m": 0.0,
        "georef": {
            "origin_lat": args.origin_lat,
            "origin_lon": args.origin_lon,
            "crs": (ortho_meta or {}).get("crs", "EPSG:4326 (stub)"),
            "note": "GeoTIFF import — gerçek CRS meta'dan okunur (rasterio ile).",
        },
    }
    with open(os.path.join(args.out, "site_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    print(f"\nTamam → {args.out}")
    for name in ("orthomosaic.jpg", "heightmap.png", "normalmap.png",
                 "buildings.json", "site_meta.json"):
        p = os.path.join(args.out, name)
        if os.path.exists(p):
            print(f"  {name:18s} {os.path.getsize(p)/1024:8.1f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
