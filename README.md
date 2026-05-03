# realand-bioface-m61-protocol

Reverse-engineered protocol documentation and reference listener for biometric terminals running **Realand / EBKN BioFace M61 firmware** — including Secureye S-FB3K, BIOFACE M61BH, and variants.

This is the only public documentation of these protocols. No vendor SDK, no Windows DLL, no ZKBio license required.

## Supported devices

| Brand | Model | Firmware | Confirmed |
|-------|-------|----------|-----------|
| Secureye | S-FB3K | M61BH v3.16.1118 | ✅ primary test device |
| Realand | BIOFACE M61BH | M61BH v3.x | same firmware |
| Any OEM | "M61BH" firmware string | TerminalType=F500 | likely works |

> How to identify: in the device menu → System Info → look for firmware string `M61BH`, product name `S-FB3K`, or in WebSocket Login frame `TerminalType=F500`.

---

## Three protocols — one device

The same device supports three modes, selectable in `Menu → Comm → Cloud Server`:

| Mode | Wire format | Port | Door unlock | Command injection |
|------|-------------|------|-------------|-------------------|
| **LogClient** | XML over raw TCP, null-terminated | 5005 | ❌ | ❌ |
| **FkWeb** | HTTP POST JSON to `/ebkn` | 80 | 🟡 INVALID_PARAM | ✅ via `receive_cmd` |
| **WebSocket** | RFC6455 + XML (F500 protocol) | any | ✅ **LockControl confirmed** | ✅ injected into ack frames |

**WebSocket mode is the most capable.** Use it if you need door control.

### Critical URL gotcha for WebSocket mode

```
ws://10.0.0.1:8089   ← CORRECT — device acts as RFC6455 WebSocket CLIENT
10.0.0.1             ← WRONG   — device falls back to WebSocket-SERVER (proprietary SBPCCOMM binary)
```

The `ws://` scheme prefix is required. Without it the device silently switches to a different (vendor-only) protocol.

---

## Door unlock (WebSocket F500)

Confirmed working — 7× OK across all 3 modes:

```bash
# Mode 3 = NormalOpen (momentary relay pulse, typical door buzz)
./examples/door-unlock.sh 3

# Mode 1 = ForceOpen (permanent unlock until Mode 2)
./examples/door-unlock.sh 1

# Mode 2 = ForceClose
./examples/door-unlock.sh 2
```

Device replies with `<Response>LockControl</Response><Result>OK</Result>`.

---

## Quick start

```bash
# Requires Python 3.8+, no third-party packages
python3 listener/listener.py
```

The listener binds all three protocol ports simultaneously. Point the device at it using any mode.

To unlock the door (WebSocket mode):
```bash
echo '{"label":"unlock","xml":"<?xml version=\"1.0\"?><Message><Request>LockControl</Request><Mode>3</Mode></Message>"}' \
  >> /tmp/secureeye-cmd-queue.jsonl
```

Commands drain within **60 seconds** in any device state — the KeepAlive frame (sent every ~60s even when idle) triggers a queue drain.

---

## Repository layout

```
listener/
  listener.py                  ← multi-protocol server (~340 lines, no deps)
  bioface-m61-listener.service ← systemd unit

docs/
  bioface-m61-logclient.md     ← LogClient XML/TCP protocol spec
  fkweb-protocol.md            ← FkWeb HTTP JSON protocol spec
  websocket-f500-protocol.md   ← WebSocket F500 protocol spec + door unlock
  cmd-catalog.md               ← Empirical FkWeb cmd_code catalog (30+ entries)

examples/
  door-unlock.sh               ← LockControl injection (WebSocket mode)
  inject-fkweb-command.sh      ← FkWeb cmd_code injection
```

---

## FkWeb command catalog highlights

30+ cmd_codes enumerated empirically. Selected entries:

| cmd_code | Status | Notes |
|----------|--------|-------|
| `GET_USER_ID_LIST` | ✅ OK | Returns list of enrolled user IDs |
| `GET_USER_INFO` | ✅ OK | Full user record (name, privilege, biometric counts) |
| `GET_DEVICE_STATUS` | ✅ OK | Firmware version, capacity, storage used |
| `GET_LOG_DATA` | ✅ OK | Pull historical attendance records |
| `SET_TIME` | ✅ OK | Sync device clock |
| `OPEN_DOOR` | 🟡 INVALID_PARAM | 40+ body variants tried — use WebSocket LockControl instead |
| `CLEAR_ENROLL_DATA` | 💀 **DESTRUCTIVE** | Wipes all enrolled users — use with extreme caution |
| `RESET_FK` | ❌ NOT_SUPPORTED | Factory reset not available via FkWeb |

Full catalog: [`docs/cmd-catalog.md`](docs/cmd-catalog.md)

---

## Device case study

Full reverse-engineering session notes, USB data extraction, recovery plan, and the original Secureye S-FB3K context:
→ [secureye-s-fb3k-research](https://github.com/Vibhav-Aggarwal/secureye-s-fb3k-research)

## Related

- [`adms-push-server`](https://github.com/Vibhav-Aggarwal/adms-push-server) — for ZKTeco/eSSL devices using ADMS HTTP push (different protocol family)
- [`biometric-oemware-guide`](https://github.com/Vibhav-Aggarwal/biometric-oemware-guide) — identify your device's firmware family

## License

MIT
