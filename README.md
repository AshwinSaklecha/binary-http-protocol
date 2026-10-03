# Network Architecture — course project

BHTTP/1: a small binary protocol, then a server and a client that speak it.

This is **not** the HTTP/1.1 calculator. New protocol, new programs.

## What you hand in

1. `SPEC.md` — the protocol (two pages). A stranger can implement against it.
2. The programs — `bserve` and `bcurl`.
3. `HEXDUMP.md` — one complete request and response, annotated.

## Run (Windows)

Python 3, standard library only.

Terminal 1:

```powershell
cd D:\binary-http-protocol
python bserve.py .\www 9000
```

Terminal 2:

```powershell
python bcurl.py -v localhost:9000/index.html
```

Same commands via wrappers: `.\bserve.cmd .\www 9000` and `.\bcurl.cmd -v localhost:9000/index.html`.

On Unix the assignment’s spelling is:

```
./bserve ./www 9000
./bcurl -v localhost:9000/index.html
```

`-v` writes a hexdump of every frame to stderr. The file body goes to stdout. Exit status is nonzero on 4xx / 5xx. The client opens **one** TCP connection.

## Layout

| File | Role |
| --- | --- |
| `SPEC.md` | Protocol. Source of truth. |
| `bhttp.py` | Framing, static table, skip-unknown-type. |
| `bserve.py` | Track 1 — document root file server, keep-alive. |
| `bcurl.py` | Track 2 — client. |
| `www/` | Sample root (`index.html`, `about.txt`). |
| `HEXDUMP.md` | Annotated capture. |
| `test_bhttp.py` | 200 / 404 / 400, unknown-type skip, two requests on one socket. |

```powershell
python test_bhttp.py
```
