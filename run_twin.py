#!/usr/bin/env python3
"""
run_twin.py — Tek komutla dijital ikiz hattı.

Sıra: images/ varsa stitch → ingest → (isteğe bağlı) serve + twin_api

Usage:
    python run_twin.py                  # stitch (gerekirse) + ingest
    python run_twin.py --serve          # ingest sonrası sunucuları başlat
    python run_twin.py --serve --port 8765
    python run_twin.py --no-stitch      # yalnızca ingest (mosaic.jpg mevcut)
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
IMAGES_DIR = os.path.join(HERE, "images")
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff",
              ".JPG", ".JPEG", ".PNG"}


def has_images(folder: str) -> bool:
    if not os.path.isdir(folder):
        return False
    return any(os.path.splitext(f)[1] in IMAGE_EXTS for f in os.listdir(folder))


def run_cmd(label: str, args: list[str]) -> int:
    print(f"\n{'='*60}\n{label}\n{'='*60}")
    print(" ", " ".join(args))
    rc = subprocess.call(args, cwd=HERE)
    if rc != 0:
        print(f"HATA: {label} başarısız (kod {rc})", file=sys.stderr)
    return rc


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Dijital ikiz hattı: stitch → ingest → serve"
    )
    ap.add_argument("--no-stitch", action="store_true",
                    help="Stitch atla (mosaic.jpg zaten var)")
    ap.add_argument("--serve", action="store_true",
                    help="Ingest sonrası serve.py başlat")
    ap.add_argument("--api-port", type=int, default=8001,
                    help="twin_api.py portu (varsayılan 8001)")
    ap.add_argument("--port", type=int, default=8000,
                    help="serve.py portu (varsayılan 8000)")
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--gsd", type=float, default=0.15)
    ap.add_argument("--max-elev", type=float, default=16.0)
    ap.add_argument("--min-elev", type=float, default=0.0)
    ap.add_argument("--stitch-method", default="auto")
    args = ap.parse_args()

    py = sys.executable

    # 1) Stitch
    if not args.no_stitch and has_images(IMAGES_DIR):
        rc = run_cmd(
            "[1/3] Mozaik birleştirme",
            [py, "stitch_mosaic.py", "--input", IMAGES_DIR,
             "--output", os.path.join(HERE, "mosaic.jpg"),
             "--method", args.stitch_method],
        )
        if rc != 0:
            return rc
    elif not os.path.exists(os.path.join(HERE, "mosaic.jpg")):
        print("\nUyarı: mosaic.jpg yok ve images/ boş — mevcut dosyalarla devam.")

    # 2) Ingest
    ingest_args = [
        py, "ingest_real_dataset.py",
        "--gsd", str(args.gsd),
        "--min-elev", str(args.min_elev),
        "--max-elev", str(args.max_elev),
    ]
    if args.no_stitch or not has_images(IMAGES_DIR):
        pass  # ingest kendi stitch kararını verir
    rc = run_cmd("[2/3] Veri sindirme (ingest)", ingest_args)
    if rc != 0:
        return rc

    print("\n✓ data_real/ hazır.")
    print(f"  twin.html → http://{args.host}:{args.port}/twin.html")
    print(f"  viewer.html → http://{args.host}:{args.port}/viewer.html")

    if not args.serve:
        print("\nSunucuyu başlatmak için: python run_twin.py --serve")
        return 0

    # 3) Serve
    print(f"\n{'='*60}\n[3/3] Sunucular başlatılıyor\n{'='*60}")

    api_proc = subprocess.Popen(
        [py, "twin_api.py", "--host", args.host, "--port", str(args.api_port)],
        cwd=HERE,
    )
    time.sleep(0.5)

    serve_proc = subprocess.Popen(
        [py, "serve.py", "--host", args.host, "--port", str(args.port),
         "--no-browser", "--page", "twin.html"],
        cwd=HERE,
    )

    print(f"\n  Ana sayfa:  http://{args.host}:{args.port}/twin.html")
    print(f"  API:        http://{args.host}:{args.port}/api/telemetry")
    print(f"  Standalone: http://{args.host}:{args.api_port}/api/telemetry")
    print("\nDurdurmak için Ctrl+C")

    try:
        serve_proc.wait()
    except KeyboardInterrupt:
        print("\nDurduruluyor…")
    finally:
        for p in (serve_proc, api_proc):
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    p.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
