"""Canonical JSON, Ed25519 signing and mandate hashing (design.md section 2).

Canonicalization is a simplified form of RFC 8785: sorted keys, compact separators, UTF-8.
"""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from pydantic import BaseModel


def canonical(obj: Any) -> bytes:
    """Deterministic JSON encoding of obj."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def body_for_signing(model: BaseModel) -> dict[str, Any]:
    """The model's fields without the signature."""
    return model.model_dump(exclude={"signature"})


def sign(model: BaseModel, private_key: Ed25519PrivateKey) -> str:
    """Base64 Ed25519 signature over canonical(body_for_signing(model))."""
    return base64.b64encode(private_key.sign(canonical(body_for_signing(model)))).decode("ascii")


def verify(model: BaseModel, public_key_b64: str) -> bool:
    """True only if model.signature is valid for the model body. Never raises."""
    try:
        public_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64, validate=True))
        signature = base64.b64decode(model.signature, validate=True)  # type: ignore[attr-defined]
        public_key.verify(signature, canonical(body_for_signing(model)))
        return True
    except Exception:
        return False


def mandate_hash(model: BaseModel) -> str:
    """sha256 hex of canonical(model.model_dump()), signature included."""
    return hashlib.sha256(canonical(model.model_dump())).hexdigest()


def generate_keypair() -> tuple[Ed25519PrivateKey, str]:
    """New Ed25519 key pair: (private key, base64 raw public key)."""
    private_key = Ed25519PrivateKey.generate()
    raw = private_key.public_key().public_bytes_raw()
    return private_key, base64.b64encode(raw).decode("ascii")


def keypair_from_seed(seed_material: bytes) -> tuple[Ed25519PrivateKey, str]:
    """Deterministic Ed25519 key pair derived from ``seed_material`` (for reproducible simulations only)."""
    private_key = Ed25519PrivateKey.from_private_bytes(hashlib.sha256(seed_material).digest())
    raw = private_key.public_key().public_bytes_raw()
    return private_key, base64.b64encode(raw).decode("ascii")
