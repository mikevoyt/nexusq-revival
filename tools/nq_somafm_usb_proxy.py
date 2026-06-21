#!/usr/bin/env python3
"""Serve SomaFM streams to a Nexus Q over the USB link.

The Nexus Q Debian image often has USB networking before it has Wi-Fi or a
default route. This proxy runs on the host, resolves SomaFM playlists there,
and exposes local stream URLs that the Q can play over usb0.
"""

from __future__ import annotations

import argparse
import contextlib
import http.server
import re
import socketserver
import sys
import urllib.error
import urllib.parse
import urllib.request


STATION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


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
        if len(parts) == 2 and parts[0] == "m3u":
            station = parts[1].removesuffix(".m3u")
            self.send_station_playlist(station)
            return

        self.send_text(404, "not found\n")

    def playlist_urls(self, station: str) -> list[str]:
        if not STATION_RE.fullmatch(station):
            raise ValueError("invalid station id")
        playlist_url = f"https://somafm.com/m3u/{station}.m3u"
        request = urllib.request.Request(
            playlist_url,
            headers={"User-Agent": "NexusQ SomaFM USB proxy"},
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            text = response.read().decode("utf-8", "replace")
        urls = [
            line.strip()
            for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        if not urls:
            raise ValueError(f"no stream URLs in {playlist_url}")
        return urls

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

    def stream_station(self, station: str) -> None:
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
                    headers={"User-Agent": "NexusQ SomaFM USB proxy"},
                )
                upstream = urllib.request.urlopen(request, timeout=20)
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
            self.end_headers()
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
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.bind, args.port), SomaProxy)
    host, port = server.server_address[:2]
    print(f"nq-somafm-usb-proxy listening on {host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
