#!/usr/bin/env python3
"""Minimal WebSocket (RFC 6455) helpers for telemetry push."""

from __future__ import annotations

import base64
import hashlib
import struct
import threading
import time
from typing import Callable

WS_MAGIC = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def accept_key(key: str) -> str:
    digest = hashlib.sha1((key + WS_MAGIC).encode()).digest()
    return base64.b64encode(digest).decode()


def send_text(wfile, text: str) -> None:
    payload = text.encode("utf-8")
    ln = len(payload)
    header = bytearray([0x81])
    if ln <= 125:
        header.append(ln)
    elif ln <= 65535:
        header.append(126)
        header.extend(struct.pack(">H", ln))
    else:
        header.append(127)
        header.extend(struct.pack(">Q", ln))
    header.extend(payload)
    wfile.write(bytes(header))
    wfile.flush()


def read_frame(rfile) -> tuple[int, bytes] | None:
    try:
        hdr = rfile.read(2)
        if len(hdr) < 2:
            return None
        b0, b1 = hdr[0], hdr[1]
        opcode = b0 & 0x0F
        masked = bool(b1 & 0x80)
        ln = b1 & 0x7F
        if ln == 126:
            ln = struct.unpack(">H", rfile.read(2))[0]
        elif ln == 127:
            ln = struct.unpack(">Q", rfile.read(8))[0]
        mask = rfile.read(4) if masked else b""
        payload = rfile.read(ln) if ln else b""
        if masked and mask:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        return opcode, payload
    except OSError:
        return None


def pump_telemetry(handler, get_payload: Callable[[], str], interval: float = 2.0) -> None:
    """Background loop: push JSON telemetry until client disconnects."""
    rfile = handler.rfile
    wfile = handler.wfile
    try:
        send_text(wfile, get_payload())
        while True:
            frame = read_frame(rfile)
            if frame is None:
                break
            opcode, _ = frame
            if opcode == 0x8:
                break
            if opcode == 0x9:
                send_text(wfile, get_payload())
            time.sleep(interval)
            send_text(wfile, get_payload())
    except (OSError, ConnectionResetError, BrokenPipeError):
        pass


def start_ws_thread(handler, get_payload: Callable[[], str]) -> threading.Thread:
    t = threading.Thread(target=pump_telemetry, args=(handler, get_payload), daemon=True)
    t.start()
    return t
