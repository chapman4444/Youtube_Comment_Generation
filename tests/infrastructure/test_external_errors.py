from __future__ import annotations

from llm_youtube_comment_generation.infrastructure.external_errors import (
    sanitize_external_error,
    sanitize_external_text,
)


def test_proxy_credentials_are_removed_from_external_failures():
    proxy = (
        "http://" + "proxy-user:proxy-password@" + "proxy.example:8080"
    )
    failure = RuntimeError(
        f"could not connect to {proxy}; "
        "proxy-user proxy-password"
    )

    detail = sanitize_external_error(failure, proxy)

    assert "RuntimeError" in detail
    assert "proxy.example:8080" in detail
    assert "proxy-user" not in detail
    assert "proxy-password" not in detail


def test_percent_encoded_proxy_credentials_are_removed():
    proxy = (
        "http://"
        + "proxy%2Duser:proxy%2Fpassword@"
        + "proxy.example:8080"
    )
    text = (
        f"{proxy} proxy%2Duser proxy%2Fpassword "
        "proxy-user proxy/password"
    )

    detail = sanitize_external_text(text, proxy)

    for secret in (
        "proxy%2Duser",
        "proxy%2Fpassword",
        "proxy-user",
        "proxy/password",
    ):
        assert secret.lower() not in detail.lower()
    assert "proxy.example:8080" in detail
