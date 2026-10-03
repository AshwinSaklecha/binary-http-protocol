# Annotated hexdump — one GET /index.html

Captured from a live `bserve` / `bcurl` exchange on loopback. Bytes are what went on the TCP connection, left to right, network byte order. This is the third hand-in item.

## Request (client → server)

One HEADERS frame. GET has no body, so `END_STREAM` is set on this same frame. The client does not open another connection afterwards.

### Frame 1 — HEADERS request

```
0000  00 00 2e 01 05 01 00 00 81 00 03 47 45 54 82 00  ...........GET..
0010  0b 2f 69 6e 64 65 78 2e 68 74 6d 6c 86 00 09 6c  ./index.html...l
0020  6f 63 61 6c 68 6f 73 74 87 00 05 62 63 75 72 6c  ocalhost...bcurl
0030  88 00 03 2a 2f 2a                                ...*/*
```

- octets 0–2 `00 00 2e` — Length = **46** (payload size, not counting the 8-octet header)
- octet 3 `01` — Type = **HEADERS**
- octet 4 `05` — Flags = **END_STREAM|END_HEADERS**
- octet 5 `01` — Version = **1**
- octets 6–7 `00 00` — Reserved, must be zero

Header block:

- `method`: `GET`
- `path`: `/index.html`
- `host`: `localhost`
- `user-agent`: `bcurl`
- `accept`: `*/*`

## Response (server → client)

HEADERS with status `200` and `content-length`, then one DATA frame carrying `www/index.html`. `END_STREAM` is on the DATA frame. After this the socket is still open; the capture simply stops.

### Frame 1 — HEADERS response

```
0000  00 00 43 01 04 01 00 00 83 00 03 32 30 30 89 00  ..C........200..
0010  08 62 73 65 72 76 65 2f 31 8a 00 1d 53 61 74 2c  .bserve/1...Sat,
0020  20 30 33 20 4f 63 74 20 32 30 32 36 20 32 30 3a   03 Oct 2026 20:
0030  34 34 3a 33 34 20 47 4d 54 84 00 09 74 65 78 74  44:34 GMT...text
0040  2f 68 74 6d 6c 85 00 03 31 39 33                 /html...193
```

- octets 0–2 `00 00 43` — Length = **67** (payload size, not counting the 8-octet header)
- octet 3 `01` — Type = **HEADERS**
- octet 4 `04` — Flags = **END_HEADERS**
- octet 5 `01` — Version = **1**
- octets 6–7 `00 00` — Reserved, must be zero

Header block:

- `status`: `200`
- `server`: `bserve/1`
- `date`: `Sat, 03 Oct 2026 20:44:34 GMT`
- `content-type`: `text/html`
- `content-length`: `193`

### Frame 2 — DATA response

```
0000  00 00 c1 02 01 01 00 00 3c 21 44 4f 43 54 59 50  ........<!DOCTYP
0010  45 20 68 74 6d 6c 3e 0d 0a 3c 68 74 6d 6c 20 6c  E html>..<html l
0020  61 6e 67 3d 22 65 6e 22 3e 0d 0a 3c 68 65 61 64  ang="en">..<head
0030  3e 0d 0a 20 20 3c 6d 65 74 61 20 63 68 61 72 73  >..  <meta chars
0040  65 74 3d 22 75 74 66 2d 38 22 3e 0d 0a 20 20 3c  et="utf-8">..  <
0050  74 69 74 6c 65 3e 42 48 54 54 50 2f 31 3c 2f 74  title>BHTTP/1</t
0060  69 74 6c 65 3e 0d 0a 3c 2f 68 65 61 64 3e 0d 0a  itle>..</head>..
0070  3c 62 6f 64 79 3e 0d 0a 20 20 3c 68 31 3e 68 65  <body>..  <h1>he
0080  6c 6c 6f 20 66 72 6f 6d 20 62 73 65 72 76 65 3c  llo from bserve<
0090  2f 68 31 3e 0d 0a 20 20 3c 70 3e 74 68 69 73 20  /h1>..  <p>this 
00a0  69 73 20 77 77 77 2f 69 6e 64 65 78 2e 68 74 6d  is www/index.htm
00b0  6c 3c 2f 70 3e 0d 0a 3c 2f 62 6f 64 79 3e 0d 0a  l</p>..</body>..
00c0  3c 2f 68 74 6d 6c 3e 0d 0a                       </html>..
```

- octets 0–2 `00 00 c1` — Length = **193** (payload size, not counting the 8-octet header)
- octet 3 `02` — Type = **DATA**
- octet 4 `01` — Flags = **END_STREAM**
- octet 5 `01` — Version = **1**
- octets 6–7 `00 00` — Reserved, must be zero
- DATA payload (193 octets), starts: `<!DOCTYPE html>\n<html lang="en">\n<head>\n  <meta charset="utf-8">\n  <title>BH`

## How to read an unknown type

If octet 3 were `63` instead of `01` or `02`, a BHTTP/1 receiver would still trust octets 0–2, read that many payload bytes, throw them away, and wait for the next 8-octet header. It would not close the socket. That is the v2 escape hatch.
