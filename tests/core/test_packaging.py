# tabs only
import pathlib
import tomllib


ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_console_entry_point_targets_app_main() -> None:
	with (ROOT / "pyproject.toml").open("rb") as handle:
		project = tomllib.load(handle)["project"]

	assert project["scripts"]["csvmusic"] == "csvmusic.app:main"


def test_module_entry_point_is_packaged() -> None:
	assert (ROOT / "csvmusic" / "__main__.py").is_file()
