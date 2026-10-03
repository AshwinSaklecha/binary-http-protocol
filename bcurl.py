#!/usr/bin/env python3
"""BHTTP/1 client. Usage: python bcurl.py [-v] localhost:9000/index.html"""

from __future__ import annotations

import argparse
import socket
import sys

from bhttp import (
    Malformed,
    hexdump_frame,
    headers_frame,
    read_frame,
    write_frame,
    TYPE_DATA,
    TYPE_HEADERS,
)


def parse_target(raw: str) -> tuple[str, int, str]:
    text = raw
    if "://" in text:
        text = text.split("://", 1)[1]
    if "/" in text:
        hostport, path = text.split("/", 1)
        path = "/" + path
    else:
        hostport, path = text, "/"
    if ":" in hostport:
        host, port_s = hostport.rsplit(":", 1)
        port = int(port_s)
    else:
        host, port = hostport, 9000
    if path == "/":
        path = "/index.html"
    return host, port, path


def fetch(host: str, port: int, path: str, verbose: bool) -> int:
    sock = socket.create_connection((host, port), timeout=10)
    try:
        request = headers_frame(
            [
                ("method", "GET"),
                ("path", path),
                ("host", host),
                ("user-agent", "bcurl"),
                ("accept", "*/*"),
            ],
            end_stream=True,
        )
        if verbose:
            print(hexdump_frame(request, ">>"), file=sys.stderr)
        write_frame(sock, request)

        # Read the response ourselves so -v can print every frame, including skipped ones.
        body = bytearray()
        headers = []
        saw_headers = False
        status = "000"
        while True:
            frame = read_frame(sock)
            if frame is None:
                raise Malformed("server closed before END_STREAM")
            if verbose:
                print(hexdump_frame(frame, "<<"), file=sys.stderr)
            if frame.type not in (TYPE_HEADERS, TYPE_DATA):
                continue
            if frame.type == TYPE_HEADERS:
                from bhttp import decode_headers, header_map

                if not frame.end_headers:
                    raise Malformed("HEADERS without END_HEADERS")
                headers = decode_headers(frame.payload)
                saw_headers = True
                status = header_map(headers).get("status", "000")
            else:
                if not saw_headers:
                    raise Malformed("DATA before HEADERS")
                body.extend(frame.payload)
            if frame.end_stream:
                break

        sys.stdout.buffer.write(bytes(body))
        sys.stdout.buffer.flush()
        try:
            code = int(status)
        except ValueError:
            code = 400
        return 1 if code >= 400 else 0
    finally:
        sock.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="BHTTP/1 client — one connection")
    parser.add_argument("-v", action="store_true", help="hexdump every frame on stderr")
    parser.add_argument("target", help="host:port/path  e.g. localhost:9000/index.html")
    args = parser.parse_args()
    try:
        host, port, path = parse_target(args.target)
        raise SystemExit(fetch(host, port, path, args.v))
    except (Malformed, OSError, ValueError) as exc:
        print(f"bcurl: {exc}", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
