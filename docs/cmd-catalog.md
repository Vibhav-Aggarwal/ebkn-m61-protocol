# EBKN Command Catalog — Empirical Test Results

**Date**: 2026-04-29 (late evening session)
**Method**: Inject `cmd_code` payloads via `receive_cmd` reply channel on listener v4 (see [Listener-v4-Reference.md](Listener-v4-Reference.md)). Watch device-side `send_cmd_result` callback for outcome.
**Device**: Secureeye S-FB3K, firmware **M61BH v3.16.1118**, `fk_bin_data_lib=M50`
**Listener**: `office-server:80/ebkn` (systemd `secureeye-fb3k-listener.service`)
**Source for command names**: `reference-projects/biometric_integration/biometric_integration/services/command_processor.py` + `adapters/ebkn.py` (Frappe ERPNext adapter — production reference)

This document is the **canonical** record of what works, what is recognised but body-format-unknown, and what the firmware refuses outright.

---

## Status legend

| Symbol | Meaning |
|--------|---------|
| ✅ OK | Device returned `cmd_return_code: OK` in `send_cmd_result` callback. Command executed. |
| 🟡 INVALID_PARAM | Device returned `cmd_return_code: ERROR_INVALID_PARAM`. Cmd_code is recognised but our body shape is wrong. |
| ❌ NOT_SUPPORTED | Device returned `cmd_return_code: ERROR_NOT_SUPPORTED`. Firmware does not implement this code. |
| 💀 EXECUTED-DESTRUCTIVE | Device returned OK *and* the operation was destructive (data wiped). |

---

## ✅ Fully working — body format known

| cmd_code | Body | Returns | Notes |
|----------|------|---------|-------|
| `GET_USER_ID_LIST` | (empty) | `{"user_id_count": 20, "user_id_array": [...]}` | First call after wipe returned `user_id_count=0`. Body must be empty (no JSON braces, no length prefix). |
| `GET_USER_INFO` | `{"user_id":"00000030"}` | Full user record incl. `enroll_data_array` | UID is **8-digit zero-padded string**, not int. Returns same shape as `realtime_enroll_data` push. |
| `GET_DEVICE_STATUS` | (empty) | Capacity / counts / door state | Per `umarfarooq57/fastapi_learning` M50 enum: ManagerCount, UserCount, FaceCount, FpCount, CardCount, PwdCount, QRCount, DoorStatus, AlarmStatus. |
| `GET_LOG_DATA` | (empty) | Attendance log dump | Empty after our `CLEAR_LOG_DATA` accident — no records to verify shape. |
| `SET_TIME` | `{"time":"YYYYMMDDHHMMSS"}` | OK | **Verified 22:36:08 IST**: queued `SET_TIME` with current laptop clock → device clock corrected by 22:37:00. First successful write operation. |
| `CLEAR_ENROLL_DATA` 💀 | (empty) | OK — **wiped all 20 users** | Fired by accident during empty-body bulk-probe. Device went from 20 users → 0. Backup at `Archive/usb-extract-2026-04-28/ENROLLDB.ZIP`. See [Recovery-Plan.md](Recovery-Plan.md). |
| `CLEAR_LOG_DATA` 💀 | (empty) | OK — **wiped attendance log** | Same incident. ALOG cleared on device. Backup of historic 11,836 records at `Archive/usb-extract-2026-04-28/ALOG_002.txt` and `Archive/parsed/`. |
| `CLEAR_ALL_ADMIN` 💀 | (empty) | OK — **wiped admin** | Same incident. UID 86 super-admin status removed from device. We can re-enrol from menu without admin auth (factory default). |

---

## 🟡 Recognised but body format unknown (`ERROR_INVALID_PARAM`)

The device **knows the cmd_code** but our request body is malformed. Most likely the body needs a specific JSON schema, length prefix, or binary blob shape that we have not yet discovered.

| cmd_code | Most-likely shape (per Frappe adapter / M50 SDK) | Variants tried |
|----------|-------------------------------------------------|----------------|
| `OPEN_DOOR` 🚪 | `{"door_no": 1}` (Frappe adapter, hardcoded) | **40+ variants**: empty, `{"door_no":1}`, `{"door_no":2}`, `{"DoorNo":1}`, `{"door":1}`, `{"machine":2,"duration":3}` (M50 XML param names), `{"OpenTime":3}`, `{"door_no":1,"open_time":3}`, length-prefixed JSON, raw bytes, all door numbers 0-7, all open_time 1-30 — none accepted. |
| `DELETE_USER` | `{"user_id":"00000030"}` | Tried `{"user_id":"30"}`, `{"user_id":"00000030"}`, `{"UID":30}`, `{"pin":30}` — INVALID_PARAM each time. Empty user record may exist post-wipe. |
| `GET_ENROLL_DATA` | likely `{"user_id":"...","backup_number":N}` (per per-finger enrol shape) | Tried `{"user_id":"00000030"}`, with and without backup_number. INVALID. |
| `GET_USER_PROFILE` | likely `{"user_id":"..."}` | Same body shapes as GET_USER_INFO — INVALID. Possibly different from GET_USER_INFO; speculation: profile = name+privilege only, info = full incl. templates. |
| `SET_ENROLL_DATA` | binary template blob with header | Untested — needs known-good blob. Frappe adapter passes `user_doc.ebkn_enroll_data` raw bytes. |
| `SET_FK_NAME` | likely `{"fk_name":"..."}` | Untested — would set device's display name. |
| `SET_REMOTE_ENROLL` | Likely toggles on-device remote-enrol mode | Tried `{}`, `{"enable":1}` — INVALID. |
| `SET_USER_INFO` | full enroll blob (binary, includes templates) | Frappe adapter sends `cmd_doc.ebkn_enroll_data` (loaded from File). We have the binary blobs in `Archive/usb-extract-2026-04-28/enrolldb-extracted/user_*_*.dat` but no schema for the wrapping JSON header. |
| `SET_USER_NAME` | likely `{"user_id":"...","user_name":"..."}` | Tried — INVALID. May want different name field, or trailing space. |
| `SET_USER_PRIVILEGE` | likely `{"user_id":"...","privilege":N}` (0-3) | Tried — INVALID. |
| `SET_USER_PROFILE` | `{"user_id":uid,"user_name":name,"privilege":0}` (Frappe adapter, exact body) | Tried verbatim — INVALID. Possibly Frappe adapter's body is wrong, or our M61BH wants a different schema (`user_privilege` vs `privilege` for example — note the push events use `user_privilege`). |
| `SET_WEB_SERVER_INFO` | Likely `{"url":"http://..."}` | Untested seriously. Would let us reconfigure the device remotely. |

### Why so many INVALID_PARAM?

Hypotheses ranked by likelihood:

1. **Body framing** — Frappe adapter wraps body as `4-byte LE length prefix + body + \x00 null terminator` (see `format_cmd_body()` in `listener_v4.py`). We send this for non-empty bodies. But empty bodies are sent literally empty (no prefix). The format may differ between command types — some may want unprefixed JSON, some prefixed binary, some need a typed header.
2. **Field naming mismatch** — push events use `user_id` / `user_name` / `user_privilege`, but write commands may want `userid` / `name` / `priv`. Need wire capture against a known-working server.
3. **Firmware variant** — our M61BH may have a subset of M50 commands. The XML door names in M50 SDK (`OpenDoor` PascalCase, `MachineID`, `OpenTime`) all return `NOT_SUPPORTED` (see below) — so the Frappe `OPEN_DOOR` snake_case is the right family but possibly wrong key.
4. **Auth state** — after `CLEAR_ALL_ADMIN`, the device may be in an auth-require state where writes fail until an admin is re-enrolled.

---

## ❌ Not supported on M61BH (`ERROR_NOT_SUPPORTED`)

These cmd_codes are **rejected at the verb level** by the firmware. Either they exist only in the M50 line, in older firmware, or in XML dialect (see Tier 6 of [Capabilities-Matrix.md](Capabilities-Matrix.md)).

| cmd_code | Source / why we tried it | Note |
|----------|--------------------------|------|
| `RESET_FK` | Frappe adapter, "Restart Device" command | Surprising — Frappe documents this for EBKN restart. Not on our firmware. |
| `DOOR_OPEN` | Variant of OPEN_DOOR, alternate verb | NOT_SUPPORTED. |
| `UNLOCK_DOOR` | Generic naming guess | NOT_SUPPORTED. |
| `LOCK_CONTROL` / `LockControl` | M50 SDK XML name (`access_control.py: LockControl`) | NOT_SUPPORTED. M50 has `LockControlMode` enum (ForceOpen=1, ForceClose=2, NormalOpen=3, AutoRecover=4, Restart=5, CancelWarning=6, IllegalOpen=7) — none reach our M61BH via `cmd_code`. |
| `SET_DOOR_STATUS` / `SetDoorStatus` | OCX manual `_SetDoorStatus(machineNum, value)` | NOT_SUPPORTED via FkWeb. (May still work via SBPCCOMM binary path on Windows DLL — untested.) |
| `GET_DOOR_STATUS` / `GetDoorStatus` | OCX manual `_GetDoorStatus` | NOT_SUPPORTED via FkWeb. |
| `SET_DIST_POINT_NAME` | Speculative — naming a distribution point | NOT_SUPPORTED. |

---

## XML door-open body (M50 SDK, sister firmware) — confirmed not portable

The M50 SDK firmware (sister product of M61BH) uses XML over WebSocket via `SBXPCDLL.dll`:

```xml
<REQUEST>OpenDoor</REQUEST>
<MSGTYPE>request</MSGTYPE>
<MachineID>2</MachineID>
<OpenTime>3</OpenTime>
```

Plus `_SetDoorStatus(machineNum, value)` where value 1-7 maps to `LockControlMode` enum.

We attempted **JSON variants of every M50 XML name** through FkWeb on M61BH:
- `cmd_code=OpenDoor` → NOT_SUPPORTED
- `cmd_code=OPEN_DOOR` body `{"MachineID":2,"OpenTime":3}` → INVALID_PARAM
- `cmd_code=OPEN_DOOR` body `{"machine":2,"duration":3}` → INVALID_PARAM
- `cmd_code=SetDoorStatus` body `{"machine":2,"value":1}` → NOT_SUPPORTED

**Conclusion**: the M50 XML dialect does not transit through M61BH's FkWeb mode. The body shape for `OPEN_DOOR` on M61BH is something else — likely revealed by either:
- Wireshark capture of an actual ZKBio CVSecurity / DevManager session against an M61BH device pushing a door-open command, OR
- Ghidra reverse engineering of the on-device handler binary (would need root shell first — see hardware section of `Research-Findings-2026-04-28.md`).

---

## Pattern hypotheses

### 1. Empty-body commands are dangerous

Every cmd_code that accepts an empty body and returns OK falls into one of two camps:

- **Read** (safe): `GET_USER_ID_LIST`, `GET_DEVICE_STATUS`, `GET_LOG_DATA`
- **Destructive write** (dangerous): `CLEAR_ENROLL_DATA`, `CLEAR_LOG_DATA`, `CLEAR_ALL_ADMIN`

There is no `CONFIRM` / `ARE_YOU_SURE` step. Once injected, the device executes immediately and irreversibly. **Bulk-probing cmd_codes with empty body destroyed our 20 users + 9.5 months of attendance.** (Backup recovery: see [Recovery-Plan.md](Recovery-Plan.md).)

### 2. UID is always 8-digit zero-padded string

Per Frappe adapter:
```python
uid = f"{int(user_doc.user_id):0>8}"
```

So UID 30 → `"00000030"`. Confirmed: `GET_USER_INFO` with `"00000030"` worked, with `"30"` returned INVALID_PARAM.

### 3. Frappe adapter is the reference, but not exhaustive

The Frappe `command_processor.py` has only 5 cmd_codes:
- `RESET_FK` (NOT_SUPPORTED on us)
- `OPEN_DOOR` (INVALID_PARAM on us)
- `GET_USER_ID_LIST` (✅ works)
- `DELETE_USER` (INVALID_PARAM)
- `GET_USER_INFO` (✅ works)
- `SET_USER_PROFILE` (INVALID_PARAM)
- `SET_USER_INFO` (untested — needs binary blob)

So Frappe documents 7 — we've now empirically confirmed 4 work on M61BH (`GET_USER_ID_LIST`, `GET_USER_INFO`, `SET_TIME`, `CLEAR_*`) and discovered the rest of the namespace by probing.

### 4. NOT_SUPPORTED vs INVALID_PARAM is informative

`ERROR_NOT_SUPPORTED` = verb missing entirely from this firmware build.
`ERROR_INVALID_PARAM` = verb is registered but body shape is wrong.

This means **all the INVALID_PARAM verbs are reachable** with the right body. Finding `OPEN_DOOR`'s correct body is the highest-value next probe — once we have door control, all the integrations (HRMS auto-unlock, time-window rules, ARES decoy door) become possible.

---

## How to inject commands (operator quick reference)

```bash
# SSH to office-server
ssh office-server

# Queue a SET_TIME command (timezone IST, current local clock)
sudo -u <listener-user> bash -c "echo '{\"cmd_code\":\"SET_TIME\",\"body\":\"{\\\"time\\\":\\\"$(date +%Y%m%d%H%M%S)\\\"}\"}' >> /tmp/secureeye-cmd-queue.jsonl"

# Queue a GET_USER_ID_LIST (read-only, safe)
echo '{"cmd_code":"GET_USER_ID_LIST","body":""}' | sudo -u <listener-user> tee -a /tmp/secureeye-cmd-queue.jsonl

# Watch outcome
sudo tail -f /tmp/secureeye-cmd-results.jsonl
```

Device polls every ~3 seconds, so command will inject on the next `receive_cmd` poll.

**DO NOT queue empty-body commands you don't recognise.** See destructive list above.

---

## Open research questions

1. **What body shape does `OPEN_DOOR` want on M61BH?** Highest-value unanswered question. Likely needs Wireshark capture against ZKBio CVSecurity or a Synacktiv-style firmware mod to log the on-device handler.
2. **Does `SET_USER_INFO` accept the binary blobs from `Archive/usb-extract-2026-04-28/enrolldb-extracted/`?** If yes, we can restore the 20 wiped users via FkWeb instead of USB import.
3. **Are there other cmd_codes we haven't tried?** The Frappe adapter only enumerates 7. The on-device handler likely supports 30+ (matching the 47-method SDK). Worth fuzzing alphabetically against a known-empty backup device.
4. **Do `SET_FK_NAME` / `SET_WEB_SERVER_INFO` allow remote re-config?** If yes, we can reconfigure the device's server URL from a script — useful for fleet ops.
5. **What's the body shape that `cmd_return_code` expects for binary uploads?** `realtime_enroll_data` push uses `4-byte LE len + JSON + binary blobs after`. `SET_USER_INFO` should mirror this — but our framing in `listener_v4.format_cmd_body()` may not match what the device expects on the inbound side.

---

## Cross-references

- [Listener-v4-Reference.md](Listener-v4-Reference.md) — listener architecture + how to inject commands
- [FkWeb-Protocol-2026-04-29.md](FkWeb-Protocol-2026-04-29.md) — wire format for `receive_cmd` / `send_cmd_result`
- [Capabilities-Matrix.md](Capabilities-Matrix.md) — full SDK method list (47 methods) and how they map to FkWeb cmd_codes
- [Recovery-Plan.md](Recovery-Plan.md) — restore the 20 wiped users
- `reference-projects/biometric_integration/biometric_integration/services/command_processor.py` — Frappe ERPNext command builder (the reference)
- `reference-projects/biometric_integration/biometric_integration/adapters/ebkn.py` — Frappe `EBKNAdapter.dispatch()` — request/response handling
