# tabs only
from dataclasses import dataclass

@dataclass
class AppConfig:
	format: str = "m4a"	# "m4a" or "mp3"
	write_m3u: bool = True
	youtube_music_only: bool = True
	confidence_min: float = 0.72
	search_concurrency: int = 3
	download_concurrency: int = 3
	rate_limit_s: float = 0.5
