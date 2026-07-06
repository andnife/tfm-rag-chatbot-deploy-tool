from fastapi import Response

from tfm_rag.infrastructure.api.auth_cookie import (
    COOKIE_NAME,
    clear_auth_cookie,
    extract_token,
    set_auth_cookie,
)


class _Req:
    def __init__(self, cookies=None, headers=None):
        self.cookies = cookies or {}
        self.headers = headers or {}


def test_set_auth_cookie_sets_httponly_cookie():
    resp = Response()
    set_auth_cookie(resp, "tok123", secure=True, max_age=3600)
    header = resp.headers["set-cookie"]
    assert f"{COOKIE_NAME}=tok123" in header
    assert "HttpOnly" in header
    assert "SameSite=Lax" in header
    assert "Secure" in header


def test_clear_auth_cookie_expires_it():
    resp = Response()
    clear_auth_cookie(resp)
    header = resp.headers["set-cookie"]
    assert f"{COOKIE_NAME}=" in header
    assert "Max-Age=0" in header


def test_extract_token_prefers_cookie_then_header():
    assert extract_token(_Req(cookies={COOKIE_NAME: "ck"})) == "ck"
    assert extract_token(_Req(headers={"authorization": "Bearer hd"})) == "hd"
    assert extract_token(_Req()) is None
    both = _Req(cookies={COOKIE_NAME: "ck"}, headers={"authorization": "Bearer hd"})
    assert extract_token(both) == "ck"


def test_extract_token_blank_bearer_returns_none():
    assert extract_token(_Req(headers={"authorization": "Bearer "})) is None
    assert extract_token(_Req(headers={"authorization": "Bearer    "})) is None
