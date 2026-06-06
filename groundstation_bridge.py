#!/usr/bin/env python3
"""
groundstation_bridge.py — digital-twin saha verisini Unity GroundStation
Digital Twin'e (DigitalTwinMessageV1 / UDP) koprular.

GroundStation tarafi:
    - DigitalTwinUdpIngress  : UDP 19090 dinler, ACK 19091
    - DigitalTwinJsonPoseBridge : mesaji uygular
    - DigitalTwinImageryService : `imagery` blogundaki goruntuyu
      StreamingAssets'ten yukleyip Twin viewport'a basar.

Bu kopru:
    1) (--copy-to) aukerman orthophoto + json'lari GroundStation
       StreamingAssets/SimurghTwin/ altina kopyalar.
    2) `imagery` blogu (net orthophoto) + `pose` (saha merkezi, site_meta georef)
       iceren DigitalTwinMessageV1 mesajini UDP ile gonderir.

Kullanim:
    # Once veriyi StreamingAssets'e kopyala (bir kez):
    python groundstation_bridge.py --copy-to "C:/.../groundstation-main/groundstation-main/Assets/StreamingAssets"

    # GroundStation Play modundayken imagery'yi gonder (suruekli):
    python groundstation_bridge.py
    # Tek sefer:
    python groundstation_bridge.py --once
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ASSET_NAMES = ("orthomosaic.jpg", "buildings.json", "trees.json",
               "site_meta.json", "heightmap.png", "normalmap.png")


def load_meta(data_dir: str) -> dict:
    with open(os.path.join(data_dir, "site_meta.json"), encoding="utf-8") as f:
        return json.load(f)


def copy_assets(data_dir: str, streaming_assets_dir: str, sub: str = "SimurghTwin") -> str:
    dst = os.path.join(streaming_assets_dir, sub)
    os.makedirs(dst, exist_ok=True)
    for name in ASSET_NAMES:
        src = os.path.join(data_dir, name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(dst, name))
            print(f"  kopyalandi: {sub}/{name}")
    return dst


def build_message(meta: dict, seq: int, image_rel: str, auth: str) -> dict:
    """GroundStation DigitalTwinMessageV1 semasi (imagery + pose)."""
    g = meta.get("georef", {}) or {}
    lat = float(g.get("origin_lat", 0.0) or 0.0)
    lon = float(g.get("origin_lon", 0.0) or 0.0)
    # site_meta georef saha kuzey-bati kosesi; merkezi yaklasik olarak kaydir.
    return {
        "schemaVersion": "1.0",
        "sequenceId": seq,
        "timestampMs": int(time.time() * 1000),
        "sourceId": "digital-twin-bridge",
        "authToken": auth,
        "vehicleType": "uav",
        "missionPhase": "scan",
        "pose": {
            "latitude": lat,
            "longitude": lon,
            "altitudeM": float(meta.get("max_elev_m", 30.0) or 30.0),
            "yawDeg": 0.0, "pitchDeg": 0.0, "rollDeg": 0.0,
        },
        "imagery": {
            "pipeline": "custom",
            "mode": "single_mosaic",
            "label": meta.get("site_name", "Digital Twin Site"),
            "streamingAssetsFile": image_rel,
            "streamingAssetsFolder": "",
            "fileNamePattern": "frame_{0:D4}.png",
            "frameNumber": 0,
            "resourceTexturePath": "",
            "overlayAlpha": 0.92,
            "streamingAssetsVideoFile": "",
            "videoLoopMode": "",
        },
        "ackRequested": False,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="digital-twin -> GroundStation UDP/imagery koprusu")
    ap.add_argument("--data", default=os.path.join(HERE, "data_real"),
                    help="Saha verisi klasoru (varsayilan: data_real)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=19090, help="GroundStation UDP ingress (varsayilan 19090)")
    ap.add_argument("--auth", default="simurgh-2026", help="authToken (README ile ayni olmali)")
    ap.add_argument("--image-rel", default="SimurghTwin/orthomosaic.jpg",
                    help="StreamingAssets altinda goreceli orthophoto yolu")
    ap.add_argument("--interval", type=float, default=2.0, help="Gonderim araligi (sn)")
    ap.add_argument("--once", action="store_true", help="Tek mesaj gonder ve cik")
    ap.add_argument("--copy-to", default=None,
                    help="GroundStation StreamingAssets yolu; verilirse veri oraya kopyalanir")
    args = ap.parse_args()

    if not os.path.isfile(os.path.join(args.data, "site_meta.json")):
        print(f"HATA: site_meta.json yok: {args.data}", file=sys.stderr)
        return 1
    meta = load_meta(args.data)

    if args.copy_to:
        print(f"Veri kopyalaniyor -> {args.copy_to}")
        copy_assets(args.data, args.copy_to)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    seq = 0
    print(f"GroundStation -> {args.host}:{args.port} | imagery={args.image_rel} | site={meta.get('site_name')}")
    print("Durdurmak icin Ctrl+C")
    try:
        while True:
            seq += 1
            msg = build_message(meta, seq, args.image_rel, args.auth)
            payload = json.dumps(msg).encode("utf-8")
            sock.sendto(payload, (args.host, args.port))
            print(f"  [{seq}] gonderildi ({len(payload)} byte)")
            if args.once:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nDurduruldu.")
    finally:
        sock.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
