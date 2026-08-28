# tabs only
import pathlib
import re
import tomllib

from csvmusic.version import APP_VERSION


ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_console_entry_point_targets_app_main() -> None:
	with (ROOT / "pyproject.toml").open("rb") as handle:
		project = tomllib.load(handle)["project"]

	assert project["scripts"]["csvmusic"] == "csvmusic.app:main"


def test_module_entry_point_is_packaged() -> None:
	assert (ROOT / "csvmusic" / "__main__.py").is_file()


def test_release_versions_are_consistent() -> None:
	with (ROOT / "pyproject.toml").open("rb") as handle:
		project = tomllib.load(handle)["project"]
	readme = (ROOT / "README.md").read_text(encoding="utf-8")

	assert project["version"] == APP_VERSION
	# The README points at the latest published release, which may trail the
	# package's in-development version between releases.
	assert "# What's New In " in readme
	tag = re.search(r"/releases/tag/v(\d+\.\d+\.\d+)", readme)
	download_versions = set(re.findall(r"/releases/download/v(\d+\.\d+\.\d+)/", readme))
	assert tag is not None
	assert download_versions == {tag.group(1)}


def test_release_workflow_fetches_packaged_deno() -> None:
	workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

	assert "Fetch Deno runtime" in workflow
	assert "resources/deno/${DENO_PLATFORM}" in workflow
	assert "hashlib.file_digest" in workflow
	assert 're.search(r"(?i)\\b[0-9a-f]{64}\\b", checksum_text)' in workflow
	assert "SHA256 mismatch" in workflow
	assert "licenses/DENO-LICENSE.md" in workflow


def test_release_workflow_pins_tested_ytdlp() -> None:
	workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

	assert 'YTDLP_VERSION: "2026.08.19"' in workflow
	assert '"yt-dlp[default]==${YTDLP_VERSION}"' in workflow
	assert 'releases/download/{ytdlp_version}/yt-dlp.exe' in workflow
	assert "releases/latest/download/yt-dlp" not in workflow


def test_pyinstaller_collects_deno_and_ejs() -> None:
	spec = (ROOT / "CSVMusic.spec").read_text(encoding="utf-8")

	assert "resources' / 'deno'" in spec
	assert "collect_all('yt_dlp_ejs')" in spec
