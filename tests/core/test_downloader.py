from csvmusic.core import downloader
import unicodedata
import pytest
from pathlib import Path
from types import SimpleNamespace
from subprocess import CompletedProcess


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


def test_large_batch_warning_requires_explicit_risk_acknowledgement():
	profile = downloader.youtube_batch_mitigation(300, using_cookies=False)
	message = downloader.youtube_risk_acknowledgement(profile)

	assert profile.active is True
	assert "repeated YouTube API, search, and media requests" in message
	assert "temporarily block requests" in message
	assert "randomized delays" in message


def test_small_batch_does_not_require_risk_acknowledgement():
	profile = downloader.youtube_batch_mitigation(20, using_cookies=False)

	assert downloader.youtube_risk_acknowledgement(profile) is None


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


def test_write_m3u_defaults_to_audio_folder(tmp_path):
	track = {"title": "Song", "artists": "Artist", "album": "Album", "duration_ms": 1000}
	path = downloader.write_m3u(tmp_path, "Mix", [track], "mp3")

	assert path == tmp_path / "Mix" / "Mix.m3u8"
	assert path.read_text(encoding="utf-8").splitlines()[-1] == "Artist - Song.mp3"


def test_write_m3u_uses_relative_media_paths_from_custom_folder(tmp_path):
	track = {"title": "Song", "artists": "Artist", "album": "Album", "duration_ms": 1000}
	playlist_dir = tmp_path / "Playlists"
	path = downloader.write_m3u(tmp_path / "Music", "Mix", [track], "mp3", playlist_output_dir=playlist_dir)

	assert path == playlist_dir / "Mix.m3u8"
	assert path.read_text(encoding="utf-8").splitlines()[-1] == "../Music/Mix/Artist - Song.mp3"


@pytest.mark.parametrize("force_lr", [False, True])
@pytest.mark.parametrize("bitrate", [None, 192, 320])
def test_mp3_stereo_encoding(monkeypatch, tmp_path, force_lr, bitrate):
	commands = []
	def fetch(cmd):
		Path(cmd[cmd.index("-o") + 1]).write_bytes(b"source")
		return 0, ""
	def encode(cmd):
		commands.append(cmd)
		Path(cmd[-1]).write_bytes(b"mp3")
		return SimpleNamespace(returncode=0, stdout="", stderr="")
	monkeypatch.setattr(downloader, "_run_ytdlp_detail", fetch)
	monkeypatch.setattr(downloader, "_run_capture", encode)
	monkeypatch.setattr(downloader, "ytdlp_js_runtime_args", lambda _: [])
	monkeypatch.setattr(downloader, "store_source", lambda _: None)
	downloader.download_mp3("video", tmp_path, "song", yt_dlp_bin="yt-dlp", ffmpeg_bin="ffmpeg", force_lr_stereo=force_lr, cbr_bitrate_kbps=bitrate)
	cmd = commands[0]
	if force_lr:
		assert cmd[cmd.index("-joint_stereo") + 1] == "0"
	else:
		assert "-joint_stereo" not in cmd
	assert "-ac" not in cmd


@pytest.mark.parametrize("disable_pns, processing, expected_codec", [
	(True, {}, "aac"),
	(True, {"volume_gain": 1}, "aac"),
	(False, {}, "copy"),
	(False, {"volume_gain": 1}, "aac"),
])
def test_m4a_encoding_options(monkeypatch, tmp_path, disable_pns, processing, expected_codec):
	calls = []
	def encode(args):
		calls.append(args)
		Path(args[-1]).write_bytes(b"encoded")
		return CompletedProcess(args, 0, "", "")
	monkeypatch.setattr(downloader, "_run_capture", encode)
	src, dst = tmp_path / "source.m4a", tmp_path / "output.m4a"
	src.write_bytes(b"download")
	assert downloader._normalize_to_m4a(src, dst, "ffmpeg", "video", processing, disable_aac_pns=disable_pns) == dst
	args, = calls
	assert args[args.index("-c:a") + 1] == expected_codec
	assert ("-af" in args) == bool(processing)
	if disable_pns:
		for option, value in (("-aac_pns", "0"), ("-b:a", "256k"), ("-ar", "44100")):
			assert args[args.index(option) + 1] == value
	else:
		assert "-aac_pns" not in args
		if expected_codec == "aac":
			assert args[args.index("-b:a") + 1] == "192k"


def test_failed_pns_encode_preserves_existing_track(monkeypatch, tmp_path):
	dst = tmp_path / "Song.m4a"
	dst.write_bytes(b"previous download")
	def download(args):
		template = args[args.index("-o") + 1]
		Path(template.replace("%(ext)s", "m4a")).write_bytes(b"unprocessed AAC")
		return 0, ""
	def reject_pns_option(args):
		assert args[args.index("-aac_pns") + 1] == "0"
		Path(args[-1]).write_bytes(b"incomplete output")
		return CompletedProcess(args, 1, "", "Unrecognized option 'aac_pns'")
	monkeypatch.setattr(downloader, "ytdlp_js_runtime_args", lambda _bin: [])
	monkeypatch.setattr(downloader, "_run_ytdlp_detail", download)
	monkeypatch.setattr(downloader, "_run_capture", reject_pns_option)
	with pytest.raises(downloader.DownloadError, match="aac_pns"):
		downloader.download_m4a("video", tmp_path, "Song", yt_dlp_bin="yt-dlp", ffmpeg_bin="ffmpeg", disable_aac_pns=True)
	assert dst.read_bytes() == b"previous download"
	assert list(tmp_path.iterdir()) == [dst]
