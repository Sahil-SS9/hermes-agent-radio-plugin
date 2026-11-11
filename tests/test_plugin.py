"""Hermes Agent Radio plugin tests: real HTTP against a stand-in station built from recorded replies.

The fixtures are the live station's own JSON, recorded on 11 November 2026, so a change in the
station's shapes shows up here as a failing test rather than as a confused agent.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"


def _load_plugin():
    spec = importlib.util.spec_from_file_location("hermes_agent_radio", ROOT / "__init__.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["hermes_agent_radio"] = module
    spec.loader.exec_module(module)
    return module


radio = _load_plugin()


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


class Station:
    """A loopback stand-in for the station: GETs from fixtures, POSTs recorded and answered."""

    def __init__(self) -> None:
        self.posts: list[tuple[str, dict]] = []
        self.replies: dict[str, tuple[int, dict]] = {}
        schedule = _fixture("schedule.json")
        # Re-date the recorded guide so "now" falls inside its second block.
        first = datetime.fromisoformat(schedule["blocks"][0]["starts_at"])
        shift = datetime.now(UTC) - (datetime.fromisoformat(schedule["blocks"][1]["starts_at"]) + timedelta(minutes=5))
        for block in schedule["blocks"]:
            for key in ("starts_at", "ends_at"):
                block[key] = (datetime.fromisoformat(block[key]) + shift).isoformat()
        assert first
        self.gets = {
            "/now-playing.json": _fixture("now-playing.json"),
            "/schedule": schedule,
            "/show-notes.json": _fixture("show-notes.json"),
            "/stations.json": _fixture("stations.json"),
            "/songs.json": _fixture("songs.json"),
            "/chart.json": _fixture("chart.json"),
        }
        station = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # quiet
                pass

            def _send(self, status: int, doc: dict) -> None:
                raw = json.dumps(doc).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):  # noqa: N802
                station.user_agent = self.headers.get("User-Agent")
                doc = station.gets.get(self.path)
                self._send(200, doc) if doc is not None else self._send(404, {"error": "not found"})

            def do_POST(self):  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                station.posts.append((self.path, body))
                status, doc = station.replies.get(self.path, (200, {"id": "abc123", "kind": body.get("kind"), "status": "queued"}))
                self._send(status, doc)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class FakeCtx:
    def __init__(self, config: dict) -> None:
        self.config = config
        self.tools: dict[str, dict] = {}
        self.commands: dict[str, dict] = {}

    def get_config(self, key, default=None):
        return self.config.get(key, default)

    def register_tool(self, **kwargs):
        self.tools[kwargs["name"]] = kwargs

    def register_command(self, name, **kwargs):
        self.commands[name] = kwargs


@pytest.fixture
def station():
    s = Station()
    yield s
    s.close()


@pytest.fixture
def ctx(station, tmp_path, monkeypatch):
    monkeypatch.setattr(radio, "_data_dir", lambda: tmp_path / "plugin-data")
    c = FakeCtx({"station_url": station.url, "sender_name": "demo-agent"})
    radio.register(c)
    yield c
    radio._config_reader = None


def test_registers_exactly_what_the_manifest_declares(ctx):
    import yaml

    manifest = yaml.safe_load((ROOT / "plugin.yaml").read_text())
    assert sorted(ctx.tools) == sorted(manifest["provides_tools"])
    assert list(ctx.commands) == ["radio"]
    assert manifest["version"] == radio.VERSION
    assert set(manifest["config_schema"]) == {"station_url", "sender_name"}
    for tool in ctx.tools.values():
        assert tool["schema"]["name"] == tool["name"]
        assert tool["schema"]["parameters"]["type"] == "object"
        assert set(tool["schema"]["parameters"]["required"]) <= set(tool["schema"]["parameters"]["properties"])


def test_now_playing_reads_the_live_shape(ctx, station):
    out = ctx.tools["radio_now_playing"]["handler"]({})
    assert 'On air: "The Garden" by Sovthpaw.' in out
    assert "Up next:" in out and "No Logic For The Soul" in out
    assert f"Listen: {station.url}/stream" in out
    assert station.user_agent.startswith("hermes-agent-radio/1.0.0")


def test_guide_marks_the_show_on_now_and_names_hosts(ctx):
    out = ctx.tools["radio_guide"]["handler"]({"hours": 12})
    lines = out.splitlines()
    assert lines[0].startswith("Programme guide")
    assert lines[1].startswith("- now-")
    assert "with " in lines[1] and "% talk" in lines[1]


def test_show_notes_list_sources(ctx):
    out = ctx.tools["radio_show_notes"]["handler"]({"limit": 3})
    assert "sources:" in out
    assert "GHSA-" in out or "http" in out
    assert "Unresolved claims in this window: 0." in out


def test_stations_resolve_stream_links(ctx, station):
    out = ctx.tools["radio_stations"]["handler"]({})
    assert f"{station.url}/stream/hiphop" in out
    assert "Hermes Agent Radio Techno" in out


def test_songs_search_and_ids(ctx):
    out = ctx.tools["radio_songs"]["handler"]({"query": "sovthpaw"})
    assert "c9e3e34e544c4e79" in out and "By Design" in out
    assert "No song matches" in ctx.tools["radio_songs"]["handler"]({"query": "zzzz-nothing"})


def test_request_posts_exactly_the_public_fields(ctx, station):
    out = ctx.tools["radio_request"]["handler"](
        {"kind": "question", "text": "  What is   the best way to give an agent memory?  "}
    )
    assert "id abc123" in out and "human producer" in out
    assert station.posts == [
        ("/api/request", {"kind": "question", "body": "What is the best way to give an agent memory?", "sender": "demo-agent"})
    ]


def test_request_validates_before_sending(ctx, station):
    tool = ctx.tools["radio_request"]["handler"]
    assert "kind must be one of" in tool({"kind": "shoutout", "text": "hi"})
    assert "needs some words" in tool({"kind": "topic", "text": "   "})
    assert "under 600" in tool({"kind": "topic", "text": "x" * 601})
    assert station.posts == []


def test_rate_limit_is_explained(ctx, station):
    station.replies["/api/request"] = (429, {"error": "the request box is full for now; try again later", "retry_after_s": 42})
    out = ctx.tools["radio_request"]["handler"]({"kind": "topic", "text": "MCP servers"})
    assert out == "The station said no: the request box is full for now; try again later (try again in about 42 s)"


def test_song_request_and_vote_use_one_stable_listener_id(ctx, station, tmp_path):
    station.replies["/api/song-request"] = (200, {"ok": True, "title": "By Design", "position": 2, "message": "You're in the queue"})
    station.replies["/api/vote"] = (200, {"ok": True, "message": "Vote counted for By Design this week."})
    assert "Requested \"By Design\": You're in the queue. Queue position 2." == ctx.tools["radio_song_request"]["handler"]({"song_id": "c9e3e34e544c4e79"})
    assert "Vote counted" in ctx.tools["radio_vote"]["handler"]({"song_id": "c9e3e34e544c4e79"})
    ids = {body["browser"] for _, body in station.posts}
    assert len(ids) == 1
    (token,) = ids
    assert radio._LISTENER_ID.fullmatch(token)
    assert (tmp_path / "plugin-data" / "listener-id").read_text().strip() == token
    assert station.posts[1][1]["category"] == "overall"


def test_bad_song_id_never_leaves_the_machine(ctx, station):
    assert "song id" in ctx.tools["radio_vote"]["handler"]({"song_id": "../../etc"})
    assert station.posts == []


def test_station_down_is_a_sentence_not_a_traceback(ctx, station):
    station.close()
    out = ctx.tools["radio_now_playing"]["handler"]({})
    assert out.startswith("Hermes Agent Radio is not answering at")


@pytest.mark.parametrize(
    "url",
    ["http://example.com", "ftp://127.0.0.1", "https://user:pw@example.com", "https://example.com/?x=1", "notaurl"],
)
def test_station_url_refuses_unsafe_addresses(url):
    with pytest.raises(radio.StationError):
        radio.station_url(url)


def test_station_url_defaults_to_the_public_station():
    radio._config_reader = None
    assert radio.station_url() == "https://hermesagentradio.com"
    assert radio.station_url("http://localhost:8799/") == "http://localhost:8799"


def test_command_routes(ctx, station):
    handler = ctx.commands["radio"]["handler"]
    assert handler("").startswith("On air:")
    assert handler("next").startswith("Programme guide")
    assert "Stations:" in handler("stations")
    assert handler("help").startswith("/radio")
    assert "human producer" in handler("ask Will you cover the new plugin catalog?")
    assert station.posts[-1] == ("/api/request", {"kind": "question", "body": "Will you cover the new plugin catalog?", "sender": "demo-agent"})


def test_desktop_half_stays_inside_the_sdk_surface():
    source = (ROOT / "desktop" / "plugin.js").read_text()
    imports = [line for line in source.splitlines() if line.startswith("import ")]
    assert imports == ["import { jsx } from 'react/jsx-runtime'"]
    for banned in ("eval(", "new Function", "import(", "createElement('script'", "MutationObserver", "data-slot", "prototype"):
        assert banned not in source
    assert "const DEFAULT_STATION = 'https://hermesagentradio.com'" in source
    # Detach only for the station's own pages, from the station's own frames.
    assert "isStationPage(event.origin, data.url)" in source
