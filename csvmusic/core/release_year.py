"""Read explicit release dates; never infer them from upload dates or titles."""
import re


def release_year(value: object) -> int | None:
	if isinstance(value, dict):
		return release_year(value.get("year")) or release_year(value.get("isoString"))
	text = str(value or "").strip()
	match = re.fullmatch(r"([1-9][0-9]{3})(?:-[0-9]{2}(?:-[0-9]{2}(?:T.*)?)?)?", text)
	return int(match[1]) if match else None


def metadata_year(data: object) -> int | None:
	if not isinstance(data, dict):
		return None
	for field in ("releaseDate", "release_date", "releaseYear", "release_year", "year"):
		year = release_year(data.get(field))
		if year is not None:
			return year
	return None
