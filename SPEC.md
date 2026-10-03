# BHTTP/1 — Binary Hypertext Transfer Protocol

This document is the protocol. A stranger should be able to implement a compatible client or server from these two pages alone. The programs in this repository (`bserve`, `bcurl`) are one implementation, not the spec.

BHTTP/1 is HTTP’s job — method, path, status, headers, bytes — moved onto a length-prefixed binary framing layer so a TCP connection can stay open. It is not multiplexed. Frames on a connection are totally ordered. One request is fully answered before the next request is processed. That is deliberate: the course already forced HTTP/1.1 keep-alive; this project is about *how you find the next message* when the bytes are no longer ASCII.

## 1. Connection

TCP. The server listens. The client opens **one** connection and must not open a second for that invocation. After a response with `END_STREAM`, the connection stays up. Either side may close TCP when it is done. There is no `Connection: close` header; closing the socket is how you hang up.

Default port for the course programs is `9000`. The protocol does not care.

## 2. Frame header — 8 octets, network byte order

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                      Length (24)              |    Type (8)   |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|    Flags (8)  |   Version (8) |         Reserved (16)         |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

Then exactly `Length` octets of payload. Then the next header. There is no delimiter and no EOF-as-end-of-message.

| Field | Width | Why |
| --- | --- | --- |
| Length | 24 bits | Same reason HTTP/2 picked 24: a receiver that does not understand `Type` can still skip the frame. Cap is 16 777 215 octets, which bounds memory. 32 bits would let a peer ask you to read 4 GiB. |
| Type | 8 bits | 256 kinds. Room to grow without a version bump for every new frame. |
| Flags | 8 bits | Per-frame bits. Cheap. Does not steal space from Length. |
| Version | 8 bits | This document is version `1`. |
| Reserved | 16 bits | MUST be sent as `0`. MUST be ignored on receipt. That is space for a future version. |

HTTP/2’s header is 9 octets: `24 / 8 / 8 / 1+31` (length, type, flags, reserved bit + stream id). HTTP/2 spent 31 bits on multiplexing. BHTTP/1 does not multiplex, so those bits become `Version` + `Reserved` and the header lands on 8 octets (aligned). Keep-alive is sequential, like HTTP/1.1, not interleaved, like HTTP/2.

**The line you may not skip:** a receiver that meets a `Type` it does not know MUST read `Length` payload octets and discard them, then continue. It MUST NOT close the connection. That is how version 2 can introduce frames a version 1 peer can still walk past.

If `Version` is not `1`, still apply the skip rule for unknown types. Known types in this document keep their v1 meaning. Do not reject a connection only because Reserved is nonzero.

A truncated header, a `Length` that never arrives, or a HEADERS payload that does not parse is **malformed**. The server answers with status `400` if it can still write; if the byte stream is desynchronized it closes.

## 3. Types and flags

| Type | Name | Payload |
| --- | --- | --- |
| `0x01` | HEADERS | header block (§4) |
| `0x02` | DATA | raw body octets |
| other | unknown | skip using Length |

Flags (bitmask):

| Bit | Name | Meaning |
| --- | --- | --- |
| `0x01` | END_STREAM | Last frame of this message. |
| `0x04` | END_HEADERS | This HEADERS payload is the complete header block. |

No CONTINUATION. A HEADERS frame without `END_HEADERS` is malformed (`400`).

A **request message** is one HEADERS frame with `END_HEADERS`. GET has no body: also set `END_STREAM` on that HEADERS. A **response message** is one HEADERS (`END_HEADERS`) followed by zero or more DATA frames. The last frame of the response sets `END_STREAM`.

## 4. Header block (HPACK’s first two ideas, nothing else)

Names are lowercase ASCII. Values are UTF-8 (file bytes themselves travel in DATA, not here).

**Static table — the ten names this protocol actually sends.** Indexed from 1.

| Index | Name |
| --- | --- |
| 1 | `method` |
| 2 | `path` |
| 3 | `status` |
| 4 | `content-type` |
| 5 | `content-length` |
| 6 | `host` |
| 7 | `user-agent` |
| 8 | `accept` |
| 9 | `server` |
| 10 | `date` |

Two entry kinds, concatenated until the payload is exhausted.

**Indexed name** (HPACK idea 1): `0x80 | index` (one octet, index 1–10), then `uint16` value length, then that many value octets. Example: method GET is `81 00 03 47 45 54`.

**Literal name** (HPACK idea 2): `0x00`, then `uint16` name length, name octets, `uint16` value length, value octets. Use this for any name not in the table.

`uint16` is network byte order. A length that overruns the HEADERS payload is malformed.

Required on requests: `method`, `path`. Required on responses: `status` (three ASCII digits, e.g. `200`). `content-length`, when present, is the decimal size of the *body* (sum of DATA payloads), not the HEADERS.

## 5. Application: a file server

`method` is `GET`. `path` is origin-form (`/index.html`). The server maps it under a document root. `GET /` means `/index.html`. Paths that escape the root (`..`) are `400`. Missing files are `404`. A well-formed GET for a file that exists is `200` plus DATA.

The server keeps the TCP connection open after every response.

## 6. Status codes this protocol uses

| Status | When |
| --- | --- |
| 200 | File found, body follows (or empty DATA). |
| 400 | Malformed frame or header block, or illegal path. |
| 404 | Path not found under the root. |

A client MUST exit nonzero if `status` is 4xx or 5xx.

## 7. One request, as a stranger would write it

HEADERS, type `01`, flags `END_STREAM|END_HEADERS` = `0x05`, version `01`, reserved `0000`, payload:

```
81 00 03 47 45 54          method = GET
82 00 0b 2f 69 6e 64 65 78 2e 68 74 6d 6c   path = /index.html
86 00 09 6c 6f 63 61 6c 68 6f 73 74          host = localhost
87 00 05 62 63 75 72 6c                     user-agent = bcurl
```

The ten names in the static table (§4) are the names `bcurl` / `bserve` actually send. `bcurl`’s GET also includes `accept: */*` (index 8). A complete on-the-wire capture, with every octet labelled, is `HEXDUMP.md`.
