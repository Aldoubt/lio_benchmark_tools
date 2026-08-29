"""Small localhost-only static/config/state server for the embedded Rerun WebViewer."""
from __future__ import annotations

import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import unquote, urlparse

VALID_LODS = {"dense", "medium", "sparse"}
VALID_LANGUAGES = {"zh-CN", "en"}


class WebViewerServer:
    def __init__(
        self,
        config: dict[str, object],
        state_callback: Callable[[dict[str, object]], None],
        dist_dir: Path,
        host: str = "127.0.0.1",
        port: int = 0,
    ) -> None:
        self._config = dict(config)
        self._state_callback = state_callback
        self._dist_dir = Path(dist_dir).resolve()
        if not (self._dist_dir / "index.html").is_file():
            raise FileNotFoundError(f"web viewer dist is missing index.html: {self._dist_dir}")

        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args: object) -> None:
                return

            def _send_json(self, status: int, payload: object) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                if body:
                    self.wfile.write(body)

            def do_GET(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                if parsed.path == "/viewer-config.json":
                    self._send_json(200, owner.config)
                    return
                relative = unquote(parsed.path.lstrip("/")) or "index.html"
                candidate = (owner._dist_dir / relative).resolve()
                try:
                    candidate.relative_to(owner._dist_dir)
                except ValueError:
                    self.send_error(404)
                    return
                if candidate.is_dir():
                    candidate = candidate / "index.html"
                if not candidate.is_file():
                    # SPA-friendly fallback for shell routes only; asset misses stay 404.
                    if "." not in Path(relative).name:
                        candidate = owner._dist_dir / "index.html"
                    else:
                        self.send_error(404)
                        return
                data = candidate.read_bytes()
                mime = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self) -> None:  # noqa: N802
                if urlparse(self.path).path != "/api/state":
                    self.send_error(404)
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    self._send_json(400, {"error": "invalid Content-Length"})
                    return
                if length <= 0 or length > 64 * 1024:
                    self._send_json(400, {"error": "invalid state payload size"})
                    return
                try:
                    payload = json.loads(self.rfile.read(length).decode("utf-8"))
                    state = owner.validate_state(payload)
                    owner._state_callback(state)
                except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
                    self._send_json(400, {"error": str(exc)})
                    return
                self.send_response(204)
                self.end_headers()

        self._server = ThreadingHTTPServer((host, int(port)), Handler)

    @property
    def config(self) -> dict[str, object]:
        return dict(self._config)

    def update_config(self, **values: object) -> None:
        self._config.update(values)

    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        display_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
        return f"http://{display_host}:{port}"

    def validate_state(self, payload: object) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise TypeError("viewer state must be a JSON object")
        algorithms = [str(item) for item in self._config.get("algorithms", [])]
        known = set(algorithms)
        visible = payload.get("visibleAlgorithms")
        if not isinstance(visible, list) or not visible:
            raise ValueError("visibleAlgorithms must be a non-empty list")
        if any(not isinstance(item, str) or item not in known for item in visible):
            raise ValueError("visibleAlgorithms contains an unknown algorithm")
        normalized_visible = list(dict.fromkeys(visible))
        world = payload.get("worldAlgorithm")
        if not isinstance(world, str) or world not in known:
            raise ValueError("worldAlgorithm is unknown")
        lod = payload.get("pointLod")
        if lod not in VALID_LODS:
            raise ValueError("pointLod must be dense, medium, or sparse")
        language = payload.get("language")
        if language not in VALID_LANGUAGES:
            raise ValueError("language must be zh-CN or en")
        return {
            "visibleAlgorithms": normalized_visible,
            "worldAlgorithm": world,
            "pointLod": lod,
            "language": language,
        }

    def serve_forever(self) -> None:
        self._server.serve_forever(poll_interval=0.2)

    def shutdown(self) -> None:
        self._server.shutdown()
        self._server.server_close()
