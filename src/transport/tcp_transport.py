import socket
from .base import Transport


class TcpTransport(Transport):
    def __init__(self, sock: socket.socket):
        self.sock = sock

    @classmethod
    def connect(cls, host: str, port: int) -> "TcpTransport":
        s = socket.create_connection((host, port))
        return cls(s)

    @classmethod
    def listen(cls, port: int) -> "TcpTransport":
        listener = TcpListener(port)
        return listener.accept()

    def send(self, data: bytes) -> None:
        self.sock.sendall(data)

    def recv(self) -> bytes:
        try:
            return self.sock.recv(4096)
        except OSError:
            return b""

    def close(self) -> None:
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()

    def peer_label(self) -> str:
        return "peer"


class TcpListener:
    """Reusable TCP listener that can accept multiple clients."""

    def __init__(self, port: int, backlog: int = 5):
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("", port))
        self.sock.listen(backlog)

    def accept(self) -> TcpTransport:
        conn, _ = self.sock.accept()
        return TcpTransport(conn)

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass