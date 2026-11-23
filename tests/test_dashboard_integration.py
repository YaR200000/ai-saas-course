"""Frontend client -> actual Vite proxy -> FastAPI -> isolated SQLite.

The tiny HTTP bridge transports requests to the existing ASGI TestClient.
No Uvicorn, environment files, Telegram, asyncpg, or Neon are started.
"""
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import shutil
import subprocess
from threading import Thread

import pytest

from app.api import app
from test_transactions_api import client  # Reuse isolated SQL fixture, not its tests.

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("scenario", ["healthy", "empty", "db-down", "backend-down"])
def test_dashboard_stack(client, scenario, caplog):
    node = shutil.which("node")
    if node is None:
        portable = ROOT / ".tools/node-v24.11.1-win-x64/node.exe"
        if portable.is_file():
            node = str(portable)
    if node is None:
        pytest.fail("Node.js required: add the portable Node directory to PATH.")

    if scenario == "empty":
        app.state.allowed_user_id = 999
    elif scenario == "db-down":
        def fail():
            raise RuntimeError("synthetic-private-db-details SQL parameters")
        app.state.session_factory = fail

    class Bridge(BaseHTTPRequestHandler):
        def do_GET(self):
            response = client.get(self.path, headers=dict(self.headers))
            self.send_response(response.status_code)
            for header in ("content-type", "cache-control", "x-content-type-options", "x-total-count"):
                if header in response.headers:
                    self.send_header(header, response.headers[header])
            self.send_header("Content-Length", str(len(response.content)))
            self.end_headers()
            self.wfile.write(response.content)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Bridge)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = subprocess.run(
            [node, "tests/dashboard-integration.mjs", scenario,
             f"http://127.0.0.1:{server.server_port}"],
            cwd=ROOT / "frontend", capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=40,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "integration OK" in result.stdout
        assert "synthetic-private-db-details" not in result.stdout + result.stderr + caplog.text
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
