from unittest.mock import patch

from csvmusic.core.subprocess_env import sanitized_subprocess_env


def test_sanitized_subprocess_env_restores_pyinstaller_orig_value():
	with patch.dict(
		"csvmusic.core.subprocess_env.os.environ",
		{
			"DYLD_LIBRARY_PATH": "/tmp/_MEI123",
			"DYLD_LIBRARY_PATH_ORIG": "/usr/local/lib",
			"PATH": "/usr/bin",
		},
		clear=True,
	):
		env = sanitized_subprocess_env()

	assert env["DYLD_LIBRARY_PATH"] == "/usr/local/lib"
	assert "DYLD_LIBRARY_PATH_ORIG" not in env
	assert env["PATH"] == "/usr/bin"


def test_sanitized_subprocess_env_removes_leaked_pyinstaller_vars():
	with patch.dict(
		"csvmusic.core.subprocess_env.os.environ",
		{
			"DYLD_FRAMEWORK_PATH": "/tmp/_MEI123",
			"PYTHONHOME": "/tmp/_MEI123",
			"_MEIPASS": "/tmp/_MEI123",
			"HOME": "/Users/test",
		},
		clear=True,
	):
		env = sanitized_subprocess_env()

	assert "DYLD_FRAMEWORK_PATH" not in env
	assert "PYTHONHOME" not in env
	assert "_MEIPASS" not in env
	assert env["HOME"] == "/Users/test"
