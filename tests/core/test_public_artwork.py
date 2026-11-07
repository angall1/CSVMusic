# tabs only
from unittest.mock import Mock

import pytest

from csvmusic.core import public_artwork as artwork


def dns(address):
	return [(2, 1, 6, "", (address, 443))]


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "192.168.1.1", "172.16.0.1", "169.254.169.254", "0.0.0.0", "::1", "fe80::1", "fc00::1", "::ffff:127.0.0.1", "100.64.0.1"])
def test_private_destinations_never_open_connection(monkeypatch, address):
	monkeypatch.setattr(artwork.socket, "getaddrinfo", lambda *a, **k: dns(address))
	connect = Mock()
	monkeypatch.setattr(artwork.urllib3, "HTTPSConnectionPool", connect)
	assert artwork.public_artwork_bytes("https://art.example/cover") is None
	connect.assert_not_called()


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com/x", "https://user:password@example.com/x", "http://example.com:8080/x", "https://example.com:8443/x"])
def test_invalid_urls_rejected_before_dns(monkeypatch, url):
	lookup = Mock()
	monkeypatch.setattr(artwork.socket, "getaddrinfo", lookup)
	assert artwork.public_artwork_bytes(url) is None
	lookup.assert_not_called()


def test_tls_uses_validated_address_and_original_hostname(monkeypatch):
	lookup = Mock(return_value=dns("8.8.8.8"))
	monkeypatch.setattr(artwork.socket, "getaddrinfo", lookup)
	response = Mock(status=200, headers={"Content-Type": "image/png"})
	response.read.return_value = b"image"
	pool = Mock()
	pool.request.return_value = response
	connect = Mock(return_value=pool)
	monkeypatch.setattr(artwork.urllib3, "HTTPSConnectionPool", connect)
	assert artwork.public_artwork_bytes("https://art.example/cover?size=1") == b"image"
	assert connect.call_args.args[0] == "8.8.8.8"
	assert connect.call_args.kwargs["server_hostname"] == "art.example"
	assert connect.call_args.kwargs["assert_hostname"] == "art.example"
	assert connect.call_args.kwargs["cert_reqs"] == "CERT_REQUIRED"
	assert pool.request.call_args.kwargs["redirect"] is False
	assert pool.request.call_args.kwargs["retries"] is False
	assert lookup.call_count == 1
	response.close.assert_called_once()
	pool.close.assert_called_once()


def test_redirect_to_private_address_is_blocked(monkeypatch):
	monkeypatch.setattr(artwork.socket, "getaddrinfo", Mock(side_effect=[dns("8.8.8.8"), dns("127.0.0.1")]))
	pool = Mock()
	pool.request.return_value = Mock(status=302, headers={"Location": "http://localhost/secret"})
	connect = Mock(return_value=pool)
	monkeypatch.setattr(artwork.urllib3, "HTTPSConnectionPool", connect)
	private_connect = Mock()
	monkeypatch.setattr(artwork.urllib3, "HTTPConnectionPool", private_connect)
	assert artwork.public_artwork_bytes("https://art.example/cover") is None
	assert connect.call_count == 1
	private_connect.assert_not_called()


def test_mixed_public_private_dns_is_rejected(monkeypatch):
	monkeypatch.setattr(artwork.socket, "getaddrinfo", lambda *a, **k: dns("8.8.8.8") + dns("10.0.0.1"))
	assert artwork.public_artwork_bytes("https://art.example/cover") is None


@pytest.mark.parametrize("status,headers,body", [(200, {"Content-Type": "text/plain"}, b"secret"), (200, {"Content-Type": "image/png", "Content-Length": str(artwork.MAX_ARTWORK_BYTES + 1)}, b""), (200, {"Content-Type": "image/png"}, b"x" * (artwork.MAX_ARTWORK_BYTES + 1))], ids=["not-image", "declared-oversize", "actual-oversize"])
def test_bad_or_oversized_responses_rejected(monkeypatch, status, headers, body):
	monkeypatch.setattr(artwork.socket, "getaddrinfo", lambda *a, **k: dns("8.8.8.8"))
	response = Mock(status=status, headers=headers)
	response.read.return_value = body
	pool = Mock()
	pool.request.return_value = response
	monkeypatch.setattr(artwork.urllib3, "HTTPSConnectionPool", lambda *a, **k: pool)
	assert artwork.public_artwork_bytes("https://art.example/cover") is None
	response.close.assert_called_once()
