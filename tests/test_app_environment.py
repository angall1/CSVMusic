# tabs only
from csvmusic.app import configure_linux_webengine_environment, configure_qt_logging


def test_linux_webengine_uses_software_rendering_and_preserves_flags() -> None:
	environment = {"QTWEBENGINE_CHROMIUM_FLAGS": "--enable-logging"}

	configure_linux_webengine_environment(environment, "linux")

	assert environment["QTWEBENGINE_CHROMIUM_FLAGS"] == "--enable-logging --disable-gpu --disable-gpu-compositing"
	assert environment["QT_OPENGL"] == "software"


def test_linux_webengine_configuration_is_idempotent() -> None:
	environment: dict[str, str] = {}

	configure_linux_webengine_environment(environment, "linux")
	configure_linux_webengine_environment(environment, "linux")

	flags = environment["QTWEBENGINE_CHROMIUM_FLAGS"].split()
	assert flags.count("--disable-gpu") == 1
	assert flags.count("--disable-gpu-compositing") == 1


def test_webengine_environment_is_unchanged_off_linux() -> None:
	environment = {"QTWEBENGINE_CHROMIUM_FLAGS": "--custom"}

	configure_linux_webengine_environment(environment, "win32")

	assert environment == {"QTWEBENGINE_CHROMIUM_FLAGS": "--custom"}


def test_qt_logging_hides_only_icc_warnings_and_preserves_existing_rules() -> None:
	environment = {"QT_LOGGING_RULES": "qt.webenginecontext.debug=true"}

	configure_qt_logging(environment)
	configure_qt_logging(environment)

	assert environment["QT_LOGGING_RULES"] == "qt.webenginecontext.debug=true;qt.gui.icc.warning=false"
