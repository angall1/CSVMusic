from csvmusic.core import downloader
import unicodedata


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
