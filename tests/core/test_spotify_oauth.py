import base64
import hashlib
from urllib.parse import parse_qs, urlparse

from csvmusic.core.spotify_oauth import create_authorization_url, create_pkce_pair, exchange_authorization_code


class Response:
	status_code = 200

	def json(self):
		return {"access_token": "access", "refresh_token": "refresh", "expires_in": 3600}


class Session:
	def __init__(self):
		self.call = None

	def post(self, url, **kwargs):
		self.call = (url, kwargs)
		return Response()


def test_pkce_pair_matches_s256_challenge():
	verifier, challenge = create_pkce_pair()
	expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
	assert challenge == expected


def test_authorization_url_contains_desktop_pkce_fields():
	url = create_authorization_url("client", "http://127.0.0.1:3000/callback", "challenge", "state")
	params = parse_qs(urlparse(url).query)
	assert params["client_id"] == ["client"]
	assert params["code_challenge_method"] == ["S256"]
	assert params["state"] == ["state"]
	assert "playlist-read-private" in params["scope"][0]


def test_exchange_code_uses_no_client_secret():
	session = Session()
	tokens = exchange_authorization_code("client", "code", "redirect", "verifier", session=session)
	assert tokens["access_token"] == "access"
	assert session.call[1]["data"]["client_id"] == "client"
	assert "client_secret" not in session.call[1]["data"]
