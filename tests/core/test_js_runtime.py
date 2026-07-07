from unittest.mock import patch

from csvmusic.core.js_runtime import JsRuntimeInfo, ytdlp_js_runtime_args


def test_ytdlp_js_runtime_args_enable_supported_node():
	runtime = JsRuntimeInfo("Node", "node", "node", "v24.0.0", True)

	with patch("csvmusic.core.js_runtime.ytdlp_supports_js_runtimes", return_value=True), \
			patch("csvmusic.core.js_runtime.detect_js_runtimes", return_value=(runtime,)):
		assert ytdlp_js_runtime_args("yt-dlp") == ["--js-runtimes", "node"]


def test_ytdlp_js_runtime_args_skip_old_ytdlp():
	runtime = JsRuntimeInfo("Node", "node", "node", "v24.0.0", True)

	with patch("csvmusic.core.js_runtime.ytdlp_supports_js_runtimes", return_value=False), \
			patch("csvmusic.core.js_runtime.detect_js_runtimes", return_value=(runtime,)):
		assert ytdlp_js_runtime_args("yt-dlp") == []


def test_ytdlp_js_runtime_args_do_not_need_deno_flag():
	runtime = JsRuntimeInfo("Deno", "deno", "deno", "deno 2.5.0", True)

	with patch("csvmusic.core.js_runtime.ytdlp_supports_js_runtimes", return_value=True), \
			patch("csvmusic.core.js_runtime.detect_js_runtimes", return_value=(runtime,)):
		assert ytdlp_js_runtime_args("yt-dlp") == []
