# tabs only
from csvmusic.ui.spotify_public_scrape import jittered_scroll_delay_ms


def test_scroll_delay_has_small_bounded_variance() -> None:
	values = [jittered_scroll_delay_ms(500) for _ in range(100)]

	assert all(460 <= value <= 540 for value in values)
	assert len(set(values)) > 1
