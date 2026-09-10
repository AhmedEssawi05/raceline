"""Symmetric encryption for secrets stored at rest (Strava OAuth tokens).

WHAT: `encrypt`/`decrypt` wrap `cryptography`'s `Fernet` — authenticated
symmetric encryption — keyed by `FERNET_KEY`. `app/models/oauth_token.py`
stores only the ciphertext these produce, never a raw token.

WHY Fernet specifically: it's authenticated (tampering is detected, not
just hidden) and needs no key-management infrastructure beyond "keep one
key safe" — appropriate for a single-key, single-app MVP. This is not
meant to survive key rotation or multi-tenant key separation; if raceline
ever needs those, this is the file to revisit.

WHY validated lazily here (raising on first use) instead of failing at
import: `app/config.py` intentionally leaves `FERNET_KEY` optional so
importing the app doesn't require Strava/session setup just to serve
`/health`. This module is the actual point of use, so it's where the "is
this configured" check belongs.

HOW to generate a key: `python -c "from cryptography.fernet import Fernet;
print(Fernet.generate_key().decode())"` — see .env.example.
"""

from functools import lru_cache

from cryptography.fernet import Fernet

from app.config import get_settings


@lru_cache
def _fernet() -> Fernet:
    key = get_settings().fernet_key
    if not key:
        raise RuntimeError(
            "FERNET_KEY is not set. Generate one with:\n"
            '  python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
        )
    return Fernet(key.encode())


def encrypt(plaintext: str) -> bytes:
    return _fernet().encrypt(plaintext.encode())


def decrypt(ciphertext: bytes) -> str:
    return _fernet().decrypt(ciphertext).decode()
