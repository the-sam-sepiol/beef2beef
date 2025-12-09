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
        ls = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        ls.bind(("", port))
        ls.listen(1)
        conn, _ = ls.accept()
        ls.close()
        return cls(conn)

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
        try:
            host, port = self.sock.getpeername()[:2]
            return f"{host}:{port}"
        except OSError:
            return "peer"