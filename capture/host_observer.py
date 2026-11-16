"""CONNECT metadata only; no HTTP bodies, headers, URLs, replay or mutation.

Run with --ignore-hosts '.*' so TLS stays encrypted. Host attribution is
unconfirmed: global proxy connections may originate from background apps.
"""
import asyncio
from datetime import datetime, timezone
import ipaddress
import json
from pathlib import Path
import re
import time
import uuid

from mitmproxy import ctx, exceptions


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def safe_host(value):
    if not isinstance(value, str) or len(value) > 253:
        return None
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        pass
    try:
        value = value.encode("idna").decode("ascii").lower().rstrip(".")
    except UnicodeError:
        return None
    labels = value.split(".")
    if all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels):
        return value
    return None


class HostObserver:
    def load(self, loader):
        loader.add_option("host_observation_file", str, "", "Absolute local CONNECT metadata JSONL path")
        loader.add_option("host_observation_seconds", int, 180, "Metadata observation window, max 300s")

    def configure(self, updated):
        if not {"host_observation_file", "host_observation_seconds"}.intersection(updated):
            return
        path = Path(ctx.options.host_observation_file)
        duration = ctx.options.host_observation_seconds
        if not path.is_absolute() or not 1 <= duration <= 300:
            raise exceptions.OptionsError("Need absolute host_observation_file and 1..300 second window")
        self.path = path
        self.duration = duration

    def emit(self, event):
        record = {"session_id": self.session_id, "observed_at": now(), **event}
        try:
            with self.path.open("a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n")
        except OSError:
            self.finished = True
            ctx.log.warn("host observer: local metadata write failed; no content logged")

    def running(self):
        if not hasattr(self, "path"):
            raise exceptions.OptionsError("Host observation output was not configured")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.session_id = str(uuid.uuid4())
        self.started = time.monotonic()
        self.finished = False
        self.count = 0
        self.recent = {}
        self.emit({"kind": "window_start", "duration_seconds": self.duration,
                   "attribution": "unconfirmed", "body_capture": False})
        self.timer = asyncio.get_running_loop().call_later(self.duration, self.finish)

    def http_connect(self, flow):
        if not hasattr(self, "started") or self.finished:
            return
        elapsed = time.monotonic() - self.started
        if elapsed >= self.duration:
            self.finish()
            return
        # Explicitly read just three CONNECT properties. No other flow values.
        request = flow.request
        if request.method != "CONNECT":
            return
        host = safe_host(request.host)
        port = request.port
        if not host or type(port) is not int or not 1 <= port <= 65535:
            return
        key = (host, port)
        if elapsed - self.recent.get(key, -10) < 2:
            return
        self.recent[key] = elapsed
        self.emit({"kind": "connect", "host": host, "port": port,
                   "elapsed_seconds": round(elapsed, 3),
                   "phase": "baseline" if elapsed < 15 else "observation",
                   "attribution": "unconfirmed"})
        self.count += 1
        if self.count >= 500:
            self.finish(reason="event_limit")

    def finish(self, reason="time_limit"):
        if not hasattr(self, "finished") or self.finished:
            return
        self.finished = True
        self.emit({"kind": "window_end", "reason": reason, "events": self.count,
                   "attribution": "unconfirmed"})

    def done(self):
        if hasattr(self, "timer"):
            self.timer.cancel()
        self.finish(reason="proxy_stopped")


addons = [HostObserver()]
