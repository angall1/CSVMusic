from csvmusic.ui.main_window import MainWindow


class _Toggle:
	def __init__(self, checked):
		self.checked = checked

	def isChecked(self):
		return self.checked


def test_opus_setting_overrides_standard_format():
	window = type("Window", (), {
		"cb_opus_output": _Toggle(True),
		"rb_m4a": _Toggle(True),
	})()

	assert MainWindow._selected_format(window) == "opus"


def test_opus_setting_is_off_by_default_behavior():
	window = type("Window", (), {
		"cb_opus_output": _Toggle(False),
		"rb_m4a": _Toggle(True),
	})()

	assert MainWindow._selected_format(window) == "m4a"
