#!/usr/bin/env python3
"""
serve.py — static file server + telemetry/asset/alarm API for the digital twin.

Usage:
    python serve.py
    python serve.py --port 8080
then open:  http://localhost:8000/          → twin.html (varsayılan)
            http://localhost:8000/twin.html  (dijital ikiz platformu)
            http://localhost:8000/viewer.html (klasik görüntüleyici)
"""

import argparse
import json
import os
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))

API_ROUTES = ("/api/telemetry", "/api/assets", "/api/alarms")


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        print("  ", self.address_string(), "-", fmt % args)

    def _cors_json(self, body: bytes, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path

        # Root → twin.html
        if path in ("/", "/index.html"):
            self.send_response(302)
            self.send_header("Location", "/twin.html")
            self.end_headers()
            return

        if path in API_ROUTES:
            try:
                from twin_api import ROUTES
                handler = ROUTES.get(path)
                if handler:
                    body = json.dumps(handler(), ensure_ascii=False).encode("utf-8")
                    self._cors_json(body)
                    return
            except Exception as exc:
                body = json.dumps({"error": str(exc)}).encode("utf-8")
                self._cors_json(body, 500)
                return

        super().do_GET()

    def do_OPTIONS(self):
        path = urlparse(self.path).path
        if path in API_ROUTES:
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.end_headers()
            return
        super().do_OPTIONS()


def main():
    ap = argparse.ArgumentParser(description="Serve the digital twin over http.")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--no-browser", action="store_true",
                    help="Do not auto-open the browser.")
    ap.add_argument("--page", default="twin.html",
                    help="Page to open in browser (default: twin.html).")
    args = ap.parse_args()

    handler = partial(Handler, directory=HERE)
    httpd = ThreadingHTTPServer((args.host, args.port), handler)
    url = f"http://{args.host}:{args.port}/{args.page}"
    print(f"Serving {HERE}")
    print(f"Open:    {url}")
    print(f"Ana:     http://{args.host}:{args.port}/  -> twin.html")
    print(f"API:     http://{args.host}:{args.port}/api/telemetry")
    print(f"         http://{args.host}:{args.port}/api/assets")
    print(f"         http://{args.host}:{args.port}/api/alarms")
    print("Press Ctrl+C to stop.")
    if not args.no_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        httpd.server_close()


if __name__ == "__main__":
    main()
