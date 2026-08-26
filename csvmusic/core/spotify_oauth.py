# tabs only
import base64
import hashlib
import secrets
from typing import Any
from urllib.parse import urlencode

import requests

from csvmusic.core.spotify_api import SpotifyAPIError


AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
DEFAULT_SCOPES = ("playlist-read-private", "playlist-read-collaborative")


def create_pkce_pair() -> tuple[str, str]:
	verifier = secrets.token_urlsafe(64)
	digest = hashlib.sha256(verifier.encode("ascii")).digest()
	challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
	return verifier, challenge


def create_authorization_url(client_id: str, redirect_uri: str, challenge: str, state: str) -> str:
	params = {
		"client_id": client_id,
		"response_type": "code",
		"redirect_uri": redirect_uri,
		"code_challenge_method": "S256",
		"code_challenge": challenge,
		"state": state,
		"scope": " ".join(DEFAULT_SCOPES),
		"show_dialog": "true",
	}
	return f"{AUTHORIZE_URL}?{urlencode(params)}"


def exchange_authorization_code(
	client_id: str,
	code: str,
	redirect_uri: str,
	verifier: str,
	*,
	timeout: int = 20,
	session: requests.Session | None = None,
) -> dict[str, Any]:
	client = session or requests.Session()
	try:
		response = client.post(
			TOKEN_URL,
			data={
				"client_id": client_id,
				"grant_type": "authorization_code",
				"code": code,
				"redirect_uri": redirect_uri,
				"code_verifier": verifier,
			},
			headers={"Content-Type": "application/x-www-form-urlencoded"},
			timeout=timeout,
		)
	except requests.RequestException as exc:
		raise SpotifyAPIError(f"Could not exchange Spotify authorization: {exc}") from exc
	try:
		data = response.json()
	except ValueError as exc:
		raise SpotifyAPIError("Spotify returned invalid authorization data.") from exc
	if response.status_code >= 400:
		message = data.get("error_description") if isinstance(data, dict) else None
		raise SpotifyAPIError(message or f"Spotify authorization returned HTTP {response.status_code}.")
	if not isinstance(data, dict) or not data.get("access_token"):
		raise SpotifyAPIError("Spotify did not return an access token.")
	return data
