from csvmusic.ui.library_mode import LibrarySettingsDialog


def test_legacy_defaults_off_and_bitrate_hidden(monkeypatch, tmp_path):
	monkeypatch.setattr("csvmusic.ui.library_mode.load_settings", lambda: {})
	dialog = LibrarySettingsDialog({"output_dir": str(tmp_path), "format": "mp3"})
	assert not dialog.legacy_ipod.isChecked()
	assert dialog.legacy_mp3.isHidden()
	assert dialog.mp3_quality.isEnabled()
	dialog.legacy_ipod.setChecked(True)
	assert not dialog.legacy_mp3.isHidden()
	dialog.legacy_mp3.setCurrentIndex(dialog.legacy_mp3.findData("cbr_192"))
	assert not dialog.mp3_quality.isEnabled()
	dialog.legacy_ipod.setChecked(False)
	assert dialog.legacy_mp3.isHidden()
	assert dialog.mp3_quality.isEnabled()
	dialog.close()
