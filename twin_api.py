#!/usr/bin/env python3
"""
twin_api.py — Dijital ikiz canlı telemetri ve varlık API'si.

Endpoints:
    GET /api/telemetry  — ortam + bina telemetrisi
    GET /api/assets   — bina/varlık kaydı (buildings.json genişletilmiş)
    GET /api/alarms   — eşik tabanlı alarmlar

Standalone:
    python twin_api.py --port 8001

serve.py aynı portta /api/* yollarını da sunar.
"""

from __future__ import annotations

import json
import math
import random
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

import os

HERE = os.path.dirname(os.path.abspath(__file__))
META_PATH = os.path.join(HERE, "data_real", "site_meta.json")
BUILDINGS_PATH = os.path.join(HERE, "data_real", "buildings.json")

_SEED = int(time.time()) % 100_000
_rng = random.Random(_SEED)
_start = time.time()

# Alarm eşikleri
WATER_LEVEL_WARN_M = 13.0
WATER_LEVEL_CRIT_M = 14.5
ENERGY_WARN_KWH = 40.0
ENERGY_CRIT_KWH = 55.0
OCC_WARN_PCT = 88.0


def _load_json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except OSError:
        return {}


def _building_list() -> list[dict]:
    data = _load_json(BUILDINGS_PATH)
    return data.get("buildings", [])


def _building_count() -> int:
    data = _load_json(BUILDINGS_PATH)
    if "count" in data:
        return int(data["count"])
    return len(data.get("buildings", []))


def get_telemetry(meta: dict | None = None) -> dict[str, Any]:
    """Return current simulated telemetry snapshot."""
    if meta is None:
        meta = _load_json(META_PATH)

    t = time.time() - _start
    n = _building_count()
    wl_base = float(meta.get("water_level_m", 0) or 0)
    buildings_raw = _building_list()

    diurnal = 0.5 + 0.5 * math.sin(t * 0.02)
    temp = 18.0 + 8.0 * diurnal + _rng.uniform(-0.3, 0.3) + math.sin(t * 0.15) * 0.4
    humidity = 55.0 + 20.0 * (1.0 - diurnal) + math.sin(t * 0.11) * 3.0
    wind = 4.0 + 6.0 * abs(math.sin(t * 0.08)) + _rng.uniform(0, 1.5)
    solar = max(0.0, 850.0 * diurnal * (0.7 + 0.3 * math.sin(t * 0.05)))
    water_level = wl_base + math.sin(t * 0.07) * 0.08

    buildings = []
    for i in range(n):
        phase = i * 1.7 + _SEED * 0.01
        occ = 35.0 + 45.0 * abs(math.sin(t * 0.03 + phase)) + _rng.uniform(-2, 2)
        occ = max(0.0, min(100.0, occ))
        energy = 12.0 + occ * 0.35 + abs(math.sin(t * 0.04 + phase)) * 8.0
        warn = occ > OCC_WARN_PCT or energy > ENERGY_WARN_KWH
        raw = buildings_raw[i] if i < len(buildings_raw) else {}
        buildings.append({
            "id": raw.get("id", f"B-{i + 1:03d}"),
            "occupancy_pct": round(occ, 1),
            "energy_kwh": round(energy, 1),
            "status": "warning" if warn else "normal",
            "maintenance": raw.get("last_maintenance", "normal") if i % 17 == 0 else "normal",
        })

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "live": True,
        "environment": {
            "temperature_c": round(temp, 1),
            "humidity_pct": round(humidity, 1),
            "wind_speed_ms": round(wind, 1),
            "solar_irradiance_wm2": round(solar, 0),
            "water_level_m": round(water_level, 3),
        },
        "buildings": buildings,
        "site": {
            "name": meta.get("site_name", "Dijital İkiz Sahası"),
            "building_count": n,
            "twin_version": meta.get("twin_version", "1.0.0"),
        },
    }


def get_assets(meta: dict | None = None) -> dict[str, Any]:
    """Return asset registry from buildings.json with live status overlay."""
    if meta is None:
        meta = _load_json(META_PATH)
    tel = get_telemetry(meta)
    tel_by_id = {b["id"]: b for b in tel["buildings"]}
    buildings_raw = _building_list()
    assets = []
    types = ["konut", "ofis", "depo", "sosyal", "teknik"]
    for i, b in enumerate(buildings_raw):
        bid = b.get("id", f"B-{i + 1:03d}")
        live = tel_by_id.get(bid, {})
        assets.append({
            "id": bid,
            "type": b.get("type", types[i % len(types)]),
            "capacity": b.get("capacity", int(50 + b.get("height_m", 5) * 10)),
            "last_maintenance": b.get("last_maintenance", "2025-06-01"),
            "footprint_m": {
                "u": b.get("u"), "v": b.get("v"),
                "su": b.get("su"), "sv": b.get("sv"),
            },
            "height_m": b.get("height_m"),
            "occupancy_pct": live.get("occupancy_pct", 0),
            "energy_kwh": live.get("energy_kwh", 0),
            "status": live.get("status", "normal"),
        })
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "count": len(assets),
        "assets": assets,
        "site": meta.get("site_name", "Dijital İkiz Sahası"),
    }


def get_alarms(meta: dict | None = None) -> dict[str, Any]:
    """Evaluate threshold-based alarms."""
    if meta is None:
        meta = _load_json(META_PATH)
    tel = get_telemetry(meta)
    env = tel["environment"]
    alarms: list[dict] = []

    wl = env["water_level_m"]
    if wl >= WATER_LEVEL_CRIT_M:
        alarms.append({
            "id": "ALM-WATER-01", "level": "critical", "category": "su",
            "message": f"Su seviyesi kritik: {wl:.2f} m (eşik {WATER_LEVEL_CRIT_M} m)",
            "value": wl, "threshold": WATER_LEVEL_CRIT_M,
        })
    elif wl >= WATER_LEVEL_WARN_M:
        alarms.append({
            "id": "ALM-WATER-01", "level": "warning", "category": "su",
            "message": f"Su seviyesi yükseldi: {wl:.2f} m",
            "value": wl, "threshold": WATER_LEVEL_WARN_M,
        })

    for b in tel["buildings"]:
        if b["energy_kwh"] >= ENERGY_CRIT_KWH:
            alarms.append({
                "id": f"ALM-ENG-{b['id']}", "level": "critical", "category": "enerji",
                "message": f"{b['id']} enerji anomalisi: {b['energy_kwh']:.1f} kWh",
                "value": b["energy_kwh"], "threshold": ENERGY_CRIT_KWH,
            })
        elif b["energy_kwh"] >= ENERGY_WARN_KWH:
            alarms.append({
                "id": f"ALM-ENG-{b['id']}", "level": "warning", "category": "enerji",
                "message": f"{b['id']} yüksek tüketim: {b['energy_kwh']:.1f} kWh",
                "value": b["energy_kwh"], "threshold": ENERGY_WARN_KWH,
            })
        if b["occupancy_pct"] >= OCC_WARN_PCT:
            alarms.append({
                "id": f"ALM-OCC-{b['id']}", "level": "warning", "category": "doluluk",
                "message": f"{b['id']} doluluk %{b['occupancy_pct']:.0f}",
                "value": b["occupancy_pct"], "threshold": OCC_WARN_PCT,
            })

    overall = "ok"
    if any(a["level"] == "critical" for a in alarms):
        overall = "critical"
    elif any(a["level"] == "warning" for a in alarms):
        overall = "warning"

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "overall": overall,
        "count": len(alarms),
        "alarms": alarms,
    }


ROUTES = {
    "/api/telemetry": get_telemetry,
    "/api/assets": get_assets,
    "/api/alarms": get_alarms,
}


class TwinAPIHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print("  [api]", self.address_string(), "-", fmt % args)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Cache-Control", "no-store")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        handler = ROUTES.get(path)
        if not handler:
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self._cors()
            self.end_headers()
            self.wfile.write(b'{"error":"not found"}')
            return
        body = json.dumps(handler(), ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Dijital ikiz telemetri/varlık API.")
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=8001)
    args = ap.parse_args()
    httpd = ThreadingHTTPServer((args.host, args.port), TwinAPIHandler)
    print(f"Twin API: http://{args.host}:{args.port}")
    print("  /api/telemetry  /api/assets  /api/alarms")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        httpd.server_close()


if __name__ == "__main__":
    main()
