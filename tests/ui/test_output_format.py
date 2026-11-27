from csvmusic.ui.main_window import MainWindow


class _Toggle:
	def __init__(self, checked):
		self.checked = checked

	def isChecked(self):
		return self.checked


def test_opus_setting_overrides_standard_format():
	window = type("Window", (), {
		"cb_opus_output": _Toggle(True),
		"rb_m4a": _Toggle(True),
	})()

	assert MainWindow._selected_format(window) == "opus"


def test_opus_setting_is_off_by_default_behavior():
	window = type("Window", (), {
		"cb_opus_output": _Toggle(False),
		"rb_m4a": _Toggle(True),
	})()

	assert MainWindow._selected_format(window) == "m4a"


def test_aac_pns_preference_is_saved_and_available_only_for_m4a(monkeypatch):
	from csvmusic.ui import main_window

	settings = {}
	monkeypatch.setattr(main_window, "load_settings", settings.copy)
	monkeypatch.setattr(main_window, "save_settings", settings.update)
	monkeypatch.setattr(MainWindow, "_start_update_check", lambda self: None)
	window = MainWindow()
	try:
		option = window.cb_disable_aac_pns
		assert option.isEnabled() and not option.isChecked()
		option.setChecked(True)
		assert settings["disable_aac_pns"] is True
		window.rb_mp3.setChecked(True)
		assert not option.isEnabled()
		window.rb_m4a.setChecked(True)
		window.cb_opus_output.setChecked(True)
		assert not option.isEnabled()
		window.cb_opus_output.setChecked(False)
		assert option.isEnabled() and option.isChecked()
		option.setChecked(False)
		settings["disable_aac_pns"] = True
		window._load_last_session()
		assert option.isChecked()
	finally:
		window.close()


def test_legacy_manifest_writer_keeps_playlists_separate(tmp_path):
	from types import SimpleNamespace
	calls = []
	a = {"playlist": "A", "title": "Shared"}
	b = {"playlist": "B", "title": "Shared"}
	tracks = [a, b, a]
	window = SimpleNamespace(ed_out=SimpleNamespace(text=lambda: str(tmp_path)), tracks=tracks,
		table=SimpleNamespace(rowCount=lambda: 3),
		track_results={i: {"track": t, "file_path": str(tmp_path / t["playlist"] / "Shared.mp3"), "downloaded": True} for i, t in enumerate(tracks)},
		cb_m3u8=SimpleNamespace(isChecked=lambda: True), cb_m3u_plain=SimpleNamespace(isChecked=lambda: False),
		_write_playlist_file=lambda root, name, entries, *args: calls.append((name, entries)),
		_remove_playlist_file=lambda *args: None)
	MainWindow._rewrite_playlists(window)
	assert [(name, len(entries)) for name, entries in calls] == [("A", 2), ("B", 1)]
	assert all(path.parent.name == name for name, entries in calls for track, path in entries)
