from __future__ import annotations

from importlib.metadata import version as distribution_version

from fastapi.testclient import TestClient

from forex_trader import __version__
from forex_trader.api.app import create_app
from forex_trader.application.campaign_policy import (
    campaign_policy_context,
    campaign_policy_fingerprint,
)


def test_runtime_and_installed_distribution_versions_match() -> None:
    assert __version__ == "0.7.26"
    assert distribution_version("forex-trader") == __version__


def test_openapi_exposes_authoritative_runtime_version(engine) -> None:  # type: ignore[no-untyped-def]
    client = TestClient(create_app(engine, allow_unsafe_local_mutations=True))
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/openapi.json").json()["info"]["version"] == __version__


def test_campaign_policy_identity_contains_implementation_version(engine, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("FOREX_BUILD_REVISION", raising=False)
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    context = campaign_policy_context(engine)
    assert context["implementation"] == {"version": __version__, "build_revision": None}


def test_build_revision_changes_campaign_fingerprint(engine, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("GITHUB_SHA", "github-sha")
    monkeypatch.setenv("FOREX_BUILD_REVISION", "abc123")
    first = campaign_policy_context(engine)
    monkeypatch.setenv("FOREX_BUILD_REVISION", "def456")
    second = campaign_policy_context(engine)
    assert first["implementation"]["build_revision"] == "abc123"  # type: ignore[index]
    assert second["implementation"]["build_revision"] == "def456"  # type: ignore[index]
    assert campaign_policy_fingerprint(first) != campaign_policy_fingerprint(second)


def test_explicit_build_revision_precedes_github_sha(engine, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("GITHUB_SHA", "github-sha")
    monkeypatch.setenv("FOREX_BUILD_REVISION", "explicit-sha")
    context = campaign_policy_context(engine)
    assert context["implementation"]["build_revision"] == "explicit-sha"  # type: ignore[index]
