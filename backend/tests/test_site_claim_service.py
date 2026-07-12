import uuid

import pytest

from app.services import site_claim_service


class FakeTxtRecord:
    def __init__(self, value: str):
        self.strings = [value.encode("utf-8")]


def test_claim_token_is_bound_to_workspace() -> None:
    first_workspace = uuid.uuid4()
    second_workspace = uuid.uuid4()
    token = "serp-strategists-verification=test-token"
    token_hash = site_claim_service.hash_claim_token(first_workspace, token)

    assert site_claim_service.token_matches(token_hash, first_workspace, token)
    assert not site_claim_service.token_matches(token_hash, second_workspace, token)
    assert not site_claim_service.token_matches(token_hash, first_workspace, f"{token}-changed")


def test_verification_record_name() -> None:
    assert (
        site_claim_service.verification_record_name("serpstrategists.com")
        == "_serp-strategists.serpstrategists.com"
    )


@pytest.mark.asyncio
async def test_dns_txt_verification(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = "serp-strategists-verification=test-token"

    async def fake_resolve(*_args, **_kwargs):
        return [FakeTxtRecord("unrelated"), FakeTxtRecord(expected)]

    monkeypatch.setattr(site_claim_service.dns.asyncresolver, "resolve", fake_resolve)

    assert await site_claim_service.dns_txt_contains(
        "_serp-strategists.serpstrategists.com",
        expected,
    )
    assert not await site_claim_service.dns_txt_contains(
        "_serp-strategists.serpstrategists.com",
        "serp-strategists-verification=wrong",
    )
