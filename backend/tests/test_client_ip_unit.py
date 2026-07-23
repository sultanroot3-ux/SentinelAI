"""CRITICAL-2: X-Forwarded-For must not be trusted from untrusted peers."""
from types import SimpleNamespace

from app.core import net
from app.core.config import settings


def _req(peer, xff=None):
    headers = {}
    if xff is not None:
        headers["x-forwarded-for"] = xff
    return SimpleNamespace(client=SimpleNamespace(host=peer), headers=headers)


def test_xff_ignored_by_default(monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_PROXY_IPS", [])
    # attacker spoofs XFF on a direct connection — must be ignored
    assert net.client_ip(_req("203.0.113.9", xff="1.1.1.1")) == "203.0.113.9"


def test_no_client_returns_unknown(monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_PROXY_IPS", [])
    req = SimpleNamespace(client=None, headers={})
    assert net.client_ip(req) == "unknown"


def test_trusted_proxy_uses_last_xff_entry(monkeypatch):
    # peer is the trusted proxy; nginx appended the real client as the LAST entry
    monkeypatch.setattr(settings, "TRUSTED_PROXY_IPS", ["172.16.0.0/12"])
    req = _req("172.18.0.5", xff="9.9.9.9, 203.0.113.7")
    assert net.client_ip(req) == "203.0.113.7"


def test_untrusted_peer_ignores_xff_even_if_present(monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_PROXY_IPS", ["172.16.0.0/12"])
    # peer is NOT in the trusted range → XFF ignored, real peer used
    assert net.client_ip(_req("203.0.113.9", xff="1.1.1.1, 2.2.2.2")) == "203.0.113.9"


def test_single_trusted_ip(monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_PROXY_IPS", ["10.0.0.1"])
    assert net.client_ip(_req("10.0.0.1", xff="8.8.8.8")) == "8.8.8.8"
    assert net.client_ip(_req("10.0.0.2", xff="8.8.8.8")) == "10.0.0.2"


def test_invalid_peer_not_trusted(monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_PROXY_IPS", ["10.0.0.0/8"])
    assert net.client_ip(_req("testclient", xff="8.8.8.8")) == "testclient"
