import pytest

from csvmusic.core.youtube_url import YouTubeVideoUrlError, parse_youtube_video_id


@pytest.mark.parametrize("url", [
	"https://www.youtube.com/watch?v=dQw4w9WgXcQ",
	"https://music.youtube.com/watch?v=dQw4w9WgXcQ",
	"https://youtu.be/dQw4w9WgXcQ",
	"https://www.youtube.com/shorts/dQw4w9WgXcQ",
])
def test_parse_youtube_video_id(url):
	assert parse_youtube_video_id(url) == "dQw4w9WgXcQ"


@pytest.mark.parametrize("url", [
	"https://www.youtube.com/playlist?list=PL123",
	"https://example.com/watch?v=dQw4w9WgXcQ",
	"https://www.youtube.com/watch?v=too-short",
	"",
])
def test_parse_youtube_video_id_rejects_unsupported_input(url):
	with pytest.raises(YouTubeVideoUrlError):
		parse_youtube_video_id(url)
