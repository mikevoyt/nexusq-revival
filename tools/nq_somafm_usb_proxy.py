#!/usr/bin/env python3
"""Serve SomaFM streams to a Nexus Q over the USB link.

The Nexus Q Debian image often has USB networking before it has Wi-Fi or a
default route. This proxy runs on the host, resolves SomaFM playlists there,
and exposes local stream URLs that the Q can play over usb0.
"""

from __future__ import annotations

import argparse
import collections
import contextlib
import http.server
import re
import socketserver
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


STATION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
USER_AGENT = "NexusQ SomaFM USB proxy"


class WarmStream:
    """Keep one SomaFM station open and ready for low-latency handoff."""

    def __init__(self, server: "SomaHTTPServer", station: str) -> None:
        self.server = server
        self.station = station
        self.chunks: collections.deque[tuple[int, bytes]] = collections.deque()
        self.buffer_bytes = 0
        self.sequence = 0
        self.content_type = "audio/mpeg"
        self.icy_name: str | None = None
        self.error: str | None = None
        self.condition = threading.Condition()
        self.thread = threading.Thread(
            target=self._run,
            name=f"somafm-warm-{station}",
            daemon=True,
        )
        self.thread.start()

    def _open_upstream(self):
        last_error: Exception | None = None
        for stream_url in self.server.playlist_urls(self.station):
            try:
                request = urllib.request.Request(
                    stream_url,
                    headers={"User-Agent": USER_AGENT},
                )
                return urllib.request.urlopen(request, timeout=self.server.upstream_timeout)
            except (OSError, urllib.error.URLError, TimeoutError) as exc:
                last_error = exc
        raise RuntimeError(f"stream error: {last_error}")

    def _append_chunk(self, chunk: bytes) -> None:
        self.sequence += 1
        self.chunks.append((self.sequence, chunk))
        self.buffer_bytes += len(chunk)
        while self.buffer_bytes > self.server.warm_buffer_bytes and self.chunks:
            _, old = self.chunks.popleft()
            self.buffer_bytes -= len(old)

    def _run(self) -> None:
        while True:
            try:
                with contextlib.closing(self._open_upstream()) as upstream:
                    with self.condition:
                        self.content_type = upstream.headers.get("Content-Type", "audio/mpeg")
                        self.icy_name = upstream.headers.get("icy-name")
                        self.error = None
                        self.condition.notify_all()

                    while True:
                        chunk = upstream.read(self.server.warm_chunk_bytes)
                        if not chunk:
                            raise EOFError("upstream ended")
                        with self.condition:
                            self._append_chunk(chunk)
                            self.condition.notify_all()
            except Exception as exc:  # Keep the warmer alive across network churn.
                with self.condition:
                    self.error = str(exc)
                    self.condition.notify_all()
                time.sleep(self.server.warm_reconnect_delay)

    def snapshot(self) -> tuple[str, str | None, list[tuple[int, bytes]], str | None]:
        with self.condition:
            content_type = self.content_type
            icy_name = self.icy_name
            chunks = list(self.chunks)
            error = self.error
        return content_type, icy_name, chunks, error

    def wait_for_chunks(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        with self.condition:
            while not self.chunks:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self.condition.wait(remaining)
            return True

    def stream_to(self, handler: "SomaProxy", prefix: bytes = b"") -> bool:
        if not self.wait_for_chunks(handler.server.warm_client_wait):
            return False

        content_type, icy_name, chunks, _ = self.snapshot()
        handler.send_response(200)
        handler.send_header("Content-Type", content_type)
        if icy_name:
            handler.send_header("icy-name", icy_name)
        handler.send_header("x-nexusq-somafm-warm", "1")
        handler.end_headers()

        last_sequence = 0
        try:
            if prefix:
                handler.wfile.write(prefix)
            for sequence, chunk in chunks:
                handler.wfile.write(chunk)
                last_sequence = sequence
            handler.wfile.flush()

            while True:
                with self.condition:
                    while self.chunks and self.chunks[-1][0] <= last_sequence:
                        self.condition.wait(10)
                    chunks = [(seq, data) for seq, data in self.chunks if seq > last_sequence]
                for sequence, chunk in chunks:
                    handler.wfile.write(chunk)
                    last_sequence = sequence
                handler.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            return True


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


class SomaHTTPServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type[http.server.BaseHTTPRequestHandler],
        *,
        playlist_ttl: float,
        playlist_timeout: float,
        upstream_timeout: float,
        warm_buffer_bytes: int,
        warm_chunk_bytes: int,
        warm_client_wait: float,
        warm_reconnect_delay: float,
        prompt_mp3: bytes,
    ) -> None:
        super().__init__(server_address, handler_class)
        self.playlist_ttl = playlist_ttl
        self.playlist_timeout = playlist_timeout
        self.upstream_timeout = upstream_timeout
        self.warm_buffer_bytes = warm_buffer_bytes
        self.warm_chunk_bytes = warm_chunk_bytes
        self.warm_client_wait = warm_client_wait
        self.warm_reconnect_delay = warm_reconnect_delay
        self.prompt_mp3 = prompt_mp3
        self._playlist_cache: dict[str, tuple[float, list[str]]] = {}
        self._playlist_lock = threading.Lock()
        self._warm_streams: dict[str, WarmStream] = {}
        self._warm_lock = threading.Lock()

    def playlist_urls(self, station: str) -> list[str]:
        if not STATION_RE.fullmatch(station):
            raise ValueError("invalid station id")

        now = time.monotonic()
        with self._playlist_lock:
            cached = self._playlist_cache.get(station)
            if cached is not None:
                expires_at, urls = cached
                if expires_at > now:
                    return list(urls)

        playlist_url = f"https://somafm.com/m3u/{station}.m3u"
        request = urllib.request.Request(
            playlist_url,
            headers={"User-Agent": USER_AGENT},
        )
        with urllib.request.urlopen(request, timeout=self.playlist_timeout) as response:
            text = response.read().decode("utf-8", "replace")
        urls = [
            line.strip()
            for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        if not urls:
            raise ValueError(f"no stream URLs in {playlist_url}")

        with self._playlist_lock:
            self._playlist_cache[station] = (now + self.playlist_ttl, list(urls))
        return urls

    def warm_stream(self, station: str) -> WarmStream:
        if not STATION_RE.fullmatch(station):
            raise ValueError("invalid station id")
        with self._warm_lock:
            warm = self._warm_streams.get(station)
            if warm is None:
                warm = WarmStream(self, station)
                self._warm_streams[station] = warm
            return warm

    def existing_warm_stream(self, station: str) -> WarmStream | None:
        with self._warm_lock:
            return self._warm_streams.get(station)

    def warm_status(self) -> str:
        with self._warm_lock:
            streams = list(self._warm_streams.values())
        if not streams:
            return "no warm streams\n"
        lines = []
        for warm in streams:
            _, icy_name, chunks, error = warm.snapshot()
            byte_count = sum(len(chunk) for _, chunk in chunks)
            state = "ready" if chunks else "warming"
            if error:
                state = f"error:{error}"
            title = f" {icy_name}" if icy_name else ""
            lines.append(f"{warm.station} {state} chunks={len(chunks)} bytes={byte_count}{title}")
        return "\n".join(lines) + "\n"


class SomaProxy(http.server.BaseHTTPRequestHandler):
    server_version = "NexusQSomaProxy/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        print("%s - - [%s] %s" % (self.client_address[0], self.log_date_time_string(), fmt % args), file=sys.stderr)

    def send_text(self, code: int, body: str, content_type: str = "text/plain; charset=utf-8") -> None:
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.strip("/")

        if path in ("", "healthz"):
            self.send_text(200, "ok\n")
            return

        parts = path.split("/")
        if len(parts) == 2 and parts[0] == "station":
            self.stream_station(parts[1])
            return
        if len(parts) == 2 and parts[0] == "cue":
            self.stream_station(parts[1], prefix=self.server.prompt_mp3)
            return
        if len(parts) == 2 and parts[0] == "warm":
            self.warm_station(parts[1])
            return
        if len(parts) == 2 and parts[0] == "m3u":
            station = parts[1].removesuffix(".m3u")
            self.send_station_playlist(station)
            return
        if path == "status":
            self.send_text(200, self.server.warm_status())
            return

        self.send_text(404, "not found\n")

    def playlist_urls(self, station: str) -> list[str]:
        return self.server.playlist_urls(station)

    def send_station_playlist(self, station: str) -> None:
        if not STATION_RE.fullmatch(station):
            self.send_text(400, "invalid station id\n")
            return
        host = self.headers.get("Host", f"{self.server.server_name}:{self.server.server_port}")
        quoted = urllib.parse.quote(station, safe="")
        body = (
            "#EXTM3U\n"
            f"#EXTINF:-1,SomaFM - {station}\n"
            f"http://{host}/station/{quoted}\n"
        )
        self.send_text(200, body, "audio/x-mpegurl; charset=utf-8")

    def warm_station(self, station: str) -> None:
        try:
            self.server.warm_stream(station)
        except ValueError:
            self.send_text(400, "invalid station id\n")
            return
        self.send_text(200, f"warming {station}\n")

    def stream_station(self, station: str, prefix: bytes = b"") -> None:
        if not STATION_RE.fullmatch(station):
            self.send_text(400, "invalid station id\n")
            return

        warm = self.server.existing_warm_stream(station)
        if warm is not None and warm.stream_to(self, prefix=prefix):
            return

        try:
            urls = self.playlist_urls(station)
        except (ValueError, urllib.error.URLError, TimeoutError) as exc:
            self.send_text(502, f"playlist error: {exc}\n")
            return

        last_error: Exception | None = None
        for stream_url in urls:
            try:
                request = urllib.request.Request(
                    stream_url,
                    headers={"User-Agent": USER_AGENT},
                )
                upstream = urllib.request.urlopen(request, timeout=self.server.upstream_timeout)
                break
            except (urllib.error.URLError, TimeoutError) as exc:
                last_error = exc
        else:
            self.send_text(502, f"stream error: {last_error}\n")
            return

        with contextlib.closing(upstream):
            self.send_response(200)
            self.send_header("Content-Type", upstream.headers.get("Content-Type", "audio/mpeg"))
            icy_name = upstream.headers.get("icy-name")
            if icy_name:
                self.send_header("icy-name", icy_name)
            if prefix:
                self.send_header("x-nexusq-somafm-cue", "1")
            self.end_headers()
            if prefix:
                self.wfile.write(prefix)
                self.wfile.flush()
            while True:
                chunk = upstream.read(64 * 1024)
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    break


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bind", default="0.0.0.0", help="address to bind, default: all interfaces")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument(
        "--warm-stations",
        default="",
        help="comma-separated station ids to keep preconnected, e.g. groovesalad,secretagent",
    )
    parser.add_argument("--playlist-ttl", type=float, default=600)
    parser.add_argument("--playlist-timeout", type=float, default=5)
    parser.add_argument("--upstream-timeout", type=float, default=10)
    parser.add_argument("--warm-buffer-bytes", type=int, default=64 * 1024)
    parser.add_argument("--warm-chunk-bytes", type=int, default=16 * 1024)
    parser.add_argument("--warm-client-wait", type=float, default=2)
    parser.add_argument("--warm-reconnect-delay", type=float, default=1)
    parser.add_argument(
        "--prompt-mp3",
        default="",
        help="optional MP3 file sent before /cue/STATION warmed station audio",
    )
    args = parser.parse_args()

    prompt_mp3 = b""
    if args.prompt_mp3:
        prompt_mp3 = Path(args.prompt_mp3).read_bytes()

    server = SomaHTTPServer(
        (args.bind, args.port),
        SomaProxy,
        playlist_ttl=args.playlist_ttl,
        playlist_timeout=args.playlist_timeout,
        upstream_timeout=args.upstream_timeout,
        warm_buffer_bytes=args.warm_buffer_bytes,
        warm_chunk_bytes=args.warm_chunk_bytes,
        warm_client_wait=args.warm_client_wait,
        warm_reconnect_delay=args.warm_reconnect_delay,
        prompt_mp3=prompt_mp3,
    )
    host, port = server.server_address[:2]
    print(f"nq-somafm-usb-proxy listening on {host}:{port}", flush=True)
    for station in [item.strip() for item in args.warm_stations.split(",") if item.strip()]:
        try:
            server.warm_stream(station)
            print(f"warming station {station}", flush=True)
        except ValueError:
            print(f"invalid warm station: {station}", file=sys.stderr, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
