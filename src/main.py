import argparse
import threading
import sys
from .chat.session import ChatSession
from .transport.tcp_transport import TcpTransport, TcpListener
from .transport.bluetooth_transport import BluetoothTransport

def run_server(port: int, username: str, transport: str, bt_channel: int | None = None):
    sessions: list[ChatSession] = []
    lock = threading.Lock()

    def add_session(sess: ChatSession):
        # enforce unique usernames
        with lock:
            for existing in sessions:
                if existing.peer_label == sess.peer_label:
                    raise ConnectionError(f"username {sess.peer_label} already connected")
        with lock:
            sessions.append(sess)

    def remove_session(sess: ChatSession):
        with lock:
            if sess in sessions:
                sessions.remove(sess)

    def broadcast(msg: str, prefix: str | None = None, exclude: ChatSession | None = None):
        payload = f"{prefix}: {msg}" if prefix else msg
        with lock:
            targets = list(sessions)
        for sess in targets:
            if exclude and sess is exclude:
                continue
            try:
                sess.send_message(payload)
            except Exception:
                remove_session(sess)
                sess.close()

    def handle_client(sess: ChatSession):
        label = sess.peer_label
        try:
            while True:
                msg = sess.recv_message()
                is_private = msg.startswith("[PRIVATE] ")
                clean = msg[len("[PRIVATE] "):] if is_private else msg
                print(f"\n[{label}{' PRIVATE' if is_private else ''}] {clean}")
                if not is_private:
                    broadcast(clean, prefix=label, exclude=sess)
        except Exception as e:
            print(f"\n[{label} disconnected] {e}")
        finally:
            remove_session(sess)
            sess.close()

    if transport == "tcp":
        listener = TcpListener(port)
        def accept_loop():
            while True:
                try:
                    t = listener.accept()
                    sess = ChatSession(t, username=username)
                    sess.handshake()
                    threading.Thread(target=handle_client, args=(sess,), daemon=True).start()
                except Exception as e:
                    print(f"[accept error] {e}", file=sys.stderr)
                    break
        threading.Thread(target=accept_loop, daemon=True).start()
    elif transport == "bt":
        if bt_channel is None:
            raise ValueError("bt transport requires --bt-channel")
        def accept_bt():
            while True:
                try:
                    t = BluetoothTransport.listen(bt_channel)
                    sess = ChatSession(t, username=username)
                    sess.handshake()
                    threading.Thread(target=handle_client, args=(sess,), daemon=True).start()
                except Exception as e:
                    print(f"[accept error] {e}", file=sys.stderr)
                    break
        threading.Thread(target=accept_bt, daemon=True).start()
    else:
        raise ValueError(f"unknown transport {transport}")

    # Host writer broadcasts to all sessions
    try:
        while True:
            line = input("> ")
            broadcast(line, prefix=username)
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        with lock:
            for sess in sessions:
                sess.close()

def run_client(host: str, port: int, username: str, transport: str, bt_channel: int | None = None):
    if transport == "tcp":
        t = TcpTransport.connect(host, port)
    elif transport == "bt":
        if bt_channel is None:
            raise ValueError("bt transport requires --bt-channel")
        t = BluetoothTransport.connect(host, bt_channel)
    else:
        raise ValueError(f"unknown transport {transport}")
    session = ChatSession(t, username=username)
    session.handshake()
    rthread = threading.Thread(target=reader, args=(session,), daemon=False)
    rthread.start()
    try:
        writer(session)
    finally:
        session.close()
        rthread.join(timeout=1)

def reader(session: ChatSession):
    try:
        while True:
            msg = session.recv_message()
            display_label = session.peer_label
            if ": " in msg:
                prefix, rest = msg.split(": ", 1)
                display_label, msg = prefix, rest
            print(f"\n[{display_label}] {msg}")
            print("> ", end="", flush=True)
    except Exception as e:
        # suppress noisy errors if we're already closing
        if not session.closed:
            print(f"\n[{session.peer_label} disconnected] {e}")
        session.close()

def writer(session: ChatSession):
    try:
        while True:
            line = input("> ")
            session.send_message(line)
    except (KeyboardInterrupt, EOFError):
        pass

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--listen", type=int, help="port to listen on")
    g.add_argument("--connect", nargs=2, metavar=("HOST", "PORT"), help="host port to connect")
    ap.add_argument("--name", default="anon", help="your username to send during handshake")
    ap.add_argument("--transport", choices=["tcp", "bt"], default="tcp", help="transport to use")
    ap.add_argument("--bt-channel", type=int, help="Bluetooth RFCOMM channel")
    args = ap.parse_args()

    if args.listen:
        run_server(args.listen, args.name, args.transport, args.bt_channel)
    else:
        host, port = args.connect[0], int(args.connect[1])
        run_client(host, port, args.name, args.transport, args.bt_channel)