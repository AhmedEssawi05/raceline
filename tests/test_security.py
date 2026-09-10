"""Tests for app/security.py's token encryption.

WHAT: confirms `encrypt`/`decrypt` round-trip correctly and that ciphertext
never contains the plaintext — the actual property that matters for the
spec's "encrypted at rest, not plaintext in the DB" requirement.
"""

from app.security import decrypt, encrypt


def test_round_trip_recovers_original_plaintext() -> None:
    plaintext = "a-fake-strava-access-token-value"

    ciphertext = encrypt(plaintext)

    assert isinstance(ciphertext, bytes)
    assert plaintext.encode() not in ciphertext
    assert decrypt(ciphertext) == plaintext


def test_encrypting_the_same_plaintext_twice_gives_different_ciphertext() -> None:
    # Fernet includes a random nonce and timestamp in every token, so two
    # encryptions of the same secret must not be byte-identical — otherwise
    # a DB dump could reveal which users share a token value.
    plaintext = "same-value"

    assert encrypt(plaintext) != encrypt(plaintext)
