from unittest.mock import patch

from csvmusic.core import js_runtime
from csvmusic.core.js_runtime import JsRuntimeInfo, ytdlp_js_runtime_args


def test_current_date_version_supports_js_runtimes():
	js_runtime.ytdlp_supports_js_runtimes.cache_clear()
	with patch("csvmusic.core.js_runtime._yt_dlp_version", return_value="2026.08.19"):
		assert js_runtime.ytdlp_supports_js_runtimes("yt-dlp.exe")
	js_runtime.ytdlp_supports_js_runtimes.cache_clear()


def test_version_probe_allows_slow_standalone_startup():
	with patch("csvmusic.core.js_runtime.subprocess.run") as run:
		run.return_value.stdout = "2026.08.19\n"
		assert js_runtime._run_version("yt-dlp.exe") == "2026.08.19"
		assert run.call_args.kwargs["timeout"] == 15


def test_ytdlp_js_runtime_args_enable_supported_node():
	runtime = JsRuntimeInfo("Node", "node", "node", "v24.0.0", True)

	with patch("csvmusic.core.js_runtime.ytdlp_supports_js_runtimes", return_value=True), \
			patch("csvmusic.core.js_runtime.detect_js_runtimes", return_value=(runtime,)):
		assert ytdlp_js_runtime_args("yt-dlp") == ["--js-runtimes", "node:node"]


def test_ytdlp_js_runtime_args_skip_old_ytdlp():
	runtime = JsRuntimeInfo("Node", "node", "node", "v24.0.0", True)

	with patch("csvmusic.core.js_runtime.ytdlp_supports_js_runtimes", return_value=False), \
			patch("csvmusic.core.js_runtime.detect_js_runtimes", return_value=(runtime,)):
		assert ytdlp_js_runtime_args("yt-dlp") == []


def test_ytdlp_js_runtime_args_pass_explicit_deno_path():
	runtime = JsRuntimeInfo("Deno", "deno", "deno", "deno 2.5.0", True)

	with patch("csvmusic.core.js_runtime.ytdlp_supports_js_runtimes", return_value=True), \
			patch("csvmusic.core.js_runtime.detect_js_runtimes", return_value=(runtime,)):
		assert ytdlp_js_runtime_args("yt-dlp") == ["--js-runtimes", "deno:deno"]
