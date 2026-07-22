# tabs only
import pathlib

import pytest

from csvmusic.core.output_folder import OutputFolderError, validate_output_folder


def test_validate_output_folder_creates_and_exercises_directory(tmp_path: pathlib.Path) -> None:
	output = tmp_path / "new output"

	result = validate_output_folder(output)

	assert result == output
	assert output.is_dir()
	assert list(output.iterdir()) == []


@pytest.mark.parametrize(
	"folder_name",
	[
		"Automatically Add to Music.localized",
		"Automatically Add to iTunes",
	],
)
def test_validate_output_folder_rejects_media_auto_import_folder(
	tmp_path: pathlib.Path,
	folder_name: str,
) -> None:
	output = tmp_path / "Music" / "Media.localized" / folder_name

	with pytest.raises(OutputFolderError, match="watched by Apple Music or iTunes"):
		validate_output_folder(output)

	assert not output.exists()


def test_validate_output_folder_rejects_file_path(tmp_path: pathlib.Path) -> None:
	output = tmp_path / "not-a-folder"
	output.write_text("content", encoding="utf-8")

	with pytest.raises(OutputFolderError, match="not a folder|could not create"):
		validate_output_folder(output)
