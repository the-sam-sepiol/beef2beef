import struct
import hmac
import hashlib
from cryptography.hazmat.primitives import serialization
from ..crypto import generate_keypair, derive_shared_key, encrypt, decrypt, NONCE_SIZE
from ..transport.base import Transport

LEN_FMT = "!I"

class ChatSession:
    def __init__(self, transport: Transport, username: str = "anon"):
        self.transport = transport
        self.username = username
        self.peer_username: str | None = None
        self.priv, self.pub = generate_keypair()
        self.aes_key = None
        self._buf = bytearray()
        self._aad: bytes | None = None
        self.closed = False
        try:
            self.peer_label = self.transport.peer_label()
        except Exception:
            self.peer_label = "peer"

    def handshake(self):
        # send my username (1-byte len) + pubkey bytes
        username_bytes = self.username.encode("utf-8")
        if len(username_bytes) > 255:
            raise ValueError("username too long (max 255 bytes)")
        pub_bytes = self.pub.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        payload = bytes([len(username_bytes)]) + username_bytes + pub_bytes
        self._send_frame(payload)

        # receive peer username + pubkey
        peer_payload = self._recv_frame()
        if not peer_payload:
            raise ConnectionError("empty handshake payload")
        name_len = peer_payload[0]
        if len(peer_payload) < 1 + name_len:
            raise ConnectionError("truncated handshake payload")
        self.peer_username = peer_payload[1 : 1 + name_len].decode("utf-8", errors="replace")
        peer_pub = peer_payload[1 + name_len :]
        self.aes_key = derive_shared_key(self.priv, peer_pub)

        # derive transcript for AAD / key confirmation (order-independent)
        transcript = self._make_transcript(username_bytes, self.peer_username.encode("utf-8"), pub_bytes, peer_pub)
        self._aad = hashlib.sha256(transcript).digest()

        # exchange confirmation tags to prove possession of shared key
        my_confirm = hmac.new(self.aes_key, transcript, hashlib.sha256).digest()
        self._send_frame(my_confirm)
        peer_confirm = self._recv_frame()
        if peer_confirm != my_confirm:
            raise ConnectionError("handshake confirmation failed")

        # update peer label to include username if available
        if self.peer_username:
            self.peer_label = f"{self.peer_username}@{self.peer_label}"

    def send_message(self, plaintext: str):
        if self.closed:
            raise ConnectionError("session closed")
        nonce, ct = encrypt(self.aes_key, plaintext.encode(), aad=self._aad)
        payload = nonce + ct
        self._send_frame(payload)

    def recv_message(self) -> str:
        if self.closed:
            raise ConnectionError("session closed")
        payload = self._recv_frame()
        nonce, ct = payload[:NONCE_SIZE], payload[NONCE_SIZE:]
        pt = decrypt(self.aes_key, nonce, ct, aad=self._aad)
        return pt.decode()

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            self.transport.close()
        except Exception:
            pass

    def _send_frame(self, payload: bytes):
        header = struct.pack(LEN_FMT, len(payload))
        self.transport.send(header + payload)

    def _recv_frame(self) -> bytes:
        header = self._recv_exact(struct.calcsize(LEN_FMT))
        (length,) = struct.unpack(LEN_FMT, header)
        return self._recv_exact(length)

    def _recv_exact(self, n: int) -> bytes:
        if self.closed:
            raise ConnectionError("session closed")
        while len(self._buf) < n:
            chunk = self.transport.recv()
            if not chunk:
                raise ConnectionError("connection closed")
            self._buf.extend(chunk)
        result = bytes(self._buf[:n])
        del self._buf[:n]
        return result

    @staticmethod
    def _make_transcript(my_name: bytes, peer_name: bytes, my_pub: bytes, peer_pub: bytes) -> bytes:
        name_a, name_b = sorted([my_name, peer_name])
        pub_a, pub_b = sorted([my_pub, peer_pub])
        return b"CHATv1|" + name_a + b"|" + name_b + b"|" + pub_a + b"|" + pub_b