# tabs only
import os, subprocess, sys

_WINDOWS = sys.platform.startswith("win")

_PYINSTALLER_LEAKED_VARS = (
	"DYLD_LIBRARY_PATH",
	"DYLD_FRAMEWORK_PATH",
	"DYLD_FALLBACK_LIBRARY_PATH",
	"DYLD_FALLBACK_FRAMEWORK_PATH",
	"DYLD_INSERT_LIBRARIES",
	"PYTHONHOME",
	"PYTHONPATH",
	"PYTHONEXECUTABLE",
	"_MEIPASS",
	"_MEIPASS2",
	"_PYI_APPLICATION_HOME_DIR",
	"_PYI_ARCHIVE_FILE",
	"_PYI_LOADER_TYPE",
	"_PYI_PARENT_PROCESS_LEVEL",
)


def sanitized_subprocess_env() -> dict[str, str]:
	env = os.environ.copy()
	for key in _PYINSTALLER_LEAKED_VARS:
		orig = env.pop(f"{key}_ORIG", None)
		if orig is not None:
			env[key] = orig
		else:
			env.pop(key, None)
	return env


def hidden_subprocess_kwargs() -> dict:
	if not _WINDOWS:
		return {}
	startupinfo = subprocess.STARTUPINFO()
	startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
	flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
	return {"startupinfo": startupinfo, "creationflags": flags}


def subprocess_kwargs() -> dict:
	return {
		"env": sanitized_subprocess_env(),
		**hidden_subprocess_kwargs(),
	}
