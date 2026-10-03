#!/usr/bin/env python3
"""BHTTP/1 file server. Usage: python bserve.py ./www 9000"""

from __future__ import annotations

import mimetypes
import socket
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from bhttp import (
    FLAG_END_HEADERS,
    FLAG_END_STREAM,
    Malformed,
    TYPE_DATA,
    TYPE_HEADERS,
    data_frame,
    decode_headers,
    header_map,
    headers_frame,
    read_frame,
    write_frame,
)

CHUNK = 16 * 1024
SERVER_NAME = "bserve/1"


def http_date() -> str:
    return datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")


def safe_path(root: Path, url_path: str) -> Path | None:
    if not url_path.startswith("/"):
        return None
    relative = url_path.split("?", 1)[0]
    if relative == "/":
        relative = "/index.html"
    candidate = (root / relative.lstrip("/")).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate


def send_status(conn, status: str, extra: list[tuple[str, str]] | None = None, body: bytes = b"") -> None:
    pairs = [
        ("status", status),
        ("server", SERVER_NAME),
        ("date", http_date()),
        ("content-length", str(len(body))),
    ]
    if extra:
        pairs.extend(extra)
    end_stream = len(body) == 0
    write_frame(conn, headers_frame(pairs, end_stream=end_stream))
    if body:
        write_frame(conn, data_frame(body, end_stream=True))


def send_file(conn, path: Path) -> None:
    data = path.read_bytes()
    ctype, _ = mimetypes.guess_type(str(path))
    extra = [("content-type", ctype or "application/octet-stream")]
    pairs = [
        ("status", "200"),
        ("server", SERVER_NAME),
        ("date", http_date()),
        ("content-type", extra[0][1]),
        ("content-length", str(len(data))),
    ]
    if len(data) == 0:
        write_frame(conn, headers_frame(pairs, end_stream=True))
        return
    write_frame(conn, headers_frame(pairs, end_stream=False))
    offset = 0
    while offset < len(data):
        chunk = data[offset : offset + CHUNK]
        offset += len(chunk)
        write_frame(conn, data_frame(chunk, end_stream=offset >= len(data)))


def handle_request_frames(conn, root: Path) -> bool:
    """Read one request message, write one response. False = close connection."""
    headers_pairs = None
    while True:
        frame = read_frame(conn)
        if frame is None:
            return False
        if frame.type not in (TYPE_HEADERS, TYPE_DATA):
            continue
        if frame.type == TYPE_DATA:
            send_status(conn, "400")
            return True
        if not (frame.flags & FLAG_END_HEADERS):
            send_status(conn, "400")
            return True
        try:
            headers_pairs = decode_headers(frame.payload)
        except (Malformed, UnicodeDecodeError):
            send_status(conn, "400")
            return True
        if not (frame.flags & FLAG_END_STREAM):
            # GET should END_STREAM on HEADERS. Extra DATA would be a body; reject for this server.
            send_status(conn, "400")
            return True
        break

    hdrs = header_map(headers_pairs)
    method = hdrs.get("method", "")
    path = hdrs.get("path", "")
    if method != "GET" or not path:
        send_status(conn, "400")
        return True

    target = safe_path(root, path)
    if target is None:
        send_status(conn, "400")
        return True
    if not target.is_file():
        send_status(conn, "404")
        return True

    send_file(conn, target)
    return True


def handle_client(conn, addr, root: Path) -> None:
    peer = f"{addr[0]}:{addr[1]}"
    try:
        while True:
            if not handle_request_frames(conn, root):
                break
            print(f"{peer} request done, connection still open", flush=True)
    except (Malformed, ConnectionResetError, BrokenPipeError, OSError) as exc:
        print(f"{peer} close: {exc}", flush=True)
        try:
            send_status(conn, "400")
        except OSError:
            pass
    finally:
        try:
            conn.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        conn.close()


def serve(root: Path, port: int, host: str = "127.0.0.1") -> None:
    root = root.resolve()
    if not root.is_dir():
        raise SystemExit(f"document root is not a directory: {root}")
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((host, port))
    listener.listen(32)
    print(f"bserve root={root}  bhttp://{host}:{port}", flush=True)
    try:
        while True:
            conn, addr = listener.accept()
            threading.Thread(target=handle_client, args=(conn, addr, root), daemon=True).start()
    except KeyboardInterrupt:
        print("\nshutting down", flush=True)
    finally:
        listener.close()


def main() -> None:
    if len(sys.argv) != 3:
        print("usage: bserve <docroot> <port>", file=sys.stderr)
        raise SystemExit(2)
    serve(Path(sys.argv[1]), int(sys.argv[2]))


if __name__ == "__main__":
    main()
