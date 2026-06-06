#!/usr/bin/env python3
"""
ingest_real_dataset.py
======================

Takes the user's REAL drone-pipeline assets and turns them into the inputs the
modern Three.js viewer (``viewer.html``) expects. Writes into a clearly
separated folder ``data_real/`` so the existing synthetic ``data/`` is never
touched.

Real inputs (next to this script):
    mosaic.jpg          orthomosaic (from stitch_mosaic.py or legacy montage)
    heightmap.jpg       approx. heightmap aligned to mosaic
    mosaic_meta.json    optional — fast stitch transforms (from stitch_mosaic.py)
    ground_texture.jpg  optional ground texture (not strictly required)
    scene_data.json     18-frame analysis (brightness, concrete_ratio, ...)

Recommended pipeline:
    python stitch_mosaic.py          # fast stitch -> mosaic.jpg + mosaic_meta.json
    python ingest_real_dataset.py

Outputs (written to ./data_real):
    orthomosaic.jpg     RGB albedo for the terrain (from mosaic.jpg)
    heightmap.png       16-bit grayscale DSM, denoised + aligned to ortho aspect
    normalmap.png       tangent-space normal map derived from the heightmap
    buildings.json      extracted 3D building footprints (UV + height in metres)
    site_meta.json      SINGLE SOURCE OF TRUTH: real-world bounds, water, georef

IMPORTANT — scale assumption
----------------------------
The real heightmap is an 8-bit JPEG with NO absolute scale, and the mosaic is a
montage (not a georeferenced orthophoto), so true ground extent is unknown. We
therefore assume a plausible drone GSD (ground sample distance) and derive the
site width/height from the mosaic pixel size, plus a plausible elevation range.
All of these are CLI-configurable and recorded in site_meta.json so the viewer
reads scale from a single place. Adjust --gsd / --max-elev if you learn the
true values.

Only numpy + Pillow are required. Paths are relative to this file (portable).

Usage:
    python ingest_real_dataset.py
    python ingest_real_dataset.py --stitch --gsd 0.12 --max-elev 18 --min-elev 0
    python ingest_real_dataset.py --gsd 0.12 --max-elev 18 --min-elev 0
"""

import argparse
import json
import os
from collections import deque

import numpy as np
from PIL import Image, ImageFilter

import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "data_real")

SRC_ORTHO = os.path.join(HERE, "mosaic.jpg")
SRC_HEIGHT = os.path.join(HERE, "heightmap.jpg")
SRC_GROUND = os.path.join(HERE, "ground_texture.jpg")
SRC_SCENE = os.path.join(HERE, "scene_data.json")
SRC_MOSAIC_META = os.path.join(HERE, "mosaic_meta.json")
DEFAULT_IMAGES_DIR = os.path.join(HERE, "images")


# --------------------------------------------------------------------------- #
# Small numpy helpers                                                         #
# --------------------------------------------------------------------------- #
def rgb_to_hsv(rgb):
    """rgb float array (...,3) in 0..1 -> (h,s,v) each (...,) in 0..1."""
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx = np.max(rgb, axis=-1)
    mn = np.min(rgb, axis=-1)
    diff = mx - mn
    v = mx
    s = np.where(mx > 1e-6, diff / np.maximum(mx, 1e-6), 0.0)
    h = np.zeros_like(mx)
    mask = diff > 1e-6
    # hue per dominant channel
    rm = mask & (mx == r)
    gm = mask & (mx == g)
    bm = mask & (mx == b)
    h[rm] = ((g[rm] - b[rm]) / diff[rm]) % 6.0
    h[gm] = ((b[gm] - r[gm]) / diff[gm]) + 2.0
    h[bm] = ((r[bm] - g[bm]) / diff[bm]) + 4.0
    h = (h / 6.0) % 1.0
    return h, s, v


def label_components(mask):
    """4-connectivity connected-component labelling (numpy + BFS, no scipy)."""
    h, w = mask.shape
    labels = np.zeros((h, w), dtype=np.int32)
    cur = 0
    for sy in range(h):
        for sx in range(w):
            if not mask[sy, sx] or labels[sy, sx]:
                continue
            cur += 1
            q = deque([(sy, sx)])
            labels[sy, sx] = cur
            while q:
                y, x = q.popleft()
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not labels[ny, nx]:
                        labels[ny, nx] = cur
                        q.append((ny, nx))
    return labels, cur


MONTAGE_COLS = 6
MONTAGE_ROWS = 3


def load_mosaic_meta():
    if os.path.exists(SRC_MOSAIC_META):
        with open(SRC_MOSAIC_META, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


GEOMETRIC_METHODS = {
    "exif_gps", "phase_correlation", "orb_partial_affine", "ransac_orb_homography",
}


def is_geometric_mosaic(mosaic_meta):
    return bool(mosaic_meta and mosaic_meta.get("method") in GEOMETRIC_METHODS)


is_ransac_mosaic = is_geometric_mosaic  # backward compat alias


def run_stitch_if_requested(args):
    images_dir = os.path.abspath(args.images)
    should_stitch = args.stitch or (
        os.path.isdir(images_dir) and list_images_in_dir(images_dir)
    )
    if not should_stitch:
        return load_mosaic_meta()

    from stitch_mosaic import stitch_folder

    if not os.path.isdir(images_dir):
        raise SystemExit(
            f"--stitch: resim klasoru bulunamadi: {images_dir}\n"
            f"DJI karelerini '{DEFAULT_IMAGES_DIR}' icine koyun."
        )
    print("[0/6] Hizli mozaik birlestirme (stitch_mosaic.py)...")
    stitch_folder(
        images_dir, HERE,
        max_dim=args.stitch_max_dim,
        output_scale=args.stitch_output_scale,
        nfeatures=args.stitch_nfeatures,
        ransac_thresh=args.stitch_ransac,
        method=args.stitch_method,
    )
    return load_mosaic_meta()


def list_images_in_dir(images_dir: str) -> list[str]:
    exts = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff",
            ".JPG", ".JPEG", ".PNG"}
    return sorted(f for f in os.listdir(images_dir)
                  if os.path.splitext(f)[1] in exts)


def build_seam_weight_mask(h, w, cols=MONTAGE_COLS, rows=MONTAGE_ROWS,
                           feather_frac=0.045):
    """Soft 0..1 mask — peaks at internal montage seam lines (6×3 grid)."""
    tw, th = w / cols, h / rows
    fw = max(5, int(tw * feather_frac))
    fh = max(5, int(th * feather_frac))
    seam = np.zeros((h, w), dtype=np.float32)
    for c in range(1, cols):
        cx = int(round(c * tw))
        seam[:, max(0, cx - fw):min(w, cx + fw)] = 1.0
    for r in range(1, rows):
        cy = int(round(r * th))
        seam[max(0, cy - fh):min(h, cy + fh), :] = 1.0
    # soften band edges so blending is gradual
    sm = np.asarray(
        Image.fromarray((seam * 255).astype(np.uint8)).filter(
            ImageFilter.GaussianBlur(radius=max(2, (fw + fh) // 5))
        ), dtype=np.float32) / 255.0
    return np.clip(sm, 0.0, 1.0)


def soften_montage_seams(arr, seam_w, blur_radius=3.5):
    """Blend original with a blurred copy near montage seams to hide tile jumps."""
    if arr.ndim == 2:
        src = arr.astype(np.float32)
        blurred = np.asarray(
            Image.fromarray(np.clip(src, 0, 255).astype(np.uint8)).filter(
                ImageFilter.GaussianBlur(radius=blur_radius)
            ), dtype=np.float32
        )
        return src * (1.0 - seam_w) + blurred * seam_w
    out = arr.astype(np.float32).copy()
    for ch in range(arr.shape[2]):
        ch_blur = np.asarray(
            Image.fromarray(np.clip(arr[..., ch], 0, 255).astype(np.uint8)).filter(
                ImageFilter.GaussianBlur(radius=blur_radius)
            ), dtype=np.float32
        )
        out[..., ch] = out[..., ch] * (1.0 - seam_w) + ch_blur * seam_w
    return out


def crossfade_montage_tiles(arr, cols=MONTAGE_COLS, rows=MONTAGE_ROWS,
                            feather_frac=0.035):
    """Feather-blend overlapping strips at tile boundaries (ortho colour seams)."""
    h, w = arr.shape[:2]
    tw, th = int(w // cols), int(h // rows)
    fw = max(4, int(tw * feather_frac))
    fh = max(4, int(th * feather_frac))
    out = arr.astype(np.float32).copy()
    chs = 1 if arr.ndim == 2 else arr.shape[2]

    def blend_strip(axis, seam_idx, band):
        """axis 0 = horizontal seam (blend rows), 1 = vertical seam (blend cols)."""
        if axis == 1:
            x0 = max(0, seam_idx - band)
            x1 = min(w, seam_idx + band)
            for x in range(x0, x1):
                t = abs(x - seam_idx) / max(1, band)
                wgt = 0.5 * (1.0 - t)  # strongest at seam centre
                xl = max(0, x - band)
                xr = min(w, x + band)
                if arr.ndim == 2:
                    left = out[:, xl:x].mean(axis=1)
                    right = out[:, x:xr].mean(axis=1)
                    blended = (1 - wgt) * out[:, x] + wgt * 0.5 * (left + right)
                    out[:, x] = blended
                else:
                    left = out[:, xl:x, :].mean(axis=1)
                    right = out[:, x:xr, :].mean(axis=1)
                    blended = (1 - wgt) * out[:, x, :] + wgt * 0.5 * (left + right)
                    out[:, x, :] = blended
        else:
            y0 = max(0, seam_idx - band)
            y1 = min(h, seam_idx + band)
            for y in range(y0, y1):
                t = abs(y - seam_idx) / max(1, band)
                wgt = 0.5 * (1.0 - t)
                yu = max(0, y - band)
                yd = min(h, y + band)
                if arr.ndim == 2:
                    up = out[yu:y, :].mean(axis=0)
                    dn = out[y:yd, :].mean(axis=0)
                    blended = (1 - wgt) * out[y, :] + wgt * 0.5 * (up + dn)
                    out[y, :] = blended
                else:
                    up = out[yu:y, :, :].mean(axis=0)
                    dn = out[y:yd, :, :].mean(axis=0)
                    blended = (1 - wgt) * out[y, :, :] + wgt * 0.5 * (up + dn)
                    out[y, :, :] = blended

    for c in range(1, cols):
        blend_strip(1, c * tw, fw)
    for r in range(1, rows):
        blend_strip(0, r * th, fh)
    return out


def build_frame_priors(scene, mosaic_meta=None, ortho_w=1, ortho_h=1,
                       cols=MONTAGE_COLS, rows=MONTAGE_ROWS):
    """Per-frame concrete/green/edge priors mapped to ortho UV space."""
    if not scene:
        return None, None, None

    if is_geometric_mosaic(mosaic_meta):
        return _build_frame_priors_geometric(scene, mosaic_meta, ortho_w, ortho_h)

    concrete = np.full((rows, cols), 0.4, dtype=np.float32)
    green = np.full((rows, cols), 0.5, dtype=np.float32)
    edge = np.full((rows, cols), 0.3, dtype=np.float32)
    for fr in scene:
        idx = fr.get("index", 0)
        row, col = idx // cols, idx % cols
        if row < rows and col < cols:
            concrete[row, col] = float(fr.get("concrete_ratio", 0.4))
            green[row, col] = float(fr.get("green_ratio", 0.5))
            edge[row, col] = float(fr.get("edge_density", 0.3))
    return concrete, green, edge


def _build_frame_priors_geometric(scene, mosaic_meta, ortho_w, ortho_h):
    """Sample priors on a coarse UV grid using stitch bboxes."""
    grid = 12
    scene_by_file = {fr.get("file", ""): fr for fr in scene}
    images = mosaic_meta.get("images", [])
    concrete = np.full((grid, grid), 0.4, dtype=np.float32)
    green = np.full((grid, grid), 0.5, dtype=np.float32)
    edge = np.full((grid, grid), 0.3, dtype=np.float32)

    for j in range(grid):
        for i in range(grid):
            px = (i + 0.5) / grid * ortho_w
            py = (j + 0.5) / grid * ortho_h
            best = None
            best_area = None
            for im in images:
                x0, y0, x1, y1 = im.get("bbox", [0, 0, 0, 0])
                if x0 <= px <= x1 and y0 <= py <= y1:
                    area = max(1, (x1 - x0) * (y1 - y0))
                    if best is None or area < best_area:
                        best = scene_by_file.get(im.get("file", ""))
                        best_area = area
            if best:
                concrete[j, i] = float(best.get("concrete_ratio", 0.4))
                green[j, i] = float(best.get("green_ratio", 0.5))
                edge[j, i] = float(best.get("edge_density", 0.3))
    return concrete, green, edge


def lookup_frame_prior(prior_conc, prior_green, prior_edge, cu, cv,
                       mosaic_meta=None, cols=MONTAGE_COLS, rows=MONTAGE_ROWS):
    """Bilinear-ish nearest lookup for a UV cell centre."""
    gy, gx = prior_conc.shape
    fi = min(gx - 1, max(0, int(cu * gx)))
    fj = min(gy - 1, max(0, int(cv * gy)))
    if is_geometric_mosaic(mosaic_meta):
        return prior_conc[fj, fi], prior_green[fj, fi], prior_edge[fj, fi]
    fcol = min(cols - 1, max(0, int(cu * cols)))
    frow = min(rows - 1, max(0, int(cv * rows)))
    return prior_conc[frow, fcol], prior_green[frow, fcol], prior_edge[frow, fcol]


# --------------------------------------------------------------------------- #
# Building extraction                                                         #
# --------------------------------------------------------------------------- #
def extract_buildings(ortho_rgb, scene, mosaic_meta=None, grid_cols=64, min_cells=2, max_buildings=80):
    """Detect built-up / concrete regions in the ortho and turn them into
    rectangular footprints (in 0..1 UV) with a plausible height in metres.

    Uses per-frame concrete_ratio / green_ratio / edge_density priors from
    scene_data.json (6×3 montage grid) to threshold cells, and excludes
    road-like uniform grey strips (low local variance, low saturation).
    """
    H, W, _ = ortho_rgb.shape
    rgb = ortho_rgb.astype(np.float32) / 255.0
    hh, ss, vv = rgb_to_hsv(rgb)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]

    green_dom = (g > r + 0.02) & (g > b + 0.02)
    # concrete / roof: greyish, bright-ish, not vegetation, not deep shadow
    concrete = (ss < 0.22) & (vv > 0.42) & (vv < 0.96) & (~green_dom)
    # roads: very uniform neutral grey, moderate-high brightness
    neutral = (np.abs(r - g) < 0.06) & (np.abs(g - b) < 0.06) & (np.abs(r - b) < 0.06)
    road_like = neutral & (ss < 0.14) & (vv > 0.48) & (vv < 0.88)

    prior_conc, prior_green, prior_edge = build_frame_priors(
        scene, mosaic_meta, W, H
    )
    if prior_conc is None:
        prior_conc = np.full((MONTAGE_ROWS, MONTAGE_COLS), 0.4, dtype=np.float32)
        prior_green = np.full((MONTAGE_ROWS, MONTAGE_COLS), 0.5, dtype=np.float32)
        prior_edge = np.full((MONTAGE_ROWS, MONTAGE_COLS), 0.3, dtype=np.float32)

    cell = max(4, W // grid_cols)
    gy = H // cell
    gx = W // cell
    frac = np.zeros((gy, gx), dtype=np.float32)
    road_frac = np.zeros((gy, gx), dtype=np.float32)
    meanv = np.zeros((gy, gx), dtype=np.float32)
    varv = np.zeros((gy, gx), dtype=np.float32)
    for j in range(gy):
        for i in range(gx):
            y0, y1 = j * cell, (j + 1) * cell
            x0, x1 = i * cell, (i + 1) * cell
            blk = concrete[y0:y1, x0:x1]
            frac[j, i] = float(blk.mean())
            road_frac[j, i] = float(road_like[y0:y1, x0:x1].mean())
            vblk = vv[y0:y1, x0:x1]
            meanv[j, i] = float(vblk.mean())
            varv[j, i] = float(vblk.var())

    cell_u = (np.arange(gx) + 0.5) / gx
    cell_v = (np.arange(gy) + 0.5) / gy
    thr = np.zeros((gy, gx), dtype=np.float32)
    frame_ok = np.ones((gy, gx), dtype=bool)
    for j in range(gy):
        for i in range(gx):
            pc, pg, pe = lookup_frame_prior(
                prior_conc, prior_green, prior_edge,
                cell_u[i], cell_v[j], mosaic_meta=mosaic_meta
            )
            # forest-heavy frames: require much stronger local concrete signal
            if pg > 0.72:
                thr[j, i] = 0.62
            elif pg > 0.58:
                thr[j, i] = float(np.interp(pc, [0.30, 0.55], [0.58, 0.42]))
            else:
                # built-up / mixed frames: lower threshold when frame has more concrete
                thr[j, i] = float(np.interp(pc, [0.30, 0.58], [0.55, 0.28]))
            # frames with very low concrete prior — skip entirely
            if pc < 0.32 and pg > 0.55:
                frame_ok[j, i] = False
            # boost threshold slightly in high-edge forest edge zones (paths, not roofs)
            if pe > 0.33 and pg > 0.65 and pc < 0.40:
                thr[j, i] += 0.08

    cells = (frac > thr) & frame_ok
    # reject road-like uniform cells (asphalt strips)
    cells &= ~((road_frac > 0.35) & (varv < 0.0045))
    cells &= ~((road_frac > 0.22) & (varv < 0.0028) & (meanv > 0.55))

    labels, _ = label_components(cells)
    comp_size = np.bincount(labels.ravel())
    keep = cells & (comp_size[labels] >= min_cells)

    B = 2
    inset = 0.82
    buildings = []
    for j0 in range(0, gy, B):
        for i0 in range(0, gx, B):
            blk = keep[j0:j0 + B, i0:i0 + B]
            if blk.size == 0:
                continue
            fill = float(blk.mean())
            if fill < 0.45:
                continue
            j1 = min(j0 + B, gy)
            i1 = min(i0 + B, gx)
            sub_road = float(road_frac[j0:j1, i0:i1].mean())
            sub_var = float(varv[j0:j1, i0:i1].mean())
            if sub_road > 0.40 and sub_var < 0.005:
                continue
            cu = (i0 + i1) / 2 / gx
            cv = (j0 + j1) / 2 / gy
            su = (i1 - i0) / gx * inset
            sv = (j1 - j0) / gy * inset
            # elongated low-variance blocks → likely road segment, not building
            aspect = max(su, sv) / max(1e-6, min(su, sv))
            if aspect > 3.2 and sub_var < 0.006 and sub_road > 0.25:
                continue
            density = float(frac[j0:j1, i0:i1].mean())
            brightness = float(meanv[j0:j1, i0:i1].mean())
            height_m = round(3.0 + 8.0 * density + 3.0 * brightness, 2)
            buildings.append({
                "u": round(cu, 5),
                "v": round(cv, 5),
                "su": round(su, 5),
                "sv": round(sv, 5),
                "height_m": height_m,
                "density": round(density, 3),
            })

    buildings.sort(key=lambda b: b["su"] * b["sv"] * b["density"], reverse=True)
    buildings = buildings[:max_buildings]
    return buildings


def enrich_buildings(buildings: list[dict]) -> list[dict]:
    """Add asset registry fields: id, type, capacity, last_maintenance."""
    import random
    from datetime import date, timedelta
    rng = random.Random(42)
    types = ["konut", "ofis", "depo", "sosyal", "teknik"]
    base = date(2024, 6, 1)
    out = []
    for i, b in enumerate(buildings):
        maint = base + timedelta(days=rng.randint(30, 400))
        out.append({
            **b,
            "id": f"B-{i + 1:03d}",
            "type": types[i % len(types)],
            "capacity": int(20 + b.get("height_m", 5) * 8 + rng.randint(0, 40)),
            "last_maintenance": maint.isoformat(),
        })
    return out


def extract_trees(ortho_rgb, scene=None, mosaic_meta=None, grid_cols=90, max_trees=600):
    """Detect tree/vegetation canopy in the ortho and return tree points
    (u, v in 0..1, height_m, radius_m). Trees = green-dominant, textured,
    darker canopy (not flat pale lawn / not bright concrete)."""
    H, W, _ = ortho_rgb.shape
    rgb = ortho_rgb.astype(np.float32) / 255.0
    _, ss, vv = rgb_to_hsv(rgb)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    green = (g > r + 0.03) & (g > b + 0.02)
    canopy = green & (vv < 0.66) & (ss > 0.10)
    cell = max(4, W // grid_cols)
    gy, gx = H // cell, W // cell
    frac = np.zeros((gy, gx), np.float32)
    varv = np.zeros((gy, gx), np.float32)
    for j in range(gy):
        for i in range(gx):
            y0, y1, x0, x1 = j * cell, (j + 1) * cell, i * cell, (i + 1) * cell
            frac[j, i] = float(canopy[y0:y1, x0:x1].mean())
            varv[j, i] = float(vv[y0:y1, x0:x1].var())
    cells = (frac > 0.40) & (varv > 0.0012)
    rng = np.random.default_rng(7)
    trees = []
    for j in range(gy):
        for i in range(gx):
            if not cells[j, i]:
                continue
            dens = float(frac[j, i])
            cu = min(0.999, max(0.001, (i + 0.5 + rng.uniform(-0.35, 0.35)) / gx))
            cv = min(0.999, max(0.001, (j + 0.5 + rng.uniform(-0.35, 0.35)) / gy))
            h = round(float(4.0 + 8.0 * dens + rng.uniform(-1.0, 2.0)), 2)
            rad = round(float(1.4 + 2.6 * dens), 2)
            trees.append({"u": round(cu, 5), "v": round(cv, 5),
                          "height_m": max(2.5, h), "radius_m": rad})
    if len(trees) > max_trees:
        keep = sorted(rng.choice(len(trees), max_trees, replace=False).tolist())
        trees = [trees[k] for k in keep]
    return trees


# --------------------------------------------------------------------------- #
# Water detection                                                             #
# --------------------------------------------------------------------------- #
def detect_water(ortho_rgb, height_norm, scene=None, mosaic_meta=None):
    """Detect bluish/teal low-lying water and return (has_water, level_frac,
    coverage). level_frac is a normalized 0..1 elevation for the water plane."""
    rgb = ortho_rgb.astype(np.float32) / 255.0
    _, ss, vv = rgb_to_hsv(rgb)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    # Teal/blue water: blue dominates, not dark forest green, moderate sat/value
    water = (
        (b >= g - 0.02) & (b >= r + 0.03)
        & (vv > 0.10) & (vv < 0.68) & (ss > 0.06)
        & ~((g > r + 0.08) & (g > b))  # exclude lush green
    )
    if not is_geometric_mosaic(mosaic_meta):
        # Legacy montaj: su rengi nadiren dikiş boyunca uniform — artefakt filtrele
        seam_w = build_seam_weight_mask(ortho_rgb.shape[0], ortho_rgb.shape[1],
                                        feather_frac=0.03)
        water &= seam_w < 0.55

    coverage = float(water.mean())

    hh, hw = height_norm.shape
    wm_img = Image.fromarray((water.astype(np.uint8) * 255))
    wm = np.asarray(wm_img.resize((hw, hh), Image.NEAREST)) > 127

    if coverage < 0.003 or wm.sum() < 16:
        return False, 0.0, coverage

    # Prefer elevation at ortho-water pixels; fall back to global low percentile
    h_at_water = height_norm[wm]
    if h_at_water.size >= 32:
        level_frac = float(np.clip(np.percentile(h_at_water, 55), 0.0, 1.0))
    else:
        level_frac = float(np.clip(np.percentile(height_norm, 12), 0.0, 1.0))
    return True, level_frac, coverage


# --------------------------------------------------------------------------- #
# Normal map                                                                  #
# --------------------------------------------------------------------------- #
def build_normalmap(elev_m, cell_size_m, strength=1.0):
    gy, gx = np.gradient(elev_m * strength, cell_size_m)
    nx, ny = -gx, -gy
    nz = np.ones_like(elev_m)
    length = np.sqrt(nx * nx + ny * ny + nz * nz)
    nx, ny, nz = nx / length, ny / length, nz / length
    rgb = np.stack([nx * 0.5 + 0.5, ny * 0.5 + 0.5, nz * 0.5 + 0.5], axis=-1)
    return (np.clip(rgb, 0, 1) * 255).astype(np.uint8)


# --------------------------------------------------------------------------- #
# Main                                                                        #
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="Ingest the real drone dataset for the viewer.")
    ap.add_argument("--gsd", type=float, default=0.15,
                    help="Assumed ground sample distance, metres/pixel of the "
                         "orthomosaic width (default 0.15). Drives site extent.")
    ap.add_argument("--min-elev", type=float, default=0.0,
                    help="Assumed minimum elevation in metres (default 0).")
    ap.add_argument("--max-elev", type=float, default=16.0,
                    help="Assumed maximum elevation in metres (default 16).")
    ap.add_argument("--height-res", type=int, default=1024,
                    help="Width (px) of the processed heightmap (default 1024).")
    ap.add_argument("--origin-lat", type=float, default=41.0082)
    ap.add_argument("--origin-lon", type=float, default=28.9784)
    ap.add_argument("--stitch", action="store_true",
                    help="Once ingest baslamadan once stitch_mosaic.py calistir (images/ klasoru gerekir).")
    ap.add_argument("--images", default=DEFAULT_IMAGES_DIR,
                    help="--stitch icin kaynak kare klasoru (varsayilan: ./images).")
    ap.add_argument("--stitch-max-dim", type=int, default=640)
    ap.add_argument("--stitch-output-scale", type=float, default=0.35)
    ap.add_argument("--stitch-nfeatures", type=int, default=500)
    ap.add_argument("--stitch-ransac", type=float, default=4.0)
    ap.add_argument("--stitch-method", default="auto",
                    help="stitch_mosaic yontemi: auto, gps, phase, orb")
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)

    mosaic_meta = run_stitch_if_requested(args)

    # ---- scene_data.json (optional prior) --------------------------------- #
    scene = None
    if os.path.exists(SRC_SCENE):
        with open(SRC_SCENE, "r", encoding="utf-8") as f:
            scene = json.load(f)

    # ---- orthomosaic ------------------------------------------------------ #
    print("[1/6] Reading orthomosaic (mosaic.jpg)...")
    ortho_img = Image.open(SRC_ORTHO).convert("RGB")
    ow, oh = ortho_img.size
    aspect = ow / oh
    ortho_rgb = np.asarray(ortho_img)
    geometric = is_geometric_mosaic(mosaic_meta)
    if geometric:
        method = mosaic_meta.get("method", "geometric")
        print(f"        Geometrik mozaik ({method}) — montaj dikiş islemi atlaniyor.")
    else:
        print("        Legacy montaj (6×3) — dikiş yumuşatma uygulanıyor...")
        seam_mask = build_seam_weight_mask(oh, ow)
        ortho_rgb = crossfade_montage_tiles(ortho_rgb)
        ortho_rgb = np.clip(
            soften_montage_seams(ortho_rgb, seam_mask, blur_radius=2.5), 0, 255
        ).astype(np.uint8)
    Image.fromarray(ortho_rgb, mode="RGB").save(
        os.path.join(OUT_DIR, "orthomosaic.jpg"), quality=92
    )

    # ---- real-world scale (documented assumption) ------------------------- #
    width_m = ow * args.gsd
    height_m = oh * args.gsd
    min_e, max_e = args.min_elev, args.max_elev

    # ---- heightmap: align to ortho aspect, denoise ------------------------ #
    print("[2/6] Processing heightmap (heightmap.jpg): align + denoise...")
    hw = args.height_res
    hh = max(2, int(round(hw / aspect)))
    h_img = Image.open(SRC_HEIGHT).convert("L").resize((hw, hh), Image.BILINEAR)
    h_arr = np.asarray(h_img).astype(np.float32)
    if geometric:
        method = mosaic_meta.get("method", "geometric")
        print(f"        Geometrik heightmap ({method}) — montaj dikiş islemi atlaniyor.")
    else:
        print("        Seam-aware smoothing on heightmap montage...")
        seam_h = build_seam_weight_mask(hh, hw, feather_frac=0.05)
        h_arr = crossfade_montage_tiles(h_arr)
        h_arr = soften_montage_seams(h_arr, seam_h, blur_radius=4.0)
    h_img = Image.fromarray(np.clip(h_arr, 0, 255).astype(np.uint8))
    # kill JPEG block artifacts: median then gaussian
    h_img = h_img.filter(ImageFilter.MedianFilter(size=5))
    h_img = h_img.filter(ImageFilter.GaussianBlur(radius=2.0))
    h_arr = np.asarray(h_img).astype(np.float32) / 255.0
    # robust normalize (clip extreme percentiles so noise doesn't dominate)
    lo, hi = np.percentile(h_arr, 1), np.percentile(h_arr, 99)
    h_norm = np.clip((h_arr - lo) / max(1e-6, (hi - lo)), 0.0, 1.0)

    elev_m = min_e + h_norm * (max_e - min_e)
    cell_size_m = width_m / hw

    h16 = (h_norm * 65535.0).astype(np.uint16)
    Image.fromarray(h16, mode="I;16").save(os.path.join(OUT_DIR, "heightmap.png"))

    print("[3/6] Building normal map from heightmap...")
    nmap = build_normalmap(elev_m, cell_size_m, strength=1.0)
    Image.fromarray(nmap, mode="RGB").save(os.path.join(OUT_DIR, "normalmap.png"))

    # ---- buildings -------------------------------------------------------- #
    print("[4/6] Extracting 3D building footprints...")
    buildings = extract_buildings(ortho_rgb, scene, mosaic_meta)
    buildings = enrich_buildings(buildings)
    with open(os.path.join(OUT_DIR, "buildings.json"), "w", encoding="utf-8") as f:
        json.dump({"count": len(buildings), "buildings": buildings}, f, indent=2)
    print(f"        -> {len(buildings)} footprints")

    # ---- trees ------------------------------------------------------------ #
    print("[4b/6] Extracting tree canopy...")
    trees = extract_trees(ortho_rgb, scene, mosaic_meta)
    with open(os.path.join(OUT_DIR, "trees.json"), "w", encoding="utf-8") as f:
        json.dump({"count": len(trees), "trees": trees}, f, indent=2)
    print(f"        -> {len(trees)} trees")

    # ---- water ------------------------------------------------------------ #
    print("[5/6] Detecting water...")
    has_water, water_frac, coverage = detect_water(ortho_rgb, h_norm, scene, mosaic_meta)
    water_level_m = round(min_e + water_frac * (max_e - min_e), 3)
    print(f"        -> has_water={has_water} coverage={coverage*100:.2f}% "
          f"level={water_level_m} m")

    # ---- site_meta.json --------------------------------------------------- #
    print("[6/6] Writing site_meta.json...")
    avg_concrete = (round(float(np.mean([f["concrete_ratio"] for f in scene])), 3)
                    if scene else None)
    stitch_method = mosaic_meta.get("method") if mosaic_meta else "legacy_grid"
    stitch_note = (
        f"Fast geometric stitch ({stitch_method}, stitch_mosaic.py)."
        if geometric else
        "Legacy 6×3 filename-order montage; seam crossfade applied at ingest."
    )
    from datetime import datetime, timezone
    b_count = len(buildings)
    site_name = "Gerçek Drone Sahası"
    if scene and len(scene) > 0:
        site_name = f"Drone Sahası ({len(scene)} kare)"
    meta = {
        "site_name": site_name,
        "twin_version": "2.0.0",
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "asset_summary": {
            "building_count": b_count,
            "has_water": bool(has_water),
            "water_coverage_pct": round(coverage * 100, 2),
            "dataset_type": "real",
            "stitch_method": stitch_method,
            "elevation_range_m": round(max_e - min_e, 3),
            "site_area_m2": round(width_m * height_m, 1),
        },
        "description": "REAL drone dataset (mosaic + approx. heightmap). "
                       "Ingested by ingest_real_dataset.py.",
        "synthetic": False,
        "source": {
            "orthomosaic": "mosaic.jpg",
            "heightmap": "heightmap.jpg",
            "mosaic_meta": "mosaic_meta.json" if mosaic_meta else None,
            "frames": len(scene) if scene else None,
            "frame_native_px": [4000, 2250],
            "avg_concrete_ratio": avg_concrete,
            "stitch_method": stitch_method,
        },
        "resolution_px": ow,
        "width_m": round(width_m, 3),
        "height_m": round(height_m, 3),
        "min_elev_m": round(min_e, 3),
        "max_elev_m": round(max_e, 3),
        "elevation_range_m": round(max_e - min_e, 3),
        "ground_sample_distance_m": round(args.gsd, 4),
        "heightmap": "heightmap.png",
        "heightmap_bits": 16,
        "heightmap_encoding": "linear 0..65535 maps to [min_elev_m, max_elev_m]",
        "orthomosaic": "orthomosaic.jpg",
        "normalmap": "normalmap.png",
        "buildings": "buildings.json",
        "trees": "trees.json",
        "has_water": bool(has_water),
        "water_level_m": water_level_m,
        "water_coverage": round(coverage, 5),
        "assumptions": {
            "note": "Scale is ASSUMED. heightmap.jpg is an 8-bit JPEG with no absolute "
                    "scale. width/height derived from GSD; elevation range chosen as "
                    "plausible for a park/campground.",
            "assumed_gsd_m_per_px": round(args.gsd, 4),
            "assumed_elev_range_m": [round(min_e, 3), round(max_e, 3)],
            "stitch_processing": stitch_note,
            "montage_grid": None if geometric else [MONTAGE_COLS, MONTAGE_ROWS],
            "seam_processing": None if geometric else "crossfade + Gaussian blend at tile boundaries",
        },
        "georef": {
            "origin_lat": args.origin_lat,
            "origin_lon": args.origin_lon,
            "crs": "EPSG:4326 (stub)",
            "note": "Top-left (north-west) corner; stub only, not georeferenced.",
        },
    }
    with open(os.path.join(OUT_DIR, "site_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    print("\nDone. Wrote to:", OUT_DIR)
    for name in ("orthomosaic.jpg", "heightmap.png", "normalmap.png",
                 "buildings.json", "site_meta.json"):
        p = os.path.join(OUT_DIR, name)
        if os.path.exists(p):
            print(f"  {name:18s} {os.path.getsize(p)/1024:8.1f} KB")
    print(f"\nSite: {width_m:.1f} x {height_m:.1f} m  |  elev {min_e:.1f}..{max_e:.1f} m "
          f"|  GSD {args.gsd} m/px  |  heightmap {hw}x{hh}")


if __name__ == "__main__":
    main()
