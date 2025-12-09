from .base import Transport

try:
    import bluetooth  # type: ignore
except ImportError:  
    bluetooth = None


class BluetoothTransport(Transport):
    """RFCOMM transport for Linux using pybluez.

    Requires: pybluez and a working Bluetooth adapter. On macOS/Windows this
    will raise a RuntimeError unless pybluez + RFCOMM are available.
    """

    def __init__(self, sock, peer_addr: str | None = None):
        if bluetooth is None:
            raise RuntimeError("pybluez not installed; bluetooth transport unavailable")
        self.sock = sock
        self._peer_addr = peer_addr or "bluetooth-peer"

    @classmethod
    def connect(cls, mac: str, channel: int) -> "BluetoothTransport":
        if bluetooth is None:
            raise RuntimeError("pybluez not installed; bluetooth transport unavailable")
        sock = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
        sock.connect((mac, channel))
        return cls(sock, peer_addr=f"{mac}:{channel}")

    @classmethod
    def listen(cls, channel: int, backlog: int = 1) -> "BluetoothTransport":
        if bluetooth is None:
            raise RuntimeError("pybluez not installed; bluetooth transport unavailable")
        server = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
        server.bind(("", channel))
        server.listen(backlog)
        client, info = server.accept()  # info is (addr, port)
        server.close()
        peer_addr = None
        if isinstance(info, (tuple, list)) and len(info) >= 1:
            peer_addr = f"{info[0]}:{info[1] if len(info) > 1 else channel}"
        return cls(client, peer_addr=peer_addr)

    def send(self, data: bytes) -> None:
        try:
            self.sock.send(data)
        except OSError as e:
            raise ConnectionError(f"bluetooth send failed: {e}") from e

    def recv(self) -> bytes:
        try:
            return self.sock.recv(4096)
        except OSError:
            return b""

    def close(self) -> None:
        try:
            self.sock.close()
        except Exception:
            pass

    def peer_label(self) -> str:
        return self._peer_addr
