from csvmusic.core.import_warnings import incomplete_import_warning


def test_incomplete_import_warning_with_known_total():
	warning = incomplete_import_warning("Example", 3, 5)

	assert "Example only let CSVMusic load 3 of 5 playlist tracks from this link" in warning
	assert "the missing tracks will be skipped" in warning
	assert "Open TuneMyMusic from CSVMusic" in warning


def test_incomplete_import_warning_with_unknown_total():
	warning = incomplete_import_warning("Example", 100, None)

	assert "Example only let CSVMusic load 100 playlist tracks from this link" in warning
	assert "If the original playlist has more tracks than this" in warning
	assert "Back in CSVMusic, choose CSV File and load that CSV" in warning
