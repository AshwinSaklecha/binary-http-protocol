#!/usr/bin/env python3
"""Protocol checks: 200, 404, 400, skip unknown type, keep-alive."""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

from bhttp import (
    FLAG_END_HEADERS,
    FLAG_END_STREAM,
    Frame,
    TYPE_DATA,
    TYPE_HEADERS,
    data_frame,
    decode_headers,
    header_map,
    headers_frame,
    read_frame,
    read_message,
    write_frame,
)

ROOT = Path(__file__).resolve().parent
HOST = "127.0.0.1"
PORT = 19000


class Fail(AssertionError):
    pass


def start_server() -> subprocess.Popen:
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "bserve.py"), str(ROOT / "www"), str(PORT)],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    deadline = time.time() + 5
    last = None
    while time.time() < deadline:
        if proc.poll() is not None:
            out = proc.stdout.read().decode("utf-8", "replace") if proc.stdout else ""
            raise Fail(f"server exited:\n{out}")
        try:
            socket.create_connection((HOST, PORT), timeout=0.2).close()
            return proc
        except OSError as exc:
            last = exc
            time.sleep(0.05)
    proc.kill()
    raise Fail(f"server did not start: {last}")


def connect() -> socket.socket:
    return socket.create_connection((HOST, PORT), timeout=5)


def get(sock, path: str):
    write_frame(sock, headers_frame(
        [("method", "GET"), ("path", path), ("host", "localhost"), ("user-agent", "test")],
        end_stream=True,
    ))
    msg = read_message(sock)
    if msg is None:
        raise Fail("server closed")
    return header_map(msg.headers).get("status"), bytes(msg.body)


def test_index(sock) -> None:
    status, body = get(sock, "/index.html")
    if status != "200":
        raise Fail(f"index status {status}")
    if b"hello from bserve" not in body:
        raise Fail("index body missing marker")
    print("  GET /index.html -> 200")


def test_slash_default(sock) -> None:
    status, body = get(sock, "/")
    if status != "200" or b"hello from bserve" not in body:
        raise Fail("/ did not map to index.html")
    print("  GET / -> 200 index.html")


def test_about_then_index_same_socket(sock) -> None:
    status, body = get(sock, "/about.txt")
    if status != "200" or body != b"about this document root\n" and body.strip() != b"about this document root":
        # Windows may write \n only; file was written with \n
        if status != "200" or b"about this document root" not in body:
            raise Fail(f"about.txt {status} {body!r}")
    status2, body2 = get(sock, "/index.html")
    if status2 != "200":
        raise Fail("second request on same socket failed")
    print("  two GETs on one connection -> keep-alive")


def test_404(sock) -> None:
    status, _ = get(sock, "/nope.html")
    if status != "404":
        raise Fail(f"missing file status {status}")
    print("  GET /nope.html -> 404")


def test_skip_unknown(sock) -> None:
    unknown = Frame(type=0x63, flags=0, payload=b"future-v2-frame")
    write_frame(sock, unknown)
    status, body = get(sock, "/about.txt")
    if status != "200" or b"about this document root" not in body:
        raise Fail(f"did not skip unknown type: {status} {body!r}")
    print("  unknown type 0x63 skipped, then GET still works")


def test_malformed(sock) -> None:
    bad = Frame(type=TYPE_HEADERS, flags=FLAG_END_HEADERS | FLAG_END_STREAM, payload=b"\x81\x00")
    write_frame(sock, bad)
    msg = read_message(sock)
    if msg is None:
        raise Fail("expected 400 on malformed HEADERS")
    status = header_map(msg.headers).get("status")
    if status != "400":
        raise Fail(f"malformed -> {status}")
    print("  malformed HEADERS -> 400")


def test_bcurl() -> None:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "bcurl.py"), f"{HOST}:{PORT}/index.html"],
        cwd=str(ROOT),
        capture_output=True,
    )
    if proc.returncode != 0:
        raise Fail(f"bcurl index exit {proc.returncode} stderr={proc.stderr!r}")
    if b"hello from bserve" not in proc.stdout:
        raise Fail("bcurl did not print the file")
    miss = subprocess.run(
        [sys.executable, str(ROOT / "bcurl.py"), f"{HOST}:{PORT}/missing"],
        cwd=str(ROOT),
        capture_output=True,
    )
    if miss.returncode == 0:
        raise Fail("bcurl 404 must exit nonzero")
    print("  bcurl 200 exit 0, 404 exit nonzero")


def write_hexdump() -> None:
    sock = connect()
    try:
        request = headers_frame(
            [
                ("method", "GET"),
                ("path", "/index.html"),
                ("host", "localhost"),
                ("user-agent", "bcurl"),
                ("accept", "*/*"),
            ],
            end_stream=True,
        )
        write_frame(sock, request)
        frames = []
        while True:
            frame = read_frame(sock)
            if frame is None:
                raise Fail("closed while capturing hexdump")
            frames.append(frame)
            if frame.end_stream:
                break
    finally:
        sock.close()

    def dump(title: str, frame: Frame) -> list[str]:
        raw = frame.to_bytes()
        lines = [f"### {title}", "", "```"]
        for off in range(0, len(raw), 16):
            chunk = raw[off : off + 16]
            hexpart = " ".join(f"{b:02x}" for b in chunk)
            ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
            lines.append(f"{off:04x}  {hexpart:<47}  {ascii_part}")
        lines.append("```")
        lines.append("")
        hdr = frame.header_bytes()
        length = int.from_bytes(hdr[0:3], "big")
        lines.append(
            f"- octets 0–2 `{' '.join(f'{b:02x}' for b in hdr[0:3])}` — Length = **{length}** (payload size, not counting the 8-octet header)"
        )
        type_name = {TYPE_HEADERS: "HEADERS", TYPE_DATA: "DATA"}.get(frame.type, hex(frame.type))
        lines.append(f"- octet 3 `{hdr[3]:02x}` — Type = **{type_name}**")
        flag_bits = []
        if frame.flags & FLAG_END_STREAM:
            flag_bits.append("END_STREAM")
        if frame.flags & FLAG_END_HEADERS:
            flag_bits.append("END_HEADERS")
        lines.append(
            f"- octet 4 `{hdr[4]:02x}` — Flags = **{'|'.join(flag_bits) or 'none'}**"
        )
        lines.append(f"- octet 5 `{hdr[5]:02x}` — Version = **{frame.version}**")
        lines.append(f"- octets 6–7 `{hdr[6]:02x} {hdr[7]:02x}` — Reserved, must be zero")
        if frame.type == TYPE_HEADERS:
            lines.append("")
            lines.append("Header block:")
            lines.append("")
            for name, value in decode_headers(frame.payload):
                lines.append(f"- `{name}`: `{value}`")
        elif frame.type == TYPE_DATA:
            preview = frame.payload[:80]
            shown = preview.decode("utf-8", "replace").replace("\n", "\\n")
            lines.append(f"- DATA payload ({len(frame.payload)} octets), starts: `{shown}`")
        lines.append("")
        return lines

    out: list[str] = []
    out.append("# Annotated hexdump — one GET /index.html")
    out.append("")
    out.append("Captured from a live `bserve` / `bcurl` exchange on loopback. Bytes are what went on the TCP connection, left to right, network byte order. This is the third hand-in item.")
    out.append("")
    out.append("## Request (client → server)")
    out.append("")
    out.append("One HEADERS frame. GET has no body, so `END_STREAM` is set on this same frame. The client does not open another connection afterwards.")
    out.append("")
    out.extend(dump("Frame 1 — HEADERS request", request))
    out.append("## Response (server → client)")
    out.append("")
    out.append("HEADERS with status `200` and `content-length`, then one DATA frame carrying `www/index.html`. `END_STREAM` is on the DATA frame. After this the socket is still open; the capture simply stops.")
    out.append("")
    for i, frame in enumerate(frames, start=1):
        kind = {TYPE_HEADERS: "HEADERS", TYPE_DATA: "DATA"}.get(frame.type, f"type {frame.type}")
        out.extend(dump(f"Frame {i} — {kind} response", frame))
    out.append("## How to read an unknown type")
    out.append("")
    out.append("If octet 3 were `63` instead of `01` or `02`, a BHTTP/1 receiver would still trust octets 0–2, read that many payload bytes, throw them away, and wait for the next 8-octet header. It would not close the socket. That is the v2 escape hatch.")
    out.append("")
    (ROOT / "HEXDUMP.md").write_text("\n".join(out), encoding="utf-8")
    print("  wrote HEXDUMP.md")


def main() -> int:
    proc = start_server()
    try:
        sock = connect()
        try:
            print("live server")
            test_index(sock)
            test_slash_default(sock)
            test_about_then_index_same_socket(sock)
            test_404(sock)
            test_skip_unknown(sock)
            test_malformed(sock)
        finally:
            sock.close()
        test_bcurl()
        write_hexdump()
        print("all checks passed")
        return 0
    except Fail as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
