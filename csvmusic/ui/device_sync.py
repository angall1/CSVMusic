# tabs only
from PySide6.QtCore import QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
	QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QProgressBar,
	QPushButton, QSizePolicy, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from csvmusic.core.device_sync import (
	PortableDevice, SyncResult, delete_device_playlist, discover_devices, eject_device, ipod_sync_available,
	list_device_playlists, sync_device,
)
from csvmusic.core.log import log
from csvmusic.core.settings import load_settings, save_settings


class DeviceSyncWorker(QThread):
	progress = Signal(int, int, str)
	completed = Signal(object)
	failed = Signal(str)

	def __init__(self, device: PortableDevice, library: dict, parent=None):
		super().__init__(parent)
		self.device = device
		self.library = library

	def run(self) -> None:
		try:
			result = sync_device(self.device, self.library, self.progress.emit)
			self.completed.emit(result)
		except Exception as exc:
			log(f"device sync failed device={self.device.root} error={exc}")
			self.failed.emit(str(exc))


class DevicePlaylistReadWorker(QThread):
	status = Signal(str)
	completed = Signal(object)
	failed = Signal(str)

	def __init__(self, device: PortableDevice, parent=None):
		super().__init__(parent)
		self.device = device

	def run(self) -> None:
		try:
			self.completed.emit(list_device_playlists(self.device, self.status.emit))
		except Exception as exc:
			log(f"device playlist read failed device={self.device.root} error={exc}")
			self.failed.emit(str(exc))


class DeviceSyncDialog(QDialog):
	def __init__(self, library: dict, parent=None):
		super().__init__(parent)
		self.library = library
		self.devices: list[PortableDevice] = []
		self.selected_device: PortableDevice | None = None
		self.worker: DeviceSyncWorker | None = None
		self.playlist_worker: DevicePlaylistReadWorker | None = None
		self.device_scan_busy = False
		self.refresh_after_sync = False
		self.setWindowTitle("Sync Portable Music Player")
		self.setMinimumWidth(620)
		self.setFont(QFont("Comic Sans MS", 10))
		self.setStyleSheet("""
			QDialog { background: #c0c0c0; color: #101010; }
			QLabel#syncTitle { background: #000080; color: #ffff00; border: 2px outset #ffffff; padding: 10px; }
			QPushButton, QComboBox {
				background: #c0c0c0; border-top: 2px solid #ffffff; border-left: 2px solid #ffffff;
				border-right: 2px solid #000000; border-bottom: 2px solid #000000; padding: 6px 10px;
			}
			QPushButton:pressed { border-top: 2px solid #000000; border-left: 2px solid #000000; border-right: 2px solid #ffffff; border-bottom: 2px solid #ffffff; }
			QPushButton:disabled { color: #707070; }
			QProgressBar { background: white; color: #101010; border: 2px inset #ffffff; min-height: 22px; text-align: center; font-weight: bold; }
			QProgressBar::chunk { background: #ffd400; border-right: 1px solid #806800; }
		""")
		self._build_ui()
		self.device_timer = QTimer(self)
		self.device_timer.setInterval(3000)
		self.device_timer.timeout.connect(self._refresh_devices)
		self.device_timer.start()
		QTimer.singleShot(150, self._refresh_devices)

	def _build_ui(self) -> None:
		layout = QVBoxLayout(self)
		layout.setContentsMargins(12, 12, 12, 12)
		layout.setSpacing(10)
		title = QLabel("PORTABLE PLAYER SYNC")
		title.setObjectName("syncTitle")
		title.setAlignment(Qt.AlignCenter)
		title.setFont(QFont("Comic Sans MS", 15, QFont.Bold))
		layout.addWidget(title)
		layout.addWidget(QLabel("Connect a portable player, select it below, then sync every fully downloaded playlist."))
		device_row = QHBoxLayout()
		self.device_combo = QComboBox()
		self.device_combo.currentIndexChanged.connect(self._selection_changed)
		device_row.addWidget(self.device_combo, 1)
		layout.addLayout(device_row)
		self.device_info = QLabel("No device selected.")
		self.device_info.setWordWrap(True)
		self.device_info.setStyleSheet("background: #ffffcc; border: 1px solid #808000; padding: 7px;")
		layout.addWidget(self.device_info)
		self.progress = QProgressBar()
		self.progress.setRange(0, 100)
		self.progress.setValue(0)
		self.progress.setFormat("Ready")
		layout.addWidget(self.progress)
		self.activity = QLabel("Select a device to begin.")
		self.activity.setWordWrap(True)
		layout.addWidget(self.activity)
		playlist_heading = QLabel("Currently synced playlists")
		playlist_heading.setFont(QFont("Comic Sans MS", 12, QFont.Bold))
		layout.addWidget(playlist_heading)
		self.playlist_list = QTreeWidget()
		self.playlist_list.setHeaderLabels(["Playlists"])
		self.playlist_list.setHeaderHidden(True)
		self.playlist_list.setRootIsDecorated(False)
		self.playlist_list.setMinimumHeight(180)
		self.playlist_list.setIndentation(0)
		self.playlist_list.setStyleSheet("QTreeWidget { background: #ffffff; border: 2px inset #ffffff; } QTreeWidget::item { padding: 0; margin: 0; }")
		layout.addWidget(self.playlist_list)
		self.auto_eject = QCheckBox("Automatically eject after a successful sync")
		self.auto_eject.setChecked(bool(load_settings().get("device_sync_auto_eject", False)))
		self.auto_eject.toggled.connect(lambda checked: save_settings({"device_sync_auto_eject": checked}))
		layout.addWidget(self.auto_eject)
		buttons = QHBoxLayout()
		self.sync_button = QPushButton("↧  Sync All Playlists")
		self.sync_button.setStyleSheet("QPushButton { background: #008000; color: white; font-weight: bold; }")
		self.sync_button.clicked.connect(self._sync_all)
		self.eject_button = QPushButton("⏏  Eject")
		self.eject_button.setEnabled(False)
		self.eject_button.clicked.connect(self._eject)
		self.close_button = QPushButton("Close")
		self.close_button.clicked.connect(self.reject)
		buttons.addWidget(self.sync_button)
		buttons.addWidget(self.eject_button)
		buttons.addStretch(1)
		buttons.addWidget(self.close_button)
		layout.addLayout(buttons)

	def _refresh_devices(self) -> None:
		if self.worker or self.playlist_worker or self.device_scan_busy:
			return
		current_key = self.selected_device.key if self.selected_device else ""
		devices = discover_devices()
		old_keys = [device.key for device in self.devices]
		new_keys = [device.key for device in devices]
		if old_keys == new_keys and self.device_combo.count() > 0:
			return
		self.devices = devices
		self.device_combo.blockSignals(True)
		self.device_combo.clear()
		for device in self.devices:
			self.device_combo.addItem(device.name, device.key)
		self.device_combo.blockSignals(False)
		if not self.devices:
			self.device_combo.addItem("No removable players detected")
			self.selected_device = None
			self.sync_button.setEnabled(False)
			self.eject_button.setEnabled(False)
			self.playlist_list.clear()
			self.device_info.setText("No player detected. Connect one; this list refreshes automatically every three seconds.")
			return
		index = next((i for i, device in enumerate(self.devices) if device.key == current_key), 0)
		self.device_combo.setCurrentIndex(index)
		self.sync_button.setEnabled(False)
		self._selection_changed(index)

	def _selection_changed(self, index: int) -> None:
		if index < 0 or index >= len(self.devices):
			return
		device = self.devices[index]
		if device.kind == "ipod_classic":
			available, reason = ipod_sync_available()
			if not available:
				QMessageBox.warning(self, "iPod Sync Unavailable", reason)
				return
		if self.selected_device and self.selected_device.key == device.key:
			return
		self.selected_device = device
		self.sync_button.setEnabled(True)
		self.eject_button.setEnabled(True)
		self.device_info.setText(f"SELECTED: {device.name}\n{device.description}\nLocation: {device.root}")
		self.activity.setText("Device selected. Ready to sync all fully downloaded playlists.")
		self._refresh_device_playlists()

	def _refresh_device_playlists(self) -> None:
		self.playlist_list.clear()
		if not self.selected_device or self.worker or self.playlist_worker:
			return
		self.playlist_list.setEnabled(False)
		self.device_combo.setEnabled(False)
		self.sync_button.setEnabled(False)
		self.eject_button.setEnabled(False)
		self.progress.setRange(0, 0)
		self.progress.setFormat("Reading device...")
		self.device_scan_busy = True
		self._device_scan_status("Connecting to the player and locating its playlist database...")
		self.playlist_worker = DevicePlaylistReadWorker(self.selected_device, self)
		self.playlist_worker.status.connect(self._device_scan_status)
		self.playlist_worker.completed.connect(self._device_playlists_loaded)
		self.playlist_worker.failed.connect(self._device_playlists_failed)
		self.playlist_worker.finished.connect(self._device_playlist_worker_finished)
		self.playlist_worker.start()

	def _device_playlists_loaded(self, playlists: list) -> None:
		for playlist in playlists:
			item = QTreeWidgetItem([playlist.name])
			item.setData(0, Qt.UserRole, playlist.name)
			item.setSizeHint(0, QSize(0, 54))
			self.playlist_list.addTopLevelItem(item)
			card = QFrame()
			card.setObjectName("devicePlaylistCard")
			card.setStyleSheet("QFrame#devicePlaylistCard { background: #c8dfcc; border: 1px solid #48624d; }")
			card_layout = QHBoxLayout(card)
			card_layout.setContentsMargins(12, 5, 7, 5)
			card_layout.setSpacing(10)
			name_label = QLabel(playlist.name)
			name_label.setFont(QFont("Comic Sans MS", 10, QFont.Bold))
			name_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
			count_label = QLabel(f"{playlist.track_count}/{playlist.track_count} tracks")
			count_label.setStyleSheet("color: #303030;")
			delete_button = QToolButton()
			delete_button.setText("🗑")
			delete_button.setToolTip(f"Delete playlist '{playlist.name}' from this player")
			delete_button.setAccessibleName(f"Delete playlist {playlist.name}")
			delete_button.setFixedSize(42, 40)
			delete_button.setStyleSheet("QToolButton { background: #c00000; color: white; font-size: 17px; padding: 1px; }")
			delete_button.clicked.connect(lambda _checked=False, name=playlist.name: self._delete_playlist(name))
			card_layout.addWidget(name_label, 1)
			card_layout.addWidget(count_label)
			card_layout.addWidget(delete_button)
			self.playlist_list.setItemWidget(item, 0, card)
		name = self.selected_device.name if self.selected_device else "the player"
		self.activity.setText(f"Found {len(playlists)} playlists on {name}.")

	def _device_playlists_failed(self, message: str) -> None:
		self.activity.setText(f"Could not read device playlists: {message}")

	def _device_playlist_worker_finished(self) -> None:
		if self.playlist_worker:
			self.playlist_worker.deleteLater()
		self.playlist_worker = None
		self.device_scan_busy = False
		self.progress.setRange(0, 100)
		self.progress.setValue(0)
		self.progress.setFormat("Ready")
		if self.worker is None:
			self.playlist_list.setEnabled(True)
			self.device_combo.setEnabled(True)
			self.sync_button.setEnabled(self.selected_device is not None)
			self.eject_button.setEnabled(self.selected_device is not None)

	def _device_scan_status(self, message: str) -> None:
		self.activity.setText(message)

	def _set_sync_locked(self, locked: bool) -> None:
		self.device_combo.setEnabled(not locked)
		self.playlist_list.setEnabled(not locked)
		self.auto_eject.setEnabled(not locked)
		self.close_button.setEnabled(not locked)
		self.sync_button.setEnabled(not locked and self.selected_device is not None)
		self.eject_button.setEnabled(not locked and self.selected_device is not None)

	def _delete_playlist(self, playlist_name: str) -> None:
		if not self.selected_device or self.worker or self.playlist_worker:
			return
		answer = QMessageBox.question(
			self, "Delete Device Playlist",
			f"Delete the playlist '{playlist_name}' from this player?\n\nThe playlist entry will be removed, but its music files will be preserved.",
			QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
		)
		if answer != QMessageBox.Yes:
			return
		try:
			delete_device_playlist(self.selected_device, playlist_name)
		except Exception as exc:
			QMessageBox.critical(self, "Playlist Delete Failed", str(exc))
			return
		self.activity.setText(f"Deleted playlist '{playlist_name}'. Music files were preserved.")
		self._refresh_device_playlists()

	def _sync_all(self) -> None:
		if not self.selected_device or self.worker or self.playlist_worker:
			return
		answer = QMessageBox.question(
			self, "Sync All Playlists",
			f"Sync every fully downloaded playlist to {self.selected_device.name}?\n\nIncomplete playlists will be skipped. Existing device content outside CSVMusic-managed playlists will be preserved.",
			QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
		)
		if answer != QMessageBox.Yes:
			return
		self._set_sync_locked(True)
		self.progress.setRange(0, 100)
		self.progress.setValue(0)
		self.progress.setFormat("Starting sync...")
		self.worker = DeviceSyncWorker(self.selected_device, self.library, self)
		self.worker.progress.connect(self._progress_changed)
		self.worker.completed.connect(self._sync_completed)
		self.worker.failed.connect(self._sync_failed)
		self.worker.finished.connect(self._worker_finished)
		self.worker.start()

	def _progress_changed(self, done: int, total: int, message: str) -> None:
		percent = round(done * 100 / max(1, total))
		self.progress.setValue(max(0, min(100, percent)))
		self.progress.setFormat(f"{done}/{total} — {percent}%")
		self.activity.setText(message)

	def _sync_completed(self, result: SyncResult) -> None:
		self.progress.setValue(100)
		self.progress.setFormat("Sync complete")
		skipped = f" Skipped incomplete: {', '.join(result.playlists_skipped)}." if result.playlists_skipped else ""
		self.activity.setText(
			f"Synced {result.playlists} playlists. Copied {result.tracks_copied} tracks; reused {result.tracks_reused}.{skipped}"
		)
		if not self.auto_eject.isChecked():
			self.refresh_after_sync = True
		if self.auto_eject.isChecked():
			self._eject(show_success=False)

	def _sync_failed(self, message: str) -> None:
		self.progress.setFormat("Sync failed")
		if "winerror 433" in message.casefold() or "does not exist" in message.casefold():
			detail = (
				"The iPod disconnected or reset during file transfer. CSVMusic stopped immediately and did not continue writing. "
				"Keep the iPod backup; reconnect the device before trying recovery or another sync."
			)
			self.activity.setText(detail)
			QMessageBox.critical(self, "iPod Disconnected During Sync", f"{detail}\n\nWindows reported:\n{message}")
			return
		self.activity.setText(message)
		QMessageBox.critical(self, "Device Sync Failed", message)

	def _worker_finished(self) -> None:
		self.worker = None
		self._set_sync_locked(False)
		if self.refresh_after_sync and self.selected_device:
			self.refresh_after_sync = False
			QTimer.singleShot(0, self._refresh_device_playlists)

	def _eject(self, *, show_success: bool = True) -> None:
		if not self.selected_device:
			return
		name = self.selected_device.name
		try:
			eject_device(self.selected_device)
		except Exception as exc:
			QMessageBox.warning(self, "Eject Failed", str(exc))
			return
		self.activity.setText(f"{name} was safely ejected.")
		self.selected_device = None
		self.eject_button.setEnabled(False)
		self.sync_button.setEnabled(False)
		if show_success:
			QMessageBox.information(self, "Device Ejected", "The portable player was safely ejected.")

	def reject(self) -> None:
		if self.worker or self.playlist_worker:
			QMessageBox.information(self, "Device Activity in Progress", "Wait for the current device operation to finish before closing this window.")
			return
		super().reject()
