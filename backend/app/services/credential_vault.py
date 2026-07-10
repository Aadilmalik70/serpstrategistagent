import base64
import hashlib
import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


class CredentialVaultError(ValueError):
    pass


class CredentialVault:
    """Encrypt and decrypt integration payloads with an application master secret."""

    def __init__(self, master_secret: str):
        if len(master_secret) < 32:
            raise CredentialVaultError("Credential encryption key must contain at least 32 characters")

        digest = hashlib.sha256(master_secret.encode("utf-8")).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(digest))

    @staticmethod
    def fingerprint(payload: dict[str, Any]) -> str:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def encrypt(self, payload: dict[str, Any]) -> tuple[str, str]:
        if not payload:
            raise CredentialVaultError("Credential payload cannot be empty")

        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        token = self._fernet.encrypt(canonical.encode("utf-8")).decode("utf-8")
        return token, self.fingerprint(payload)

    def decrypt(self, encrypted_payload: str) -> dict[str, Any]:
        try:
            decoded = self._fernet.decrypt(encrypted_payload.encode("utf-8"))
            payload = json.loads(decoded.decode("utf-8"))
        except (InvalidToken, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CredentialVaultError("Credential payload could not be decrypted") from exc

        if not isinstance(payload, dict):
            raise CredentialVaultError("Credential payload must decode to an object")
        return payload


def get_credential_vault() -> CredentialVault:
    settings = get_settings()
    if not settings.credential_encryption_key:
        raise CredentialVaultError("CREDENTIAL_ENCRYPTION_KEY is not configured")
    return CredentialVault(settings.credential_encryption_key)
