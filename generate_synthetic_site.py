#!/usr/bin/env python3
"""
generate_synthetic_site.py
==========================

Procedurally generate a *realistic* synthetic photogrammetry site WITHOUT
needing any real drone photos. The output mimics what a WebODM / ODM run
would produce so the SAME viewer pipeline works later when real GeoTIFF
orthophoto + DSM data is dropped in.

Outputs (written next to this script, in ./data):
    data/heightmap.png    16-bit grayscale DSM (elevation, normalized 0..65535)
    data/orthomosaic.jpg  RGB aerial-looking texture, aligned to the DSM
    data/normalmap.png    tangent-space normal map derived from the DSM
    data/site_meta.json   SINGLE SOURCE OF TRUTH: real-world bounds + georef stub

Everything is portable: paths are relative to this file. No hardcoded user
paths. Only numpy + Pillow are required.

Usage:
    python generate_synthetic_site.py
    python generate_synthetic_site.py --resolution 1024 --width-m 500 --max-elev 45 --seed 7
"""

import argparse
import json
import os

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")


# --------------------------------------------------------------------------- #
# Noise helpers (simple multi-octave value noise, numpy only)                 #
# --------------------------------------------------------------------------- #
def _smoothstep(t):
    return t * t * (3.0 - 2.0 * t)


def _value_noise(res, freq, rng):
    """Single-octave value noise upsampled to (res, res) via smooth bilinear.

    `freq` is the number of lattice cells across the image (low freq = large
    smooth features).
    """
    grid = max(2, int(freq) + 2)
    lattice = rng.random((grid, grid)).astype(np.float32)

    # coordinates of every output pixel in lattice space.
    # Use float64 then clamp; float32 can round the endpoint up to grid-1.
    coords = np.linspace(0, grid - 1.0, res, dtype=np.float64)
    x0 = np.clip(np.floor(coords).astype(np.int32), 0, grid - 2)
    fx = _smoothstep((coords - x0).astype(np.float32))

    # gather corners
    gx0 = lattice[:, x0]                 # (grid, res)
    gx1 = lattice[:, x0 + 1]
    row = gx0 * (1 - fx)[None, :] + gx1 * fx[None, :]   # (grid, res)

    y0 = x0
    fy = fx
    c0 = row[y0, :]                      # (res, res)
    c1 = row[y0 + 1, :]
    out = c0 * (1 - fy)[:, None] + c1 * fy[:, None]
    return out


def fbm(res, seed, octaves=6, base_freq=4.0, persistence=0.5, lacunarity=2.0):
    """Fractal Brownian motion (sum of value-noise octaves), normalized 0..1.

    `base_freq` = lattice cells across the image at the first (largest) octave.
    """
    rng = np.random.default_rng(seed)
    total = np.zeros((res, res), dtype=np.float32)
    amp = 1.0
    freq = base_freq
    norm = 0.0
    for o in range(octaves):
        total += amp * _value_noise(res, freq, rng)
        norm += amp
        amp *= persistence
        freq *= lacunarity
    total /= norm
    total -= total.min()
    total /= max(1e-6, float(np.ptp(total)))
    return total


# --------------------------------------------------------------------------- #
# Terrain construction                                                        #
# --------------------------------------------------------------------------- #
def build_terrain(res, seed, max_elev):
    """Return (elev_m, masks) where elev_m is float elevation in METERS."""
    yy, xx = np.meshgrid(
        np.linspace(0, 1, res, dtype=np.float32),
        np.linspace(0, 1, res, dtype=np.float32),
        indexing="ij",
    )

    # Base rolling hills (large features) + medium detail + fine roughness.
    # Low base_freq -> large smooth landforms (this is a DSM, not pixel noise).
    base = fbm(res, seed, octaves=5, base_freq=3.0, persistence=0.5)
    medium = fbm(res, seed + 11, octaves=5, base_freq=6.0, persistence=0.5)
    fine = fbm(res, seed + 23, octaves=4, base_freq=14.0, persistence=0.45)
    elev = 0.70 * base + 0.24 * medium + 0.06 * fine

    # A gentle large-scale tilt so one side is a valley
    elev = elev * 0.85 + 0.15 * (1.0 - yy)

    # ---- Flat-ish built area (plateau) in a region of the map ------------- #
    # Soft rectangular plateau, blended in.
    bx0, bx1, by0, by1 = 0.55, 0.92, 0.10, 0.45
    plateau_mask = _soft_rect(xx, yy, bx0, bx1, by0, by1, feather=0.05)
    plateau_level = np.average(elev, weights=plateau_mask + 1e-6)
    elev = elev * (1 - plateau_mask) + (
        plateau_level * 0.9 + 0.02 * fine
    ) * plateau_mask

    # ---- River / channel carved across the terrain ----------------------- #
    # Sinuous path: x as function of y.
    t = np.linspace(0, 1, res, dtype=np.float32)
    river_x = 0.30 + 0.16 * np.sin(t * 6.28318 * 1.3) + 0.06 * np.sin(t * 6.28318 * 3.1)
    river_x_full = river_x[:, None]                      # (res,1) varies along y(rows)
    dist_river = np.abs(xx - river_x_full)
    river_width = 0.035
    river_mask = np.clip(1.0 - dist_river / river_width, 0.0, 1.0)
    river_mask = _smoothstep(river_mask)
    # carve down
    elev = elev - river_mask * 0.18
    river_water = river_mask > 0.55

    # ---- Road crossing the flat area ------------------------------------- #
    road_y = 0.27
    dist_road = np.abs(yy - road_y)
    road_mask = (np.clip(1.0 - dist_road / 0.012, 0, 1) > 0.5) & (xx > 0.5)
    elev = np.where(road_mask, plateau_level * 0.9, elev)

    # Normalize to 0..max_elev meters
    elev -= elev.min()
    elev /= max(1e-6, elev.max())
    elev_m = elev * max_elev

    masks = {
        "plateau": plateau_mask,
        "river": river_mask,
        "river_water": river_water,
        "road": road_mask,
    }
    return elev_m.astype(np.float32), masks


def _soft_rect(xx, yy, x0, x1, y0, y1, feather=0.04):
    fx = np.clip((xx - x0) / feather, 0, 1) * np.clip((x1 - xx) / feather, 0, 1)
    fy = np.clip((yy - y0) / feather, 0, 1) * np.clip((y1 - yy) / feather, 0, 1)
    return _smoothstep(np.clip(fx, 0, 1)) * _smoothstep(np.clip(fy, 0, 1))


# --------------------------------------------------------------------------- #
# Slope / shading                                                             #
# --------------------------------------------------------------------------- #
def compute_slope_normals(elev_m, cell_size_m):
    """Return (slope_rad, normals[res,res,3]) from elevation in meters."""
    gy, gx = np.gradient(elev_m, cell_size_m)
    nz = np.ones_like(elev_m)
    nx = -gx
    ny = -gy
    length = np.sqrt(nx * nx + ny * ny + nz * nz)
    normals = np.stack([nx / length, ny / length, nz / length], axis=-1)
    slope = np.arccos(np.clip(normals[..., 2], -1, 1))
    return slope, normals


def hillshade(normals, az_deg=315.0, alt_deg=45.0):
    az = np.radians(az_deg)
    alt = np.radians(alt_deg)
    lx = np.cos(alt) * np.cos(az)
    ly = np.cos(alt) * np.sin(az)
    lz = np.sin(alt)
    shade = normals[..., 0] * lx + normals[..., 1] * ly + normals[..., 2] * lz
    return np.clip(shade, 0, 1)


# --------------------------------------------------------------------------- #
# Orthomosaic synthesis                                                       #
# --------------------------------------------------------------------------- #
def build_orthomosaic(elev_m, slope, masks, normals, seed, max_elev):
    res = elev_m.shape[0]
    rng = np.random.default_rng(seed + 99)

    elev_n = elev_m / max(1e-6, max_elev)            # 0..1
    slope_n = np.clip(slope / np.radians(55.0), 0, 1)

    # texture noise to break up flat colors (medium + fine grain)
    speckle = fbm(res, seed + 41, octaves=5, base_freq=24.0)
    micro = fbm(res, seed + 67, octaves=4, base_freq=80.0)

    rgb = np.zeros((res, res, 3), dtype=np.float32)

    # --- grass (gentle slopes, mid elevation) ----------------------------- #
    grass = np.array([0.30, 0.42, 0.20]) + 0.0
    grass_var = (speckle[..., None] - 0.5) * np.array([0.10, 0.14, 0.08])
    grass_col = np.clip(grass + grass_var, 0, 1)

    # --- rock / soil (steep slopes, high elevation) ----------------------- #
    rock = np.array([0.46, 0.40, 0.34])
    rock_var = (micro[..., None] - 0.5) * np.array([0.14, 0.12, 0.10])
    rock_col = np.clip(rock + rock_var, 0, 1)

    # --- bare soil at high flat tops -------------------------------------- #
    soil = np.array([0.55, 0.46, 0.34])

    # blend grass->rock by slope, push toward rock at high elevation
    rock_weight = np.clip(slope_n * 1.6 + (elev_n - 0.6) * 1.2, 0, 1)
    ground = grass_col * (1 - rock_weight[..., None]) + rock_col * rock_weight[..., None]

    # snow-ish / light soil cap on very high gentle areas
    cap = np.clip((elev_n - 0.82) / 0.18, 0, 1) * (1 - slope_n)
    ground = ground * (1 - cap[..., None]) + soil * cap[..., None]

    rgb = ground

    # --- water (river channel + low areas) -------------------------------- #
    water = np.array([0.12, 0.26, 0.38])
    water_deep = np.array([0.06, 0.16, 0.28])
    water_mask = masks["river_water"].astype(np.float32)
    # also flood the very lowest cells
    low = (elev_n < 0.06).astype(np.float32)
    water_mask = np.clip(water_mask + low, 0, 1)
    # ripple variation
    wcol = water + (speckle[..., None] - 0.5) * np.array([0.03, 0.04, 0.05])
    wcol = np.clip(wcol, 0, 1)
    rgb = rgb * (1 - water_mask[..., None]) + wcol * water_mask[..., None]

    # --- buildings on the plateau ----------------------------------------- #
    plateau = masks["plateau"]
    building_map = _scatter_buildings(res, plateau > 0.5, rng)
    roof_tint = rng.random((res, res, 1)).astype(np.float32) * np.array([0.25, 0.15, 0.12])
    roof = np.array([0.55, 0.45, 0.40]) + roof_tint - 0.06
    roof = np.clip(roof, 0, 1)
    b_mask = building_map[..., None]
    rgb = rgb * (1 - b_mask) + roof * b_mask

    # --- road ------------------------------------------------------------- #
    road = masks["road"].astype(np.float32)
    road_col = np.array([0.18, 0.18, 0.19])
    rgb = rgb * (1 - road[..., None]) + road_col * road[..., None]

    # --- baked shading (AO + hillshade) so it reads as aerial imagery ----- #
    shade = hillshade(normals, az_deg=315.0, alt_deg=50.0)
    ao = 0.5 + 0.5 * fbm(res, seed + 5, octaves=4, base_freq=8.0)  # soft large AO
    light = (0.55 + 0.65 * shade) * (0.85 + 0.15 * ao)
    rgb = np.clip(rgb * light[..., None], 0, 1)

    # subtle global contrast / color grade
    rgb = np.clip((rgb - 0.5) * 1.06 + 0.5 + 0.01, 0, 1)

    return (rgb * 255).astype(np.uint8)


def _scatter_buildings(res, area_mask, rng):
    """Place axis-aligned rectangular building footprints inside area_mask."""
    out = np.zeros((res, res), dtype=np.float32)
    ys, xs = np.where(area_mask)
    if len(xs) == 0:
        return out
    y0, y1 = ys.min(), ys.max()
    x0, x1 = xs.min(), xs.max()
    n = max(8, int((x1 - x0) * (y1 - y0) / (res * res) * 220))
    for _ in range(n):
        bw = rng.integers(max(4, res // 90), max(6, res // 40))
        bh = rng.integers(max(4, res // 90), max(6, res // 40))
        cx = rng.integers(x0, max(x0 + 1, x1 - bw))
        cy = rng.integers(y0, max(y0 + 1, y1 - bh))
        if area_mask[cy:cy + bh, cx:cx + bw].mean() > 0.85:
            out[cy:cy + bh, cx:cx + bw] = 1.0
    return out


# --------------------------------------------------------------------------- #
# Normal map (tangent space, for the viewer)                                  #
# --------------------------------------------------------------------------- #
def build_normalmap(elev_m, cell_size_m, strength=1.0):
    gy, gx = np.gradient(elev_m * strength, cell_size_m)
    nx = -gx
    ny = -gy
    nz = np.ones_like(elev_m)
    length = np.sqrt(nx * nx + ny * ny + nz * nz)
    nx, ny, nz = nx / length, ny / length, nz / length
    # encode to 0..255 (tangent space convention: +Y up)
    r = ((nx * 0.5) + 0.5)
    g = ((ny * 0.5) + 0.5)
    b = ((nz * 0.5) + 0.5)
    rgb = np.stack([r, g, b], axis=-1)
    return (np.clip(rgb, 0, 1) * 255).astype(np.uint8)


# --------------------------------------------------------------------------- #
# Main                                                                        #
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="Generate a synthetic photogrammetry site.")
    ap.add_argument("--resolution", type=int, default=1024,
                    help="Pixel resolution of square outputs (default 1024).")
    ap.add_argument("--width-m", type=float, default=400.0,
                    help="Real-world site width/height in meters (default 400).")
    ap.add_argument("--max-elev", type=float, default=40.0,
                    help="Max DSM elevation in meters (default 40).")
    ap.add_argument("--min-elev", type=float, default=0.0,
                    help="Min DSM elevation in meters (default 0).")
    ap.add_argument("--seed", type=int, default=42, help="Random seed (default 42).")
    ap.add_argument("--origin-lat", type=float, default=41.0082,
                    help="Georef stub origin latitude (default Istanbul).")
    ap.add_argument("--origin-lon", type=float, default=28.9784,
                    help="Georef stub origin longitude.")
    args = ap.parse_args()

    res = args.resolution
    width_m = args.width_m
    height_m = args.width_m  # square
    max_elev = args.max_elev
    gsd = width_m / res  # ground sample distance, meters/pixel
    cell = gsd

    os.makedirs(DATA_DIR, exist_ok=True)

    print(f"[1/5] Building terrain ({res}x{res}, {width_m} m, max {max_elev} m)...")
    elev_m, masks = build_terrain(res, args.seed, max_elev)
    elev_m += args.min_elev

    print("[2/5] Computing slope & normals...")
    slope, normals = compute_slope_normals(elev_m, cell)

    print("[3/5] Synthesizing orthomosaic...")
    ortho = build_orthomosaic(elev_m, slope, masks, normals, args.seed, max_elev)

    print("[4/5] Building normal map...")
    nmap = build_normalmap(elev_m, cell, strength=1.0)

    print("[5/5] Writing outputs...")
    # 16-bit heightmap: normalize true elevation across [min_elev, max_elev+min]
    e_min = float(elev_m.min())
    e_max = float(elev_m.max())
    h16 = ((elev_m - e_min) / max(1e-6, (e_max - e_min)) * 65535.0).astype(np.uint16)
    Image.fromarray(h16, mode="I;16").save(os.path.join(DATA_DIR, "heightmap.png"))
    Image.fromarray(ortho, mode="RGB").save(
        os.path.join(DATA_DIR, "orthomosaic.jpg"), quality=92
    )
    Image.fromarray(nmap, mode="RGB").save(os.path.join(DATA_DIR, "normalmap.png"))

    meta = {
        "description": "Synthetic photogrammetry site (DSM + orthomosaic). "
                       "Drop-in compatible with WebODM/ODM GeoTIFF exports.",
        "resolution_px": res,
        "width_m": round(width_m, 3),
        "height_m": round(height_m, 3),
        "min_elev_m": round(e_min, 3),
        "max_elev_m": round(e_max, 3),
        "elevation_range_m": round(e_max - e_min, 3),
        "ground_sample_distance_m": round(gsd, 4),
        "heightmap": "heightmap.png",
        "heightmap_bits": 16,
        "heightmap_encoding": "linear 0..65535 maps to [min_elev_m, max_elev_m]",
        "orthomosaic": "orthomosaic.jpg",
        "normalmap": "normalmap.png",
        "georef": {
            "origin_lat": args.origin_lat,
            "origin_lon": args.origin_lon,
            "crs": "EPSG:4326 (stub)",
            "note": "Origin is the top-left (north-west) corner; stub only."
        },
        "synthetic": True,
        "seed": args.seed,
    }
    with open(os.path.join(DATA_DIR, "site_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    print("\nDone. Wrote to:", DATA_DIR)
    for name in ("heightmap.png", "orthomosaic.jpg", "normalmap.png", "site_meta.json"):
        p = os.path.join(DATA_DIR, name)
        print(f"  {name:18s} {os.path.getsize(p)/1024:8.1f} KB")
    print(f"\nElevation range: {e_min:.2f} .. {e_max:.2f} m  |  GSD: {gsd:.3f} m/px")


if __name__ == "__main__":
    main()
