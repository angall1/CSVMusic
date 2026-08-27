import pathlib

from csvmusic.ui import workers


def _pipeline(tmp_path: pathlib.Path, *, force_download: bool) -> workers.PipelineWorker:
	return workers.PipelineWorker(
		csv_path="",
		out_dir=str(tmp_path),
		playlist="Test Playlist",
		fmt="mp3",
		write_m3u8=False,
		write_m3u_plain=False,
		embed_art=False,
		yt_dlp_path=None,
		ffmpeg_path_override=None,
		cookies_browser=None,
		cookies_file=None,
		force_download=force_download,
		tracks_override=[{
			"title": "Complicated",
			"artists": "Avril Lavigne",
			"playlist": "Test Playlist",
			"duration_ms": 244000,
		}],
		row_indices=[0],
	)


def _low_confidence_result():
	option = {
		"videoId": "test-video",
		"title": "Complicated",
		"author": "Avril Lavigne",
		"source": "music",
		"score": 0.4,
	}
	return None, 0.4, [option]


def test_force_download_uses_best_low_confidence_candidate(monkeypatch, tmp_path):
	worker = _pipeline(tmp_path, force_download=True)
	results = []
	finished = []
	worker.sig_track_result.connect(lambda row, payload: results.append((row, payload)))
	worker.sig_done.connect(lambda message, done, skipped, failed: finished.append((message, done, skipped, failed)))

	monkeypatch.setattr(workers, "YTMusic", lambda: object())
	monkeypatch.setattr(workers, "find_best", lambda _yt, _track: _low_confidence_result())
	monkeypatch.setattr(workers, "yt_thumbnail_bytes", lambda _video_id: None)
	monkeypatch.setattr(workers, "tag_file", lambda *_args, **_kwargs: None)
	monkeypatch.setattr(workers.time, "sleep", lambda _seconds: None)

	def fake_download(_video_id, destination, base_name, _profile):
		path = destination / f"{base_name}.mp3"
		path.write_bytes(b"audio")
		return path

	monkeypatch.setattr(worker, "_download_with_profile", fake_download)
	worker.run()

	assert len(results) == 1
	assert results[0][1]["downloaded"] is True
	assert results[0][1]["forced_match"] is True
	assert results[0][1]["match"]["videoId"] == "test-video"
	assert len(finished[0][1]) == 1
	assert finished[0][2] == []
	assert finished[0][3] == []


def test_low_confidence_candidate_is_skipped_without_force(monkeypatch, tmp_path):
	worker = _pipeline(tmp_path, force_download=False)
	results = []
	finished = []
	worker.sig_track_result.connect(lambda row, payload: results.append((row, payload)))
	worker.sig_done.connect(lambda message, done, skipped, failed: finished.append((message, done, skipped, failed)))

	monkeypatch.setattr(workers, "YTMusic", lambda: object())
	monkeypatch.setattr(workers, "find_best", lambda _yt, _track: _low_confidence_result())
	monkeypatch.setattr(workers.time, "sleep", lambda _seconds: None)
	worker.run()

	assert len(results) == 1
	assert results[0][1]["skipped"] is True
	assert results[0][1]["downloaded"] is False
	assert finished[0][1] == []
	assert len(finished[0][2]) == 1
	assert finished[0][3] == []


def test_track_volume_gain_is_added_to_global_processing(tmp_path):
	worker = _pipeline(tmp_path, force_download=False)
	worker.audio_processing = {"enabled": True, "normalize": True, "volume_gain": 2, "bass_gain": 1}
	worker._set_track_audio_processing({"audio_volume_gain": -5})

	assert worker._active_audio_processing == {
		"enabled": True,
		"normalize": True,
		"volume_gain": -3,
		"bass_gain": 1,
	}


def test_track_volume_gain_enables_processing_without_global_equalizer(tmp_path):
	worker = _pipeline(tmp_path, force_download=False)
	worker._set_track_audio_processing({"audio_volume_gain": 4})

	assert worker._active_audio_processing["enabled"] is True
	assert worker._active_audio_processing["volume_gain"] == 4
