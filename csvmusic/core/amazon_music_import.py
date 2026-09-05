# tabs only
import html
import json
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import requests

from csvmusic.core.import_warnings import incomplete_import_warning


class AmazonMusicImportError(Exception):
	pass


@dataclass
class AmazonMusicSource:
	id: str
	name: str
	tracks: list[dict]
	total_count: int | None = None
	source_type: str = "playlist"
	warning: str | None = None


def fetch_amazon_music_source(value: str, *, timeout: int = 20, session: requests.Session | None = None) -> AmazonMusicSource:
	url, source_type, source_id = parse_amazon_music_source(value)
	client = session or requests.Session()
	user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
	try:
		response = client.get(url, headers={"User-Agent": user_agent, "Accept-Language": "en-US,en;q=0.9"}, timeout=timeout)
	except requests.RequestException as exc:
		raise AmazonMusicImportError("Could not reach Amazon Music. Check your connection and try again.") from exc
	if response.status_code in (401, 403, 404):
		raise AmazonMusicImportError("Could not find Amazon Music playlist or album. Is it public?")
	if response.status_code >= 400:
		raise AmazonMusicImportError(f"Amazon Music returned HTTP {response.status_code}. Try again later.")
	page = response.content.decode("utf-8", errors="replace")
	try:
		return parse_amazon_music_page(page, source_id, source_type)
	except AmazonMusicImportError:
		# Current Amazon Music pages are JavaScript shells. Their public web-player
		# endpoint still returns the playlist metadata without requiring sign-in.
		return _fetch_amazon_web_player_source(client, url, source_id, source_type, user_agent, timeout)


def parse_amazon_music_source(value: str) -> tuple[str, str, str]:
	text = (value or "").strip()
	parsed = urlparse(text)
	host = parsed.netloc.lower()
	if "music.amazon." not in host:
		raise AmazonMusicImportError("Paste an Amazon Music playlist or album link.")
	match = re.search(r"/(user-playlists|playlists|albums)/([A-Za-z0-9]+)", parsed.path, re.I)
	if not match:
		raise AmazonMusicImportError("This Amazon Music link does not identify a playlist or album.")
	return text, "album" if match.group(1).lower() == "albums" else "playlist", match.group(2)


def _fetch_amazon_web_player_source(
	client: requests.Session,
	url: str,
	source_id: str,
	source_type: str,
	user_agent: str,
	timeout: int,
) -> AmazonMusicSource:
	parsed = urlparse(url)
	origin = f"{parsed.scheme}://{parsed.netloc}"
	try:
		config_response = client.get(
			f"{origin}/config.json?skipToken=false",
			headers={"User-Agent": user_agent, "Accept-Language": "en-US,en;q=0.9"},
			timeout=timeout,
		)
		config_response.raise_for_status()
		config = config_response.json()
		payload = _amazon_web_player_payload(url, config, user_agent)
		region = _text(config.get("siteRegion") or "NA").lower()
		api_response = client.post(
			f"https://{region}.web.skill.music.a2z.com/api/showHome",
			json=payload,
			headers={"User-Agent": user_agent, "Origin": origin, "Referer": url},
			timeout=timeout,
		)
		api_response.raise_for_status()
	except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
		raise AmazonMusicImportError(
			"Amazon Music did not expose tracks for this link. Is it public and available without signing in?"
		) from exc
	return parse_amazon_music_web_player(api_response.json(), source_id, source_type)


def _amazon_web_player_payload(url: str, config: dict[str, Any], user_agent: str) -> dict[str, str]:
	parsed = urlparse(url)
	csrf = config.get("csrf") or {}
	territory = _text(config.get("musicTerritory")).upper()
	currency = {"AU": "AUD", "CA": "CAD", "GB": "GBP", "JP": "JPY", "US": "USD"}.get(territory, "")
	client_headers = {
		"x-amzn-authentication": json.dumps({"interface": "ClientAuthenticationInterface.v1_0.ClientTokenElement", "accessToken": config.get("accessToken", "")}, separators=(",", ":")),
		"x-amzn-device-model": "WEBPLAYER",
		"x-amzn-device-width": "1920",
		"x-amzn-device-family": "WebPlayer",
		"x-amzn-device-id": config["deviceId"],
		"x-amzn-user-agent": user_agent,
		"x-amzn-session-id": config["sessionId"],
		"x-amzn-device-height": "1080",
		"x-amzn-request-id": str(uuid.uuid4()),
		"x-amzn-device-language": config.get("displayLanguage", "en_US"),
		"x-amzn-currency-of-preference": currency,
		"x-amzn-os-version": "1.0",
		"x-amzn-application-version": config.get("version", "1.0"),
		"x-amzn-device-time-zone": time.tzname[0],
		"x-amzn-timestamp": str(int(time.time() * 1000)),
		"x-amzn-csrf": json.dumps({"interface": "CSRFInterface.v1_0.CSRFHeaderElement", "token": csrf["token"], "timestamp": csrf["ts"], "rndNonce": csrf["rnd"]}, separators=(",", ":")),
		"x-amzn-music-domain": parsed.netloc,
		"x-amzn-referer": "",
		"x-amzn-affiliate-tags": "",
		"x-amzn-ref-marker": "",
		"x-amzn-page-url": url,
		"x-amzn-weblab-id-overrides": "",
		"x-amzn-video-player-token": "",
		"x-amzn-feature-flags": "hd-supported,uhd-supported",
		"x-amzn-has-profile-id": "",
		"x-amzn-age-band": "",
	}
	deeplink = {"interface": "DeeplinkInterface.v1_0.DeeplinkClientInformation", "deeplink": parsed.path}
	return {"deeplink": json.dumps(deeplink, separators=(",", ":")), "headers": json.dumps(client_headers, separators=(",", ":"))}


def parse_amazon_music_web_player(root: Any, source_id: str, source_type: str) -> AmazonMusicSource:
	name = ""
	cover_url = None
	tracks: list[dict] = []
	seen: set[str] = set()
	for item in _walk(root):
		if not isinstance(item, dict):
			continue
		deeplink = _text((item.get("templateData") or {}).get("deeplink")) if isinstance(item.get("templateData"), dict) else ""
		if source_id in deeplink and str(item.get("interface", "")).endswith("DetailTemplateInterface.DetailTemplate"):
			name = _element_text(item.get("headerText")) or _text(item.get("headerPrimaryText")) or name
			cover_url = _text(item.get("headerImage")) or cover_url
		if not str(item.get("interface", "")).endswith("VisualRowItemElement"):
			continue
		track_id = _text(item.get("id"))
		primary_link = item.get("primaryLink") if isinstance(item.get("primaryLink"), dict) else {}
		if not track_id or "trackAsin=" not in _text(primary_link.get("deeplink")) or track_id in seen:
			continue
		seen.add(track_id)
		tracks.append({
			"title": _text(item.get("primaryText")),
			"artists": _text(item.get("secondaryText1")),
			"album": _text(item.get("secondaryText2")),
			"playlist": "",
			"isrc": None,
			"sp_id": track_id,
			"duration_ms": _clock_duration_ms(item.get("secondaryText3")),
			"year": None,
			"cover_url": _text(item.get("image")) or None,
			"track_no": len(tracks) + 1,
			"disc_no": 1,
		})
	if not tracks:
		raise AmazonMusicImportError("Amazon Music did not expose tracks for this link. Is it public and available without signing in?")
	name = name or f"Amazon Music {source_type.title()}"
	for track in tracks:
		track["playlist"] = name
		track["cover_url"] = track["cover_url"] or cover_url
	return AmazonMusicSource(source_id, name, tracks, len(tracks), source_type, None)


def _element_text(value: Any) -> str:
	return _text(value.get("text")) if isinstance(value, dict) else _text(value)


def _clock_duration_ms(value: Any) -> int:
	try:
		parts = [int(part) for part in _text(value).split(":")]
		seconds = 0
		for part in parts:
			seconds = seconds * 60 + part
		return seconds * 1000
	except (TypeError, ValueError):
		return 0


def parse_amazon_music_page(page: str, source_id: str, source_type: str) -> AmazonMusicSource:
	objects = _json_objects(page)
	name = ""
	tracks: list[dict] = []
	seen: set[str] = set()
	for root in objects:
		for item in _walk(root):
			if not name and isinstance(item, dict):
				name = _text(item.get("playlistName") or item.get("albumName"))
			track = _amazon_track(item, name or "Amazon Music")
			if not track:
				continue
			key = str(track.get("sp_id") or f"{track['artists']}:{track['title']}")
			if key in seen:
				continue
			seen.add(key)
			track["track_no"] = len(tracks) + 1
			tracks.append(track)
	if not tracks:
		raise AmazonMusicImportError(
			"Amazon Music did not expose tracks for this link. Is it public and available without signing in?"
		)
	name = name or f"Amazon Music {source_type.title()}"
	for track in tracks:
		track["playlist"] = name
	warning = incomplete_import_warning("Amazon Music", len(tracks), None, source_type)
	return AmazonMusicSource(source_id, name, tracks, len(tracks), source_type, warning)


def _json_objects(page: str) -> list[Any]:
	out: list[Any] = []
	for match in re.finditer(r"<script[^>]*>(.*?)</script>", page or "", re.S | re.I):
		text = html.unescape(match.group(1).strip())
		candidates = [text]
		if "=" in text:
			candidates.append(text.split("=", 1)[1].strip().rstrip(";"))
		for candidate in candidates:
			try:
				out.append(json.loads(candidate))
				break
			except Exception:
				continue
	return out


def _walk(value: Any):
	if isinstance(value, dict):
		yield value
		for child in value.values():
			yield from _walk(child)
	elif isinstance(value, list):
		for child in value:
			yield from _walk(child)


def _amazon_track(item: Any, playlist_name: str) -> dict | None:
	if not isinstance(item, dict):
		return None
	title = _text(item.get("title") or item.get("trackName"))
	artist = item.get("artistName") or item.get("artist")
	if isinstance(artist, dict):
		artist = artist.get("name")
	artist = _text(artist)
	item_type = _text(item.get("type") or item.get("__typename")).lower()
	if not title or not artist or ("track" not in item_type and "song" not in item_type):
		return None
	return {
		"title": title,
		"artists": artist,
		"album": _text(item.get("albumName")),
		"playlist": playlist_name,
		"isrc": _text(item.get("isrc")) or None,
		"sp_id": _text(item.get("id") or item.get("asin")) or None,
		"duration_ms": _duration_ms(item),
		"year": None,
		"cover_url": _text(item.get("imageUrl") or item.get("artwork")) or None,
		"track_no": 0,
		"disc_no": 1,
	}


def _duration_ms(item: dict[str, Any]) -> int:
	try:
		value = int(item.get("duration") or item.get("durationMs") or 0)
		return value if value > 10000 else value * 1000
	except Exception:
		return 0


def _text(value: Any) -> str:
	return re.sub(r"\s+", " ", str(value or "")).strip()
