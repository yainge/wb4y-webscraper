from __future__ import annotations

import hashlib
import json
from typing import Any


def sha256_of_string(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def sha256_of_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def content_hash_for_observation(fields: dict[str, Any]) -> str:
    """Compute a deterministic hash of the canonical fields that define a unique price observation."""
    key_fields = [
        "provider_name",
        "contract_name",
        "contract_type",
        "commodity",
        "meter_direction",
        "tou",
        "unit",
        "valid_from",
        "value",
    ]
    parts = [str(fields.get(k, "")) for k in key_fields]
    return sha256_of_string("|".join(parts))


def hash_file(path: str | bytes) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def hash_dict(d: dict[str, Any]) -> str:
    """Hash a dict by serializing to sorted JSON."""
    return sha256_of_string(json.dumps(d, sort_keys=True, default=str, ensure_ascii=False))
