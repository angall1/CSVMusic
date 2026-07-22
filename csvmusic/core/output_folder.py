# tabs only
import os
import pathlib
import tempfile


_WATCHED_FOLDER_NAMES = {
	"automatically add to itunes",
	"automatically add to itunes.localized",
	"automatically add to music",
	"automatically add to music.localized",
}


class OutputFolderError(ValueError):
	pass


def _is_media_auto_import_folder(path: pathlib.Path) -> bool:
	return any(part.casefold() in _WATCHED_FOLDER_NAMES for part in path.parts)


def validate_output_folder(value: str | pathlib.Path) -> pathlib.Path:
	"""Create and exercise an output directory before starting FFmpeg work."""
	path = pathlib.Path(value).expanduser()
	if _is_media_auto_import_folder(path):
		raise OutputFolderError(
			"The selected folder is watched by Apple Music or iTunes and may move audio files "
			"before FFmpeg finishes writing them. Choose a normal folder, then import the "
			"completed files into Music afterward."
		)
	try:
		path.mkdir(parents=True, exist_ok=True)
	except OSError as exc:
		raise OutputFolderError(f"CSVMusic could not create the output folder: {exc}") from exc
	if not path.is_dir():
		raise OutputFolderError("The selected output path is not a folder.")

	probe: pathlib.Path | None = None
	renamed: pathlib.Path | None = None
	try:
		with tempfile.NamedTemporaryFile(
			mode="wb",
			prefix=".csvmusic-write-test-",
			suffix=".tmp",
			dir=path,
			delete=False,
		) as handle:
			probe = pathlib.Path(handle.name)
			handle.write(b"CSVMusic output folder test\n")
			handle.flush()
			os.fsync(handle.fileno())
		renamed = probe.with_suffix(".renamed")
		probe.rename(renamed)
		renamed.unlink()
		return path
	except OSError as exc:
		raise OutputFolderError(
			"CSVMusic cannot safely create, rename, and remove files in the selected output "
			f"folder. Check its permissions or choose another folder. Details: {exc}"
		) from exc
	finally:
		for candidate in (probe, renamed):
			if candidate is None:
				continue
			try:
				candidate.unlink(missing_ok=True)
			except OSError:
				pass
