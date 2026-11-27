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


def test_stereo_option_defaults_and_persistence(monkeypatch, tmp_path):
	settings = {}
	monkeypatch.setattr("csvmusic.ui.library_mode.load_settings", lambda: settings)
	monkeypatch.setattr("csvmusic.ui.library_mode.save_settings", settings.update)
	library = {"output_dir": str(tmp_path), "format": "mp3"}
	dialog = LibrarySettingsDialog(library)
	assert not dialog.force_lr_stereo.isChecked()
	assert dialog.force_lr_stereo.isEnabled()
	dialog.force_lr_stereo.setChecked(True)
	dialog._save()
	reopened = LibrarySettingsDialog(library)
	assert reopened.force_lr_stereo.isChecked()
	reopened.format.setCurrentText("m4a")
	assert not reopened.force_lr_stereo.isEnabled()
	reopened.format.setCurrentText("mp3")
	assert reopened.force_lr_stereo.isChecked()
	reopened.force_lr_stereo.setChecked(False)
	reopened._save()
	assert settings["force_lr_stereo"] is False


def test_pns_setting_is_opt_in_and_remembered_across_formats(monkeypatch, tmp_path):
	settings = {}
	monkeypatch.setattr("csvmusic.ui.library_mode.load_settings", settings.copy)
	monkeypatch.setattr("csvmusic.ui.library_mode.save_settings", settings.update)
	library = {"output_dir": str(tmp_path), "format": "m4a"}
	dialog = LibrarySettingsDialog(library, download_confirmation=True)
	assert dialog.disable_aac_pns.isEnabled()
	assert not dialog.disable_aac_pns.isChecked()
	dialog.disable_aac_pns.setChecked(True)
	for fmt in ("mp3", "opus"):
		dialog.format.setCurrentText(fmt)
		assert not dialog.disable_aac_pns.isEnabled()
	dialog._save()
	assert settings["disable_aac_pns"] is True

	reopened = LibrarySettingsDialog(library)
	reopened.format.setCurrentText("m4a")
	assert reopened.disable_aac_pns.isEnabled()
	assert reopened.disable_aac_pns.isChecked()
	reopened.disable_aac_pns.setChecked(False)
	reopened._save()
	assert settings["disable_aac_pns"] is False
