# BioFace M61 Modular Protocol — Reverse-Engineered Spec

**Discovery date**: 2026-04-28
**Status**: ✅ FULLY WORKING — verified on Secureeye S-FB3K firmware (`TerminalType=M61`)
**Source-of-truth**: vendor-shipped C# reference server `Terminal.cs` (BioTime 4.5.5N BioFace SDK)

## TL;DR — What we cracked

Earlier docs in this folder said port 5005 ran a "proprietary ZKTeco binary WebSocket" with no FOSS client (see [WebSocket-Mode-Research.md](WebSocket-Mode-Research.md)). **That was wrong.** Once the device was switched out of `Server-Client Mode = WebSocket` to a different mode (whichever ADMS-like option exists in the menu), it started speaking a **plain XML-over-raw-TCP protocol** to our server — and it is fully documented in a vendor-shipped C# SDK that nobody had cited in the prior research session.

The protocol has nothing to do with WebSockets despite the device-menu label. It is internally called **"BioFace M61 Modular Protocol"** in the vendor SDK.

## Transport

- **Direction**: device → server (device is the TCP client; server listens)
- **Port**: configurable (we used 5005 because that's what was already in `TCP Port` field after mode switch)
- **Connection lifecycle**: one TCP connection per event. Device opens, sends one `<Message>...</Message>` payload (~500 bytes), waits for ack, closes the connection. Reconnects 2 seconds later for next event.
- **No HTTP wrapping**: pure raw TCP, ASCII payload
- **No TLS**, no comm-key handshake required at the protocol layer — the comm password is configured but not validated by this XML dialect

## Event payload format (device → server)

Example `TimeLog` event captured 2026-04-28:

```xml
<?xml version="1.0"?><Message><TerminalType>M61</TerminalType>
<DeviceUID>90a6dbc7-e013fd16</DeviceUID>
<TerminalID>2</TerminalID>
<DeviceSerialNo>102025040003353</DeviceSerialNo>
<TransID>10661</TransID>
<Event>TimeLog</Event>
<Year>2026</Year>
<Month>2</Month>
<Day>5</Day>
<Hour>19</Hour>
<Minute>28</Minute>
<Second>5</Second>
<UserID>39</UserID>
<AttendStat>Duty Off</AttendStat>
<VerifMode>FP</VerifMode>
<JobCode>0</JobCode>
<APStat>None</APStat>
<Photo>No</Photo>
</Message>
```

### Field reference

| Tag | Meaning |
|-----|---------|
| `TerminalType` | Always `M61` for this device family |
| `DeviceUID` | Per-device hardware UID (used as primary key) — `90a6dbc7-e013fd16` for our unit |
| `TerminalID` | The "Device ID" set in the menu (we have 2) |
| `DeviceSerialNo` | The "Cloud Id" shown on screen — `102025040003353` for our unit |
| `TransID` | Sequential, device-side. Increments only after the server returns a valid `UploadedLog` ack echoing the same TransID. |
| `Event` | One of `TimeLog`, `AdminLog`, `Alarm`, `KeepAlive` |
| `Year/Month/Day/Hour/Minute/Second` | Device clock at time of event (NOT zero-padded — `Month=2` not `02`) |
| `UserID` | Internal user ID enrolled via the menu |
| `AttendStat` | `Duty On` / `Duty Off` / `OT On` / `OT Off` / `Break On` / `Break Off` |
| `VerifMode` | `FP` (fingerprint), `Face`, `Card`, `PWD` (password), or combinations like `FP+PWD` |
| `JobCode` | Optional job-cost code (0 if unused) |
| `APStat` | Auto-pulse / access-control state, mostly `None` |
| `Photo` | `Yes` / `No` — photo capture flag (not yet observed `Yes`) |

## Server reply format (the part nobody had documented)

**The reply that makes the device advance** to the next TransID:

```
<?xml version="1.0"?><Message><Request>UploadedLog</Request><TransID>{N}</TransID></Message>\x00
```

- Tag is `<Request>` — **not** `<Response>`. (Counter-intuitive — server's reply uses the verb `Request` because it's "requesting acknowledgement state".)
- Value is the literal string `UploadedLog` for `TimeLog`/`AdminLog`/`Alarm`. For `KeepAlive` events, use `KeptAlive`.
- `<TransID>` must echo the TransID the device just sent.
- **Must end with a single `0x00` byte** (this was the most commonly missed detail).
- ASCII-encoded, no HTTP headers, no Content-Length, no trailing whitespace.

### Reply lookup table

| Device sends `<Event>` | Server replies `<Request>` |
|---|---|
| `TimeLog` | `UploadedLog` |
| `AdminLog` | `UploadedLog` |
| `Alarm` | `UploadedLog` |
| `KeepAlive` | `KeptAlive` |

### Why earlier attempts failed

We tried 6 reply formats before finding the right one. The mistakes:

| Attempt | What was wrong |
|---------|----------------|
| `<Response>OK</Response>` | Tag should be `<Request>`, not `<Response>` |
| Plain `OK\r\n` | Wrong shape entirely |
| HTTP-wrapped XML | Protocol is raw TCP, no HTTP envelope |
| Echoed envelope with `<DeviceUID>`/`<TerminalID>`/etc | Extra fields aren't read by the device's parser; only `<Request>` and `<TransID>` matter |
| `<Response>ACK</Response><Result>1</Result>` | Wrong tag name AND missing trailing `\x00` |
| Silent close | Device times out and retransmits |

The **single missing `0x00` byte** at the end was the most common silent failure — without it, the device's XML parser sits waiting for end-of-message and eventually times out, triggering retransmission.

## Sequence diagram

```
Device (10.0.0.201)                         Server (10.0.0.148:5005)
     |                                                    |
     | TCP SYN ─────────────────────────────────────────> |
     | <───── SYN/ACK ─────────────────────────────────── |
     | ACK ─────────────────────────────────────────────> |
     |                                                    |
     | <Message><TransID>10661</TransID>...               |
     | <Event>TimeLog</Event>...</Message>  ────────────> |
     |                                                    |
     |                  <Message>                         |
     |                    <Request>UploadedLog</Request>  |
     |                    <TransID>10661</TransID>        |
     |                  </Message>\x00                    |
     | <───────────────────────────────────────────────── |
     |                                                    |
     | TCP FIN ─────────────────────────────────────────> |
     |                                                    |
     | (2-second wait, then new connection)               |
     |                                                    |
     | TCP SYN ─────────────────────────────────────────> |
     | ... <TransID>10662</TransID> ...                   |
```

## What about server-initiated commands?

**EARLIER VERSION OF THIS DOC CLAIMED 11 commands work via the reply channel — that was speculation and is WRONG.** The full vendor SDK was downloaded April 28, 2026 and analysed:

- `BIOFACE_BIOT5N/C#_LogServer/Terminal.cs` (the file we cracked) only handles **2 reply types**: `UploadedLog` and `KeptAlive`. Nothing else. There is **no command channel** in the LogServer protocol.
- Device commands live in a **separate component**: `BIOFACE_BIOT5N/C#_SBXPCDLL_Sample/SBXPCDLLSampleCSharp/sbxpc/SBXPCDLL.cs` — a 2110-line C# wrapper around `SBXPCDLL.dll`. This DLL exposes **65 device commands**, not 11.
- The SDK uses **the same port 5005** but in the **opposite direction**: when device is in `WebSocket Server` mode, port 5005 is INBOUND on the device, and the SDK connects TO it. When device is in `BioFace M61 / LogClient` mode (current), port 5005 is OUTBOUND from the device and SDK commands cannot be sent.

In other words: **you cannot run the LogServer (event receiver) and the SDK command channel at the same time** unless the device firmware supports a dual-mode setting (Push+Pull). Standard BioFace firmware is one-or-the-other.

## Full SBXPCDLL command list (65 functions)

Source: `vendor-sdk/SDK_BIOTIME_4_5_5N_BIOFACE/.../SBXPCDLL.cs`. Port 5005, password (default `0`, our device `123456`), via `ConnectTcpip(machineNum, ip, port, password)` first.

### User management (14)
`GetAllUserID`, `ReadAllUserID`, `GetUserName`, `SetUserName`, `GetUserName1`, `SetUserName1`, `EnableUser`, `ModifyPrivilege`, `GetEnrollData`, `SetEnrollData`, `GetEnrollData1`, `SetEnrollData1`, `DeleteEnrollData`, `EmptyEnrollData`

### Time / clock (5)
`GetDeviceTime`, `SetDeviceTime`, `SetDeviceTime1`, `GetBellTime`, `SetBellTime`

### Attendance logs (13)
`GetAllGLogData`, `ReadAllGLogData`, `GetGeneralLogData`, `ReadGeneralLogData`, `ReadGLogWithPos`, `EmptyGeneralLogData`, `GetAllSLogData`, `ReadAllSLogData`, `GetSuperLogData`, `ReadSuperLogData`, `ReadSLogWithPos`, `EmptySuperLogData`, `SetTranseiveCallback`

### Access control / door (2)
`GetDoorStatus`, `SetDoorStatus`

### Power (2)
`PowerOffDevice`, `PowerOnAllDevice`

### Device info / config (10)
`GetDeviceInfo`, `SetDeviceInfo`, `GetDeviceLongInfo`, `SetDeviceLongInfo`, `GetDeviceStatus`, `GetSerialNumber`, `GetMachineIP`, `GetProductCode`, `SetMachineType`, `EnableDevice`

### Company / department (5)
`GetCompanyName`, `SetCompanyName`, `GetCompanyName1`, `SetCompanyName1`, `GetDepartName`, `SetDepartName`

### Communication (5)
`ConnectTcpip`, `ConnectSerial`, `Disconnect`, `DisconnectAll`, `PrepareP2p`

### Event capture (real-time) (2)
`StartEventCapture`, `StopEventCapture`

### Misc / utility (7)
`ClearKeeperData`, `ModifyDuressFP`, `GetLastError`, `GeneralOperationXML`, `XML`, `DotNET`, `SetTranseiveCallback`

## To actually call any of the 65 commands

**Three paths, ranked by effort:**

### A. Run SDK sample on Windows VM (1 hour)
1. Toggle device `Server-Client Mode` → `WebSocket` (server mode, restores port 5005 inbound)
2. Boot a Windows 10 VM
3. Compile `SBXPCDLL_Sample/` with Visual Studio (or use the prebuilt `bin/Debug/SBXPCDLLSampleCSharp.exe` ~21 KB shipped in the repo)
4. Configure: IP `10.0.0.201`, Port `5005`, Password `123456` → Connect
5. All 65 commands available via the Windows GUI: enroll users, set time, open door, dump logs, power off, etc.

### B. Reverse-engineer the wire protocol for a Linux/Python port (1-2 days)
1. Run path A first to confirm device connectivity
2. Wireshark capture on the Windows VM during a series of SDK calls
3. Identify the binary frame format (likely length-prefixed XML or proprietary TLV)
4. Reproduce in Python — start with `ConnectTcpip` handshake, then `GetDeviceTime` (simplest), then `SetDeviceTime`, then user-management calls
5. Open-source the result. **No public FOSS Python port of SBXPCDLL exists** as of April 2026, so this is publishable.

### C. Run SBXPCDLL.dll under Wine on Linux (uncertain)
The DLL is `x86` Windows binary (1.9 MB). Wine *might* run it for `pinvoke`-style calls but the underlying TCP socket calls go through Wine's networking stack which has known quirks for proprietary binary protocols. Worth ~2 hours to try; not worth more.

## Trade-off

| Capability | LogServer (current) | SBXPCDLL (alternative mode) |
|---|---|---|
| Port | 5005 (us listening) | 5005 (device listening) |
| Real-time event push | ✅ Yes (~2 s) | ❌ No (must poll) |
| Send commands to device | ❌ No | ✅ 65 commands |
| Linux/Python native | ✅ Yes (cracked) | ❌ Not yet (DLL is Windows) |
| Mode toggle on device | "BioFace M61" / "LogClient" | "WebSocket" |

**Decision rule**: stay on LogServer mode for production attendance ingestion. Switch to WebSocket mode (or run a periodic sync window) only for administrative tasks like enroll-new-user or set-time. A future improvement is to merge: poll-and-push hybrid mode if firmware supports it.

## Reference implementation (canonical for this folder)

Working Python listener is at `/tmp/adms_listener.py` (during the 2026-04-28 session). For production deployment, a copy will live at `/opt/secureeye-fb3k-attlog/listener.py` on `office-server` (10.0.0.2) — see [Integration.md](Integration.md).

Core handler:

```python
def handle(conn, addr, port):
    data = conn.recv(16384)
    if not data.lstrip().startswith((b'<?xml', b'<Message')):
        return
    tid   = re_extract(data, 'TransID', '0')
    event = re_extract(data, 'Event')
    request_type = {
        'TimeLog':   'UploadedLog',
        'AdminLog':  'UploadedLog',
        'Alarm':     'UploadedLog',
        'KeepAlive': 'KeptAlive',
    }.get(event, 'UploadedLog')
    reply = (
        f'<?xml version="1.0"?>'
        f'<Message><Request>{request_type}</Request>'
        f'<TransID>{tid}</TransID></Message>'
    ).encode('ascii') + b'\x00'
    conn.sendall(reply)
    conn.close()
```

## Verified test results (2026-04-28)

Listener ran for 25 seconds during initial drain. Cleared 12 backed-up events:

| Metric | Value |
|--------|-------|
| TransID range | 10661 → 10672 |
| Unique users seen | 12 (UserIDs: 30, 32, 33, 34, 36, 37, 39, 41, 42, 44, 46, 48) |
| All events | `Event=TimeLog`, `AttendStat=Duty Off`, `VerifMode=FP` |
| Date in payloads | All `2026-02-05` (device clock is wrong — see Access.md TODO) |
| Drain rate | 1 event / 2 s |
| All acks accepted | Yes — TransID advanced monotonically |

See [Captured-Punches-2026-04-28.md](Captured-Punches-2026-04-28.md) for the raw event log.

## Key insight for the project

This protocol turns out to be **dramatically simpler** than the WebSocket binary protocol researched in [WebSocket-Mode-Research.md](WebSocket-Mode-Research.md). Production integration with our existing FastAPI / n8n stack is a straightforward FastAPI endpoint — no ZKBio CVSecurity, no Wireshark replay, no proprietary binary parsing.

Effectively this is the same complexity tier as the eSSL X2008's ADMS HTTP push pattern on `office-server:8081`, just with a different framing (raw TCP XML instead of HTTP `/iclock/cdata.aspx`).

## Sources

- **Primary**: [staffinn-main/Terminal.cs](https://github.com/staffinnsolutionsllp-commits/staffinn-main/blob/main/SDK_BIOTIME_4_5_5N_BIOFACE/SDK_BIOTIME_4_5_5N_BIOFACE/SDK_BIOTIME_4_5_5N_BIOFACE/BIOFACE_BIOT5N/C%23_LogServer/Terminal.cs) — vendor-shipped C# reference server (734 lines). Cited lines: 237 (event dispatch), 411-412 (TimeLog reply), 549 (AdminLog), 631 (Alarm), 638 (KeepAlive), 644-646 (`\x00` terminator + ASCII encoding).
- **Cross-check** (different transport, do not copy): [umarfarooq57/fastapi_learning devicebroker](https://github.com/umarfarooq57/fastapi_learning/blob/main/Attendance-Management-System/packages/devicebroker/worker.py) — Python WebSocket variant. Confirms event-tag names but uses different transport (websockets), so reply shape differs.
- **Live capture**: `/tmp/adms_capture.log` (12 events, 2026-04-28 18:40 IST) — see [Captured-Punches-2026-04-28.md](Captured-Punches-2026-04-28.md).
