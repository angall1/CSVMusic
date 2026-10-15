from unittest.mock import MagicMock, patch

from csvmusic.core.youtube_session import youtube_cookie_text, verify_youtube_session


def cookie(domain=".youtube.com"):
	return {"domain": domain, "path": "/", "name": "SAPISID", "value": "test-only", "secure": True, "http_only": True, "expires": 0}


def test_popup_exports_only_youtube():
	text = youtube_cookie_text([cookie(), cookie(".google.com"), cookie("evilyoutube.com")])
	assert text.count("test-only") == 1
	assert "#HttpOnly_.youtube.com" in text


def test_popup_rejects_cookie_line_injection():
	row = cookie()
	row["value"] = "bad\nrow"
	assert "bad" not in youtube_cookie_text([row])


def test_verification_requires_server_login_marker(tmp_path):
	path = tmp_path / "cookies.txt"
	path.write_text(youtube_cookie_text([cookie()]))
	session = MagicMock()
	session.__enter__.return_value = session
	session.get.return_value.status_code = 200
	with patch("csvmusic.core.youtube_session.requests.Session", return_value=session):
		for body, expected in (("guest", False), ('{"LOGGED_IN":false}', False), ('{"LOGGED_IN":true}', True)):
			session.get.return_value.text = body
			assert verify_youtube_session(str(path)) is expected
	assert session.get.call_args.kwargs["allow_redirects"] is False
	assert session.get.call_args.kwargs["timeout"] == (10, 20)


def test_guest_cookie_file_does_not_make_network_request(tmp_path):
	path = tmp_path / "guest.txt"
	path.write_text("# Netscape HTTP Cookie File\n")
	with patch("csvmusic.core.youtube_session.requests.Session") as session:
		assert not verify_youtube_session(str(path))
		session.assert_not_called()
