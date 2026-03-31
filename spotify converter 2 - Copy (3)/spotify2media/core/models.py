# tabs only
from dataclasses import dataclass

@dataclass
class Track:
	sp_id: str
	title: str
	artists: str
	album: str
	duration_ms: int
	isrc: str | None
	year: str | None
	cover_url: str | None
	track_no: int
	disc_no: int

@dataclass
class MatchResult:
	video_id: str
	confidence: float
	duration_s: int
	channel: str
