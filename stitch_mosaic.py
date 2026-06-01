#!/usr/bin/env python3
"""
stitch_mosaic.py — Fast drone mosaicing (competition speed).

Auto-selects the fastest method that still gives deterministic alignment:
  1. EXIF GPS + gimbal yaw  (~seconds, no feature matching)
  2. Phase correlation (FFT translation chain, ~1-2 s/pair)
  3. Lightweight ORB + partial affine (minimal RANSAC fallback)

Usage:
    python stitch_mosaic.py --input images/ --output mosaic.jpg
    python stitch_mosaic.py --method phase   # force a method
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from fractions import Fraction

import cv2
import numpy as np
from PIL import Image
from PIL.ExifTags import GPSTAGS, TAGS

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_IMAGES_DIR = os.path.join(HERE, "images")
DEFAULT_OUTPUT_DIR = HERE

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff",
              ".JPG", ".JPEG", ".PNG"}

GEOMETRIC_METHODS = {
    "exif_gps", "phase_correlation", "orb_partial_affine", "ransac_orb_homography",
}


def list_images(images_dir: str) -> list[str]:
    files = [f for f in os.listdir(images_dir)
             if os.path.splitext(f)[1] in IMAGE_EXTS]
    return sorted(files)


def resize_long_edge(img: np.ndarray, max_dim: int) -> tuple[np.ndarray, float]:
    h, w = img.shape[:2]
    longest = max(h, w)
    if longest <= max_dim:
        return img, 1.0
    scale = max_dim / longest
    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))
    return cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA), scale


def image_corners(w: int, h: int) -> np.ndarray:
    return np.float32([[0, 0], [w, 0], [w, h], [0, h]]).reshape(-1, 1, 2)


def transform_corners(w: int, h: int, H: np.ndarray) -> np.ndarray:
    return cv2.perspectiveTransform(image_corners(w, h), H).reshape(-1, 2)


def affine_to_homography(M: np.ndarray) -> np.ndarray:
    H = np.eye(3, dtype=np.float64)
    H[:2, :] = M
    return H


def build_height_tile(img: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    edges = cv2.Canny(gray.astype(np.uint8), 30, 100).astype(np.float32) / 255.0
    brightness = gray / 255.0
    height = edges * 0.6 + brightness * 0.4
    return cv2.GaussianBlur(height, (21, 21), 7)


def feather_mask(mask_u8: np.ndarray, sigma: float = 8.0) -> np.ndarray:
    m = (mask_u8 > 0).astype(np.float32)
    if m.sum() == 0:
        return m
    dist = cv2.distanceTransform((m * 255).astype(np.uint8), cv2.DIST_L2, 5)
    mx = float(dist.max())
    if mx > 1e-6:
        dist = dist / mx
    if sigma > 0:
        dist = cv2.GaussianBlur(dist, (0, 0), sigma)
    return np.clip(dist, 0.0, 1.0).astype(np.float32)


# --------------------------------------------------------------------------- #
# EXIF GPS                                                                    #
# --------------------------------------------------------------------------- #
def _dms_to_deg(dms, ref: str) -> float | None:
    try:
        deg = float(dms[0])
        minutes = float(dms[1])
        seconds = float(dms[2])
        val = deg + minutes / 60.0 + seconds / 3600.0
        if ref in ("S", "W"):
            val = -val
        return val
    except (TypeError, ValueError, IndexError):
        return None


def _rational_to_float(val) -> float | None:
    if val is None:
        return None
    if isinstance(val, Fraction):
        return float(val)
    if isinstance(val, tuple) and len(val) == 2:
        num, den = val
        return float(num) / float(den) if den else None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def read_exif_geo(path: str) -> dict | None:
    """Return lat, lon, alt_m, yaw_deg if GPS EXIF is present."""
    try:
        with Image.open(path) as im:
            exif = im.getexif()
            if not exif:
                return None
            gps_ifd = exif.get_ifd(0x8825)
            if not gps_ifd:
                return None

            gps = {}
            for k, v in gps_ifd.items():
                tag = GPSTAGS.get(k, k)
                gps[tag] = v

            lat = _dms_to_deg(gps.get("GPSLatitude"), gps.get("GPSLatitudeRef", "N"))
            lon = _dms_to_deg(gps.get("GPSLongitude"), gps.get("GPSLongitudeRef", "E"))
            if lat is None or lon is None:
                return None

            alt = _rational_to_float(gps.get("GPSAltitude"))
            alt_ref = int(gps.get("GPSAltitudeRef", 0)) if gps.get("GPSAltitudeRef") is not None else 0
            if alt is not None and alt_ref == 1:
                alt = -alt

            yaw = None
            for tag_id, val in exif.items():
                name = TAGS.get(tag_id, tag_id)
                if name in ("GimbalYawDegree", "FlightYawDegree", "CameraYaw"):
                    yaw = _rational_to_float(val)
                    break

            return {"lat": lat, "lon": lon, "alt_m": alt, "yaw_deg": yaw}
    except Exception:
        return None


def gps_to_local_m(lat: float, lon: float, lat0: float, lon0: float) -> tuple[float, float]:
    cos_lat = math.cos(math.radians(lat0))
    dx = (lon - lon0) * 111_320.0 * cos_lat
    dy = (lat - lat0) * 110_540.0
    return dx, dy


def exif_coverage(image_paths: list[str]) -> tuple[int, list[dict]]:
    records = []
    for path in image_paths:
        geo = read_exif_geo(path)
        records.append({"path": path, "geo": geo})
    count = sum(1 for r in records if r["geo"] is not None)
    return count, records


def choose_method(image_paths: list[str], forced: str | None) -> str:
    if forced and forced != "auto":
        mapping = {
            "gps": "exif_gps",
            "exif": "exif_gps",
            "phase": "phase_correlation",
            "orb": "orb_partial_affine",
        }
        return mapping.get(forced, forced)

    gps_count, _ = exif_coverage(image_paths)
    if gps_count >= max(2, len(image_paths) // 2):
        return "exif_gps"
    return "phase_correlation"


def estimate_gsd_from_gps(records: list[dict], img_w: int, img_h: int) -> float:
    """Metres per pixel from median GPS spacing vs image size."""
    pts = []
    for r in records:
        g = r["geo"]
        if g:
            pts.append((g["lat"], g["lon"]))
    if len(pts) < 2:
        return 0.12

    dists = []
    for i in range(len(pts) - 1):
        dx, dy = gps_to_local_m(pts[i + 1][0], pts[i + 1][1], pts[i][0], pts[i][1])
        dists.append(math.hypot(dx, dy))
    median_step_m = float(np.median(dists)) if dists else 0.12
    overlap = 0.65
    step_px = min(img_w, img_h) * (1.0 - overlap)
    return max(0.02, median_step_m / max(step_px, 1.0))


def chain_exif_gps(images: list[np.ndarray], names: list[str],
                   records: list[dict], verbose: bool) -> tuple[list[np.ndarray], list[dict], dict]:
    valid = [(i, r) for i, r in enumerate(records) if r["geo"] is not None]
    if len(valid) < 2:
        raise RuntimeError("EXIF GPS yetersiz")

    lat0 = valid[0][1]["geo"]["lat"]
    lon0 = valid[0][1]["geo"]["lon"]
    h0, w0 = images[0].shape[:2]
    gsd = estimate_gsd_from_gps(records, w0, h0)

    indexed = []
    for i, r in valid:
        g = r["geo"]
        dx, dy = gps_to_local_m(g["lat"], g["lon"], lat0, lon0)
        indexed.append((dx, dy, i, g.get("yaw_deg")))

    indexed.sort(key=lambda t: (t[1], t[0], t[2]))

    H_chain: list[np.ndarray | None] = [None] * len(images)
    align_info: list[dict] = [{"pair": None, "method": "exif_gps"}]
    bounds_dx, bounds_dy = [], []

    for rank, (dx_m, dy_m, idx, yaw_deg) in enumerate(indexed):
        img = images[idx]
        h, w = img.shape[:2]
        cx = dx_m / gsd + w / 2.0
        cy = -dy_m / gsd + h / 2.0

        T = np.array([[1, 0, cx - w / 2.0],
                      [0, 1, cy - h / 2.0],
                      [0, 0, 1]], dtype=np.float64)
        if yaw_deg is not None and abs(yaw_deg) > 0.5:
            rad = math.radians(-yaw_deg)
            c, s = math.cos(rad), math.sin(rad)
            R = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], dtype=np.float64)
            C = np.array([[1, 0, w / 2.0], [0, 1, h / 2.0], [0, 0, 1]], dtype=np.float64)
            Cinv = np.array([[1, 0, -w / 2.0], [0, 1, -h / 2.0], [0, 0, 1]], dtype=np.float64)
            T = T @ C @ R @ Cinv

        H_chain[idx] = T
        corners = transform_corners(w, h, T)
        bounds_dx.extend(corners[:, 0].tolist())
        bounds_dy.extend(corners[:, 1].tolist())
        align_info.append({
            "file": names[idx],
            "pair": [idx, "gps"],
            "dx_m": round(dx_m, 3),
            "dy_m": round(dy_m, 3),
            "yaw_deg": yaw_deg,
        })
        if verbose:
            print(f"  [{rank + 1}/{len(indexed)}] GPS {names[idx]}  "
                  f"dx={dx_m:.1f}m dy={dy_m:.1f}m gsd={gsd:.3f}m/px")

    for i in range(len(images)):
        if H_chain[i] is None:
            if verbose:
                print(f"  UYARI: {names[i]} GPS yok — komşuya sabit ofset")
            h, w = images[i].shape[:2]
            prev = next(j for j in range(i - 1, -1, -1) if H_chain[j] is not None)
            H_chain[i] = H_chain[prev] @ np.array([[1, 0, 0.35 * w], [0, 1, 0], [0, 0, 1]])

    extra = {
        "gsd_m_per_px": round(gsd, 4),
        "origin_lat": lat0,
        "origin_lon": lon0,
        "gps_count": len(valid),
    }
    return H_chain, align_info, extra


# --------------------------------------------------------------------------- #
# Phase correlation                                                           #
# --------------------------------------------------------------------------- #
def _phase_shift(gray_a: np.ndarray, gray_b: np.ndarray) -> tuple[float, float, float]:
    a = gray_a.astype(np.float64)
    b = gray_b.astype(np.float64)
    hann = cv2.createHanningWindow((a.shape[1], a.shape[0]), cv2.CV_64F)
    shift, response = cv2.phaseCorrelate(a * hann, b * hann)
    return float(shift[0]), float(shift[1]), float(response)


def chain_phase_correlation(images: list[np.ndarray], max_dim: int = 640,
                            verbose: bool = True) -> tuple[list[np.ndarray], list[dict]]:
    n = len(images)
    H_chain: list[np.ndarray] = [np.eye(3, dtype=np.float64)]
    align_info: list[dict] = [{"pair": None, "method": "phase_correlation"}]

    for i in range(1, n):
        prev_s, scale_p = resize_long_edge(images[i - 1], max_dim)
        curr_s, scale_c = resize_long_edge(images[i], max_dim)
        gp = cv2.cvtColor(prev_s, cv2.COLOR_BGR2GRAY)
        gc = cv2.cvtColor(curr_s, cv2.COLOR_BGR2GRAY)
        dx, dy, resp = _phase_shift(gp, gc)
        dx_full = dx / scale_c
        dy_full = dy / scale_c

        ref = i - 1
        if resp < 0.05 and i >= 2:
            prev2_s, scale_p2 = resize_long_edge(images[i - 2], max_dim)
            gp2 = cv2.cvtColor(prev2_s, cv2.COLOR_BGR2GRAY)
            dx2, dy2, resp2 = _phase_shift(gp2, gc)
            if resp2 > resp:
                dx_full, dy_full, resp = dx2 / scale_c, dy2 / scale_c, resp2
                ref = i - 2

        H_local = np.array([[1, 0, dx_full],
                              [0, 1, dy_full],
                              [0, 0, 1]], dtype=np.float64)
        if ref == i - 1:
            H_chain.append(H_chain[i - 1] @ H_local)
        else:
            H_chain.append(H_chain[i - 2] @ H_local)

        align_info.append({
            "pair": [i, ref],
            "dx_px": round(dx_full, 2),
            "dy_px": round(dy_full, 2),
            "response": round(resp, 4),
        })
        if verbose:
            print(f"  [{i + 1}/{n}] phase: dx={dx_full:.1f} dy={dy_full:.1f} "
                  f"resp={resp:.3f} ref={ref}")

    return H_chain, align_info


# --------------------------------------------------------------------------- #
# Lightweight ORB + partial affine                                            #
# --------------------------------------------------------------------------- #
def _detect_and_match(gray_src: np.ndarray, gray_dst: np.ndarray,
                      nfeatures: int) -> tuple[np.ndarray, np.ndarray, int]:
    orb = cv2.ORB_create(nfeatures=nfeatures, scaleFactor=1.2, nlevels=6,
                         edgeThreshold=15, patchSize=31)
    kp_s, des_s = orb.detectAndCompute(gray_src, None)
    kp_d, des_d = orb.detectAndCompute(gray_dst, None)
    if des_s is None or des_d is None or len(kp_s) < 6 or len(kp_d) < 6:
        return np.empty((0, 1, 2), np.float32), np.empty((0, 1, 2), np.float32), 0

    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
    raw = bf.knnMatch(des_s, des_d, k=2)
    good = []
    for pair in raw:
        if len(pair) != 2:
            continue
        m, n = pair
        if m.distance < 0.75 * n.distance:
            good.append(m)
    if len(good) < 6:
        return np.empty((0, 1, 2), np.float32), np.empty((0, 1, 2), np.float32), len(good)

    src_pts = np.float32([kp_s[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst_pts = np.float32([kp_d[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    return src_pts, dst_pts, len(good)


def compute_partial_affine(img_src: np.ndarray, img_dst: np.ndarray,
                           max_dim: int = 640, nfeatures: int = 500,
                           ransac_thresh: float = 4.0
                           ) -> tuple[np.ndarray | None, int, int]:
    src_s, scale_s = resize_long_edge(img_src, max_dim)
    dst_s, scale_d = resize_long_edge(img_dst, max_dim)
    gray_src = cv2.cvtColor(src_s, cv2.COLOR_BGR2GRAY)
    gray_dst = cv2.cvtColor(dst_s, cv2.COLOR_BGR2GRAY)

    src_pts, dst_pts, n_good = _detect_and_match(gray_src, gray_dst, nfeatures)
    if n_good < 6:
        return None, n_good, 0

    src_pts = (src_pts / scale_s).astype(np.float32)
    dst_pts = (dst_pts / scale_d).astype(np.float32)

    M, mask = cv2.estimateAffinePartial2D(
        src_pts, dst_pts, method=cv2.RANSAC,
        ransacReprojThreshold=ransac_thresh, maxIters=500, confidence=0.99,
    )
    inliers = int(mask.ravel().sum()) if mask is not None else 0
    if M is None or inliers < 4:
        return None, n_good, inliers
    return affine_to_homography(M), n_good, inliers


def chain_orb_partial_affine(images: list[np.ndarray], max_dim: int = 640,
                             nfeatures: int = 500, ransac_thresh: float = 4.0,
                             verbose: bool = True) -> tuple[list[np.ndarray], list[dict]]:
    n = len(images)
    H_chain: list[np.ndarray] = [np.eye(3, dtype=np.float64)]
    align_info: list[dict] = [{"pair": None, "method": "orb_partial_affine"}]

    for i in range(1, n):
        H_local, n_good, inliers = compute_partial_affine(
            images[i], images[i - 1], max_dim=max_dim,
            nfeatures=nfeatures, ransac_thresh=ransac_thresh,
        )
        ref = i - 1
        if H_local is None and i >= 2:
            H_local, n_good, inliers = compute_partial_affine(
                images[i], images[i - 2], max_dim=max_dim,
                nfeatures=nfeatures, ransac_thresh=ransac_thresh,
            )
            if H_local is not None:
                H_local = H_chain[i - 2] @ H_local
                ref = i - 2

        if H_local is None:
            h, w = images[i].shape[:2]
            H_local = np.array([[1, 0, -0.05 * w], [0, 1, 0], [0, 0, 1]], dtype=np.float64)
            if verbose:
                print(f"  [{i + 1}/{n}] UYARI: ORB basarisiz, varsayilan ofset")
        elif verbose:
            print(f"  [{i + 1}/{n}] ORB partial: {inliers} inlier / {n_good} "
                  f"(ref={ref})")

        H_chain.append(H_chain[i - 1] @ H_local if ref == i - 1 else H_local)
        align_info.append({"pair": [i, ref], "good_matches": n_good, "inliers": inliers})

    return H_chain, align_info


# --------------------------------------------------------------------------- #
# Canvas + render                                                             #
# --------------------------------------------------------------------------- #
def compute_canvas_transforms(images: list[np.ndarray],
                            H_chain: list[np.ndarray]
                            ) -> tuple[list[np.ndarray], int, int, float, float, float, float]:
    all_pts = []
    for img, H in zip(images, H_chain):
        h, w = img.shape[:2]
        all_pts.append(transform_corners(w, h, H))
    stacked = np.vstack(all_pts)
    min_x, min_y = stacked.min(axis=0)
    max_x, max_y = stacked.max(axis=0)
    T = np.array([[1, 0, -min_x], [0, 1, -min_y], [0, 0, 1]], dtype=np.float64)
    H_canvas = [T @ H for H in H_chain]
    canvas_w = int(np.ceil(max_x - min_x))
    canvas_h = int(np.ceil(max_y - min_y))
    return H_canvas, canvas_w, canvas_h, float(min_x), float(min_y), float(max_x), float(max_y)


def render_mosaic(images: list[np.ndarray], names: list[str],
                  H_canvas: list[np.ndarray], canvas_w: int, canvas_h: int
                  ) -> tuple[np.ndarray, np.ndarray, list[dict]]:
    rgb_acc = np.zeros((canvas_h, canvas_w, 3), dtype=np.float32)
    h_acc = np.zeros((canvas_h, canvas_w), dtype=np.float32)
    w_acc = np.zeros((canvas_h, canvas_w), dtype=np.float32)
    image_meta: list[dict] = []

    for img, name, H in zip(images, names, H_canvas):
        mask = np.full((img.shape[0], img.shape[1]), 255, dtype=np.uint8)
        warped_mask = cv2.warpPerspective(mask, H, (canvas_w, canvas_h),
                                          flags=cv2.INTER_NEAREST,
                                          borderMode=cv2.BORDER_CONSTANT,
                                          borderValue=0)
        wgt = feather_mask(warped_mask, sigma=6.0)
        warped_rgb = cv2.warpPerspective(img, H, (canvas_w, canvas_h),
                                         flags=cv2.INTER_LINEAR,
                                         borderMode=cv2.BORDER_CONSTANT,
                                         borderValue=0)
        for c in range(3):
            rgb_acc[:, :, c] += warped_rgb[:, :, c].astype(np.float32) * wgt

        height_tile = build_height_tile(img)
        warped_h = cv2.warpPerspective(height_tile, H, (canvas_w, canvas_h),
                                       flags=cv2.INTER_LINEAR,
                                       borderMode=cv2.BORDER_CONSTANT,
                                       borderValue=0)
        h_acc += warped_h * wgt
        w_acc += wgt

        h, w = img.shape[:2]
        corners = transform_corners(w, h, H)
        x0, y0 = corners.min(axis=0)
        x1, y1 = corners.max(axis=0)
        image_meta.append({
            "file": name,
            "homography_to_mosaic": H.tolist(),
            "bbox": [int(x0), int(y0), int(x1), int(y1)],
        })

    w_safe = np.maximum(w_acc, 1e-6)
    mosaic = np.clip(rgb_acc / w_safe[..., None], 0, 255).astype(np.uint8)
    heightmap_f = h_acc / w_safe
    hm_min, hm_max = heightmap_f.min(), heightmap_f.max()
    if hm_max > hm_min:
        heightmap_u8 = ((heightmap_f - hm_min) / (hm_max - hm_min) * 255).astype(np.uint8)
    else:
        heightmap_u8 = np.zeros((canvas_h, canvas_w), dtype=np.uint8)
    heightmap_u8 = cv2.GaussianBlur(heightmap_u8, (15, 15), 5)
    return mosaic, heightmap_u8, image_meta


def stitch_folder(images_dir: str, output_dir: str, output_mosaic: str | None = None,
                  max_dim: int = 640, output_scale: float = 0.35,
                  nfeatures: int = 500, ransac_thresh: float = 4.0,
                  method: str = "auto", verbose: bool = True) -> dict:
    names = list_images(images_dir)
    if not names:
        raise FileNotFoundError(
            f"Girdi klasorunde resim yok: {images_dir}\n"
            f"DJI karelerini (DJI_0018.JPG …) '{images_dir}' icine koyun."
        )

    paths = [os.path.join(images_dir, n) for n in names]
    chosen = choose_method(paths, method)

    if verbose:
        print(f"Toplam {len(names)} kare: {images_dir}")
        print(f"Yontem: {chosen}")

    images_full: list[np.ndarray] = []
    for path in paths:
        img = cv2.imread(path)
        if img is None:
            raise RuntimeError(f"Okunamadi: {path}")
        images_full.append(img)

    if output_scale < 1.0:
        images = []
        for img in images_full:
            h, w = img.shape[:2]
            new_w = max(1, int(round(w * output_scale)))
            new_h = max(1, int(round(h * output_scale)))
            images.append(cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA))
    else:
        images = images_full

    t0 = time.perf_counter()
    extra: dict = {}

    if chosen == "exif_gps":
        _, records = exif_coverage(paths)
        H_chain, align_info, extra = chain_exif_gps(images, names, records, verbose)
    elif chosen == "phase_correlation":
        H_chain, align_info = chain_phase_correlation(images, max_dim=max_dim, verbose=verbose)
    else:
        H_chain, align_info = chain_orb_partial_affine(
            images, max_dim=max_dim, nfeatures=nfeatures,
            ransac_thresh=ransac_thresh, verbose=verbose,
        )
        chosen = "orb_partial_affine"

    H_canvas, cw, ch, min_x, min_y, max_x, max_y = compute_canvas_transforms(images, H_chain)

    if verbose:
        print(f"Mozaik tuvali: {cw}x{ch}px — birlestiriliyor...")

    mosaic, heightmap, image_meta = render_mosaic(images, names, H_canvas, cw, ch)
    elapsed = time.perf_counter() - t0

    os.makedirs(output_dir, exist_ok=True)
    mosaic_path = output_mosaic or os.path.join(output_dir, "mosaic.jpg")
    if not mosaic_path.lower().endswith((".jpg", ".jpeg", ".png")):
        mosaic_path = os.path.join(mosaic_path, "mosaic.jpg")

    mosaic_dir = os.path.dirname(os.path.abspath(mosaic_path))
    os.makedirs(mosaic_dir, exist_ok=True)
    heightmap_path = os.path.join(mosaic_dir, "heightmap.jpg")
    meta_path = os.path.join(mosaic_dir, "mosaic_meta.json")

    cv2.imwrite(mosaic_path, mosaic, [cv2.IMWRITE_JPEG_QUALITY, 92])
    cv2.imwrite(heightmap_path, heightmap, [cv2.IMWRITE_JPEG_QUALITY, 95])

    meta = {
        "method": chosen,
        "image_count": len(names),
        "mosaic_w": cw,
        "mosaic_h": ch,
        "bounds": {"min_x": min_x, "min_y": min_y, "max_x": max_x, "max_y": max_y},
        "output_scale": output_scale,
        "match_max_dim": max_dim,
        "elapsed_s": round(elapsed, 3),
        "orthomosaic": os.path.basename(mosaic_path),
        "heightmap": "heightmap.jpg",
        "images": image_meta,
        "alignment": align_info,
        "note": "Fast deterministic stitch (EXIF GPS > phase FFT > ORB partial affine).",
        **extra,
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    if verbose:
        print(f"\nTamam ({elapsed:.2f}s) — {chosen}")
        print(f"  {mosaic_path}  ({cw}x{ch})")
        print(f"  {heightmap_path}")
        print(f"  {meta_path}")

    return meta


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Hizli drone mozaik birlestirme (EXIF GPS / phase / ORB partial)."
    )
    ap.add_argument("--input", "--images", dest="images", default=DEFAULT_IMAGES_DIR,
                    help=f"Kaynak kare klasoru (varsayilan: {DEFAULT_IMAGES_DIR})")
    ap.add_argument("--output", default=DEFAULT_OUTPUT_DIR,
                    help="Cikis dosyasi veya klasor (varsayilan: proje koku / mosaic.jpg)")
    ap.add_argument("--method", default="auto",
                    choices=["auto", "gps", "exif", "phase", "orb",
                             "exif_gps", "phase_correlation", "orb_partial_affine"],
                    help="Yontem secimi (varsayilan: auto)")
    ap.add_argument("--max-dim", type=int, default=640,
                    help="Eslestirme uzun kenar limiti px (varsayilan 640)")
    ap.add_argument("--output-scale", type=float, default=0.35,
                    help="Cikti mozaigin kaynak cozunurluge orani (varsayilan 0.35)")
    ap.add_argument("--nfeatures", type=int, default=500,
                    help="ORB ozellik sayisi (fallback, varsayilan 500)")
    ap.add_argument("--ransac", type=float, default=4.0,
                    help="ORB partial affine RANSAC esik px (varsayilan 4.0)")
    args = ap.parse_args()

    images_dir = os.path.abspath(args.images)
    output = os.path.abspath(args.output)

    if not os.path.isdir(images_dir):
        print(f"HATA: Klasor bulunamadi: {images_dir}", file=sys.stderr)
        print(f"\nDJI drone karelerini su klasore koyun:", file=sys.stderr)
        print(f"  {DEFAULT_IMAGES_DIR}", file=sys.stderr)
        return 1

    output_dir = output
    output_mosaic = None
    if output.lower().endswith((".jpg", ".jpeg", ".png")):
        output_dir = os.path.dirname(output) or HERE
        output_mosaic = output

    try:
        stitch_folder(
            images_dir, output_dir, output_mosaic=output_mosaic,
            max_dim=args.max_dim,
            output_scale=args.output_scale,
            nfeatures=args.nfeatures,
            ransac_thresh=args.ransac,
            method=args.method,
        )
    except FileNotFoundError as exc:
        print(f"HATA: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(f"HATA: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
