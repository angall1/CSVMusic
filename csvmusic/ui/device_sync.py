# tabs only
from PySide6.QtCore import QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
	QCheckBox, QComboBox, QDialog, QFrame, QHeaderView, QHBoxLayout, QLabel, QMessageBox, QProgressBar,
	QPushButton, QSizePolicy, QTabWidget, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
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

	def __init__(self, device: PortableDevice, library: dict, playlist_indexes: set[int], parent=None):
		super().__init__(parent)
		self.device = device
		self.library = dict(library)
		self.library["playlists"] = [
			playlist for index, playlist in enumerate(library.get("playlists", []))
			if index in playlist_indexes
		]

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
		self.resize(700, 720)
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
		layout.addWidget(QLabel("Connect a portable player, choose library playlists below, then sync the fully downloaded selections."))
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
		self.playlist_tabs = QTabWidget()
		self.playlist_tabs.setStyleSheet("""
			QTabWidget::pane { border: 2px inset #ffffff; background: #c0c0c0; }
			QTabBar::tab { background: #c0c0c0; border: 2px outset #ffffff; padding: 7px 16px; font-weight: bold; }
			QTabBar::tab:selected { background: #000080; color: white; }
		""")
		choose_page = QWidget()
		choose_layout = QVBoxLayout(choose_page)
		choose_layout.setContentsMargins(5, 7, 5, 5)
		selection_heading = QHBoxLayout()
		selection_label = QLabel("Library playlists to sync")
		selection_label.setFont(QFont("Comic Sans MS", 12, QFont.Bold))
		self.select_all = QCheckBox("Select All")
		self.select_all.setChecked(True)
		self.select_all.toggled.connect(self._toggle_all_playlists)
		selection_heading.addWidget(selection_label)
		selection_heading.addStretch(1)
		selection_heading.addWidget(self.select_all)
		choose_layout.addLayout(selection_heading)
		self.library_playlist_list = QTreeWidget()
		self.library_playlist_list.setHeaderLabels(["Playlists"])
		self.library_playlist_list.setHeaderHidden(True)
		self.library_playlist_list.setRootIsDecorated(False)
		self.library_playlist_list.setIndentation(0)
		self.library_playlist_list.header().setSectionResizeMode(0, QHeaderView.Stretch)
		self.library_playlist_list.setMinimumHeight(300)
		self.library_playlist_list.setStyleSheet("""
			QTreeWidget { background: #ffffff; border: 2px inset #ffffff; }
			QTreeWidget::item { padding: 0; margin: 0; }
		""")
		indexed_playlists = sorted(
			enumerate(self.library.get("playlists", [])),
			key=lambda pair: str(pair[1].get("name") or "Playlist").casefold(),
		)
		for index, playlist in indexed_playlists:
			tracks = [track for track in playlist.get("tracks", []) if track.get("enabled", True)]
			queued = sum(1 for track in tracks if track.get("force_redownload"))
			item = QTreeWidgetItem([""])
			item.setData(0, Qt.UserRole, index)
			item.setSizeHint(0, QSize(0, 46))
			self.library_playlist_list.addTopLevelItem(item)
			card = QFrame()
			card.setObjectName("syncLibraryPlaylistCard")
			color = "#fff0a8" if queued else "#c8ddc8"
			card.setStyleSheet(
				f"QFrame#syncLibraryPlaylistCard {{ background: {color}; border-top: 2px solid #ffffff; "
				"border-left: 2px solid #ffffff; border-right: 2px solid #404040; border-bottom: 2px solid #404040; }"
			)
			card_layout = QHBoxLayout(card)
			card_layout.setContentsMargins(7, 3, 8, 3)
			card_layout.setSpacing(7)
			checkbox = QCheckBox()
			checkbox.setChecked(True)
			checkbox.setToolTip(f"Sync {playlist.get('name') or 'Playlist'}")
			checkbox.toggled.connect(self._playlist_selection_changed)
			icon = QLabel("♫")
			icon.setAlignment(Qt.AlignCenter)
			icon.setFixedSize(32, 32)
			icon.setFont(QFont("Comic Sans MS", 14, QFont.Bold))
			icon.setStyleSheet("background: #606060; color: white; border: 1px inset #404040;")
			name_label = QLabel(str(playlist.get("name") or "Playlist"))
			name_label.setFont(QFont("Comic Sans MS", 10, QFont.Bold))
			name_label.setWordWrap(True)
			name_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
			count_text = f"{len(tracks)} tracks" + (f"\n{queued} awaiting download" if queued else "")
			count_label = QLabel(count_text)
			count_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
			card_layout.addWidget(checkbox)
			card_layout.addWidget(icon)
			card_layout.addWidget(name_label, 1)
			card_layout.addWidget(count_label)
			if queued:
				card.setToolTip("This playlist will be skipped until its queued replacements are downloaded.")
			self.library_playlist_list.setItemWidget(item, 0, card)
		choose_layout.addWidget(self.library_playlist_list, 1)
		self.playlist_tabs.addTab(choose_page, "✓  Choose Playlists")
		on_device_page = QWidget()
		on_device_layout = QVBoxLayout(on_device_page)
		on_device_layout.setContentsMargins(5, 7, 5, 5)
		playlist_heading = QLabel("Currently synced playlists")
		playlist_heading.setFont(QFont("Comic Sans MS", 12, QFont.Bold))
		on_device_layout.addWidget(playlist_heading)
		self.playlist_list = QTreeWidget()
		self.playlist_list.setHeaderLabels(["Playlists"])
		self.playlist_list.setHeaderHidden(True)
		self.playlist_list.setRootIsDecorated(False)
		self.playlist_list.setMinimumHeight(300)
		self.playlist_list.setIndentation(0)
		self.playlist_list.setStyleSheet("QTreeWidget { background: #ffffff; border: 2px inset #ffffff; } QTreeWidget::item { padding: 0; margin: 0; }")
		on_device_layout.addWidget(self.playlist_list, 1)
		self.playlist_tabs.addTab(on_device_page, "♫  On Device")
		layout.addWidget(self.playlist_tabs, 1)
		self.auto_eject = QCheckBox("Automatically eject after a successful sync")
		self.auto_eject.setChecked(bool(load_settings().get("device_sync_auto_eject", False)))
		self.auto_eject.toggled.connect(lambda checked: save_settings({"device_sync_auto_eject": checked}))
		layout.addWidget(self.auto_eject)
		buttons = QHBoxLayout()
		self.sync_button = QPushButton("↧  Sync Selected Playlists")
		self.sync_button.setStyleSheet("""
			QPushButton { background: #008000; color: white; font-weight: bold; }
			QPushButton:disabled { background: #8c8c8c; color: #d8d8d8; border: 2px inset #b0b0b0; }
		""")
		self.sync_button.clicked.connect(self._sync_all)
		self.eject_button = QPushButton("⏏  Eject")
		self.eject_button.setStyleSheet("QPushButton:disabled { background: #8c8c8c; color: #d8d8d8; border: 2px inset #b0b0b0; }")
		self.eject_button.setEnabled(False)
		self.eject_button.clicked.connect(self._eject)
		self.close_button = QPushButton("Close")
		self.close_button.clicked.connect(self.reject)
		buttons.addWidget(self.sync_button)
		buttons.addWidget(self.eject_button)
		buttons.addStretch(1)
		buttons.addWidget(self.close_button)
		layout.addLayout(buttons)

	def _selected_playlist_indexes(self) -> set[int]:
		selected: set[int] = set()
		for index in range(self.library_playlist_list.topLevelItemCount()):
			item = self.library_playlist_list.topLevelItem(index)
			card = self.library_playlist_list.itemWidget(item, 0)
			checkbox = card.findChild(QCheckBox) if card else None
			if checkbox and checkbox.isChecked():
				selected.add(int(item.data(0, Qt.UserRole)))
		return selected

	def _toggle_all_playlists(self, checked: bool) -> None:
		self.library_playlist_list.blockSignals(True)
		for index in range(self.library_playlist_list.topLevelItemCount()):
			item = self.library_playlist_list.topLevelItem(index)
			card = self.library_playlist_list.itemWidget(item, 0)
			checkbox = card.findChild(QCheckBox) if card else None
			if checkbox:
				checkbox.blockSignals(True)
				checkbox.setChecked(checked)
				checkbox.blockSignals(False)
		self.library_playlist_list.blockSignals(False)
		self._update_sync_button()

	def _playlist_selection_changed(self, _checked: bool) -> None:
		selected = len(self._selected_playlist_indexes())
		total = self.library_playlist_list.topLevelItemCount()
		self.select_all.blockSignals(True)
		self.select_all.setChecked(bool(total) and selected == total)
		self.select_all.blockSignals(False)
		self._update_sync_button()

	def _update_sync_button(self) -> None:
		available = bool(self.selected_device and self._selected_playlist_indexes() and not self.worker and not self.playlist_worker)
		self.sync_button.setEnabled(available)

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
		self._update_sync_button()
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
		for playlist in sorted(playlists, key=lambda entry: entry.name.casefold()):
			item = QTreeWidgetItem([playlist.name])
			item.setData(0, Qt.UserRole, playlist.name)
			item.setSizeHint(0, QSize(0, 46))
			self.playlist_list.addTopLevelItem(item)
			card = QFrame()
			card.setObjectName("devicePlaylistCard")
			card.setStyleSheet(
				"QFrame#devicePlaylistCard { background: #c8ddc8; border-top: 2px solid #ffffff; "
				"border-left: 2px solid #ffffff; border-right: 2px solid #404040; border-bottom: 2px solid #404040; }"
			)
			card_layout = QHBoxLayout(card)
			card_layout.setContentsMargins(7, 3, 7, 3)
			card_layout.setSpacing(7)
			icon = QLabel("♫")
			icon.setAlignment(Qt.AlignCenter)
			icon.setFixedSize(32, 32)
			icon.setFont(QFont("Comic Sans MS", 14, QFont.Bold))
			icon.setStyleSheet("background: #606060; color: white; border: 1px inset #404040;")
			name_label = QLabel(playlist.name)
			name_label.setFont(QFont("Comic Sans MS", 10, QFont.Bold))
			name_label.setWordWrap(True)
			name_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
			count_label = QLabel(f"{playlist.track_count}/{playlist.track_count} tracks")
			count_label.setStyleSheet("color: #303030;")
			delete_button = QToolButton()
			delete_button.setText("🗑")
			delete_button.setToolTip(f"Delete playlist '{playlist.name}' from this player")
			delete_button.setAccessibleName(f"Delete playlist {playlist.name}")
			delete_button.setFixedSize(36, 34)
			delete_button.setStyleSheet("QToolButton { background: #c00000; color: white; font-size: 15px; padding: 1px; }")
			delete_button.clicked.connect(lambda _checked=False, name=playlist.name: self._delete_playlist(name))
			card_layout.addWidget(icon)
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
			self._update_sync_button()
			self.eject_button.setEnabled(self.selected_device is not None)

	def _device_scan_status(self, message: str) -> None:
		self.activity.setText(message)

	def _set_sync_locked(self, locked: bool) -> None:
		self.device_combo.setEnabled(not locked)
		self.playlist_list.setEnabled(not locked)
		self.library_playlist_list.setEnabled(not locked)
		self.select_all.setEnabled(not locked)
		self.auto_eject.setEnabled(not locked)
		self.close_button.setEnabled(not locked)
		self.sync_button.setEnabled(not locked and self.selected_device is not None and bool(self._selected_playlist_indexes()))
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
		playlist_indexes = self._selected_playlist_indexes()
		if not playlist_indexes:
			QMessageBox.information(self, "No Playlists Selected", "Select at least one library playlist to sync.")
			return
		playlist_names = [
			str(playlist.get("name") or "Playlist") for index, playlist in enumerate(self.library.get("playlists", []))
			if index in playlist_indexes
		]
		answer = QMessageBox.question(
			self, "Sync Selected Playlists",
			f"Sync {len(playlist_names)} selected playlist(s) to {self.selected_device.name}?\n\n"
			"Incomplete selections will be skipped. Existing device content outside the selected playlists will be preserved.",
			QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
		)
		if answer != QMessageBox.Yes:
			return
		self._set_sync_locked(True)
		self.progress.setRange(0, 100)
		self.progress.setValue(0)
		self.progress.setFormat("Starting sync...")
		self.worker = DeviceSyncWorker(self.selected_device, self.library, playlist_indexes, self)
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
			QMessageBox.critical(self, "iPod Disconnected During Sync", f"{detail}\n\nThe operating system reported:\n{message}")
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
