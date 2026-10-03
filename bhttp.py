"""BHTTP/1 framing. This file is the implementation of SPEC.md."""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

VERSION = 1
HEADER_SIZE = 8
MAX_LENGTH = 0xFFFFFF

TYPE_HEADERS = 0x01
TYPE_DATA = 0x02

FLAG_END_STREAM = 0x01
FLAG_END_HEADERS = 0x04

STATIC_TABLE = {
    1: "method",
    2: "path",
    3: "status",
    4: "content-type",
    5: "content-length",
    6: "host",
    7: "user-agent",
    8: "accept",
    9: "server",
    10: "date",
}
NAME_TO_INDEX = {name: idx for idx, name in STATIC_TABLE.items()}


class Malformed(Exception):
    """Frame or header block cannot be parsed."""


@dataclass
class Frame:
    type: int
    flags: int
    payload: bytes
    version: int = VERSION

    @property
    def end_stream(self) -> bool:
        return bool(self.flags & FLAG_END_STREAM)

    @property
    def end_headers(self) -> bool:
        return bool(self.flags & FLAG_END_HEADERS)

    def header_bytes(self) -> bytes:
        length = len(self.payload)
        if length > MAX_LENGTH:
            raise Malformed("payload exceeds 24-bit length")
        return (
            length.to_bytes(3, "big")
            + bytes([self.type & 0xFF, self.flags & 0xFF, self.version & 0xFF])
            + b"\x00\x00"
        )

    def to_bytes(self) -> bytes:
        return self.header_bytes() + self.payload


def encode_headers(pairs: list[tuple[str, str]]) -> bytes:
    out = bytearray()
    for name, value in pairs:
        name_l = name.lower()
        value_b = value.encode("utf-8")
        if len(value_b) > 0xFFFF:
            raise Malformed("value too long")
        idx = NAME_TO_INDEX.get(name_l)
        if idx is not None:
            out.append(0x80 | idx)
            out += len(value_b).to_bytes(2, "big")
            out += value_b
        else:
            name_b = name_l.encode("ascii")
            if len(name_b) > 0xFFFF:
                raise Malformed("name too long")
            out.append(0x00)
            out += len(name_b).to_bytes(2, "big")
            out += name_b
            out += len(value_b).to_bytes(2, "big")
            out += value_b
    return bytes(out)


def decode_headers(payload: bytes) -> list[tuple[str, str]]:
    headers: list[tuple[str, str]] = []
    i = 0
    n = len(payload)
    while i < n:
        kind = payload[i]
        i += 1
        if kind & 0x80:
            idx = kind & 0x7F
            if idx not in STATIC_TABLE:
                raise Malformed(f"unknown static index {idx}")
            if i + 2 > n:
                raise Malformed("truncated indexed value length")
            vlen = int.from_bytes(payload[i : i + 2], "big")
            i += 2
            if i + vlen > n:
                raise Malformed("truncated indexed value")
            value = payload[i : i + vlen].decode("utf-8")
            i += vlen
            headers.append((STATIC_TABLE[idx], value))
        elif kind == 0x00:
            if i + 2 > n:
                raise Malformed("truncated literal name length")
            nlen = int.from_bytes(payload[i : i + 2], "big")
            i += 2
            if i + nlen > n:
                raise Malformed("truncated literal name")
            name = payload[i : i + nlen].decode("ascii").lower()
            i += nlen
            if i + 2 > n:
                raise Malformed("truncated literal value length")
            vlen = int.from_bytes(payload[i : i + 2], "big")
            i += 2
            if i + vlen > n:
                raise Malformed("truncated literal value")
            value = payload[i : i + vlen].decode("utf-8")
            i += vlen
            headers.append((name, value))
        else:
            raise Malformed(f"bad header entry kind 0x{kind:02x}")
    return headers


def header_map(pairs: list[tuple[str, str]]) -> dict[str, str]:
    return {k.lower(): v for k, v in pairs}


def recvall(sock, n: int) -> bytes | None:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            if not buf:
                return None
            raise Malformed("truncated frame")
        buf.extend(chunk)
    return bytes(buf)


def read_frame(sock) -> Frame | None:
    """Read one frame. Unknown types are returned as Frame with that type (payload already consumed)."""
    header = recvall(sock, HEADER_SIZE)
    if header is None:
        return None
    length = int.from_bytes(header[0:3], "big")
    type_ = header[3]
    flags = header[4]
    version = header[5]
    payload = recvall(sock, length)
    if payload is None:
        raise Malformed("truncated payload")
    return Frame(type=type_, flags=flags, payload=payload, version=version)


def write_frame(sock, frame: Frame) -> None:
    sock.sendall(frame.to_bytes())


def headers_frame(pairs: list[tuple[str, str]], *, end_stream: bool) -> Frame:
    flags = FLAG_END_HEADERS
    if end_stream:
        flags |= FLAG_END_STREAM
    return Frame(type=TYPE_HEADERS, flags=flags, payload=encode_headers(pairs))


def data_frame(chunk: bytes, *, end_stream: bool) -> Frame:
    flags = FLAG_END_STREAM if end_stream else 0
    return Frame(type=TYPE_DATA, flags=flags, payload=chunk)


def hexdump_frame(frame: Frame, direction: str) -> str:
    raw = frame.to_bytes()
    type_name = {TYPE_HEADERS: "HEADERS", TYPE_DATA: "DATA"}.get(frame.type, f"UNKNOWN(0x{frame.type:02x})")
    flag_parts = []
    if frame.flags & FLAG_END_STREAM:
        flag_parts.append("END_STREAM")
    if frame.flags & FLAG_END_HEADERS:
        flag_parts.append("END_HEADERS")
    flags = "|".join(flag_parts) if flag_parts else "none"
    lines = [
        f"{direction} {type_name}  len={len(frame.payload)}  flags={flags}  ver={frame.version}",
        f"{direction} header: {frame.header_bytes().hex(' ')}",
    ]
    for off in range(0, len(raw), 16):
        chunk = raw[off : off + 16]
        hexpart = " ".join(f"{b:02x}" for b in chunk)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"  {off:04x}  {hexpart:<47}  {ascii_part}")
    if frame.type == TYPE_HEADERS:
        try:
            for name, value in decode_headers(frame.payload):
                lines.append(f"       {name}: {value}")
        except Malformed as exc:
            lines.append(f"       (malformed header block: {exc})")
    return "\n".join(lines)


@dataclass
class Message:
    headers: list[tuple[str, str]] = field(default_factory=list)
    body: bytearray = field(default_factory=bytearray)

    def map(self) -> dict[str, str]:
        return header_map(self.headers)


def read_message(sock) -> Message | None:
    """Read frames until END_STREAM. Unknown types are skipped. None = peer closed before a message."""
    msg = Message()
    saw_headers = False
    while True:
        frame = read_frame(sock)
        if frame is None:
            if saw_headers:
                raise Malformed("peer closed mid-message")
            return None
        if frame.type not in (TYPE_HEADERS, TYPE_DATA):
            # Spec: unknown type MUST be skipped. Payload already consumed by read_frame.
            continue
        if frame.type == TYPE_HEADERS:
            if not frame.end_headers:
                raise Malformed("HEADERS without END_HEADERS")
            msg.headers = decode_headers(frame.payload)
            saw_headers = True
        elif frame.type == TYPE_DATA:
            if not saw_headers:
                raise Malformed("DATA before HEADERS")
            msg.body.extend(frame.payload)
        if frame.end_stream:
            if not saw_headers:
                raise Malformed("END_STREAM before HEADERS")
            return msg
