# tabs only
import pathlib
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
	assert f"# What's New In {APP_VERSION}" in readme
	assert f"/releases/tag/v{APP_VERSION}" in readme
	assert f"/releases/download/v{APP_VERSION}/" in readme


def test_release_workflow_fetches_packaged_deno() -> None:
	workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

	assert "Fetch Deno runtime" in workflow
	assert "resources/deno/${DENO_PLATFORM}" in workflow
	assert "sha256sum --check" in workflow
	assert "licenses/DENO-LICENSE.md" in workflow


def test_pyinstaller_collects_deno_and_ejs() -> None:
	spec = (ROOT / "CSVMusic.spec").read_text(encoding="utf-8")

	assert "resources' / 'deno'" in spec
	assert "collect_all('yt_dlp_ejs')" in spec
