# ebkn-m61-protocol

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Schema.org](https://img.shields.io/badge/Schema.org-CodeMeta_JSON--LD-orange.svg)](codemeta.json)
[![Citation](https://img.shields.io/badge/Citation-CITATION.cff-green.svg)](CITATION.cff)
[![Author](https://img.shields.io/badge/ORCID-0009--0000--7686--7119-green.svg)](https://orcid.org/0009-0000-7686-7119)
[![Atlas Hub](https://img.shields.io/badge/Ecosystem-Terminal_Firmware_Atlas-blue.svg)](https://github.com/Vibhav-Aggarwal/terminal-firmware-atlas)

Reverse-engineered wire protocol documentation, command catalogs, and a pure-Python reference listener for biometric access control terminals running **EBKN / Realand BioFace M61 firmware** — including **Secureye S-FB3K, S-FB4K, BIOFACE M61BH**, and variants.

This is the only open documentation of these protocols. No vendor SDK, no Windows DLL, and no cloud license required.

---

## 📋 Tested & Supported Devices

| Brand Label | Model Name | Firmware Version | Verified Modes | Door Unlock |
| :--- | :--- | :--- | :--- | :--- |
| **Secureye** | S-FB3K | `M61BH v3.16.1118` | LogClient, FkWeb, WebSocket | ✅ Verified (`LockControl`) |
| **Secureye** | S-FB4K | `M61BH v3.x` | WebSocket, FkWeb | ✅ Compatible |
| **Realand** | BIOFACE M61BH | `M61BH v3.x` | LogClient, WebSocket | ✅ Verified |
| **Realand** | A-C121 | `M61BH` | LogClient, FkWeb | ✅ Compatible |
| **Any OEM** | Firmware: `M61BH` | `TerminalType=F500` | All 3 modes | ✅ Compatible |

> **How to verify your device:** On the terminal, navigate to `Menu → System Info`. Look for firmware string `M61BH` or algorithm `EbknFace V3.0`.

---

## ⚡ The Three Protocols

The EBKN M61 firmware family supports three distinct communication modes in `Menu → Comm → Cloud Server`:

| Mode | Transport / Wire Format | Default Port | Attendance | Door Unlock | Command Injection | Documentation |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **WebSocket** | RFC 6455 + XML (`F500`) | `8089` (or any) | ✅ Push | ✅ **Yes** (`LockControl`) | ✅ Bidirectional | [docs/websocket-f500-protocol.md](docs/websocket-f500-protocol.md) |
| **FkWeb** | HTTP POST JSON (`/ebkn`) | `80` / `8080` | ✅ Push | ❌ No | ✅ Queue response | [docs/fkweb-protocol.md](docs/fkweb-protocol.md) |
| **LogClient** | Raw TCP + XML stream | `5005` | ✅ Push | ❌ No | ❌ No | [docs/bioface-m61-logclient.md](docs/bioface-m61-logclient.md) |

---

## 🚀 Quick Start (Reference Listener)

The reference listener daemon ([`listener/listener.py`](listener/listener.py)) is written in **pure Python 3 with zero external dependencies**. It supports all three protocols simultaneously.

```bash
# 1. Clone repository
git clone https://github.com/Vibhav-Aggarwal/ebkn-m61-protocol.git
cd ebkn-m61-protocol

# 2. Run multi-protocol listener daemon
python3 listener/listener.py --ws-port 8089 --http-port 8080 --logclient-port 5005
```

### Configure Terminal
1. Go to `Menu → Comm → Cloud Server Setting`.
2. Set **Server Mode** to `WebSocket` (recommended for door unlock) or `FkWeb`.
3. Set **Server IP / URL** to `ws://<your-server-ip>:8089` (include the `ws://` prefix).
4. Terminal connects immediately and registers with a Login handshake.

---

## 🚪 Door Unlock via WebSocket

Send a `LockControl` frame over the active WebSocket connection to trigger the door relay:

```bash
# Using example unlock script
./examples/door-unlock.sh --device-sn "90A6DBXXXX" --seconds 5
```

Wire format packet sent to terminal:
```xml
<Request>
  <Cmd>LockControl</Cmd>
  <DeviceSN>90A6DBXXXX</DeviceSN>
  <DoorNum>1</DoorNum>
  <OpenTime>5</OpenTime>
</Request>
```

---

## 📚 Detailed Specifications

- 📄 **[WebSocket F500 Protocol Spec](docs/websocket-f500-protocol.md):** Full framing, handshake, login, keep-alive, and binary dispatch.
- 📄 **[FkWeb Protocol Spec](docs/fkweb-protocol.md):** HTTP endpoint specifications and JSON structure.
- 📄 **[BioFace M61 LogClient Spec](docs/bioface-m61-logclient.md):** TCP port 5005 streaming protocol.
- 📄 **[Complete Command Catalog](docs/cmd-catalog.md):** All known opcodes, queries, user management, and lock control frames.

---

## 🛡️ Security & Responsible Use

Please review [`SECURITY.md`](SECURITY.md) before deploying access control tools. Never test physical actuation without independent manual overrides.

---

## 📄 License & Attribution

- **Code & Specs:** [Apache-2.0 License](LICENSE)
- **Author:** Vibhav Aggarwal ([ORCID: 0009-0000-7686-7119](https://orcid.org/0009-0000-7686-7119))
- **Citation:** See [`CITATION.cff`](CITATION.cff)
