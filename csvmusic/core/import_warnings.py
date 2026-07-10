# tabs only


CSV_FALLBACK_STEPS = (
	"\n\nFor the most reliable complete playlist import:\n"
	"1. Open TuneMyMusic from CSVMusic.\n"
	"2. Choose the original music service as the source.\n"
	"3. Paste the same playlist link, or connect the service if TuneMyMusic asks.\n"
	"4. Export the playlist as a CSV file.\n"
	"5. Back in CSVMusic, choose CSV File and load that CSV."
)


def incomplete_import_warning(platform: str, loaded_count: int, total_count: int | None, source_label: str = "playlist") -> str:
	if total_count and total_count > loaded_count:
		lead = (
			f"{platform} only let CSVMusic load {loaded_count} of {total_count} {source_label} tracks from this link. "
			"If you continue with this import, the missing tracks will be skipped."
		)
	else:
		lead = (
			f"{platform} only let CSVMusic load {loaded_count} {source_label} tracks from this link. "
			f"If the original {source_label} has more tracks than this, the missing tracks will be skipped."
		)
	return lead + CSV_FALLBACK_STEPS
