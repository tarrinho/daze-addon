#!/usr/bin/env python3
"""Serve tools/get_tokens.html to a phone on the local network, for testing.

This exists because the obvious command is dangerous here. Running
``python3 -m http.server`` in this repository publishes the whole
working directory to every device on the network, and this repository
contains ``.env`` (a GitHub token), ``log`` (a capture carrying the
charger's serial number), ``rules.md``, and 15 MB of ``.git`` history.
None of that is hypothetical -- all four are present right now, and all
four are ignored by git precisely because they must not travel.

So this server has one route. It serves the single HTML file at ``/``
and answers 404 to everything else. There is no directory listing, no
path traversal, and no second file to reach, because the file is read
once at start-up and nothing on disk is consulted again per request.

    python3 tools/serve_get_tokens.py           # all interfaces, port 8000
    python3 tools/serve_get_tokens.py 9000      # a different port

This is for TESTING the page from a phone. It is not how the page is
meant to be used: whoever serves a page controls the code that sees the
password, which is the whole reason the real instructions say to copy
the file onto the phone and open it from local storage. Stop this
server when the test is done, with Ctrl-C.

Two differences from the real thing to expect while testing over HTTP:

    - The clipboard buttons fall back to selecting the text, because
      navigator.clipboard needs a secure context and a plain http://
      address on a LAN is not one. Opening the file locally on the
      phone, or any https:// origin, gets the real copy button.
    - The page's origin here is http://<address>:<port> rather than
      the "null" a file:// page sends. Both are accepted by Daze and
      Cognito, so the sign-in works either way.
"""

from __future__ import annotations

import http.server
import socket
import sys
from pathlib import Path

PAGE = Path(__file__).resolve().parent / "get_tokens.html"
DEFAULT_PORT = 8000


def _local_addresses() -> list[str]:
    """Best-effort list of addresses a phone could reach this machine on."""
    addresses: list[str] = []
    try:
        # Opening a UDP socket to a routable address picks the interface
        # the kernel would actually use, without sending anything.
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("192.0.2.1", 9))  # TEST-NET-1, never routed
        addresses.append(probe.getsockname()[0])
        probe.close()
    except OSError:
        pass
    return addresses


def _handler(body: bytes) -> type[http.server.BaseHTTPRequestHandler]:
    """Build a handler that knows one file and nothing about the disk."""

    class OneFileHandler(http.server.BaseHTTPRequestHandler):
        server_version = "daze-token-page/1.0"

        def do_GET(self) -> None:
            # Compared against an exact allowlist rather than mapped onto
            # the filesystem, so there is no path to traverse.
            if self.path.split("?")[0] not in ("/", "/get_tokens.html"):
                self.send_error(404, "Not found")
                return

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            # The page handles a password. Nothing about it should sit in
            # a cache, here or in the phone's browser.
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()

            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                # A client that hangs up mid-response is ordinary -- a
                # phone locking its screen does it, and so does any
                # probe that only wants the status line. Without this
                # the base class prints a traceback, which reads like a
                # fault in a tool whose whole job is to look
                # trustworthy.
                pass

        def log_message(self, fmt: str, *args: object) -> None:
            # Keep the request log: watching the phone connect is how you
            # know the address was right. Nothing sensitive is in a GET
            # here, because there is only one path.
            sys.stderr.write(
                f"  {self.address_string()} {fmt % args}\n"
            )

    return OneFileHandler


def main() -> int:
    """Serve the page until interrupted."""
    if not PAGE.is_file():
        print(f"Not found: {PAGE}", file=sys.stderr)
        return 1

    port = DEFAULT_PORT
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            print(f"Not a port number: {sys.argv[1]}", file=sys.stderr)
            return 1

    body = PAGE.read_bytes()

    server = http.server.ThreadingHTTPServer(
        # Bound to all interfaces deliberately: the phone has to reach it.
        ("0.0.0.0", port),
        _handler(body),
    )

    print(f"Serving {PAGE.name} ({len(body)} bytes) and nothing else.")
    print("Every other path answers 404. Ctrl-C to stop.\n")
    for address in _local_addresses():
        print(f"  http://{address}:{port}/")
    print(f"  http://localhost:{port}/   (this machine only)\n")
    print(
        "Testing only. The page is meant to be copied onto the phone and\n"
        "opened from local storage -- whoever serves it controls the code\n"
        "that sees the password.\n"
    )

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
