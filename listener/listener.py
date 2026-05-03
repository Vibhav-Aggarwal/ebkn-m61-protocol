#!/usr/bin/env python3
"""
Realand BioFace M61 multi-protocol listener

Handles all three communication modes the device supports simultaneously:
  - LogClient mode: BioFace M61 raw-TCP XML (port 5005)
  - FkWeb mode:     HTTP POST /ebkn JSON (port 80 or configurable)
  - WebSocket mode: RFC6455 + XML, F500/v2 protocol (any port, e.g. 8089)

Tested on:
  - Secureye S-FB3K  (firmware M61BH v3.16.1118, TerminalType=F500)
  - BIOFACE M61BH (same firmware family)

WebSocket mode is the most capable — it supports door unlock via LockControl.
Set the device's "Web Server URL" to ws://<server-ip>:<port> (must include scheme).
"""
import socket, threading, datetime, re, hashlib, base64, struct, json, os, uuid

PORTS = [5005, 8080, 8081, 8082, 8088, 8089, 8090, 4370, 80]
LOG = "/dev/null"
WS_GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
CMD_QUEUE_FILE = "/tmp/secureeye-cmd-queue.jsonl"
CMD_RESULTS_FILE = "/tmp/secureeye-cmd-results.jsonl"
EVENTS_FILE = "/tmp/secureeye-events.jsonl"
QUEUE_LOCK = threading.Lock()


def log(msg):
    line = f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)


def append_event(d):
    try:
        d["_ts"] = datetime.datetime.now().isoformat()
        with open(EVENTS_FILE, "a") as f:
            f.write(json.dumps(d) + "\n")
    except Exception:
        pass


def append_result(d):
    try:
        d["_ts"] = datetime.datetime.now().isoformat()
        with open(CMD_RESULTS_FILE, "a") as f:
            f.write(json.dumps(d) + "\n")
    except Exception:
        pass


def pop_pending_command():
    with QUEUE_LOCK:
        try:
            if not os.path.exists(CMD_QUEUE_FILE):
                return None
            with open(CMD_QUEUE_FILE, "r") as f:
                lines = f.readlines()
            if not lines:
                return None
            first = lines[0].strip()
            with open(CMD_QUEUE_FILE, "w") as f:
                f.writelines(lines[1:])
            if not first:
                return None
            return json.loads(first)
        except Exception as e:
            log(f"queue err: {e}")
            return None


def format_cmd_body(body):
    if not body:
        body_bytes = b""
    elif isinstance(body, bytes):
        body_bytes = body
    elif isinstance(body, str):
        body_bytes = body.encode("utf-8")
    else:
        body_bytes = json.dumps(body).encode("utf-8")
    return struct.pack("<I", len(body_bytes) + 1) + body_bytes + b"\x00"


TAG_RE = lambda t: re.compile(rb'<' + t.encode() + rb'>([^<]*)</' + t.encode() + rb'>')

def x(data, tag, default=''):
    m = TAG_RE(tag).search(data)
    return m.group(1).decode() if m else default


def parse_http(data):
    try:
        head, _, body = data.partition(b'\r\n\r\n')
        lines = head.split(b'\r\n')
        request_line = lines[0].decode('ascii', errors='replace')
        parts = request_line.split(' ', 2)
        method = parts[0] if len(parts) else ''
        path = parts[1] if len(parts) > 1 else ''
        headers = {}
        for ln in lines[1:]:
            if b':' in ln:
                k, _, v = ln.partition(b':')
                headers[k.decode(errors='replace').strip().lower()] = v.decode(errors='replace').strip()
        return method, path, headers, body, int(headers.get('content-length', 0))
    except Exception:
        return '', '', {}, b'', 0


def read_body(conn, body, content_length):
    while len(body) < content_length:
        try:
            chunk = conn.recv(min(8192, content_length - len(body)))
            if not chunk: break
            body += chunk
        except socket.timeout: break
    return body


# ============ RFC6455 frame I/O ============
def ws_send_frame(conn, payload, opcode=0x1):
    if isinstance(payload, str):
        payload = payload.encode('utf-8')
    head = bytes([0x80 | opcode])
    n = len(payload)
    if n <= 125: head += bytes([n])
    elif n <= 65535: head += bytes([126]) + struct.pack('>H', n)
    else: head += bytes([127]) + struct.pack('>Q', n)
    conn.sendall(head + payload)


def ws_recv_frame(conn):
    try:
        hdr = b''
        while len(hdr) < 2:
            ch = conn.recv(2 - len(hdr))
            if not ch: return None, None
            hdr += ch
        b1, b2 = hdr[0], hdr[1]
        opcode = b1 & 0x0F
        masked = bool(b2 & 0x80)
        plen = b2 & 0x7F
        if plen == 126:
            ext = conn.recv(2); plen = struct.unpack('>H', ext)[0]
        elif plen == 127:
            ext = conn.recv(8); plen = struct.unpack('>Q', ext)[0]
        mask_key = conn.recv(4) if masked else b''
        payload = b''
        while len(payload) < plen:
            ch = conn.recv(min(8192, plen - len(payload)))
            if not ch: return None, None
            payload += ch
        if masked:
            payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
        return opcode, payload
    except Exception:
        return None, None


def ws_handshake(conn, headers):
    key = headers.get('sec-websocket-key', '')
    if not key: return False
    accept = base64.b64encode(hashlib.sha1(key.encode() + WS_GUID).digest()).decode()
    response = (
        f"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
        f"Connection: Upgrade\r\nSec-WebSocket-Accept: {accept}\r\n\r\n"
    )
    conn.sendall(response.encode())
    return True


# ============ F500/v2 EBKN WebSocket session handler ============
def handle_ws_session_v2(conn, addr, port):
    """Device speaks RFC6455 + XML in WebSocket-Client mode.
    Frames are tagged Register / KeepAlive / TimeLog_v2 / AdminLog_v2 etc.
    Server can push commands via response frames (LockControl, SetUserData, etc.).
    """
    while True:
        opcode, payload = ws_recv_frame(conn)
        if opcode is None:
            log(f"  WS-v2 session ended"); return
        if opcode == 0x8:
            log(f"  WS-v2 close frame"); return
        if opcode == 0x9:
            ws_send_frame(conn, payload, opcode=0xA); continue
        if opcode == 0xA:
            continue
        if opcode not in (0x1, 0x2):
            continue

        log(f"  WS-v2 frame ({len(payload)}B): {payload[:300]!r}")

        request = x(payload, 'Request')
        event = x(payload, 'Event')
        sn = x(payload, 'DeviceSerialNo')
        cloud_id = x(payload, 'CloudId')
        product = x(payload, 'ProductName')
        terminal_type = x(payload, 'TerminalType')
        trans_id_v2 = x(payload, 'TransID', '0')

        try:
            append_event({
                '_ws_v2': True, 'request': request, 'event': event,
                'sn': sn, 'cloud_id': cloud_id, 'product': product,
                'terminal_type': terminal_type, 'trans_id': trans_id_v2,
                'payload_prefix': payload[:300].decode('utf-8', 'replace'),
            })
        except Exception:
            pass

        # Login — device's first request, asks server for a session Token
        if request == 'Login':
            token = uuid.uuid4().hex[:16]
            log(f"  V2 LOGIN sn={sn} terminal={terminal_type} product={product} → token={token}")
            reply = (
                '<?xml version="1.0"?>\r\n'
                '<Message>\r\n'
                '<Response>Login</Response>\r\n'
                f'<DeviceSerialNo>{sn}</DeviceSerialNo>\r\n'
                f'<Token>{token}</Token>\r\n'
                '<Result>OK</Result>\r\n'
                '</Message>'
            )
            ws_send_frame(conn, reply)
            log(f"  → V2 Login reply OK token={token}")
            # Inject queued command right after login (good moment — device just opened session)
            cmd = pop_pending_command()
            if cmd:
                cmd_xml = cmd.get('xml')
                if cmd_xml:
                    log(f"  ⬇ V2 INJECT (post-login) cmd={cmd.get('label','?')}: {cmd_xml[:200]}")
                    ws_send_frame(conn, cmd_xml)
            continue

        # Register handshake
        if request == 'Register':
            session = str(uuid.uuid4())
            log(f"  V2 REGISTER sn={sn} terminal={terminal_type} product={product} → session={session}")
            reply = (
                '<?xml version="1.0"?>\r\n'
                '<Message>\r\n'
                '<Response>Register</Response>\r\n'
                f'<DeviceSerialNo>{sn}</DeviceSerialNo>\r\n'
                f'<Session>{session}</Session>\r\n'
                '<Result>OK</Result>\r\n'
                '</Message>'
            )
            ws_send_frame(conn, reply)
            log(f"  → V2 Register reply OK session={session[:8]}...")
            continue

        # KeepAlive
        if event == 'KeepAlive' or request == 'KeepAlive':
            reply = '<?xml version="1.0"?><Message><Response>KeepAlive</Response><Result>OK</Result></Message>'
            ws_send_frame(conn, reply)
            # Inject queued command after KeepAlive ack — KeepAlives are the most frequent trigger
            cmd = pop_pending_command()
            if cmd:
                cmd_xml = cmd.get('xml')
                if cmd_xml:
                    log(f"  ⬇ V2 INJECT (post-keepalive) cmd={cmd.get('label','?')}: {cmd_xml[:200]}")
                    ws_send_frame(conn, cmd_xml)
            continue

        # TimeLog/AdminLog (v1 or v2)
        if event in ('TimeLog_v2', 'AdminLog_v2', 'TimeLog', 'AdminLog'):
            log_id = x(payload, 'LogID')
            uid = x(payload, 'UserID')
            time_v = x(payload, 'Time')
            stat = x(payload, 'AttendStat')
            log(f"  V2 {event} LogID={log_id} Time={time_v} UserID={uid} stat={stat} TransID={trans_id_v2}")
            # Echo all key fields — device may verify TransID + DeviceSerialNo + LogID
            reply = (
                '<?xml version="1.0"?>\r\n<Message>\r\n'
                f'<Response>{event}</Response>\r\n'
                f'<DeviceSerialNo>{sn}</DeviceSerialNo>\r\n'
                f'<TerminalID>2</TerminalID>\r\n'
                f'<TransID>{trans_id_v2}</TransID>\r\n'
                f'<LogID>{log_id}</LogID>\r\n'
                '<Result>OK</Result>\r\n'
                '</Message>'
            )
            ws_send_frame(conn, reply)
            # After acking event, opportunistically push queued command
            cmd = pop_pending_command()
            if cmd:
                cmd_xml = cmd.get('xml')
                if cmd_xml:
                    log(f"  ⬇ V2 INJECT (post-event) cmd={cmd.get('label','?')}: {cmd_xml[:200]}")
                    ws_send_frame(conn, cmd_xml)
            continue

        # Result-only frame from device — it's acking OUR previous reply, don't echo
        result_only = x(payload, 'Result')
        if result_only and not request and not event:
            log(f"  V2 device-ack <Result>{result_only}</Result> — silent")
            # Inject queued command (if any) after device ack — good moment
            cmd = pop_pending_command()
            if cmd:
                cmd_xml = cmd.get('xml')
                if cmd_xml:
                    log(f"  ⬇ V2 INJECT cmd={cmd.get('label','?')}: {cmd_xml[:200]}")
                    ws_send_frame(conn, cmd_xml)
            continue

        # Inject pending command (if any) on this round-trip
        cmd = pop_pending_command()
        if cmd:
            cmd_xml = cmd.get('xml')
            if cmd_xml:
                log(f"  ⬇ V2 INJECT cmd={cmd.get('label','?')}: {cmd_xml[:200]}")
                ws_send_frame(conn, cmd_xml)
                continue

        # Unknown frame type — log but don't reply (avoid feedback loops)
        log(f"  V2 unknown frame type — no reply (Request='{request}' Event='{event}')")


# ============ Main connection handler ============
def handle(conn, addr, port):
    try:
        conn.settimeout(120)
        data = conn.recv(32768)
        log(f"PORT {port} <- {addr[0]}:{addr[1]}  ({len(data)} bytes)")
        if not data: return

        stripped = data.lstrip()

        # Path 1: BioFace M61 raw-TCP XML (LogClient v1)
        if stripped.startswith(b'<?xml') or stripped.startswith(b'<Message'):
            tid = x(data, 'TransID', '0')
            event = x(data, 'Event')
            request_type = {'TimeLog':'UploadedLog','AdminLog':'UploadedLog','Alarm':'UploadedLog','KeepAlive':'KeptAlive'}.get(event, 'UploadedLog')
            reply = (f'<?xml version="1.0"?><Message><Request>{request_type}</Request><TransID>{tid}</TransID></Message>').encode('ascii') + b'\x00'
            conn.sendall(reply)
            log(f"  -> [BioFace-M61-v1] Request={request_type} TransID={tid} Event={event}")
            return

        # Path 2/3/4: HTTP request — could be FkWeb, ADMS, or WebSocket upgrade
        if data.startswith((b'GET ', b'POST ', b'PUT ', b'HEAD ', b'OPTIONS ')):
            method, path, headers, body, content_length = parse_http(data)
            log(f"  HTTP {method} {path}")

            if '://' in path:
                rest = path.split('://', 1)[1]
                slash = rest.find('/')
                path_only = rest[slash:] if slash > 0 else '/'
            else:
                path_only = path

            # WebSocket upgrade → F500/v2 protocol session
            if (headers.get('upgrade', '').lower() == 'websocket'
                    and 'upgrade' in headers.get('connection', '').lower()):
                log(f"  >>> WebSocket upgrade, sec-key={headers.get('sec-websocket-key','')[:20]}...")
                if ws_handshake(conn, headers):
                    log(f"  >>> WS upgraded — F500 v2 protocol session")
                    handle_ws_session_v2(conn, addr, port)
                return

            if content_length and len(body) < content_length:
                body = read_body(conn, body, content_length)

            # FkWeb /ebkn handler
            if path_only.startswith('/ebkn'):
                req_code = headers.get('request_code', 'unknown')
                dev_id = headers.get('dev_id', '?')
                trans_id = headers.get('trans_id', '0')
                blk_no = headers.get('blk_no', None)
                cmd_return_code = headers.get('cmd_return_code', '')

                parsed_json = None
                if body and b'{' in body[:20]:
                    try:
                        json_start = body.find(b'{')
                        json_end = body.rfind(b'}')
                        if json_start >= 0 and json_end > json_start:
                            parsed_json = json.loads(body[json_start:json_end+1])
                    except Exception:
                        pass

                log(f"  EBKN: req_code={req_code} dev_id={dev_id} trans_id={trans_id} blk={blk_no} ret={cmd_return_code}")
                if parsed_json:
                    log(f"  JSON: {json.dumps(parsed_json)[:400]}")

                append_event({
                    'req_code': req_code, 'dev_id': dev_id, 'trans_id': trans_id,
                    'blk_no': blk_no, 'cmd_return_code': cmd_return_code,
                    'json': parsed_json, 'body_len': len(body),
                })

                resp_headers = {
                    'Content-Type': 'application/octet-stream',
                    'response_code': 'OK',
                    'trans_id': trans_id,
                }
                resp_body = b''

                if req_code == 'receive_cmd':
                    cmd = pop_pending_command()
                    if cmd:
                        cmd_trans_id = cmd.get('trans_id') or str(uuid.uuid4())[:8]
                        cmd_code = cmd.get('cmd_code', '')
                        cmd_body = cmd.get('body', '')
                        resp_body = format_cmd_body(cmd_body) if cmd_body or cmd_body == '' else b''
                        if cmd_body in ('', None):
                            resp_body = b''
                        resp_headers['cmd_code'] = cmd_code
                        resp_headers['trans_id'] = cmd_trans_id
                        log(f"  ⬇ INJECT cmd_code={cmd_code} trans_id={cmd_trans_id} body_len={len(resp_body)} body={cmd_body[:80] if isinstance(cmd_body,str) else '(bytes)'}")

                if req_code == 'send_cmd_result':
                    log(f"  ⬆ CMD_RESULT trans_id={trans_id} ret={cmd_return_code} json={parsed_json}")
                    append_result({
                        'trans_id': trans_id, 'cmd_return_code': cmd_return_code,
                        'blk_no': blk_no, 'json': parsed_json, 'body_len': len(body),
                    })

                lines = [b"HTTP/1.1 200 OK"]
                for k, v in resp_headers.items():
                    lines.append(f"{k}: {v}".encode())
                lines.append(f"Content-Length: {len(resp_body)}".encode())
                lines.append(b"Connection: close")
                lines.append(b"")
                lines.append(resp_body)
                resp = b"\r\n".join(lines)
                conn.sendall(resp)
                log(f"  -> [FkWeb/EBKN] response_code=OK trans_id={resp_headers.get('trans_id')} cmd_code={resp_headers.get('cmd_code','')}")
                return

            if path_only.startswith('/iclock'):
                resp_body = b"OK"
                resp = (b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: " + str(len(resp_body)).encode() + b"\r\nConnection: close\r\n\r\n" + resp_body)
                conn.sendall(resp)
                log(f"  -> [ADMS-/iclock] HTTP 200 OK")
                return

            resp_body = b"OK"
            resp = (b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: " + str(len(resp_body)).encode() + b"\r\nConnection: close\r\n\r\n" + resp_body)
            conn.sendall(resp)
            log(f"  -> [HTTP-generic] 200 OK ({path_only})")
            return

        log(f"  UNKNOWN protocol prefix: {data[:32].hex()}  ({data[:60]!r})")
    except Exception as e:
        log(f"  ERR: {e}")
    finally:
        try: conn.close()
        except: pass


def listen(port):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('0.0.0.0', port))
        s.listen(8)
        log(f"+++ listening on port {port}")
        while True:
            conn, addr = s.accept()
            threading.Thread(target=handle, args=(conn, addr, port), daemon=True).start()
    except PermissionError:
        log(f"--- port {port} requires privileges (skipped)")
    except Exception as e:
        log(f"--- port {port} bind failed: {e}")


if __name__ == "__main__":
    log("=== S-FB3K listener v5 (LogClient + FkWeb + WS-v2-F500) starting ===")
    log(f"=== Cmd queue: {CMD_QUEUE_FILE}")
    for p in PORTS:
        threading.Thread(target=listen, args=(p,), daemon=True).start()
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        log("=== stopped ===")
