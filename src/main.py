import argparse
import threading
from .chat.session import ChatSession
from .transport.tcp_transport import TcpTransport
from .transport.bluetooth_transport import BluetoothTransport

def run_server(port: int, username: str, transport: str, bt_channel: int | None = None):
    if transport == "tcp":
        t = TcpTransport.listen(port)
    elif transport == "bt":
        if bt_channel is None:
            raise ValueError("bt transport requires --bt-channel")
        t = BluetoothTransport.listen(bt_channel)
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
            print(f"\n[{session.peer_label}] {msg}")
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