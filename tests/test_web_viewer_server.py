import json
import threading
import urllib.error
import urllib.request

from lio_benchmark.web_viewer_server import WebViewerServer


def _config():
    return {
        "grpcUrl": "rerun+http://127.0.0.1:9876/proxy",
        "language": "zh-CN",
        "algorithms": ["fast_livo2", "glim_full_slam"],
        "baseline": "fast_livo2",
        "worldAlgorithm": "fast_livo2",
        "anomalyWindows": [],
    }


def test_server_exposes_config_and_accepts_valid_state(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>ok</html>", encoding="utf-8")
    received = []
    server = WebViewerServer(_config(), received.append, dist, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(server.url + "/viewer-config.json", timeout=2) as response:
            config = json.load(response)
        assert config["baseline"] == "fast_livo2"

        payload = json.dumps(
            {
                "visibleAlgorithms": ["fast_livo2"],
                "worldAlgorithm": "fast_livo2",
                "pointLod": "medium",
                "language": "zh-CN",
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            server.url + "/api/state",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            assert response.status == 204
        assert received == [
            {
                "visibleAlgorithms": ["fast_livo2"],
                "worldAlgorithm": "fast_livo2",
                "pointLod": "medium",
                "language": "zh-CN",
            }
        ]
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_server_rejects_unknown_world_algorithm(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>ok</html>", encoding="utf-8")
    server = WebViewerServer(_config(), lambda state: None, dist, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = json.dumps(
            {
                "visibleAlgorithms": ["fast_livo2"],
                "worldAlgorithm": "unknown",
                "pointLod": "medium",
                "language": "zh-CN",
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            server.url + "/api/state",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(request, timeout=2)
        except urllib.error.HTTPError as exc:
            assert exc.code == 400
        else:
            raise AssertionError("unknown world algorithm must return HTTP 400")
    finally:
        server.shutdown()
        thread.join(timeout=2)
