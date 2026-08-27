# tabs only
import pathlib

from csvmusic.core import settings


def test_macos_uses_application_support(monkeypatch, tmp_path: pathlib.Path) -> None:
	monkeypatch.setattr(settings.sys, "platform", "darwin")
	monkeypatch.setattr(settings.pathlib.Path, "home", classmethod(lambda cls: tmp_path))

	assert settings._settings_dir() == tmp_path / "Library" / "Application Support" / "CSVMusic"


def test_linux_honors_xdg_data_home(monkeypatch, tmp_path: pathlib.Path) -> None:
	monkeypatch.setattr(settings.sys, "platform", "linux")
	monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
	monkeypatch.setattr(settings.pathlib.Path, "home", classmethod(lambda cls: tmp_path))

	assert settings._settings_dir() == tmp_path / "xdg-data" / "csvmusic"


def test_macos_migrates_previous_cross_platform_location(monkeypatch, tmp_path: pathlib.Path) -> None:
	legacy = tmp_path / ".local" / "share" / "csvmusic"
	legacy.mkdir(parents=True)
	(legacy / "library.json").write_text("{}", encoding="utf-8")
	monkeypatch.setattr(settings.sys, "platform", "darwin")
	monkeypatch.setattr(settings.pathlib.Path, "home", classmethod(lambda cls: tmp_path))

	target = settings._settings_dir()

	assert target == tmp_path / "Library" / "Application Support" / "CSVMusic"
	assert (target / "library.json").exists()
