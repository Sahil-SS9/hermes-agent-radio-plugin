"""Hermes Agent Radio for Hermes Agent.

A 24/7 station about Hermes Agent and the open-source agent world, written, fact-checked and voiced
by agents. This plugin brings it into Hermes:

- Desktop: a player bar under the composer, a full player page in the sidebar, a status-bar dot and
  a detachable pop-out window (``desktop/plugin.js``).
- Agent tools: what is on air, the programme guide, show notes with their sources, the genre
  stations, the song library and weekly chart, and the listener writes (send a question, topic,
  roast or track request; request a song; vote).
- ``/radio``: the same in one line, in the CLI, the TUI and every messaging platform.

The station owns the truth. The plugin holds no queue and decides nothing on air: it reads the
station's public JSON and posts to its public listener endpoints, which validate, rate-limit and
hand every free-text request to a human producer. Nothing the plugin sends airs automatically.

Stdlib only. One small file of its own: an anonymous random listener id under the plugin's data
directory, which the station needs to count one vote per listener. No credentials, no telemetry.
"""

from __future__ import annotations

import ipaddress
import json
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PLUGIN_NAME = "hermes-agent-radio"
VERSION = "1.0.0"
DEFAULT_STATION = "https://hermesagentradio.com"
TIMEOUT_S = 8.0
USER_AGENT = f"{PLUGIN_NAME}/{VERSION} (+https://github.com/Sahil-SS9/hermes-agent-radio-plugin)"
REQUEST_KINDS = ("question", "topic", "roast", "track")
MAX_REQUEST_CHARS = 600
MAX_SENDER_CHARS = 80
_LISTENER_ID = re.compile(r"[A-Za-z0-9_-]{16,100}")
_SONG_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")

#: Set by ``register``: reads a ``config_schema`` value for this plugin from Hermes.
_config_reader: Callable[[str, Any], Any] | None = None


class StationError(Exception):
    """The station could not be reached, or refused; the message is fit to show a person."""


# --- configuration ----------------------------------------------------------------------------


def _config(key: str, default: Any = None) -> Any:  # noqa: ANN401 - config values are untyped
    if _config_reader is None:
        return default
    try:
        value = _config_reader(key, default)
    except Exception:  # noqa: BLE001 - a host without the value keeps the default
        return default
    return default if value in (None, "") else value


def station_url(override: str | None = None) -> str:
    """The station's base address: https anywhere, plain http only on this machine."""
    raw = str(override or _config("station_url", DEFAULT_STATION) or DEFAULT_STATION).strip()
    parsed = urllib.parse.urlsplit(raw)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise StationError(f"station_url must be an http(s) address, not {raw!r}")
    if parsed.scheme == "http" and not _is_loopback(parsed.hostname):
        raise StationError("station_url must use https unless the station is on this machine")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise StationError("station_url must be a plain address with no credentials or query")
    return raw.rstrip("/")


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _data_dir() -> Path:
    try:
        from plugins.plugin_storage import plugin_data_dir  # public plugin API

        return Path(plugin_data_dir(PLUGIN_NAME))
    except Exception:  # noqa: BLE001 - older hosts: the documented location
        from hermes_constants import get_hermes_home  # public plugin API

        return Path(get_hermes_home()) / "plugin-data" / PLUGIN_NAME


def listener_id(directory: Path | None = None) -> str:
    """An anonymous random id the station uses to count one vote per listener. Made once."""
    folder = directory or _data_dir()
    path = folder / "listener-id"
    try:
        existing = path.read_text(encoding="utf-8").strip()
        if _LISTENER_ID.fullmatch(existing):
            return existing
    except OSError:
        pass
    token = secrets.token_urlsafe(24)
    folder.mkdir(parents=True, exist_ok=True)
    path.write_text(token + "\n", encoding="utf-8")
    return token


# --- the station's public API -----------------------------------------------------------------


def _call(base: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(f"{base}{path}", data=data, method="GET" if data is None else "POST")
    request.add_header("User-Agent", USER_AGENT)
    request.add_header("Accept", "application/json")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:  # noqa: S310 - checked scheme
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        raise StationError(_refusal(exc)) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise StationError(f"Hermes Agent Radio is not answering at {base} ({reason}).") from exc
    except json.JSONDecodeError as exc:
        raise StationError(f"{base}{path} did not answer with JSON.") from exc


def _refusal(exc: urllib.error.HTTPError) -> str:
    try:
        doc = json.loads(exc.read() or b"{}")
    except (json.JSONDecodeError, OSError):
        doc = {}
    message = str(doc.get("error") or doc.get("message") or exc.reason or "refused")
    if doc.get("retry_after_s"):
        message += f" (try again in about {int(doc['retry_after_s'])} s)"
    return f"The station said no: {message}"


def get(path: str, base: str | None = None) -> dict[str, Any]:
    return _call(station_url(base), path)


def post(path: str, body: dict[str, Any], base: str | None = None) -> dict[str, Any]:
    return _call(station_url(base), path, body)


# --- formatting -------------------------------------------------------------------------------


def _clock(stamp: str | None) -> str:
    if not stamp:
        return "?"
    try:
        return datetime.fromisoformat(stamp).astimezone(UTC).strftime("%H:%M UTC")
    except ValueError:
        return stamp


def _item(item: dict[str, Any] | None) -> str:
    if not item:
        return "nothing reported"
    title = str(item.get("title") or item.get("item_id") or "untitled").strip()
    if item.get("artist"):
        return f'"{title}" by {item["artist"]}'
    kind = item.get("segment_kind") or item.get("kind") or "talk"
    if len(title) > 140:
        title = title[:137].rstrip() + "..."
    return f"{str(kind).replace('_', ' ')}: {title}"


def _host_names(hosts: list[str]) -> str:
    return ", ".join(h.replace("_", " ").title() for h in hosts) or "the station"


#: Station furniture: the short links between pieces. Real, but not what "up next" should list.
_FURNITURE = {"back_announce", "song_intro", "station_id", "ident", "jingle", "promo", "transition", "sign_off"}


def _is_furniture(item: dict[str, Any]) -> bool:
    return str(item.get("segment_kind") or "") in _FURNITURE


def now_playing(base: str | None = None) -> str:
    doc = get("/now-playing.json", base)
    stream = urllib.parse.urljoin(station_url(base) + "/", str(doc.get("stream_url") or "/stream"))
    lines = [f"On air: {_item(doc.get('now'))}."]
    upcoming = doc.get("up_next") or ([doc["next"]] if doc.get("next") else [])
    upcoming = [i for i in upcoming if isinstance(i, dict) and not _is_furniture(i)]
    if upcoming:
        lines.append("Up next: " + "; ".join(_item(i) for i in upcoming[:3]) + ".")
    if doc.get("listeners"):
        lines.append(f"Listeners: {doc['listeners']}.")
    lines.append(f"Listen: {stream} (or the player at {station_url(base)}/listen).")
    return "\n".join(lines)


def guide(base: str | None = None, hours: int = 12) -> str:
    doc = get("/schedule", base)
    now = datetime.now(UTC)
    blocks = []
    for block in doc.get("blocks", []):
        try:
            ends = datetime.fromisoformat(block["ends_at"])
            starts = datetime.fromisoformat(block["starts_at"])
        except (KeyError, ValueError):
            continue
        if ends > now and (starts - now).total_seconds() <= hours * 3600:
            blocks.append((starts, block))
    if not blocks:
        return "The programme guide is empty for the next few hours."
    lines = [f"Programme guide (times in {doc.get('timezone', 'UTC')}):"]
    for starts, block in blocks:
        marker = "now" if starts <= now else _clock(block["starts_at"])
        ratio = block.get("ratio") or {}
        mix = f", {ratio.get('talk', '?')}% talk / {ratio.get('music', '?')}% music" if ratio else ""
        lines.append(
            f"- {marker}-{_clock(block['ends_at'])}: {block.get('name', block.get('programme'))}"
            f" with {_host_names(block.get('hosts', []))}{mix}"
        )
    return "\n".join(lines)


def show_notes(base: str | None = None, limit: int = 5) -> str:
    doc = get("/show-notes.json", base)
    talk = [i for i in doc.get("items", []) if i.get("item_kind") == "talk" and i.get("claims")]
    if not talk:
        return "No talk with sources has aired in the last day."
    lines = ["Recent talk and the sources behind it:"]
    for item in list(reversed(talk))[: max(1, min(limit, 10))]:
        sources = []
        for claim in item.get("claims", []):
            label = claim.get("url") or claim.get("title") or claim.get("event_id")
            if label and label not in sources:
                sources.append(label)
        lines.append(
            f"- {_clock(item.get('started_at'))} {_item(item)} — sources: {', '.join(sources[:4]) or 'none listed'}"
        )
    if doc.get("unresolved_claims") is not None:
        lines.append(f"Unresolved claims in this window: {doc['unresolved_claims']}.")
    return "\n".join(lines)


def stations(base: str | None = None) -> str:
    doc = get("/stations.json", base)
    root = station_url(base) + "/"
    lines = ["Stations:"]
    for s in doc.get("stations", []):
        lines.append(
            f"- {s.get('name')} ({s.get('id')}): {s.get('tagline', '')} — "
            f"{urllib.parse.urljoin(root, str(s.get('stream') or '/stream'))}"
        )
    return "\n".join(lines)


def songs(query: str = "", base: str | None = None, limit: int = 10) -> str:
    doc = get("/songs.json", base)
    needle = query.strip().lower()
    found = [
        s
        for s in doc.get("songs", [])
        if not needle
        or needle in " ".join(str(s.get(k) or "") for k in ("title", "artist", "genre")).lower()
    ]
    if not found:
        return f"No song matches {query!r}." if needle else "The song library is empty."
    lines = [f"Songs ({len(found)} match{'es' if len(found) != 1 else ''}; request one by its id):"]
    for s in found[: max(1, min(limit, 25))]:
        lines.append(f"- {s.get('song_id')}: \"{s.get('title')}\" by {s.get('artist')} [{s.get('genre')}]")
    chart = get("/chart.json", base)
    if chart.get("rows"):
        top = chart["rows"][:3]
        lines.append(
            f"This week's chart ({chart.get('week')}): "
            + "; ".join(f"{r.get('title')} ({r.get('votes', r.get('score', '?'))})" for r in top)
        )
    return "\n".join(lines)


# --- listener writes --------------------------------------------------------------------------


def send_request(kind: str, body: str, sender: str = "", base: str | None = None) -> str:
    kind = kind.strip().lower()
    if kind not in REQUEST_KINDS:
        raise StationError(f"kind must be one of {', '.join(REQUEST_KINDS)}")
    text = " ".join(body.split())
    if not text:
        raise StationError("a request needs some words")
    if len(text) > MAX_REQUEST_CHARS:
        raise StationError(f"keep it under {MAX_REQUEST_CHARS} characters")
    who = " ".join((sender or str(_config("sender_name", "") or "")).split())[:MAX_SENDER_CHARS]
    receipt = post("/api/request", {"kind": kind, "body": text, "sender": who}, base)
    return (
        f"Sent to Hermes Agent Radio as a {receipt.get('kind', kind)} request "
        f"(id {receipt.get('id', '?')}, {receipt.get('status', 'queued')}). "
        "A human producer reads every request; nothing airs automatically."
    )


def request_song(song_id: str, base: str | None = None) -> str:
    if not _SONG_ID.fullmatch(song_id.strip()):
        raise StationError("give the song id from radio_songs")
    doc = post("/api/song-request", {"song_id": song_id.strip(), "browser": listener_id()}, base)
    message = doc.get("message") or "requested"
    position = f" Queue position {doc['position']}." if doc.get("position") else ""
    return f"Requested \"{doc.get('title', song_id)}\": {message}.{position}".replace("..", ".")


def vote(song_id: str, category: str = "overall", base: str | None = None) -> str:
    if not _SONG_ID.fullmatch(song_id.strip()):
        raise StationError("give the song id from radio_songs")
    doc = post(
        "/api/vote",
        {"song_id": song_id.strip(), "category": category.strip() or "overall", "browser": listener_id()},
        base,
    )
    return str(doc.get("message") or f"Vote counted for {song_id} in {category}.")


# --- tool and command wiring ------------------------------------------------------------------


def _safe(fn: Callable[[], str]) -> str:
    try:
        return fn()
    except StationError as exc:
        return str(exc)


def _args(args: dict[str, Any] | None) -> dict[str, Any]:
    return args if isinstance(args, dict) else {}


def _tool_now(args: dict[str, Any] | None = None, **_: Any) -> str:
    return _safe(lambda: now_playing())


def _tool_guide(args: dict[str, Any] | None = None, **_: Any) -> str:
    hours = _args(args).get("hours", 12)
    return _safe(lambda: guide(hours=max(1, min(int(hours or 12), 24))))


def _tool_notes(args: dict[str, Any] | None = None, **_: Any) -> str:
    return _safe(lambda: show_notes(limit=int(_args(args).get("limit", 5) or 5)))


def _tool_stations(args: dict[str, Any] | None = None, **_: Any) -> str:
    return _safe(lambda: stations())


def _tool_songs(args: dict[str, Any] | None = None, **_: Any) -> str:
    return _safe(lambda: songs(str(_args(args).get("query", "") or "")))


def _tool_request(args: dict[str, Any] | None = None, **_: Any) -> str:
    a = _args(args)
    return _safe(
        lambda: send_request(str(a.get("kind", "")), str(a.get("text", "")), str(a.get("sender", "") or ""))
    )


def _tool_song_request(args: dict[str, Any] | None = None, **_: Any) -> str:
    return _safe(lambda: request_song(str(_args(args).get("song_id", ""))))


def _tool_vote(args: dict[str, Any] | None = None, **_: Any) -> str:
    a = _args(args)
    return _safe(lambda: vote(str(a.get("song_id", "")), str(a.get("category", "overall") or "overall")))


HELP = (
    "/radio — what's on air now\n"
    "/radio next — the programme guide\n"
    "/radio notes — recent talk and its sources\n"
    "/radio stations — the genre stations\n"
    "/radio songs [search] — the song library\n"
    "/radio ask <question> — send the hosts a question (a human reads it first)\n"
    "/radio listen — the listen links"
)


def command(raw_args: str = "") -> str:
    verb, _, rest = (raw_args or "").strip().partition(" ")
    verb = verb.lower()
    if verb in ("", "now"):
        return _safe(lambda: now_playing())
    if verb in ("next", "guide", "schedule"):
        return _safe(lambda: guide())
    if verb == "notes":
        return _safe(lambda: show_notes())
    if verb == "stations":
        return _safe(lambda: stations())
    if verb == "songs":
        return _safe(lambda: songs(rest))
    if verb == "ask":
        return _safe(lambda: send_request("question", rest))
    if verb == "listen":
        return _safe(lambda: f"Player: {station_url()}/listen\nStream: {station_url()}/stream")
    return HELP


def _schema(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required},
    }


TOOLS: list[tuple[str, str, dict[str, Any], list[str], Callable[..., str], str]] = [
    (
        "radio_now_playing",
        "What Hermes Agent Radio is playing now, what is up next, and the listen link.",
        {},
        [],
        _tool_now,
        "📻",
    ),
    (
        "radio_guide",
        "The Hermes Agent Radio programme guide: which show is on, which come next, and their AI hosts.",
        {"hours": {"type": "integer", "description": "How far ahead to look, 1-24 hours (default 12)."}},
        [],
        _tool_guide,
        "🗓️",
    ),
    (
        "radio_show_notes",
        "Talk that aired on Hermes Agent Radio in the last day, each with the sources its claims came from.",
        {"limit": {"type": "integer", "description": "How many pieces, 1-10 (default 5)."}},
        [],
        _tool_notes,
        "📝",
    ),
    (
        "radio_stations",
        "The Hermes Agent Radio stations (main plus genre stations) and their stream links.",
        {},
        [],
        _tool_stations,
        "📡",
    ),
    (
        "radio_songs",
        "Search the Hermes Agent Radio song library (community music) and see this week's chart.",
        {"query": {"type": "string", "description": "Title, artist or genre to look for (optional)."}},
        [],
        _tool_songs,
        "🎵",
    ),
    (
        "radio_request",
        "Send Hermes Agent Radio a listener request: a question for the hosts, a topic to cover, a repo to "
        "roast (the repo owner must opt in) or a track. A human producer reads it before anything airs.",
        {
            "kind": {"type": "string", "enum": list(REQUEST_KINDS), "description": "What sort of request."},
            "text": {"type": "string", "description": f"The request, under {MAX_REQUEST_CHARS} characters."},
            "sender": {"type": "string", "description": "Name to credit (optional; defaults to the setting)."},
        },
        ["kind", "text"],
        _tool_request,
        "✉️",
    ),
    (
        "radio_song_request",
        "Ask Hermes Agent Radio to play a song from its library, by song id (from radio_songs).",
        {"song_id": {"type": "string", "description": "The song id."}},
        ["song_id"],
        _tool_song_request,
        "🙋",
    ),
    (
        "radio_vote",
        "Vote for a song in the Hermes Agent Radio weekly chart (one vote per listener per song and week).",
        {
            "song_id": {"type": "string", "description": "The song id."},
            "category": {"type": "string", "description": "Chart category, e.g. overall or a genre."},
        },
        ["song_id"],
        _tool_vote,
        "🗳️",
    ),
]


def register(ctx: Any) -> None:  # noqa: ANN401 - host object, shape documented upstream
    """Register the tools and /radio. No hooks, no background work, no state beyond the listener id."""
    global _config_reader
    getter = getattr(ctx, "get_config", None)
    _config_reader = getter if callable(getter) else None
    for name, description, properties, required, handler, emoji in TOOLS:
        ctx.register_tool(
            name=name,
            toolset="radio",
            schema=_schema(name, description, properties, required),
            handler=handler,
            description=description,
            emoji=emoji,
        )
    ctx.register_command(
        "radio",
        handler=command,
        description="Hermes Agent Radio: what's on, the guide, show notes, songs, ask the hosts",
        args_hint="[next|notes|stations|songs|ask|listen]",
    )
