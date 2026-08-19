from csvmusic.ui.main_window import ResumeLocationDialog


def test_resume_location_accepts_folder_or_m3u(tmp_path):
	folder = tmp_path / "Playlist"
	folder.mkdir()
	m3u = tmp_path / "Playlist.m3u8"
	m3u.write_text("#EXTM3U\n", encoding="utf-8")

	assert ResumeLocationDialog._is_allowed(folder)
	assert ResumeLocationDialog._is_allowed(m3u)


def test_resume_location_rejects_unrelated_files(tmp_path):
	csv_file = tmp_path / "Playlist.csv"
	csv_file.write_text("Track name\n", encoding="utf-8")

	assert not ResumeLocationDialog._is_allowed(csv_file)
	assert not ResumeLocationDialog._is_allowed(tmp_path / "missing.m3u")
