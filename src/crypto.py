from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import serialization
import os

NONCE_SIZE = 12
KEY_SIZE = 32

def generate_keypair():
    priv = X25519PrivateKey.generate()
    return priv, priv.public_key()

def derive_shared_key(private_key: X25519PrivateKey, peer_public_bytes: bytes) -> bytes:
    peer_pub = X25519PublicKey.from_public_bytes(peer_public_bytes)
    shared = private_key.exchange(peer_pub)
    return HKDF(
        algorithm=hashes.SHA256(), length=KEY_SIZE, salt=None, info=b"secure-chat"
    ).derive(shared)

def encrypt(aes_key: bytes, plaintext: bytes, aad: bytes | None = None) -> tuple[bytes, bytes]:
    nonce = os.urandom(NONCE_SIZE)
    ct = AESGCM(aes_key).encrypt(nonce, plaintext, aad)
    return nonce, ct

def decrypt(aes_key: bytes, nonce: bytes, ciphertext: bytes, aad: bytes | None = None) -> bytes:
    return AESGCM(aes_key).decrypt(nonce, ciphertext, aad)