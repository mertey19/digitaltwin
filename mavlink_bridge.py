#!/usr/bin/env python3
"""
mavlink_bridge.py — MAVLink (Pixhawk / SITL) telemetrisini Unity GroundStation
Digital Twin'e (DigitalTwinMessageV1, UDP 19090, JSON) koprular.

Dinlenen MAVLink mesajlari:
    HEARTBEAT           -> mode (mavutil.mode_string_v10), armed
    GLOBAL_POSITION_INT -> lat / lon / relative alt / vx,vy (hiz fallback) / hdg
    VFR_HUD             -> groundspeed, heading (tercih edilen hiz/yon)
    ATTITUDE            -> yaw / pitch / roll (radyan -> derece)
    SYS_STATUS          -> voltage_battery (mV -> V), battery_remaining (%)
    MISSION_CURRENT     -> waypointIndex

Kullanim:
    # Gercek Pixhawk (telemetri radyosu / USB):
    python mavlink_bridge.py --conn com5,57600                 # Windows seri
    python mavlink_bridge.py --conn /dev/ttyACM0,115200        # Linux seri

    # SITL / MAVProxy udp cikisi:
    python mavlink_bridge.py --conn udp:0.0.0.0:14550

    # GroundStation baska makinede:
    python mavlink_bridge.py --conn udp:0.0.0.0:14550 --target 192.168.1.20:19090

    # MAVLink olmadan test (sahte ama gercekci telemetri):
    python mavlink_bridge.py --dry-run

    # Linux mesh metrikleri (batctl / iw; basarisizsa sessizce atlanir):
    python mavlink_bridge.py --conn udp:0.0.0.0:14550 --mesh-iface bat0

Bagimlilik: pip install pymavlink   (--dry-run icin gerekmez)
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import random
import re
import socket
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# pymavlink istege bagli: --dry-run icin gerekmez, py_compile her zaman gecmeli.
try:
    from pymavlink import mavutil  # type: ignore
except ImportError:
    mavutil = None

SCHEMA_VERSION = "1.0"
DEFAULT_SOURCE_ID = "mavlink-bridge"
DEFAULT_AUTH = "simurgh-2026"
VALID_PHASES = ("scan", "joint_operation", "dynamic_replan", "complete")


# ---------------------------------------------------------------------------
# Arac durumu (son gelen MAVLink verileri)
# ---------------------------------------------------------------------------

class VehicleState:
    """MAVLink akisından toplanan son telemetri degerleri."""

    def __init__(self) -> None:
        self.lat: float = 0.0
        self.lon: float = 0.0
        self.alt_m: float = 0.0            # relative alt (m)
        self.yaw_deg: float = 0.0
        self.pitch_deg: float = 0.0
        self.roll_deg: float = 0.0
        self.speed_mps: float = 0.0
        self.mode: str = "UNKNOWN"
        self.armed: bool = False
        self.waypoint_index: int = 0
        self.battery_percent: float | None = None
        self.battery_voltage: float | None = None
        self.have_position: bool = False
        self.last_vfr_hud_ts: float = 0.0
        self.last_msg_ts: float = 0.0


def update_state_from_msg(state: VehicleState, msg) -> None:
    """Gelen MAVLink mesajini VehicleState'e isler. Asla exception firlatmaz."""
    try:
        mtype = msg.get_type()
        now = time.time()
        state.last_msg_ts = now

        if mtype == "HEARTBEAT":
            # mode adi aynen gecsin (RTL/AUTO/GUIDED...) — Unity RTL tespiti icin.
            try:
                if mavutil is not None:
                    state.mode = mavutil.mode_string_v10(msg)
            except Exception:
                pass
            try:
                state.armed = bool(msg.base_mode & 0x80)  # MAV_MODE_FLAG_SAFETY_ARMED
            except Exception:
                pass

        elif mtype == "GLOBAL_POSITION_INT":
            state.lat = msg.lat / 1e7
            state.lon = msg.lon / 1e7
            state.alt_m = msg.relative_alt / 1000.0
            state.have_position = True
            # VFR_HUD yakin zamanda gelmediyse hizi vx/vy'den hesapla (cm/s).
            if now - state.last_vfr_hud_ts > 3.0:
                state.speed_mps = math.hypot(msg.vx / 100.0, msg.vy / 100.0)
                if getattr(msg, "hdg", 65535) != 65535:
                    state.yaw_deg = msg.hdg / 100.0

        elif mtype == "VFR_HUD":
            state.speed_mps = float(msg.groundspeed)
            state.last_vfr_hud_ts = now

        elif mtype == "ATTITUDE":
            state.yaw_deg = math.degrees(msg.yaw) % 360.0
            state.pitch_deg = math.degrees(msg.pitch)
            state.roll_deg = math.degrees(msg.roll)

        elif mtype == "SYS_STATUS":
            if getattr(msg, "voltage_battery", 65535) != 65535:
                state.battery_voltage = msg.voltage_battery / 1000.0  # mV -> V
            if getattr(msg, "battery_remaining", -1) >= 0:
                state.battery_percent = float(msg.battery_remaining)

        elif mtype == "MISSION_CURRENT":
            state.waypoint_index = int(msg.seq)
    except Exception:
        # Bozuk / beklenmedik mesaj koprunun calismasini durdurmasin.
        pass


# ---------------------------------------------------------------------------
# Mesh metrikleri (batctl / iw) — yalnizca Linux, basarisizsa None
# ---------------------------------------------------------------------------

class MeshLinkReader:
    """`batctl o` veya `iw dev <iface> station dump` ciktisindan mesh metrikleri.

    Windows'ta otomatik devre disi. Art arda cok hata olursa kendini kapatir;
    hicbir kosulda exception yukari tasimaz (basarisizlik -> None).
    """

    def __init__(self, iface: str | None, refresh_s: float = 2.0) -> None:
        self.iface = iface
        self.refresh_s = refresh_s
        self.enabled = bool(iface) and platform.system() != "Windows" and os.name != "nt"
        self._cache: dict | None = None
        self._last_read: float = 0.0
        self._fail_count: int = 0
        if iface and not self.enabled:
            print("Mesh: Windows'ta batctl/iw yok — meshLink atlanacak.")

    def read(self) -> dict | None:
        if not self.enabled:
            return None
        now = time.time()
        if now - self._last_read < self.refresh_s:
            return self._cache
        self._last_read = now
        metrics = None
        try:
            metrics = self._read_batctl() or self._read_iw()
        except Exception:
            metrics = None
        if metrics is None:
            self._fail_count += 1
            if self._fail_count >= 5:
                print("Mesh: batctl/iw okunamadi, meshLink devre disi birakildi.")
                self.enabled = False
        else:
            self._fail_count = 0
        self._cache = metrics
        return metrics

    def _run(self, cmd: list[str]) -> str | None:
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=2.0)
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout
        except Exception:
            pass
        return None

    def _read_batctl(self) -> dict | None:
        """batman-adv originator tablosu: TQ (0-255) -> linkQualityPercent."""
        out = None
        for cmd in (["batctl", "meshif", self.iface, "o"],
                    ["batctl", "-m", self.iface, "o"],
                    ["batctl", "o"]):
            out = self._run(cmd)
            if out:
                break
        if not out:
            return None
        best_tq = -1
        hop_count = 1
        mac_re = r"([0-9a-fA-F:]{17})"
        for line in out.splitlines():
            m = re.search(r"\*?\s*" + mac_re + r"\s+[\d.]+s\s+\(\s*(\d+)\s*\)\s+" + mac_re, line)
            if not m:
                continue
            originator, tq, nexthop = m.group(1), int(m.group(2)), m.group(3)
            if tq > best_tq:
                best_tq = tq
                hop_count = 1 if originator.lower() == nexthop.lower() else 2
        if best_tq < 0:
            return None
        quality = best_tq / 255.0 * 100.0
        # TQ'dan kaba sinyal tahmini: 255 -> ~-45 dBm, 0 -> ~-95 dBm
        signal_dbm = -95.0 + (best_tq / 255.0) * 50.0
        return {
            "hopCount": hop_count,
            "signalDbm": round(signal_dbm, 1),
            "snrDb": round(max(0.0, signal_dbm + 95.0), 1),
            "latencyMs": 30.0 + (2 - hop_count) * 0.0 + (hop_count - 1) * 25.0,
            "packetLossPercent": round(max(0.0, (100.0 - quality) * 0.1), 2),
            "linkQualityPercent": round(quality, 1),
            "relayModeActive": hop_count > 1,
        }

    def _read_iw(self) -> dict | None:
        """802.11s / adhoc istasyon dokumu: signal dBm + tx istatistikleri."""
        out = self._run(["iw", "dev", self.iface, "station", "dump"])
        if not out:
            return None
        signal = None
        tx_packets = tx_failed = None
        m = re.search(r"signal avg:\s*(-?\d+)", out) or re.search(r"signal:\s*(-?\d+)", out)
        if m:
            signal = float(m.group(1))
        m = re.search(r"tx packets:\s*(\d+)", out)
        if m:
            tx_packets = int(m.group(1))
        m = re.search(r"tx failed:\s*(\d+)", out)
        if m:
            tx_failed = int(m.group(1))
        if signal is None:
            return None
        snr = max(0.0, signal + 95.0)  # ~-95 dBm gurultu tabani varsayimi
        loss = 0.0
        if tx_packets and tx_failed is not None and tx_packets > 0:
            loss = min(100.0, tx_failed / tx_packets * 100.0)
        quality = max(0.0, min(100.0, (signal + 90.0) / 40.0 * 100.0))
        return {
            "hopCount": 1,
            "signalDbm": round(signal, 1),
            "snrDb": round(snr, 1),
            "latencyMs": 25.0,
            "packetLossPercent": round(loss, 2),
            "linkQualityPercent": round(quality, 1),
            "relayModeActive": False,
        }


# ---------------------------------------------------------------------------
# Dry-run simulasyonu (MAVLink baglantisi olmadan gercekci telemetri)
# ---------------------------------------------------------------------------

class DryRunSimulator:
    """Daire ucusu + batarya bosalmasi + QR hedefi ile sahte gorev uretir."""

    def __init__(self, home_lat: float, home_lon: float) -> None:
        self.home_lat = home_lat
        self.home_lon = home_lon
        self.t = 0.0
        self.radius_m = 80.0
        self.speed_mps = 8.0
        self.battery = 100.0
        self.qr_reached = False
        self.qr_angle = math.pi / 3  # QR hedefinin dairedeki konumu

    def _offset(self, north_m: float, east_m: float) -> tuple[float, float]:
        dlat = north_m / 111320.0
        dlon = east_m / (111320.0 * max(0.2, math.cos(math.radians(self.home_lat))))
        return self.home_lat + dlat, self.home_lon + dlon

    def step(self, dt: float, state: VehicleState) -> tuple[str, dict | None, list]:
        """State'i ilerletir; (missionPhase, meshLink, targets) dondurur."""
        self.t += dt
        self.battery = max(15.0, self.battery - dt * 0.12)

        # Faz zamanlamasi: kalkis -> tarama -> ortak gorev -> RTL/tamamlandi
        if self.t < 8.0:
            mode, phase = "GUIDED", "scan"
            alt = 4.0 * self.t          # tirmanis
            angle = 0.0
            speed = 2.5
        elif self.battery > 35.0:
            mode = "AUTO"
            phase = "joint_operation" if self.qr_reached else "scan"
            alt = 32.0 + 3.0 * math.sin(self.t * 0.15)
            angle = (self.t - 8.0) * self.speed_mps / self.radius_m
            speed = self.speed_mps + random.uniform(-0.4, 0.4)
        else:
            mode, phase = "RTL", "complete"
            alt = max(5.0, 32.0 - (35.0 - self.battery) * 4.0)
            angle = (self.t - 8.0) * self.speed_mps / self.radius_m
            speed = 6.0

        north = self.radius_m * math.cos(angle)
        east = self.radius_m * math.sin(angle)
        state.lat, state.lon = self._offset(north, east)
        state.alt_m = alt + random.uniform(-0.2, 0.2)
        state.yaw_deg = (math.degrees(angle) + 90.0) % 360.0
        state.pitch_deg = random.uniform(-3.0, 1.0)
        state.roll_deg = 12.0 * math.sin(angle) + random.uniform(-1.0, 1.0)
        state.speed_mps = max(0.0, speed)
        state.mode = mode
        state.armed = True
        state.waypoint_index = int(angle / (math.pi / 2)) % 8
        state.battery_percent = round(self.battery, 1)
        state.battery_voltage = round(10.5 + (self.battery / 100.0) * 2.1, 2)  # 3S LiPo
        state.have_position = True
        state.last_msg_ts = time.time()

        # QR hedefi: drone yaklastiginda "reached" + decodedContent
        qr_lat, qr_lon = self._offset(self.radius_m * math.cos(self.qr_angle),
                                      self.radius_m * math.sin(self.qr_angle))
        ang_diff = abs((angle - self.qr_angle + math.pi) % (2 * math.pi) - math.pi)
        if not self.qr_reached and self.t > 8.0 and ang_diff < 0.08:
            self.qr_reached = True
        targets = [{
            "id": "qr-1",
            "operation": "upsert",
            "kind": "qrcode",
            "latitude": qr_lat,
            "longitude": qr_lon,
            "reached": self.qr_reached,
            "confidence": 0.95 if self.qr_reached else 0.6,
            "decodedContent": "SIMURGH-QR-001" if self.qr_reached else "",
        }]

        # Sahte ama tutarli mesh metrikleri
        signal = -52.0 - 8.0 * math.sin(self.t * 0.05) + random.uniform(-2.0, 2.0)
        hop = 2 if signal < -62.0 else 1
        quality = max(0.0, min(100.0, (signal + 90.0) / 40.0 * 100.0))
        mesh = {
            "hopCount": hop,
            "signalDbm": round(signal, 1),
            "snrDb": round(signal + 95.0, 1),
            "latencyMs": round(35.0 + (hop - 1) * 30.0 + random.uniform(-5.0, 5.0), 1),
            "packetLossPercent": round(random.uniform(0.0, 1.5) + (hop - 1) * 1.0, 2),
            "linkQualityPercent": round(quality, 1),
            "relayModeActive": hop > 1,
        }
        return phase, mesh, targets


# ---------------------------------------------------------------------------
# DigitalTwinMessageV1 uretimi
# ---------------------------------------------------------------------------

def build_twin_message(state: VehicleState, seq: int, args,
                       mission_phase: str,
                       mesh: dict | None,
                       targets: list | None) -> dict:
    """VehicleState'ten DigitalTwinMessageV1 sozlugu uretir."""
    battery_pct = state.battery_percent if state.battery_percent is not None else 100.0
    battery_v = state.battery_voltage if state.battery_voltage is not None else 12.6

    # Link metrikleri: mesh varsa oradan, yoksa makul varsayilanlar.
    if mesh:
        hop = mesh["hopCount"]
        signal = mesh["signalDbm"]
        snr = mesh["snrDb"]
        latency = mesh["latencyMs"]
        loss = mesh["packetLossPercent"]
    else:
        hop, signal, snr, latency, loss = 1, -60.0, 20.0, 40.0, 0.5

    # slamPose: gercek poz + kucuk drift (SLAM belirsizligi) + confidence
    conf = max(0.55, min(0.99, 0.97 - state.speed_mps * 0.01 + random.uniform(-0.02, 0.02)))
    slam_pose = {
        "latitude": state.lat + random.uniform(-1.5e-6, 1.5e-6),
        "longitude": state.lon + random.uniform(-1.5e-6, 1.5e-6),
        "altitudeM": state.alt_m + random.uniform(-0.3, 0.3),
        "yawDeg": (state.yaw_deg + random.uniform(-1.2, 1.2)) % 360.0,
        "pitchDeg": state.pitch_deg + random.uniform(-0.4, 0.4),
        "rollDeg": state.roll_deg + random.uniform(-0.4, 0.4),
        "confidence": round(conf, 3),
    }

    mode_upper = (state.mode or "").upper()
    if mission_phase not in VALID_PHASES:
        mission_phase = "scan"
    status = "running" if state.armed else "idle"
    warning = ""
    if mode_upper == "RTL":
        warning = "RTL aktif — arac eve donuyor"
    elif battery_pct < 25.0:
        warning = f"Dusuk batarya: %{battery_pct:.0f}"

    msg = {
        "schemaVersion": SCHEMA_VERSION,
        "sequenceId": seq,
        "timestampMs": int(time.time() * 1000),
        "sourceId": args.source_id,
        "authToken": args.auth,
        "vehicleType": args.vehicle_type,
        "missionPhase": mission_phase,
        "pose": {
            "latitude": state.lat,
            "longitude": state.lon,
            "altitudeM": state.alt_m,
            "yawDeg": state.yaw_deg,
            "pitchDeg": state.pitch_deg,
            "rollDeg": state.roll_deg,
        },
        "slamPose": slam_pose,
        "telemetry": {
            "altitudeM": state.alt_m,
            "speedMps": round(state.speed_mps, 2),
            "mode": state.mode,
            "waypointIndex": state.waypoint_index,
            "hopCount": hop,
            "signalDbm": signal,
            "snrDb": snr,
            "latencyMs": latency,
            "packetLossPercent": loss,
            "batteryPercent": round(battery_pct, 1),
            "batteryVoltage": round(battery_v, 2),
        },
        "mission": {
            "phase": mission_phase,
            "status": status,
            "activeVehicle": args.vehicle_type,
            "warning": warning,
            "note": f"mode={state.mode} armed={state.armed}",
        },
    }
    if mesh is not None:
        msg["meshLink"] = mesh
    if targets:
        msg["targets"] = targets
    return msg


def phase_from_state(state: VehicleState, default_phase: str) -> str:
    """Ucus modundan missionPhase tahmini (gercek MAVLink modunda)."""
    mode = (state.mode or "").upper()
    if mode in ("RTL", "LAND", "SMART_RTL", "QRTL"):
        return "complete"
    return default_phase


# ---------------------------------------------------------------------------
# Ana dongu
# ---------------------------------------------------------------------------

def parse_target(value: str) -> tuple[str, int]:
    host, _, port = value.rpartition(":")
    if not host:
        raise argparse.ArgumentTypeError(f"Gecersiz hedef: {value} (IP:PORT bekleniyor)")
    return host, int(port)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="MAVLink -> GroundStation DigitalTwinMessageV1 UDP koprusu")
    ap.add_argument("--conn", default="udp:0.0.0.0:14550",
                    help="MAVLink baglantisi (udp:0.0.0.0:14550, com5,57600, /dev/ttyACM0,115200)")
    ap.add_argument("--target", default="127.0.0.1:19090",
                    help="GroundStation UDP hedefi IP:PORT (varsayilan 127.0.0.1:19090)")
    ap.add_argument("--rate", type=float, default=5.0,
                    help="Gonderim frekansi Hz (varsayilan 5)")
    ap.add_argument("--auth", default=DEFAULT_AUTH, help="authToken")
    ap.add_argument("--source-id", default=DEFAULT_SOURCE_ID, help="sourceId alani")
    ap.add_argument("--vehicle-type", default="uav", choices=("uav", "rover"))
    ap.add_argument("--phase", default="scan", choices=VALID_PHASES,
                    help="Varsayilan missionPhase (RTL/LAND'de otomatik 'complete')")
    ap.add_argument("--mesh-iface", default=None,
                    help="Mesh arayuzu (bat0 / wlan0); Linux'ta batctl/iw denenir")
    ap.add_argument("--dry-run", action="store_true",
                    help="MAVLink'e baglanmadan sahte gercekci telemetri uret")
    ap.add_argument("--home-lat", type=float, default=40.2306,
                    help="--dry-run merkez enlem")
    ap.add_argument("--home-lon", type=float, default=28.8720,
                    help="--dry-run merkez boylam")
    ap.add_argument("--verbose", action="store_true", help="Her paketi yazdir")
    args = ap.parse_args()

    try:
        target = parse_target(args.target)
    except (ValueError, argparse.ArgumentTypeError) as exc:
        print(f"HATA: {exc}", file=sys.stderr)
        return 1

    rate = max(0.1, args.rate)
    period = 1.0 / rate

    conn = None
    sim = None
    if args.dry_run:
        sim = DryRunSimulator(args.home_lat, args.home_lon)
        print(f"DRY-RUN: sahte telemetri ({args.home_lat:.4f}, {args.home_lon:.4f}) merkezli")
    else:
        if mavutil is None:
            print("HATA: pymavlink kurulu degil. MAVLink baglantisi icin:\n"
                  "    pip install pymavlink\n"
                  "MAVLink olmadan test icin: python mavlink_bridge.py --dry-run",
                  file=sys.stderr)
            return 1
        conn_str = args.conn
        baud = 115200
        if "," in conn_str:  # "com5,57600" / "/dev/ttyACM0,115200"
            conn_str, baud_s = conn_str.split(",", 1)
            try:
                baud = int(baud_s)
            except ValueError:
                pass
        print(f"MAVLink baglaniliyor: {conn_str} ...")
        try:
            conn = mavutil.mavlink_connection(conn_str, baud=baud)
        except Exception as exc:
            print(f"HATA: MAVLink baglantisi acilamadi: {exc}", file=sys.stderr)
            return 1
        print("Heartbeat bekleniyor (Ctrl+C ile iptal)...")
        try:
            while True:
                hb = conn.recv_match(type="HEARTBEAT", blocking=True, timeout=5)
                if hb is not None:
                    break
                print("  ... heartbeat yok, bekleniyor")
        except KeyboardInterrupt:
            print("\nIptal edildi.")
            return 0
        print(f"Heartbeat alindi (sistem {conn.target_system}).")

    mesh_reader = MeshLinkReader(args.mesh_iface)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    state = VehicleState()
    seq = 0
    sent = 0
    print(f"GroundStation -> {target[0]}:{target[1]} @ {rate:g} Hz | "
          f"source={args.source_id} vehicle={args.vehicle_type}")
    print("Durdurmak icin Ctrl+C")

    next_send = time.time()
    last_report = time.time()
    try:
        while True:
            now = time.time()
            if sim is not None:
                # Dry-run: bir periyot ilerlet, uyut.
                phase, mesh, targets = sim.step(period, state)
                time.sleep(period)
            else:
                # MAVLink oku (gonderim zamanina kadar blokla).
                timeout = max(0.01, next_send - now)
                msg = conn.recv_match(blocking=True, timeout=min(timeout, 0.25))
                if msg is not None:
                    update_state_from_msg(state, msg)
                if time.time() < next_send:
                    continue
                phase = phase_from_state(state, args.phase)
                mesh = mesh_reader.read()
                targets = None
                if not state.have_position:
                    # Konum gelmeden paket gondermenin anlami yok.
                    if time.time() - last_report > 5.0:
                        print("  GLOBAL_POSITION_INT bekleniyor (GPS fix?)...")
                        last_report = time.time()
                    next_send = time.time() + period
                    continue

            seq += 1
            twin_msg = build_twin_message(state, seq, args, phase, mesh, targets)
            payload = json.dumps(twin_msg, separators=(",", ":")).encode("utf-8")
            sock.sendto(payload, target)
            sent += 1
            next_send = max(next_send + period, time.time())

            if args.verbose:
                print(f"  [{seq}] {len(payload)}B mode={state.mode} "
                      f"alt={state.alt_m:.1f}m spd={state.speed_mps:.1f}m/s "
                      f"bat=%{twin_msg['telemetry']['batteryPercent']}")
            elif time.time() - last_report >= 2.0:
                print(f"  [{seq}] gonderildi | mode={state.mode} phase={phase} "
                      f"alt={state.alt_m:.1f}m spd={state.speed_mps:.1f}m/s "
                      f"bat=%{twin_msg['telemetry']['batteryPercent']} "
                      f"mesh={'ok' if mesh else '-'}")
                last_report = time.time()
    except KeyboardInterrupt:
        print(f"\nDurduruldu. Toplam {sent} paket gonderildi.")
    finally:
        sock.close()
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
