from csvmusic.core import downloader
import unicodedata


def test_youtube_client_fallbacks_use_current_client_names():
	assert downloader.YOUTUBE_CLIENTS[0] == "web_embedded"
	assert downloader.YOUTUBE_CLIENTS[1] is None
	assert "tv_embedded" not in downloader.YOUTUBE_CLIENTS
	assert "webremix" not in downloader.YOUTUBE_CLIENTS
	assert downloader._extractor_args(None) == []


def test_mp3_source_format_falls_back_to_combined_stream():
	assert downloader.MP3_SOURCE_FORMAT == "bestaudio/best"


def test_auth_required_errors_do_not_retry_without_cookies():
	assert not downloader._should_retry_without_cookies(
		"ERROR: Sign in to confirm your age",
		"",
	)
	assert not downloader._should_retry_without_cookies(
		"ERROR: login_required: age-restricted video",
		"",
	)
	assert not downloader._should_retry_without_cookies(
		"ERROR: Precondition check failed",
		"",
	)


def test_cookie_backed_age_failure_mentions_cookies_were_used():
	detail = downloader._summarize_tool_output(
		"ERROR: Sign in to confirm your age",
		"",
		using_cookies=True,
	)

	assert "Cookies were used" in detail
	assert "Sign into YouTube with Firefox cookies" not in detail


def test_public_extraction_errors_can_still_retry_without_cookies():
	assert downloader._should_retry_without_cookies(
		"ERROR: signature solving failed",
		"",
	)


def test_js_runtime_failure_mentions_deno_or_node():
	detail = downloader._summarize_tool_output(
		"WARNING: No supported JavaScript runtime could be found",
		"",
	)

	assert "Deno 2.3+" in detail
	assert "Node 22+" in detail


def test_error_summary_prefers_error_over_trailing_progress():
	detail = downloader._summarize_tool_output(
		"ERROR: [youtube] challenge solving failed\n[youtube] Downloading android vr player API JSON",
		"[youtube] Sleeping 1.25 seconds",
	)

	assert "challenge solving failed" in detail
	assert "Sleeping" not in detail


def test_list_downloads_matches_decomposed_accents(tmp_path):
	base = downloader.sanitize_name("Björk - Jóga")
	decomposed = unicodedata.normalize("NFD", base)
	path = tmp_path / f"{decomposed}.webm"
	path.write_text("audio")

	assert downloader._list_downloads(tmp_path, base) == [path]


def test_cleanup_outputs_removes_decomposed_accents(tmp_path):
	base = downloader.sanitize_name("Mötley Crüe - Über")
	decomposed = unicodedata.normalize("NFD", base)
	path = tmp_path / f"{decomposed}.tmp.webm"
	path.write_text("audio")

	downloader._cleanup_outputs(tmp_path, base)

	assert not path.exists()


def test_sanitize_name_shortens_long_windows_filenames_deterministically():
	first = downloader.sanitize_name("Orchestra - " + "A" * 300)
	second = downloader.sanitize_name("Orchestra - " + "B" * 300)

	assert len(first) == downloader._MAX_SAFE_NAME_LENGTH
	assert len(second) == downloader._MAX_SAFE_NAME_LENGTH
	assert first != second
	assert first == downloader.sanitize_name("Orchestra - " + "A" * 300)


def test_tag_file_writes_mp3_track_and_disc_numbers(monkeypatch, tmp_path):
	tags = {}

	class FakeEasyID3(dict):
		def save(self, *_args, **_kwargs):
			pass

	class FakeID3:
		def __init__(self, _path):
			pass

	def fake_easy_id3(_path=None):
		return tags_object

	tags_object = FakeEasyID3()
	monkeypatch.setattr(downloader, "EasyID3", fake_easy_id3)
	monkeypatch.setattr(downloader, "ID3", FakeID3)

	downloader.tag_file(
		tmp_path / "track.mp3",
		{"title": "Song", "artists": "Artist", "album": "Album", "track_no": 7, "disc_no": 2},
		None,
	)

	assert tags_object["tracknumber"] == "7"
	assert tags_object["discnumber"] == "2"


def test_tag_file_writes_m4a_track_and_disc_numbers(monkeypatch, tmp_path):
	class FakeMP4(dict):
		def save(self):
			pass

	tags = FakeMP4()
	monkeypatch.setattr(downloader, "MP4", lambda _path: tags)

	downloader.tag_file(
		tmp_path / "track.m4a",
		{"title": "Song", "artists": "Artist", "album": "Album", "track_no": 7, "disc_no": 2},
		None,
	)

	assert tags["trkn"] == [(7, 0)]
	assert tags["disk"] == [(2, 0)]


def test_tag_file_writes_opus_metadata(monkeypatch, tmp_path):
	class FakeOpus(dict):
		def save(self):
			pass

	tags = FakeOpus()
	monkeypatch.setattr(downloader, "OggOpus", lambda _path: tags)

	downloader.tag_file(
		tmp_path / "track.opus",
		{"title": "Song", "artists": "Artist", "album": "Album", "year": 2026, "track_no": 7, "disc_no": 2},
		None,
	)

	assert tags["title"] == ["Song"]
	assert tags["artist"] == ["Artist"]
	assert tags["date"] == ["2026"]
	assert tags["tracknumber"] == ["7"]
	assert tags["discnumber"] == ["2"]
