import pytest

from app.services.credential_vault import CredentialVault, CredentialVaultError


MASTER_KEY = "phase-two-test-encryption-key-that-is-long-enough"


def test_credential_vault_round_trip() -> None:
    vault = CredentialVault(MASTER_KEY)
    payload = {
        "access_token": "sensitive-token",
        "refresh_token": "sensitive-refresh-token",
        "account_id": "account-123",
    }

    encrypted, fingerprint = vault.encrypt(payload)

    assert "sensitive-token" not in encrypted
    assert len(fingerprint) == 64
    assert vault.decrypt(encrypted) == payload


def test_credential_fingerprint_is_deterministic() -> None:
    first = {"token": "abc", "account": "123"}
    second = {"account": "123", "token": "abc"}

    assert CredentialVault.fingerprint(first) == CredentialVault.fingerprint(second)


def test_credential_vault_rejects_short_key() -> None:
    with pytest.raises(CredentialVaultError):
        CredentialVault("too-short")


def test_credential_vault_rejects_wrong_key() -> None:
    encrypted, _ = CredentialVault(MASTER_KEY).encrypt({"token": "abc"})

    with pytest.raises(CredentialVaultError):
        CredentialVault("another-test-encryption-key-that-is-long-enough").decrypt(encrypted)
