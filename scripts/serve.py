"""Tiny static file server for the project site that disables caching.

Use during local development so the browser always refetches edited CSS/JS:

    pixi run python scripts/serve.py            # serves ./site on :8000
    python3 scripts/serve.py 8001               # custom port

Plain `python -m http.server` lets the browser cache style.css, which makes
edits appear not to take effect until a hard refresh. This sends
`Cache-Control: no-store` so an ordinary reload always shows the latest files.
"""
from __future__ import annotations

import http.server
import socketserver
import sys
from pathlib import Path

SITE = Path(__file__).resolve().parents[1] / "site"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8000


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(SITE), **k)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        super().end_headers()


def main() -> None:
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), NoCacheHandler) as httpd:
        print(f"serving {SITE} at http://localhost:{PORT} (no-store; reload always fresh)")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
