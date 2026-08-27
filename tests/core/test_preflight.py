import subprocess

from csvmusic.core import preflight


def test_bad_bundled_ffmpeg_uses_working_system_fallback(monkeypatch):
	errors = []
	warnings = []
	details = {}
	monkeypatch.setattr(preflight, "ffmpeg_path", lambda: "/bundle/ffmpeg")
	monkeypatch.setattr(preflight, "_system_ffmpeg_candidates", lambda: ["/opt/homebrew/bin/ffmpeg"])

	def probe(path):
		if path == "/bundle/ffmpeg":
			raise OSError(86, "Bad CPU type in executable")
		return subprocess.CompletedProcess([path, "-version"], 0, "ffmpeg version", "")

	monkeypatch.setattr(preflight, "_run_ffmpeg_version", probe)

	preflight._check_ffmpeg(errors, warnings, details)

	assert errors == []
	assert details["ffmpeg"] == "/opt/homebrew/bin/ffmpeg"
	assert any("using system ffmpeg" in warning for warning in warnings)


def test_invalid_explicit_ffmpeg_does_not_silently_change_tools(monkeypatch):
	errors = []
	warnings = []
	details = {}
	monkeypatch.setattr(preflight, "_valid_executable", lambda _path: False)
	monkeypatch.setattr(preflight, "_system_ffmpeg_candidates", lambda: ["/usr/local/bin/ffmpeg"])

	preflight._check_ffmpeg(errors, warnings, details, "/chosen/ffmpeg")

	assert errors == ["ffmpeg override invalid: /chosen/ffmpeg"]
	assert warnings == []
