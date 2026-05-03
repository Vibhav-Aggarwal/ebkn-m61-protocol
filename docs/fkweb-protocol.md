# FkWeb Protocol — Live Cracked + Working

**Date**: 2026-04-29 evening session (extended to late evening for command catalog probe)
**Status**: ✅ End-to-end working — listener on `office-server:80/ebkn` capturing live device data with proper ack + injecting commands via `receive_cmd` channel

**Companion docs**:
- [Command-Catalog.md](Command-Catalog.md) — empirically tested cmd_codes (✅ working / 🟡 INVALID_PARAM / ❌ NOT_SUPPORTED)
- [Listener-v4-Reference.md](Listener-v4-Reference.md) — listener architecture, queue file, operator usage
- [Recovery-Plan.md](Recovery-Plan.md) — restore plan after destructive cmd_code probing wiped 20 users

---

## TL;DR

The third (previously unexplored) device mode `FkWeb` is **HTTP POST to `/ebkn` with JSON bodies and proprietary headers**. It is the EBKN cloud-server protocol used by EBKN/Realand devices to push events to a server. We deployed a working listener that:

- Acks `realtime_glog` (attendance) events with proper `response_code: OK` header
- Captures `realtime_enroll_data` (bulk user template push) with names + binary templates
- Receives `receive_cmd` polls every 3 seconds — **bidirectional command channel**

This protocol matches what `KhaledBinAmir/biometric_integration` (Frappe ERPNext adapter) handles.

---

## All three device modes compared

| Mode | Transport | Format | Direction | Our support |
|------|-----------|--------|-----------|-------------|
| **LogClient** | Raw TCP port 5005 | XML over TCP, `\x00` terminator | device → server | ✅ working since Apr 28 |
| **WebSocket** | TCP 8089 (or 5005) | SBPCCOMM proprietary binary | device acts as server | ❌ silent without DLL |
| **FkWeb** ⭐ NEW | HTTP POST port 80 | JSON + proprietary headers + binary | device → server (push) | ✅ working since Apr 29 |

FkWeb is the **simplest** and most modern mode. It's also the path the Frappe ERPNext app supports natively.

---

## Wire format

### Request from device

```http
POST http://10.0.0.253:80/ebkn HTTP/1.1
Host: 10.0.0.253:80
Accept: */*
Content-Type: application/octet-stream
request_code: realtime_glog                  ← what type of event
dev_id: 102025040003353                      ← device serial number
trans_id: 132                                 ← per-request transaction ID (incremented)
blk_no: 1                                     ← block number for multi-part uploads (optional)
Content-Length: 105
Connection: close

{"fk_bin_data_lib":"M50","user_id":"00000086","verify_mode":2,"io_mode":1,"io_time":"20260429222905"}
```

Notes:
- **Path is sent as absolute URL** (`POST http://10.0.0.253:80/ebkn HTTP/1.1`), not just `/ebkn` — header parsers must handle both
- Body is **JSON** (sometimes prefixed with 4-byte length), often followed by **binary template data** for enrollment
- Headers use **underscore_in_headers** style — make sure your nginx allows them (`underscore_in_headers on;`)

### Required response from server

```http
HTTP/1.1 200 OK
Content-Type: application/octet-stream
response_code: OK
trans_id: 132                                 ← echo from request
Content-Length: 0
Connection: close

```

Empty body. The critical bit is the **`response_code: OK` HEADER** (not body field). If you reply with any other format (XML, JSON body, plain "OK"), the device will **retransmit** the same event indefinitely — we observed 1413 retransmits before adding the proper header.

For ERROR: same shape with `response_code: ERROR`.

---

## All `request_code` types observed

### `realtime_glog` — attendance event push

```json
{
  "fk_bin_data_lib": "M50",
  "user_id": "00000086",
  "verify_mode": 2,
  "io_mode": 1,
  "io_time": "20260429222905"
}
```

| Field | Meaning |
|-------|---------|
| `fk_bin_data_lib` | Confirms protocol generation — **"M50"** for our M61BH device |
| `user_id` | Zero-padded 8-digit UID |
| `verify_mode` | 0=SystemDefault, 1=FP only, 2=FP, 3=Card+FP, 7=Card+PWD, 8=FP+PWD, 11=Card+Face (per `umarfarooq57/fastapi_learning` enum) |
| `io_mode` | 0=Out, 1=In (or attend stat: DutyOn/DutyOff) |
| `io_time` | YYYYMMDDHHMMSS local |

### `realtime_enroll_data` — user template bulk push

```json
{
  "user_id": "00000030",
  "user_name": "Employee001",
  "user_privilege": 0,
  "user_enabled": 1,
  "user_depart_id": 1,
  "enroll_data_array": [
    {"backup_number": 0,  "enroll_data": "BIN_1"},
    {"backup_number": 1,  "enroll_data": "BIN_2"},
    {"backup_number": 2,  "enroll_data": "BIN_3"},
    {"backup_number": 12, "enroll_data": "BIN_4"}
  ]
}
[+ binary template data after the JSON, byte length per BIN_N]
```

| Field | Meaning |
|-------|---------|
| `user_id` | UID (8-digit zero-padded) |
| `user_name` | Display name (often trailing space) |
| `user_privilege` | 0=User, 1=Manager, 2=Admin, 3=Super-admin |
| `user_enabled` | 1=enabled, 0=disabled |
| `user_depart_id` | Department ID |
| `enroll_data_array[].backup_number` | 0-9 = fingerprints (different fingers), 10=password, 11=card, **12 = face**, 14=user TZ, 15=PWD with leading zero, 16=user dept |
| `enroll_data_array[].enroll_data` | `"BIN_1"`, `"BIN_2"` ... = placeholder IDs; actual binary blobs follow JSON in the body |

The body has structure:
1. 4-byte little-endian length prefix
2. JSON metadata
3. `|` separator (sometimes)
4. Binary template blobs (1404 bytes each for FP, 27668 bytes for face)

### `receive_cmd` — device polling for server commands ⭐

Device hits this **every 3 seconds** with incrementing `trans_id`:

```json
{
  "fk_name": "M61BH",
  "fk_time": "20260429222912",
  "fk_info": {
    "supported_enroll_data": ["FP", "PASSWORD", "IDCARD", "FACE"],
    "fk_bin_data_lib": "M50",
    "firmware": "M61BH v3.16.1118"
  }
}
```

The device asks: *"any commands for me?"*

To **inject a command** (open door, set time, enroll user, etc.), reply with the command **body**:

```http
HTTP/1.1 200 OK
response_code: OK
cmd_code: <command_code>                       ← e.g. "OpenDoor", "SetTime"
trans_id: <new_trans_id>                       ← unique for this command
Content-Length: <N>

<command body — JSON or binary>
```

If empty body → device interprets as "no command, keep polling". This is the **command channel** for active control.

### `send_cmd_result` ✅ NOW OBSERVED (2026-04-29 late evening)

Per `KhaledBinAmir/biometric_integration` adapter, after device executes a command we pushed via `receive_cmd`, it calls back with `send_cmd_result` to report success/failure. Headers include `cmd_return_code: OK` / `ERROR_INVALID_PARAM` / `ERROR_NOT_SUPPORTED`.

We have now empirically verified this round-trip for 30+ cmd_codes — see [Command-Catalog.md](Command-Catalog.md). Sample callback after `SET_TIME` injection:

```http
POST http://10.0.0.253:80/ebkn HTTP/1.1
request_code: send_cmd_result
dev_id: 102025040003353
trans_id: ab123c45                              ← matches our injected trans_id
cmd_return_code: OK                              ← outcome
Content-Length: 0
```

Listener v4 captures these to `/tmp/secureeye-cmd-results.jsonl`.

---

## Listener implementation (`reference-server/listener_v4.py`)

The v3 listener (in same folder) was the first to implement FkWeb. v4 extends it with command injection + result capture — that's the production version on `office-server` now. See [Listener-v4-Reference.md](Listener-v4-Reference.md) for full architecture and operator usage. Key code (FkWeb handler core, identical between v3 and v4 for the read path):

```python
if path_only.startswith('/ebkn'):
    req_code = headers.get('request_code', 'unknown')
    dev_id = headers.get('dev_id', '?')
    trans_id = headers.get('trans_id', '0')
    blk_no = headers.get('blk_no', None)

    # Parse JSON portion of body (binary blobs follow)
    if body and b'{' in body[:20]:
        try:
            json_start = body.find(b'{')
            json_end = body.rfind(b'}')
            j = json.loads(body[json_start:json_end+1])
            log(f"  EBKN: req_code={req_code} dev_id={dev_id} trans_id={trans_id} blk={blk_no} json={j}")
        except Exception:
            pass

    # The critical ack format — empty body + response_code: OK header
    resp = (
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: application/octet-stream\r\n"
        b"response_code: OK\r\n"
        b"trans_id: " + trans_id.encode() + b"\r\n"
        b"Content-Length: 0\r\n"
        b"Connection: close\r\n\r\n"
    )
    conn.sendall(resp)
```

**Critical detail about HTTP path**: device sends absolute URL in request line:

```
POST http://10.0.0.253:80/ebkn HTTP/1.1
```

NOT relative `/ebkn`. Our parser must handle both:

```python
if '://' in path:
    path_only = '/' + path.split('://', 1)[1].split('/', 1)[1]
else:
    path_only = path
```

---

## Live test results (2026-04-29 22:27-22:30 session)

### Counts in 30-second window after deploying proper ack

| request_code | Count | Notes |
|--------------|-------|-------|
| `realtime_glog` | 2 | ✅ Our ack accepted (was 1413 before fix) |
| `realtime_enroll_data` | 587 | Device mid-bulk-uploading all 20 users |
| `receive_cmd` | 32 | Polling every ~3 sec |

### Live attendance event captured (the proof)

```
[2026-04-29 22:29:06]
  EBKN: req_code=realtime_glog
  dev_id=102025040003353
  trans_id=0
  json={'fk_bin_data_lib': 'M50', 'user_id': '00000086',
        'verify_mode': 2, 'io_mode': 1, 'io_time': '20260429222905'}
```

End-to-end: punch at 22:29:05 IST → server log at 22:29:06 IST. **~1 second latency.**

### Per-user enrollment data flowing live

| UserID | Name | FP templates | Face | Notes |
|--------|------|--------------|------|-------|
| 30 | Employee001 | 3 | 1 | (BIN_1+2+3 fingers, BIN_4 face) |
| 32 | Employee002 | 2 | 1 | |
| 33 | Employee003 | 1 | 1 | |
| 35 | Employee004 | 2 | 1 | |
| 36 | Employee005 | 1 | 1 | |
| 38 | Employee006 | 1 | 1 | |
| ... | ... | | | + 14 more users |

(Cross-check with `Archive/parsed/user-mapping.md` — exact same enrollment counts as USB extract)

### Device firmware self-disclosure (via receive_cmd JSON)

```json
{
  "fk_name": "M61BH",
  "firmware": "M61BH v3.16.1118",
  "supported_enroll_data": ["FP", "PASSWORD", "IDCARD", "FACE"],
  "fk_bin_data_lib": "M50"
}
```

Confirms device firmware tag visible to server **without** physical access. Also confirms M50 is the protocol library (not M61) — device hardware is M61BH but speaks M50 protocol generation.

---

## Comparison with LogClient mode

| Aspect | LogClient (port 5005) | FkWeb (port 80) |
|--------|----------------------|-----------------|
| Transport | Raw TCP | HTTP |
| Format | XML | JSON |
| Event tags | `TimeLog`, `AdminLog`, `KeepAlive` (v1) | `realtime_glog`, `realtime_enroll_data`, `receive_cmd` |
| Per-event TransID | Sequential per event type | Per-request, incrementing |
| Binary template push | No | Yes — full enrollment data flowing |
| Server → device commands | Reply tag only (no real bidirectional) | `receive_cmd` channel — true bidirectional |
| Connection lifecycle | One TCP per event | Multiple per event (POST + close) |
| Production reference | None public for our M61BH | `KhaledBinAmir/biometric_integration` (Frappe) |

**FkWeb is strictly superior** for our use case:
- Captures user names + biometric templates (LogClient doesn't)
- Has bidirectional command channel
- HTTP = easier to debug, integrate, proxy through nginx
- Production-grade reference implementation exists

---

## Production deployment paths

### Path 1: Use Frappe `biometric_integration` directly (recommended)
Deploy on `genauto-server` (which already runs Frappe/ERPNext). The Frappe app's `EBKNAdapter.dispatch()` handles all 4 request_codes (`realtime_glog`, `realtime_enroll_data`, `receive_cmd`, `send_cmd_result`) and creates Employee Checkin records automatically.

Effort: 1 day (Frappe app install + nginx config + device URL update).

### Path 2: Extend our Python listener
Build on `listener_v3.py` to:
- Forward `realtime_glog` events to ERPNext / n8n / OpenClaw / wherever
- Capture full `realtime_enroll_data` to local DB
- Handle multi-block enroll uploads (currently we only ack each block but don't reassemble)
- Inject commands via `receive_cmd` reply

Effort: 2-3 days to make production-grade.

### Path 3: Pure-Python EBKN broker (publication-grade)
Take `umarfarooq57/fastapi_learning` (M50 RFC6455 broker) and adapt to our HTTP/JSON variant. Combined with the firmware research from `samiulazm/EN-818-firmware-AK3760` and our LogClient/FkWeb cracks, this becomes the **first comprehensive FOSS implementation** for EBKN/Realand BIOFACE family.

Effort: 1-2 weeks. Output: GitHub repo + Zenodo paper.

---

## Outstanding research questions

1. **Multi-block reassembly** — when `blk_no=1`, is there a follow-up `blk_no=2,3,...,0`? We see only `blk_no=1` in current data. Likely device sends one user per block when all fits in one POST (1024 bytes including binary). For larger enrollments (e.g. multiple FP per user with face), it might split.

2. ~~**`send_cmd_result` flow**~~ ✅ **CONFIRMED 2026-04-29 late evening** — see Command-Catalog.md. Outcome reported via `cmd_return_code` header (OK / ERROR_INVALID_PARAM / ERROR_NOT_SUPPORTED).

3. ~~**What command codes does the device accept?**~~ ✅ **CATALOGUED 2026-04-29** — 30+ codes tested. 8 fully working (incl. SET_TIME, GET_USER_INFO, GET_USER_ID_LIST, GET_DEVICE_STATUS, GET_LOG_DATA, plus the destructive triple). See [Command-Catalog.md](Command-Catalog.md). Open: body format for OPEN_DOOR (INVALID_PARAM) is the highest-value remaining unknown.

4. **Binary template format** — the `BIN_1`/`BIN_2` placeholders refer to chunks of the body after JSON. We need to parse the 4-byte length prefix + binary blob structure. Templates are likely the same proprietary format we have in `Archive/usb-extract-2026-04-28/enrolldb-extracted/user_*_fp_*.dat` and `user_*_face.dat`.

5. **`receive_cmd` polling rate** — 3 seconds. Configurable? Some firmwares allow tuning. Worth checking device menu.

6. **`OPEN_DOOR` body shape** — recognised verb (INVALID_PARAM not NOT_SUPPORTED) but 40+ JSON variants tried. May need: a different framing (raw, no prefix), a typed binary header, or the M50 XML envelope wrapped in length-prefix. See [Command-Catalog.md](Command-Catalog.md) "🟡 Recognised but body format unknown" section.

---

## Files added/modified in this session

| Path | Action |
|------|--------|
| `reference-server/listener_v3.py` | NEW — multi-protocol listener (BioFace M61 v1 + FkWeb + RFC6455 WS) |
| `reference-server/listener_v4.py` | NEW — adds `receive_cmd` injection, `send_cmd_result` capture, queue file |
| `/opt/secureeye-fb3k-attlog/listener.py` (on office-server) | Updated to v4 |
| `FkWeb-Protocol-2026-04-29.md` | UPDATED — this document |
| `Command-Catalog.md` | NEW — empirical cmd_code catalog (30+ verbs) |
| `Listener-v4-Reference.md` | NEW — listener architecture + operator usage |
| `Recovery-Plan.md` | NEW — restore plan after destructive cmd_code probe wiped 20 users |

---

## What this enables RIGHT NOW

- **Full real-time attendance capture** with user IDs + names + verify modes
- **Live enrollment data including biometric templates** for all 20 users
- **Server → device command channel ready** (just need to fill `receive_cmd` reply body to push commands)
- **Device firmware version + capabilities self-disclosed** in receive_cmd JSON

The device is now effectively a **fully observable, partially controllable** node in our infrastructure. Read = 100%, write = pending command-injection test.

---

## Bottom-line for the project

We now have **three working paths** to the device:

1. **LogClient** — read events (working since Apr 28)
2. **FkWeb** ⭐ — read events + bidirectional command channel (working since Apr 29) ← **best path**
3. **WebSocket** — proprietary, needs SBPCCOMM RE or Windows DLL (not viable on FOSS Linux)

Recommendation: **stay on FkWeb mode**. It's superior to LogClient and matches the Frappe ERPNext production stack.
