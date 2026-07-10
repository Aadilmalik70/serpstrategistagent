import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import dns.asyncresolver
import dns.exception
import dns.resolver
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.site import Site

CLAIM_TTL = timedelta(minutes=30)
VERIFICATION_PREFIX = "serp-strategists-verification="


class SiteClaimError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def verification_record_name(domain: str) -> str:
    return f"_serp-strategists.{domain.rstrip('.')}"


def make_verification_value() -> str:
    return f"{VERIFICATION_PREFIX}{secrets.token_urlsafe(24)}"


def hash_claim_token(workspace_id: uuid.UUID, token: str) -> str:
    payload = f"{workspace_id}:{token}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def token_matches(expected_hash: str | None, workspace_id: uuid.UUID, token: str) -> bool:
    if not expected_hash:
        return False
    return hmac.compare_digest(expected_hash, hash_claim_token(workspace_id, token))


def _txt_value(record: object) -> str:
    chunks = getattr(record, "strings", None)
    if chunks:
        return "".join(chunk.decode("utf-8") for chunk in chunks)
    return str(record.to_text()).replace('" "', "").strip('"')


async def dns_txt_contains(record_name: str, expected_value: str) -> bool:
    try:
        answer = await dns.asyncresolver.resolve(record_name, "TXT", lifetime=8.0)
    except (
        dns.resolver.NXDOMAIN,
        dns.resolver.NoAnswer,
        dns.resolver.NoNameservers,
        dns.exception.Timeout,
    ):
        return False

    return any(hmac.compare_digest(_txt_value(record), expected_value) for record in answer)


async def start_site_claim(
    db: AsyncSession,
    *,
    domain: str,
    workspace_id: uuid.UUID,
) -> tuple[Site, str, datetime]:
    site = await db.scalar(select(Site).where(Site.domain == domain).with_for_update())
    if not site:
        raise SiteClaimError("site_not_found", "No existing site is available to claim")

    if site.workspace_id == workspace_id:
        raise SiteClaimError("already_owned", "This site already belongs to your workspace")
    if site.workspace_id is not None:
        raise SiteClaimError("domain_unavailable", "This domain is already managed by another workspace")

    now = datetime.now(timezone.utc)
    if (
        site.pending_claim_workspace_id
        and site.pending_claim_workspace_id != workspace_id
        and site.verification_expires_at
        and site.verification_expires_at > now
    ):
        raise SiteClaimError(
            "claim_in_progress",
            "An ownership verification is already in progress for this domain. Try again later.",
        )

    token = make_verification_value()
    expires_at = now + CLAIM_TTL
    site.pending_claim_workspace_id = workspace_id
    site.verification_token_hash = hash_claim_token(workspace_id, token)
    site.verification_status = "pending"
    site.verification_method = "dns_txt"
    site.verification_expires_at = expires_at
    await db.commit()
    await db.refresh(site)
    return site, token, expires_at


async def verify_and_complete_site_claim(
    db: AsyncSession,
    *,
    domain: str,
    workspace_id: uuid.UUID,
    token: str,
) -> Site:
    site = await db.scalar(select(Site).where(Site.domain == domain))
    if not site or site.workspace_id is not None:
        raise SiteClaimError("claim_unavailable", "This site is not available to claim")

    now = datetime.now(timezone.utc)
    if site.pending_claim_workspace_id != workspace_id:
        raise SiteClaimError("claim_mismatch", "Start a new ownership verification for this workspace")
    if not site.verification_expires_at or site.verification_expires_at <= now:
        raise SiteClaimError("claim_expired", "Ownership verification expired. Start a new claim")
    if not token_matches(site.verification_token_hash, workspace_id, token):
        raise SiteClaimError("invalid_token", "The ownership verification token is invalid")

    record_name = verification_record_name(domain)
    if not await dns_txt_contains(record_name, token):
        raise SiteClaimError(
            "dns_not_verified",
            f"TXT record was not found at {record_name}. DNS changes may take time to propagate.",
        )

    site = await db.scalar(select(Site).where(Site.id == site.id).with_for_update())
    if not site or site.workspace_id is not None:
        raise SiteClaimError("claim_unavailable", "This site is no longer available to claim")
    if site.pending_claim_workspace_id != workspace_id:
        raise SiteClaimError("claim_mismatch", "The ownership claim changed. Start again")
    if not site.verification_expires_at or site.verification_expires_at <= datetime.now(timezone.utc):
        raise SiteClaimError("claim_expired", "Ownership verification expired. Start a new claim")
    if not token_matches(site.verification_token_hash, workspace_id, token):
        raise SiteClaimError("invalid_token", "The ownership verification token is invalid")

    site.workspace_id = workspace_id
    site.pending_claim_workspace_id = None
    site.verification_status = "verified"
    site.verification_method = "dns_txt"
    site.verification_token_hash = None
    site.verification_expires_at = None
    site.verified_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(site)
    return site
