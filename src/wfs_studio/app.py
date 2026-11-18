"""WFS Studio desktop window."""

from __future__ import annotations

import os
import queue
import signal
import sys
import threading
import time
import zipfile
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QEventLoop, QSize, Qt, QProcess, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QFontMetrics, QIcon, QKeySequence, QPalette, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from wfs_studio import __version__
from wfs_studio.binaries import ensure_binary, installed_binary, repo_root
from wfs_studio.crashlog import install as install_crash_log
from wfs_studio.crashlog import log_failure, log_path
from wfs_studio.copy_job import (
    CopyResult,
    copy_game_data,
    copy_titles,
    game_folder_name,
    planned_game_folders,
    relative_archive_members,
)
from wfs_studio.extract import (
    ExtractRequest,
    append_extract_chunk,
    build_args,
    format_command,
    parse_extract_line,
    recovery_warning,
)
from wfs_studio.gametdb import (
    COVER_TIMEOUT,
    annotate,
    disc_urls,
    download_titles,
    fetch_cover,
    fetch_png,
    index_cover_zip,
    load_database,
    load_zip,
    read_cover_cache,
    read_zip_png,
    remember_cover,
    remember_cover_miss,
)
from wfs_studio.icon import title_icon_png
from wfs_studio.locations import data_dir, license_dir
from wfs_studio.music import MENU_CREDIT, MENU_VOLUME, menu_track, quiet_ffmpeg_logs
from wfs_studio.paths import PathIssue, output_is_nonempty, validate_copy, validate_extract_paths
from wfs_studio.saves import (
    SaveRecord,
    archive_dialog_filter,
    archive_format,
    archive_suffix,
    backup_saves,
    savemii_dir_name,
    scan_saves,
    with_archive_suffix,
    write_save_archive,
)
from wfs_studio.settings import load_settings, save_settings
from wfs_studio.titles import (
    TitleRecord,
    directory_size,
    load_size_cache,
    meta_stamp,
    region_label,
    save_size_cache,
    scan_titles,
)
from wfs_studio.util import format_bytes, progress_permille

CHECK_COL = 0
KIND_COL = 1
NAME_COL = 2
ID_COL = 3
PRODUCT_COL = 4
REGION_COL = 5
SIZE_COL = 6
DB_COL = 7


class ScanWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, source: Path):
        super().__init__()
        self.source = source

    def run(self) -> None:
        try:
            self.succeeded.emit(scan_titles(self.source))
        except Exception as exc:
            log_failure("Scan failed")
            self.failed.emit(str(exc))


class SizeWorker(QThread):
    # Qt's int signal is 32-bit and wraps any title larger than 2 GiB.
    sized = Signal(object)

    def __init__(
        self,
        records: list[TitleRecord],
        cancel: threading.Event,
        cache_path: Path | None = None,
        refresh: bool = False,
    ):
        super().__init__()
        self.records = records
        self.cancel = cancel
        self.cache_path = cache_path
        self.refresh = refresh

    def _measure(self, record: TitleRecord, cache: dict, lock: threading.Lock) -> tuple[str, int] | None:
        if self.cancel.is_set():
            return None
        key = str(record.path)
        stamp = meta_stamp(record.path)
        if not self.refresh and stamp:
            with lock:
                cached = cache.get(key)
            if (
                isinstance(cached, dict)
                and cached.get("stamp") == stamp
                and isinstance(cached.get("size"), int)
            ):
                return key, cached["size"]
        size = directory_size(record.path, self.cancel)
        if size is None or self.cancel.is_set():
            return None
        if self.cache_path is not None and stamp:
            with lock:
                cache[key] = {"size": size, "stamp": stamp}
        return key, size

    def run(self) -> None:
        cache = load_size_cache(self.cache_path) if self.cache_path else {}
        lock = threading.Lock()
        results: queue.Queue[tuple[str, int] | None] = queue.Queue()

        def measure(record: TitleRecord) -> None:
            payload: tuple[str, int] | None = None
            try:
                payload = self._measure(record, cache, lock)
            except Exception:
                log_failure(f"Size measure failed for {record.path}")
            finally:
                results.put(payload)

        workers = min(4, max(1, len(self.records)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for record in self.records:
                pool.submit(measure, record)
            for _ in self.records:
                payload = results.get()
                if payload is not None:
                    self.sized.emit(payload)
        if self.cache_path is not None and not self.cancel.is_set():
            with lock:
                snapshot = dict(cache)
            if snapshot:
                save_size_cache(self.cache_path, snapshot)


class CopyWorker(QThread):
    progress = Signal(object)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        jobs,
        dest: Path,
        skip_same_size: bool,
        cancel: threading.Event,
        game_data: bool = False,
        archive: Path | None = None,
        archive_members: list[str] | None = None,
    ):
        super().__init__()
        self.jobs = jobs
        self.dest = dest
        self.skip_same_size = skip_same_size
        self.cancel = cancel
        self.game_data = game_data
        self.archive = archive
        self.archive_members = archive_members or []
        self.archive_note = ""

    def run(self) -> None:
        try:
            copy = copy_game_data if self.game_data else copy_titles
            result = copy(
                self.jobs,
                self.dest,
                skip_same_size=self.skip_same_size,
                cancel=self.cancel,
                on_progress=self.progress.emit,
            )
            clean = not result.cancelled and not result.halted and not result.errors
            packed = result.verified or not self.game_data
            if self.archive is not None and clean and packed:
                try:
                    written = write_save_archive(self.dest, self.archive_members, self.archive)
                    self.archive_note = f"Archive written to {written}"
                except (OSError, PathIssue) as exc:
                    log_failure("Title archive failed")
                    self.archive_note = f"Archive failed: {exc}"
            self.succeeded.emit(result)
        except Exception as exc:
            log_failure("Copy failed")
            self.failed.emit(str(exc))


class SaveBackupWorker(QThread):
    progress = Signal(object)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        records: list[SaveRecord],
        dest: Path,
        storage: str,
        cancel: threading.Event,
        archive: Path | None = None,
    ):
        super().__init__()
        self.records = records
        self.dest = dest
        self.storage = storage
        self.cancel = cancel
        self.archive = archive
        self.archive_note = ""

    def run(self) -> None:
        try:
            result = backup_saves(
                self.records,
                self.dest,
                storage=self.storage,
                cancel=self.cancel,
                on_progress=self.progress.emit,
            )
            if (
                self.archive is not None
                and result.verified
                and not result.cancelled
                and not result.errors
                and not result.halted
            ):
                names = [
                    savemii_dir_name(record.display_name, record.high_id, record.low_id)
                    for record in self.records
                ]
                try:
                    written = write_save_archive(self.dest, names, self.archive)
                    self.archive_note = f"Archive written to {written}"
                except (OSError, PathIssue) as exc:
                    log_failure("Save archive failed")
                    self.archive_note = f"Archive failed: {exc}"
            self.succeeded.emit(result)
        except Exception as exc:
            log_failure("Save backup failed")
            self.failed.emit(str(exc))


class FetchWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self._fn = fn

    def run(self) -> None:
        try:
            self.succeeded.emit(self._fn())
        except Exception as exc:
            log_failure("Download failed")
            self.failed.emit(str(exc))


class CoverWorker(QThread):
    ready = Signal(int, object)

    def __init__(
        self,
        generation: int,
        urls: list[str],
        cache: Path,
        gametdb_id: str,
        cancel: threading.Event,
    ):
        super().__init__()
        self.generation = generation
        self.urls = urls
        self.cache = cache
        self.gametdb_id = gametdb_id
        self.cancel = cancel

    def run(self) -> None:
        try:
            self._fetch()
        except Exception:
            log_failure("Cover download failed")
            self.ready.emit(self.generation, None)

    def _fetch(self) -> None:
        status, data = read_cover_cache(self.cache, self.gametdb_id)
        if status == "hit":
            self.ready.emit(self.generation, data)
            return
        if status == "miss":
            self.ready.emit(self.generation, None)
            return
        kind, downloaded = fetch_cover(self.urls, fetch_png, COVER_TIMEOUT, self.cancel)
        if kind == "png" and downloaded:
            remember_cover(self.cache, self.gametdb_id, downloaded)
            self.ready.emit(self.generation, downloaded)
            return
        if kind == "missing" and not self.cancel.is_set():
            remember_cover_miss(self.cache, self.gametdb_id)
        self.ready.emit(self.generation, None)


class SizeItem(QTableWidgetItem):
    def __lt__(self, other: QTableWidgetItem) -> bool:
        left = self.data(Qt.ItemDataRole.UserRole)
        right = other.data(Qt.ItemDataRole.UserRole)
        return (left if isinstance(left, int) else -1) < (right if isinstance(right, int) else -1)


class MainWindow(QMainWindow):
    def __init__(self, root: Path | None = None, data: Path | None = None):
        super().__init__()
        self.root = root or repo_root()
        self.data = data if data is not None else data_dir(self.root)
        self.settings = load_settings(self.data)
        self.records: list[TitleRecord] = []
        self.sizes: dict[str, int] = {}
        self.database = load_database(self.data / "cache", self.settings.get("gametdb_zip"))
        self._cover_index: dict[str, str] = {}
        self._index_cover_zip()
        self._cancel_sizes = threading.Event()
        self._cancel_copy = threading.Event()
        self._cancel_covers = threading.Event()
        self._sizing = False
        self._size_done = 0
        self._size_total = 0
        self._size_generation = 0
        self._closing = False
        self._busy = False
        self._process: QProcess | None = None
        self._extract_buffer = ""
        self._files_started = 0
        self._cover_generation = 0
        self._last_copy_was_game_data = False
        self._cancel_saves = threading.Event()
        self.save_records: list[SaveRecord] = []
        self._save_archive: Path | None = None
        self._save_archive_declined = False
        self._title_archive: Path | None = None
        self._title_archive_declined = False
        self._workers: list[QThread] = []
        self._player = None
        self._audio = None
        self._releasing_music = False
        self.setWindowTitle("WFS Studio")
        self.resize(1180, 760)
        self._build()
        self._load_fields()
        self._refresh_binary_label()
        self._refresh_db_label()
        self._refresh_command()
        self.menu_music_action.toggled.connect(self._on_menu_music)
        if self.menu_music_action.isChecked():
            self._start_menu_music()

    def _build(self) -> None:
        shell = QWidget()
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)
        version = QLabel(f"v{__version__}")
        version.setObjectName("version")
        version.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        shell_layout.addWidget(version, 0, Qt.AlignmentFlag.AlignRight)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_titles_tab(), "Titles")
        self.tabs.addTab(self._build_saves_tab(), "Saves")
        self.tabs.addTab(self._build_extract_tab(), "Extract")
        shell_layout.addWidget(self.tabs, 1)
        self.setCentralWidget(shell)
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Ready")

        file_menu = self.menuBar().addMenu("File")
        self.menu_music_action = QAction("Menu music", self)
        self.menu_music_action.setCheckable(True)
        file_menu.addAction(self.menu_music_action)
        file_menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        edit_menu = self.menuBar().addMenu("Edit")
        self.select_all_action = QAction("Select all", self)
        self.select_all_action.triggered.connect(self._select_all_on_tab)
        edit_menu.addAction(self.select_all_action)
        self._bind_select_all(self.table, self._select_all_titles)
        self._bind_select_all(self.save_table, self._select_all_saves)

        help_menu = self.menuBar().addMenu("Help")
        about_action = QAction("About WFS Studio", self)
        about_action.triggered.connect(self._about)
        help_menu.addAction(about_action)

    def _build_titles_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        source_row = QHBoxLayout()
        self.source_edit = QLineEdit()
        self.source_edit.setPlaceholderText("Extracted dump, usr/title folder, or one title folder")
        source_button = QPushButton("Browse")
        source_button.clicked.connect(self._browse_source)
        self.scan_button = QPushButton("Scan")
        self.scan_button.setObjectName("primary")
        self.scan_button.clicked.connect(self._scan)
        source_row.addWidget(QLabel("Source"))
        source_row.addWidget(self.source_edit, 1)
        source_row.addWidget(source_button)
        source_row.addWidget(self.scan_button)
        layout.addLayout(source_row)

        filter_row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Filter by name, title ID, or product code")
        self.search_edit.textChanged.connect(self._apply_filter)
        self.db_label = QLabel()
        self.db_button = QPushButton("Download GameTDB")
        self.db_button.clicked.connect(self._download_db)
        self.zip_button = QPushButton("Open zip")
        self.zip_button.clicked.connect(self._open_db_zip)
        self.banner_button = QPushButton("Banner zip")
        self.banner_button.clicked.connect(self._open_banner_zip)
        filter_row.addWidget(QLabel("Search"))
        filter_row.addWidget(self.search_edit, 1)
        filter_row.addWidget(self.db_label)
        filter_row.addWidget(self.db_button)
        filter_row.addWidget(self.zip_button)
        filter_row.addWidget(self.banner_button)
        layout.addLayout(filter_row)

        body = QSplitter(Qt.Orientation.Horizontal)
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["", "Kind", "Name", "Title ID", "Product", "Region", "Size", "GameTDB"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.currentCellChanged.connect(lambda *_args: self._show_details())
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(NAME_COL, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(DB_COL, QHeaderView.ResizeMode.Stretch)
        for column in (CHECK_COL, KIND_COL, REGION_COL, SIZE_COL):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setIconSize(QSize(32, 32))
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.setSortingEnabled(True)
        body.addWidget(self.table)

        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        self.cover_label = QLabel("No disc image")
        self.cover_label.setObjectName("cover")
        self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_label.setFixedSize(180, 180)
        detail_layout.addWidget(self.cover_label, 0, Qt.AlignmentFlag.AlignHCenter)
        self.detail_label = QLabel("Scan a source folder to list titles.")
        self.detail_label.setWordWrap(True)
        detail_layout.addWidget(self.detail_label)
        detail_layout.addStretch(1)
        body.addWidget(detail)
        body.setStretchFactor(0, 4)
        body.setStretchFactor(1, 1)
        layout.addWidget(body, 1)

        check_row = QHBoxLayout()
        select_all_button = QPushButton("Select all")
        select_all_button.clicked.connect(self._select_all_titles)
        all_button = QPushButton("Check visible")
        all_button.clicked.connect(lambda: self._set_visible_checks(True))
        none_button = QPushButton("Uncheck visible")
        none_button.clicked.connect(lambda: self._set_visible_checks(False))
        self.checked_label = QLabel("0 checked")
        self.recount_button = QPushButton("Recount sizes")
        self.recount_button.clicked.connect(self._recount_sizes)
        check_row.addWidget(select_all_button)
        check_row.addWidget(all_button)
        check_row.addWidget(none_button)
        check_row.addWidget(self.checked_label)
        check_row.addStretch(1)
        check_row.addWidget(self.recount_button)
        layout.addLayout(check_row)

        dest_row = QHBoxLayout()
        self.dest_edit = QLineEdit()
        self.dest_edit.setPlaceholderText("Folder that will receive the copy")
        dest_button = QPushButton("Browse")
        dest_button.clicked.connect(self._browse_dest)
        dest_row.addWidget(QLabel("Destination"))
        dest_row.addWidget(self.dest_edit, 1)
        dest_row.addWidget(dest_button)
        layout.addLayout(dest_row)

        self.skip_box = QCheckBox("Skip files that already exist with the same size")
        self.skip_box.setChecked(True)
        layout.addWidget(self.skip_box)
        self.game_data_box = QCheckBox("Game data copy: one named folder per title, saves left behind")
        self.game_data_box.setChecked(True)
        layout.addWidget(self.game_data_box)

        action_row = QHBoxLayout()
        self.copy_button = QPushButton("Transfer")
        self.copy_button.setObjectName("primary")
        self.copy_button.clicked.connect(self._start_copy)
        self.cancel_copy_button = QPushButton("Stop")
        self.cancel_copy_button.setEnabled(False)
        self.cancel_copy_button.clicked.connect(self._stop_copy)
        action_row.addWidget(self.copy_button)
        action_row.addWidget(self.cancel_copy_button)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        self.copy_progress = QProgressBar()
        self.copy_progress.setRange(0, 1000)
        self.copy_progress.setValue(0)
        self.copy_progress.setFormat("%p%")
        layout.addWidget(self.copy_progress)
        self.copy_label = QLabel("Idle")
        self.copy_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.copy_label)
        self.copy_log = QPlainTextEdit()
        self.copy_log.setReadOnly(True)
        self.copy_log.setMaximumBlockCount(500)
        self.copy_log.setPlaceholderText("Copy log")
        self.copy_log.setFixedHeight(110)
        layout.addWidget(self.copy_log)
        return page

    def _build_saves_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        intro = QLabel(
            "Copies usr/save into SaveMii folders on this computer. "
            "The dump is not changed, and save contents are not edited. "
            "Copy the backup folder to sd:/wiiu/backups when you want SaveMii to restore it."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.save_table = QTableWidget(0, 4)
        self.save_table.setHorizontalHeaderLabels(["", "Name", "Title ID", "Profiles"])
        self.save_table.verticalHeader().setVisible(False)
        self.save_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.save_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.save_table.itemChanged.connect(self._on_save_check_changed)
        header = self.save_table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.save_table, 1)

        dest_row = QHBoxLayout()
        self.save_dest_edit = QLineEdit()
        self.save_dest_edit.setPlaceholderText("PC folder that will hold the SaveMii backups")
        browse = QPushButton("Browse")
        browse.clicked.connect(self._browse_save_dest)
        dest_row.addWidget(QLabel("Backup folder"))
        dest_row.addWidget(self.save_dest_edit, 1)
        dest_row.addWidget(browse)
        layout.addLayout(dest_row)

        self.save_usb_box = QCheckBox("This dump came from a USB drive (SaveMii will show USB instead of NAND)")
        layout.addWidget(self.save_usb_box)

        action_row = QHBoxLayout()
        self.save_scan_button = QPushButton("Scan saves")
        self.save_scan_button.clicked.connect(self._scan_saves)
        self.save_all_button = QPushButton("Select all")
        self.save_all_button.clicked.connect(self._select_all_saves)
        self.save_backup_button = QPushButton("Back up checked")
        self.save_backup_button.setObjectName("primary")
        self.save_backup_button.clicked.connect(self._start_save_backup)
        self.save_stop_button = QPushButton("Stop")
        self.save_stop_button.setEnabled(False)
        self.save_stop_button.clicked.connect(lambda: self._cancel_saves.set())
        action_row.addWidget(self.save_scan_button)
        action_row.addWidget(self.save_all_button)
        action_row.addWidget(self.save_backup_button)
        action_row.addWidget(self.save_stop_button)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        self.save_progress = QProgressBar()
        self.save_progress.setRange(0, 1000)
        self.save_progress.setValue(0)
        self.save_progress.setFormat("%p%")
        layout.addWidget(self.save_progress)
        self.save_label = QLabel("Idle")
        self.save_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.save_label)
        self.save_log = QPlainTextEdit()
        self.save_log.setReadOnly(True)
        self.save_log.setMaximumBlockCount(500)
        self.save_log.setFixedHeight(110)
        layout.addWidget(self.save_log)
        return page

    def _browse_save_dest(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Save backup folder", self.save_dest_edit.text())
        if chosen:
            self.save_dest_edit.setText(chosen)
            self._persist()

    def _scan_saves(self) -> None:
        source = self.source_edit.text().strip()
        if not source:
            self._warn("Choose a source folder on the Titles tab first.")
            return
        self._persist()
        self._save_archive = None
        self._save_archive_declined = False
        self.save_records = scan_saves(Path(source), self.database)
        self.save_table.setRowCount(len(self.save_records))
        for row, record in enumerate(self.save_records):
            check = QTableWidgetItem()
            check.setFlags(
                Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable
            )
            check.setCheckState(Qt.CheckState.Unchecked)
            self.save_table.setItem(row, 0, check)
            self.save_table.setItem(row, 1, QTableWidgetItem(record.display_name))
            self.save_table.setItem(row, 2, QTableWidgetItem(record.title_id))
            profiles = ", ".join(record.profiles)
            if record.has_common:
                profiles = f"{profiles}, common" if profiles else "common"
            self.save_table.setItem(row, 3, QTableWidgetItem(profiles or "none"))
        count = len(self.save_records)
        message = f"{count} saves" if count else f"No saves in {source}"
        self.save_label.setText(message)
        self.statusBar().showMessage(message)

    def _set_save_checks(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self.save_table.blockSignals(True)
        try:
            for row in range(self.save_table.rowCount()):
                item = self.save_table.item(row, 0)
                if item is not None:
                    item.setCheckState(state)
        finally:
            self.save_table.blockSignals(False)

    def _all_saves_checked(self) -> bool:
        return bool(self.save_records) and len(self._checked_saves()) == len(self.save_records)

    def _select_all_saves(self) -> None:
        if not self.save_records:
            self._warn("Scan saves first.")
            return
        self._save_archive = None
        self._save_archive_declined = False
        self._set_save_checks(True)
        self._offer_save_archive()

    def _on_save_check_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != 0 or item.checkState() != Qt.CheckState.Checked:
            return
        if self._all_saves_checked():
            self._offer_save_archive()

    def _offer_save_archive(self) -> None:
        if self._save_archive is not None or self._save_archive_declined:
            return
        count = len(self.save_records)
        answer = QMessageBox.question(
            self,
            "Archive saves",
            f"All {count} saves are selected. Write them into an archive?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            self._save_archive_declined = True
            return
        fmt = archive_format()
        suggested = Path.home() / f"WFS Studio saves{archive_suffix(fmt)}"
        dest_text = self.save_dest_edit.text().strip()
        if dest_text:
            suggested = Path(dest_text).expanduser().parent / suggested.name
        chosen, _selected = QFileDialog.getSaveFileName(
            self,
            "Save archive",
            str(suggested),
            archive_dialog_filter(fmt),
        )
        if not chosen:
            self._save_archive_declined = True
            return
        self._save_archive = with_archive_suffix(Path(chosen), fmt)

    def _checked_saves(self) -> list[SaveRecord]:
        chosen: list[SaveRecord] = []
        for row, record in enumerate(self.save_records):
            item = self.save_table.item(row, 0)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                chosen.append(record)
        return chosen

    def _start_save_backup(self) -> None:
        if self._busy:
            self._warn("Wait for the current job to finish.")
            return
        chosen = self._checked_saves()
        if not chosen:
            self._warn("Check at least one save.")
            return
        dest_text = self.save_dest_edit.text().strip()
        if not dest_text:
            self._warn("Choose a backup folder.")
            return
        self._persist()
        storage = "USB" if self.save_usb_box.isChecked() else "NAND"
        archive = self._save_archive if len(chosen) == len(self.save_records) else None
        if archive is None and self._all_saves_checked() and not self._save_archive_declined:
            self._offer_save_archive()
            archive = self._save_archive
        message = (
            f"Back up {len(chosen)} saves into {dest_text}?\n\n"
            "Files are copied only. The dump is not changed."
        )
        if archive is not None:
            message += f"\n\nAn archive will also be written to {archive}."
        answer = QMessageBox.question(self, "Back up saves", message)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._busy = True
        self._cancel_saves = threading.Event()
        self.save_backup_button.setEnabled(False)
        self.save_stop_button.setEnabled(True)
        self.save_progress.setValue(0)
        self.save_log.clear()
        self.save_label.setText("Starting")
        worker = SaveBackupWorker(chosen, Path(dest_text), storage, self._cancel_saves, archive)
        worker.progress.connect(self._save_progress)
        worker.succeeded.connect(self._save_finished)
        worker.failed.connect(self._save_failed)
        self._track(worker)

    def _save_progress(self, progress) -> None:
        if self._closing:
            return
        self.save_progress.setValue(progress_permille(progress.copied_bytes, progress.total_bytes))
        self.save_label.setText(f"{format_bytes(progress.copied_bytes)} · {progress.current_path}")

    def _save_finished(self, result: CopyResult) -> None:
        self._busy = False
        if self._closing:
            return
        self.save_backup_button.setEnabled(True)
        self.save_stop_button.setEnabled(False)
        if result.cancelled:
            self.save_label.setText("Stopped. Files already written were left in the backup folder.")
        elif result.verified and not result.errors:
            self.save_progress.setValue(1000 if result.total_bytes else 0)
            self.save_label.setText(
                f"Finished. Wrote {result.files_written}, skipped {result.files_skipped}."
            )
            self.save_log.appendPlainText("SaveMii folders match the source file count and byte total.")
            note = getattr(self.sender(), "archive_note", "")
            if note:
                self.save_log.appendPlainText(note)
        else:
            self.save_label.setText(result.halted or "Backup finished with errors.")
            for error in result.errors:
                self.save_log.appendPlainText(error)
        self.statusBar().showMessage("Save backup finished")

    def _save_failed(self, message: str) -> None:
        self._busy = False
        if self._closing:
            return
        self.save_backup_button.setEnabled(True)
        self.save_stop_button.setEnabled(False)
        self.save_label.setText("Backup failed")
        self.save_log.appendPlainText(message)
        self._warn(message)

    def _build_extract_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        intro = QLabel(
            "Runs the official wfs-extract. It reads the input image or device and writes "
            "files into the output folder. The input is not modified. SLC and SLCCMPT images "
            "are not WFS, so this tool cannot open them."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        binary_row = QHBoxLayout()
        self.binary_label = QLabel()
        self.binary_label.setWordWrap(True)
        self.binary_button = QPushButton("Download wfs-tools v1.2.3")
        self.binary_button.clicked.connect(self._download_binary)
        binary_row.addWidget(self.binary_label, 1)
        binary_row.addWidget(self.binary_button)
        layout.addLayout(binary_row)

        form_host = QWidget()
        form = QFormLayout(form_host)
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("mlc image, USB image, or a device path such as /dev/disk4")
        self.input_edit.textChanged.connect(self._refresh_command)
        form.addRow("Input", self._path_row(self.input_edit, self._browse_input, file_mode=True))

        type_row = QHBoxLayout()
        self.type_group = QButtonGroup(self)
        self.usb_radio = QRadioButton("usb")
        self.mlc_radio = QRadioButton("mlc")
        self.plain_radio = QRadioButton("plain")
        for radio in (self.usb_radio, self.mlc_radio, self.plain_radio):
            self.type_group.addButton(radio)
            type_row.addWidget(radio)
        type_row.addStretch(1)
        form.addRow("Type", type_row)

        self.otp_edit = QLineEdit()
        self.otp_edit.setPlaceholderText("otp.bin from this console")
        self.otp_edit.textChanged.connect(self._refresh_command)
        form.addRow("otp.bin", self._path_row(self.otp_edit, self._browse_otp, file_mode=True))

        self.seeprom_edit = QLineEdit()
        self.seeprom_edit.setPlaceholderText("seeprom.bin, required for USB")
        self.seeprom_edit.textChanged.connect(self._refresh_command)
        form.addRow("seeprom.bin", self._path_row(self.seeprom_edit, self._browse_seeprom, file_mode=True))
        for radio in (self.usb_radio, self.mlc_radio, self.plain_radio):
            radio.toggled.connect(self._on_type_changed)
        self.mlc_radio.setChecked(True)

        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("Empty folder for the extracted files")
        self.output_edit.textChanged.connect(self._refresh_command)
        form.addRow("Output", self._path_row(self.output_edit, self._browse_output, file_mode=False))

        self.dump_edit = QLineEdit("/")
        self.dump_edit.textChanged.connect(self._refresh_command)
        form.addRow("Dump path", self.dump_edit)

        self.recovery_box = QCheckBox("Recovery mode (--dump-usr-dir). Use this when the WFS header is damaged.")
        self.recovery_box.toggled.connect(self._refresh_command)
        form.addRow("", self.recovery_box)
        layout.addWidget(form_host)

        self.command_preview = QPlainTextEdit()
        self.command_preview.setReadOnly(True)
        self.command_preview.setFixedHeight(70)
        layout.addWidget(self.command_preview)

        action_row = QHBoxLayout()
        self.extract_button = QPushButton("Start extract")
        self.extract_button.setObjectName("primary")
        self.extract_button.clicked.connect(self._start_extract)
        self.cancel_extract_button = QPushButton("Stop")
        self.cancel_extract_button.setEnabled(False)
        self.cancel_extract_button.clicked.connect(self._stop_extract)
        action_row.addWidget(self.extract_button)
        action_row.addWidget(self.cancel_extract_button)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        self.extract_progress = QProgressBar()
        self.extract_progress.setRange(0, 0)
        self.extract_progress.setValue(0)
        self.extract_progress.setTextVisible(False)
        layout.addWidget(self.extract_progress)
        self.extract_label = QLabel("Idle. Official wfs-extract reports the file name, not a byte total.")
        self.extract_label.setWordWrap(True)
        self.extract_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.extract_label)

        self.extract_log = QPlainTextEdit()
        self.extract_log.setReadOnly(True)
        self.extract_log.setMaximumBlockCount(2000)
        layout.addWidget(self.extract_log, 1)
        return page

    def _path_row(self, edit: QLineEdit, handler, file_mode: bool) -> QWidget:
        del file_mode
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        button = QPushButton("Browse")
        button.clicked.connect(handler)
        layout.addWidget(edit, 1)
        layout.addWidget(button)
        return row

    def _load_fields(self) -> None:
        self.source_edit.setText(self.settings["source"])
        self.dest_edit.setText(self.settings["dest"])
        self.skip_box.setChecked(bool(self.settings["skip_same_size"]))
        self.game_data_box.setChecked(bool(self.settings["game_data_copy"]))
        self.input_edit.setText(self.settings["input"])
        self.otp_edit.setText(self.settings["otp"])
        self.seeprom_edit.setText(self.settings["seeprom"])
        self.output_edit.setText(self.settings["output"])
        self.dump_edit.setText(self.settings["dump_path"] or "/")
        self.recovery_box.setChecked(bool(self.settings["dump_usr_dir"]))
        self.save_dest_edit.setText(self.settings["save_dest"])
        self.save_usb_box.setChecked(bool(self.settings["save_usb"]))
        self.menu_music_action.setChecked(bool(self.settings.get("menu_music", True)))
        kind = self.settings["extract_type"]
        {"usb": self.usb_radio, "mlc": self.mlc_radio, "plain": self.plain_radio}.get(
            kind, self.mlc_radio
        ).setChecked(True)
        self._on_type_changed()

    def _collect_settings(self) -> dict:
        return {
            "source": self.source_edit.text().strip(),
            "dest": self.dest_edit.text().strip(),
            "skip_same_size": self.skip_box.isChecked(),
            "game_data_copy": self.game_data_box.isChecked(),
            "save_dest": self.save_dest_edit.text().strip(),
            "save_usb": self.save_usb_box.isChecked(),
            "input": self.input_edit.text().strip(),
            "extract_type": self._image_type(),
            "otp": self.otp_edit.text().strip(),
            "seeprom": self.seeprom_edit.text().strip(),
            "output": self.output_edit.text().strip(),
            "dump_path": self.dump_edit.text().strip() or "/",
            "dump_usr_dir": self.recovery_box.isChecked(),
            "gametdb_zip": self.settings.get("gametdb_zip", ""),
            "cover_zip": self.settings.get("cover_zip", ""),
            "menu_music": self.menu_music_action.isChecked(),
        }

    def _persist(self) -> None:
        self.settings = self._collect_settings()
        save_settings(self.data, self.settings)

    def _image_type(self) -> str:
        if self.usb_radio.isChecked():
            return "usb"
        if self.plain_radio.isChecked():
            return "plain"
        return "mlc"

    def _on_type_changed(self) -> None:
        if not hasattr(self, "otp_edit"):
            return
        image_type = self._image_type()
        self.otp_edit.setEnabled(image_type != "plain")
        self.seeprom_edit.setEnabled(image_type == "usb")
        self._refresh_command()

    def _browse_source(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Source folder", self.source_edit.text())
        if path:
            self.source_edit.setText(path)

    def _browse_dest(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Destination folder", self.dest_edit.text())
        if path:
            self.dest_edit.setText(path)

    def _browse_input(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(self, "WFS image", self.input_edit.text(), "All files (*)")
        if path:
            self.input_edit.setText(path)

    def _browse_otp(self) -> None:
        self._browse_key(self.otp_edit, "otp.bin")

    def _browse_seeprom(self) -> None:
        self._browse_key(self.seeprom_edit, "seeprom.bin")

    def _browse_key(self, edit: QLineEdit, title: str) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, title, edit.text(), "Key files (*.bin);;All files (*)"
        )
        if path:
            edit.setText(path)

    def _browse_output(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Output folder", self.output_edit.text())
        if path:
            self.output_edit.setText(path)

    def _track(self, worker: QThread) -> None:
        self._workers.append(worker)
        worker.finished.connect(lambda worker=worker: self._drop_worker(worker))
        worker.start()

    def _drop_worker(self, worker: QThread) -> None:
        if worker in self._workers:
            self._workers.remove(worker)

    def _scan(self) -> None:
        source = self.source_edit.text().strip()
        if not source:
            self._warn("Choose a source folder first.")
            return
        self._persist()
        self.scan_button.setEnabled(False)
        self._cancel_sizes.set()
        self.statusBar().showMessage("Scanning titles")
        worker = ScanWorker(Path(source))
        worker.succeeded.connect(self._scan_finished)
        worker.failed.connect(self._scan_failed)
        self._track(worker)

    def _scan_failed(self, message: str) -> None:
        self.scan_button.setEnabled(True)
        if self._closing:
            return
        self.statusBar().showMessage("Scan failed")
        self._warn(message)

    def _scan_finished(self, records: list[TitleRecord]) -> None:
        if self._closing:
            return
        self.scan_button.setEnabled(True)
        self.records = annotate(records, self.database)
        self.sizes.clear()
        self._title_archive = None
        self._title_archive_declined = False
        self._fill_table()
        self.statusBar().showMessage(f"{len(self.records)} titles")
        if not self.records:
            self.detail_label.setText(
                "No title folders found. Point the source at a dump that contains usr/title, "
                "or at a single title folder with meta/meta.xml."
            )
            return
        self._start_sizing(refresh=False)

    def _recount_sizes(self) -> None:
        if self._closing:
            return
        if not self.records:
            self._warn("Scan a source folder first.")
            return
        for row in range(self.table.rowCount()):
            size_item = self.table.item(row, SIZE_COL)
            if isinstance(size_item, QTableWidgetItem):
                self.table.blockSignals(True)
                size_item.setText("…")
                size_item.setData(Qt.ItemDataRole.UserRole, -1)
                self.table.blockSignals(False)
        self.sizes.clear()
        self._update_checked_label()
        self._start_sizing(refresh=True)

    def _start_sizing(self, refresh: bool) -> None:
        self._cancel_sizes.set()
        self._cancel_sizes = threading.Event()
        self._sizing = True
        self._size_done = 0
        self._size_total = len(self.records)
        self._size_generation += 1
        generation = self._size_generation
        self.statusBar().showMessage(f"Sizing 0 of {self._size_total}")
        worker = SizeWorker(
            list(self.records),
            self._cancel_sizes,
            cache_path=self.data / "cache" / "title-sizes.json",
            refresh=refresh,
        )
        worker.sized.connect(lambda payload, generation=generation: self._size_ready(payload, generation))
        self._track(worker)

    def _fill_table(self) -> None:
        self.table.setSortingEnabled(False)
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.records))
        for row, record in enumerate(self.records):
            check = QTableWidgetItem()
            check.setFlags(
                Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
            )
            check.setCheckState(Qt.CheckState.Unchecked)
            check.setData(Qt.ItemDataRole.UserRole, row)
            self.table.setItem(row, CHECK_COL, check)
            kind = QTableWidgetItem(record.kind)
            kind.setData(Qt.ItemDataRole.UserRole, row)
            self.table.setItem(row, KIND_COL, kind)
            name = QTableWidgetItem(record.name)
            name.setData(Qt.ItemDataRole.UserRole, str(record.path))
            icon = self._list_icon(record)
            if not icon.isNull():
                name.setIcon(icon)
            self.table.setItem(row, NAME_COL, name)
            self.table.setItem(row, ID_COL, QTableWidgetItem(record.title_id))
            self.table.setItem(row, PRODUCT_COL, QTableWidgetItem(record.product_code))
            self.table.setItem(row, REGION_COL, QTableWidgetItem(region_label(record.region)))
            size_item = SizeItem("…")
            size_item.setData(Qt.ItemDataRole.UserRole, -1)
            self.table.setItem(row, SIZE_COL, size_item)
            self.table.setItem(row, DB_COL, QTableWidgetItem(record.gametdb_name))
        self.table.blockSignals(False)
        self.table.setSortingEnabled(True)
        self._update_checked_label()
        self._apply_filter()

    def _list_icon(self, record: TitleRecord) -> QIcon:
        png = title_icon_png(record.path / "meta" / "iconTex.tga")
        if not png:
            return QIcon()
        pixmap = QPixmap()
        if not pixmap.loadFromData(png):
            return QIcon()
        return QIcon(pixmap)

    def _record_for_row(self, row: int) -> TitleRecord | None:
        item = self.table.item(row, NAME_COL)
        if item is None:
            return None
        path = item.data(Qt.ItemDataRole.UserRole)
        for record in self.records:
            if str(record.path) == path:
                return record
        return None

    def _size_ready(self, payload: object, generation: int | None = None) -> None:
        if generation is not None and generation != self._size_generation:
            return
        if self._closing or not isinstance(payload, tuple) or len(payload) != 2:
            return
        path, size = payload
        if not isinstance(path, str) or not isinstance(size, int) or size < 0:
            return
        self.sizes[path] = size
        if self._sizing:
            self._size_done += 1
            if self._size_done >= self._size_total:
                self._sizing = False
                self.statusBar().showMessage(f"{len(self.records)} titles")
            else:
                self.statusBar().showMessage(f"Sizing {self._size_done} of {self._size_total}")
        for row in range(self.table.rowCount()):
            item = self.table.item(row, NAME_COL)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == path:
                size_item = self.table.item(row, SIZE_COL)
                if isinstance(size_item, QTableWidgetItem):
                    self.table.blockSignals(True)
                    sorting = self.table.isSortingEnabled()
                    self.table.setSortingEnabled(False)
                    size_item.setText(format_bytes(size))
                    size_item.setData(Qt.ItemDataRole.UserRole, size)
                    self.table.setSortingEnabled(sorting)
                    self.table.blockSignals(False)
                break
        self._update_checked_label()

    def _apply_filter(self) -> None:
        query = self.search_edit.text().strip().lower()
        for row in range(self.table.rowCount()):
            if not query:
                self.table.setRowHidden(row, False)
                continue
            values = []
            for column in (NAME_COL, ID_COL, PRODUCT_COL, DB_COL, KIND_COL):
                item = self.table.item(row, column)
                values.append(item.text().lower() if item is not None else "")
            self.table.setRowHidden(row, not any(query in value for value in values))

    def _bind_select_all(self, widget: QWidget, handler) -> None:
        shortcut = QShortcut(QKeySequence.StandardKey.SelectAll, widget)
        shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        shortcut.activated.connect(handler)

    def _select_all_on_tab(self) -> None:
        """Edit → Select all for the tab in front.

        Titles checks every title, including rows hidden by the filter.
        Saves checks every save. Extract selects the whole log. A text field
        keeps its own Select all key.
        """
        page = self.tabs.currentIndex()
        if page == 0:
            self._select_all_titles()
        elif page == 1:
            self._select_all_saves()
        else:
            self.extract_log.selectAll()
            self.extract_log.setFocus()

    def _select_all_titles(self) -> None:
        if not self.records:
            self._warn("Scan a source folder first.")
            return
        self._title_archive = None
        self._title_archive_declined = False
        self.table.blockSignals(True)
        for row in range(self.table.rowCount()):
            item = self.table.item(row, CHECK_COL)
            if item is not None:
                item.setCheckState(Qt.CheckState.Checked)
        self.table.blockSignals(False)
        self._update_checked_label()
        self._offer_title_archive()

    def _set_visible_checks(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self.table.blockSignals(True)
        for row in range(self.table.rowCount()):
            if self.table.isRowHidden(row):
                continue
            item = self.table.item(row, CHECK_COL)
            if item is not None:
                item.setCheckState(state)
        self.table.blockSignals(False)
        self._update_checked_label()
        if checked and self._all_titles_checked():
            self._title_archive = None
            self._title_archive_declined = False
            self._offer_title_archive()

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != CHECK_COL:
            return
        self._update_checked_label()
        if item.checkState() == Qt.CheckState.Checked and self._all_titles_checked():
            self._offer_title_archive()

    def _all_titles_checked(self) -> bool:
        return bool(self.records) and len(self._checked_records()) == len(self.records)

    def _offer_title_archive(self) -> None:
        if self._title_archive is not None or self._title_archive_declined:
            return
        count = len(self.records)
        answer = QMessageBox.question(
            self,
            "Archive titles",
            f"All {count} titles are selected. Write them into an archive?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            self._title_archive_declined = True
            return
        fmt = archive_format()
        suggested = Path.home() / f"WFS Studio titles{archive_suffix(fmt)}"
        dest_text = self.dest_edit.text().strip()
        if dest_text:
            suggested = Path(dest_text).expanduser().parent / suggested.name
        chosen, _selected = QFileDialog.getSaveFileName(
            self,
            "Title archive",
            str(suggested),
            archive_dialog_filter(fmt),
        )
        if not chosen:
            self._title_archive_declined = True
            return
        self._title_archive = with_archive_suffix(Path(chosen), fmt)

    def _checked_records(self) -> list[TitleRecord]:
        chosen: list[TitleRecord] = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, CHECK_COL)
            if item is None or item.checkState() != Qt.CheckState.Checked:
                continue
            record = self._record_for_row(row)
            if record is not None:
                chosen.append(record)
        return chosen

    def _update_checked_label(self) -> None:
        count = len(self._checked_records())
        known = [self.sizes[str(record.path)] for record in self._checked_records() if str(record.path) in self.sizes]
        if known and len(known) == count:
            self.checked_label.setText(f"{count} checked · {format_bytes(sum(known))}")
        else:
            self.checked_label.setText(f"{count} checked")

    def _show_details(self) -> None:
        row = self.table.currentRow()
        record = self._record_for_row(row) if row >= 0 else None
        if record is None:
            self.detail_label.setText("Select a title.")
            self.cover_label.setText("No disc image")
            self.cover_label.setPixmap(QPixmap())
            return
        lines = [
            record.name,
            record.title_id,
            record.product_code or "No product code",
            f"{record.kind} · {region_label(record.region) or 'region unknown'} · version {record.version or '?'}",
        ]
        if record.publisher:
            lines.append(record.publisher)
        if record.gametdb_id:
            lines.append(f"GameTDB {record.gametdb_id}: {record.gametdb_name}")
            info = self.database.info.get(record.gametdb_id) if self.database is not None else None
            if info is not None:
                credits = " · ".join(part for part in (info.developer, info.publisher) if part)
                if credits:
                    lines.append(credits)
                facts = " · ".join(part for part in (info.date, info.genre, info.region) if part)
                if facts:
                    lines.append(facts)
        elif self.database is not None and record.product_code:
            lines.append("No GameTDB match for this product code.")
        lines.append(str(record.path))
        self.detail_label.setText("\n".join(lines))
        self._load_cover(record)

    def _load_cover(self, record: TitleRecord) -> None:
        if self._closing:
            return
        self._cancel_covers.set()
        self._cancel_covers = threading.Event()
        self._cover_generation += 1
        generation = self._cover_generation
        self.cover_label.setPixmap(QPixmap())
        if record.gametdb_id:
            banner = self._banner_from_zip(record.gametdb_id)
            if banner is not None and self._show_cover(banner):
                return
            status, data = read_cover_cache(self.data / "cache", record.gametdb_id)
            if status == "hit" and isinstance(data, (bytes, bytearray)) and self._show_cover(data):
                return
            if status != "miss":
                if not self._show_title_icon(record):
                    self.cover_label.setText("Loading disc")
                worker = CoverWorker(
                    generation,
                    disc_urls(record.gametdb_id, record.region),
                    self.data / "cache",
                    record.gametdb_id,
                    self._cancel_covers,
                )
                worker.ready.connect(self._cover_ready)
                self._track(worker)
                return
        if not self._show_title_icon(record):
            self.cover_label.setText("No disc image")

    def _show_title_icon(self, record: TitleRecord) -> bool:
        png = title_icon_png(record.path / "meta" / "iconTex.tga")
        return png is not None and self._show_cover(png)

    def _show_cover(self, data: bytes | bytearray) -> bool:
        pixmap = QPixmap()
        if not pixmap.loadFromData(bytes(data)):
            self.cover_label.setText("No disc image")
            self.cover_label.setPixmap(QPixmap())
            return False
        scaled = pixmap.scaled(
            self.cover_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        if scaled.isNull():
            scaled = pixmap
        self.cover_label.setText("")
        self.cover_label.setPixmap(scaled)
        return True

    def _cover_ready(self, generation: int, data: object) -> None:
        if self._closing or generation != self._cover_generation:
            return
        if isinstance(data, (bytes, bytearray)) and self._show_cover(data):
            return
        row = self.table.currentRow()
        record = self._record_for_row(row) if row >= 0 else None
        if record is not None and self._show_title_icon(record):
            return
        self.cover_label.setText("No disc image")
        self.cover_label.setPixmap(QPixmap())

    def _index_cover_zip(self) -> None:
        path = Path(self.settings.get("cover_zip", ""))
        self._cover_index = {}
        if not path.is_file():
            return
        try:
            self._cover_index = index_cover_zip(path)
        except (OSError, zipfile.BadZipFile):
            self._cover_index = {}

    def _banner_from_zip(self, gametdb_id: str) -> bytes | None:
        member = self._cover_index.get(gametdb_id)
        path = Path(self.settings.get("cover_zip", ""))
        if not member or not path.is_file():
            return None
        return read_zip_png(path, member)

    def _open_db_zip(self) -> None:
        if self._closing:
            return
        chosen, _selected = QFileDialog.getOpenFileName(
            self,
            "Open GameTDB zip",
            self.settings.get("gametdb_zip", ""),
            "Zip archives (*.zip)",
        )
        if not chosen:
            return
        try:
            database = load_zip(Path(chosen))
        except (OSError, zipfile.BadZipFile, ET.ParseError, RuntimeError) as exc:
            self._warn(str(exc))
            return
        self.settings["gametdb_zip"] = chosen
        self._persist()
        self._db_ready(database)

    def _open_banner_zip(self) -> None:
        if self._closing:
            return
        chosen, _selected = QFileDialog.getOpenFileName(
            self,
            "Open banner zip",
            self.settings.get("cover_zip", ""),
            "Zip archives (*.zip)",
        )
        if not chosen:
            return
        self.settings["cover_zip"] = chosen
        self._persist()
        self._index_cover_zip()
        count = len(self._cover_index)
        self.statusBar().showMessage(f"Banner zip indexed, {count} images")
        self._show_details()

    def _download_db(self) -> None:
        self.db_button.setEnabled(False)
        self.statusBar().showMessage("Downloading GameTDB")
        worker = FetchWorker(lambda: download_titles(self.data / "cache"))
        worker.succeeded.connect(self._downloaded_db)
        worker.failed.connect(self._db_failed)
        self._track(worker)

    def _downloaded_db(self, database) -> None:
        self.settings["gametdb_zip"] = ""
        self._persist()
        self._db_ready(database)

    def _db_ready(self, database) -> None:
        if self._closing:
            return
        self.database = database
        self.db_button.setEnabled(True)
        self.records = annotate(self.records, database)
        self._refresh_db_cells()
        self._refresh_db_label()
        self._show_details()
        self.statusBar().showMessage(f"GameTDB loaded, {len(database)} titles")

    def _db_failed(self, message: str) -> None:
        self.db_button.setEnabled(True)
        if self._closing:
            return
        self.statusBar().showMessage("GameTDB download failed")
        self._warn(message)

    def _refresh_db_cells(self) -> None:
        by_path = {str(record.path): record for record in self.records}
        self.table.blockSignals(True)
        sorting = self.table.isSortingEnabled()
        self.table.setSortingEnabled(False)
        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, NAME_COL)
            db_item = self.table.item(row, DB_COL)
            if name_item is None or db_item is None:
                continue
            record = by_path.get(name_item.data(Qt.ItemDataRole.UserRole))
            if record is not None:
                db_item.setText(record.gametdb_name)
        self.table.setSortingEnabled(sorting)
        self.table.blockSignals(False)

    def _refresh_db_label(self) -> None:
        if self.database is None:
            self.db_label.setText("GameTDB not loaded")
        else:
            version = f" · {self.database.version}" if self.database.version else ""
            self.db_label.setText(f"GameTDB {len(self.database)}{version}")

    def _start_copy(self) -> None:
        if self._busy:
            self._warn("Wait for the current copy to finish.")
            return
        chosen = self._checked_records()
        if not chosen:
            self._warn("Check at least one title.")
            return
        dest_text = self.dest_edit.text().strip()
        if not dest_text:
            self._warn("Choose a destination folder.")
            return
        try:
            _source, dest = validate_copy(chosen[0].source_root, Path(dest_text))
        except PathIssue as exc:
            self._warn(str(exc))
            return
        known = [self.sizes.get(str(record.path)) for record in chosen]
        if all(size is not None for size in known):
            size_text = format_bytes(sum(size for size in known if size is not None))
        else:
            size_text = "size still counting"
        game_data = self.game_data_box.isChecked()
        if game_data:
            detail = "Each title is written to its own folder. Save data under usr/save is not copied."
            folder_names = planned_game_folders(
                [game_folder_name(record.gametdb_name or record.name, record.title_id) for record in chosen]
            )
        else:
            detail = "The copy keeps the path relative to the source."
            folder_names = relative_archive_members(chosen)
        archive = self._title_archive if len(chosen) == len(self.records) else None
        if archive is None and self._all_titles_checked() and not self._title_archive_declined:
            self._offer_title_archive()
            archive = self._title_archive
        message = (
            f"Copy {len(chosen)} titles ({size_text}) into {dest}?\n\n"
            f"{detail}\nThe source is not changed or deleted."
        )
        if archive is not None:
            message += f"\n\nAn archive will also be written to {archive}."
        answer = QMessageBox.question(self, "Copy titles", message)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._persist()
        self._busy = True
        self._cancel_copy = threading.Event()
        self.copy_button.setEnabled(False)
        self.cancel_copy_button.setEnabled(True)
        self.copy_progress.setValue(0)
        self.copy_log.clear()
        self.copy_label.setText("Counting files")
        if game_data:
            jobs = [
                (record.path, game_folder_name(record.gametdb_name or record.name, record.title_id))
                for record in chosen
            ]
        else:
            jobs = [(record.source_root, record.path) for record in chosen]
        self._last_copy_was_game_data = game_data
        worker = CopyWorker(
            jobs,
            dest,
            self.skip_box.isChecked(),
            self._cancel_copy,
            game_data,
            archive,
            folder_names if archive is not None else None,
        )
        worker.progress.connect(self._copy_progress)
        worker.succeeded.connect(self._copy_finished)
        worker.failed.connect(self._copy_failed)
        self._track(worker)

    def _copy_progress(self, progress) -> None:
        if self._closing:
            return
        self.copy_progress.setValue(progress_permille(progress.copied_bytes, progress.total_bytes))
        amount = (
            f"{format_bytes(progress.copied_bytes)} of {format_bytes(progress.total_bytes)}"
            if progress.total_bytes
            else format_bytes(progress.copied_bytes)
        )
        file_part = (
            f" · file {progress.file_index} of {progress.file_count}" if progress.file_count else ""
        )
        self.copy_label.setText(self._elide(f"{amount}{file_part} · {progress.current_path}"))
        self.copy_label.setToolTip(progress.current_path)

    def _copy_finished(self, result: CopyResult) -> None:
        self._busy = False
        if self._closing:
            return
        self.copy_button.setEnabled(True)
        self.cancel_copy_button.setEnabled(False)
        if result.halted:
            self.copy_label.setText(result.halted)
            self.statusBar().showMessage("Copy stopped")
        elif result.cancelled:
            self.copy_label.setText("Stopped. Files already written were left in the destination.")
            self.statusBar().showMessage("Copy stopped")
        else:
            self.copy_progress.setValue(1000 if result.total_bytes else 0)
            self.copy_label.setText(
                f"Finished. Wrote {result.files_written}, skipped {result.files_skipped}, "
                f"errors {len(result.errors)}."
            )
            self.statusBar().showMessage("Copy finished")
        for error in result.errors:
            self.copy_log.appendPlainText(error)
        if not result.errors and not result.cancelled and not result.halted:
            if self._last_copy_was_game_data and result.verified:
                self.copy_log.appendPlainText("Destination file count and byte total match the source.")
            else:
                self.copy_log.appendPlainText("Copy finished.")
            note = getattr(self.sender(), "archive_note", "")
            if note:
                self.copy_log.appendPlainText(note)

    def _copy_failed(self, message: str) -> None:
        self._busy = False
        if self._closing:
            return
        self.copy_button.setEnabled(True)
        self.cancel_copy_button.setEnabled(False)
        self.copy_label.setText("Copy failed")
        self.copy_log.appendPlainText(message)
        self._warn(message)

    def _stop_copy(self) -> None:
        self._cancel_copy.set()
        self.cancel_copy_button.setEnabled(False)
        self.copy_label.setText("Stopping after the current block")

    def _refresh_binary_label(self) -> None:
        binary = installed_binary(self.data)
        if binary is None:
            self.binary_label.setText("wfs-extract is not downloaded yet.")
        else:
            self.binary_label.setText(str(binary))

    def _download_binary(self) -> None:
        self.binary_button.setEnabled(False)
        self.statusBar().showMessage("Downloading wfs-tools")
        worker = FetchWorker(lambda: ensure_binary(self.data))
        worker.succeeded.connect(self._binary_ready)
        worker.failed.connect(self._binary_failed)
        self._track(worker)

    def _binary_ready(self, path: Path) -> None:
        if self._closing:
            return
        self.binary_button.setEnabled(True)
        self._refresh_binary_label()
        self._refresh_command()
        self.statusBar().showMessage(f"wfs-extract ready at {path}")

    def _binary_failed(self, message: str) -> None:
        self.binary_button.setEnabled(True)
        if self._closing:
            return
        self.statusBar().showMessage("wfs-tools download failed")
        self._warn(message)

    def _current_request(self) -> ExtractRequest | None:
        binary = installed_binary(self.data)
        if binary is None:
            return None
        image_type = self._image_type()
        otp = Path(self.otp_edit.text().strip()) if self.otp_edit.text().strip() else None
        seeprom = Path(self.seeprom_edit.text().strip()) if self.seeprom_edit.text().strip() else None
        return ExtractRequest(
            binary=binary,
            input_path=Path(self.input_edit.text().strip() or "input"),
            image_type=image_type,
            output_path=Path(self.output_edit.text().strip() or "output"),
            dump_path=self.dump_edit.text().strip() or "/",
            otp=otp if image_type != "plain" else None,
            seeprom=seeprom if image_type == "usb" else None,
            dump_usr_dir=self.recovery_box.isChecked(),
        )

    def _refresh_command(self) -> None:
        if not hasattr(self, "command_preview"):
            return
        request = self._current_request()
        if request is None:
            self.command_preview.setPlainText("Download wfs-extract to see the command.")
            return
        lines = [format_command(build_args(request))]
        warning = recovery_warning(request.dump_path, request.dump_usr_dir)
        if warning:
            lines.append(warning)
        self.command_preview.setPlainText("\n".join(lines))

    def _start_extract(self) -> None:
        if self._process is not None and self._process.state() != QProcess.ProcessState.NotRunning:
            self._warn("An extract is already running.")
            return
        binary = installed_binary(self.data)
        if binary is None:
            self._warn("Download wfs-extract first.")
            return
        image_type = self._image_type()
        input_text = self.input_edit.text().strip()
        output_text = self.output_edit.text().strip()
        otp_text = self.otp_edit.text().strip()
        seeprom_text = self.seeprom_edit.text().strip()
        if not input_text or not output_text:
            self._warn("Choose an input and an output folder.")
            return
        otp = Path(otp_text) if otp_text else None
        seeprom = Path(seeprom_text) if seeprom_text else None
        try:
            validate_extract_paths(Path(input_text), Path(output_text), otp, seeprom, image_type)
        except PathIssue as exc:
            self._warn(str(exc))
            return
        warning = recovery_warning(self.dump_edit.text(), self.recovery_box.isChecked())
        if warning:
            self._warn(warning)
            return
        output = Path(output_text)
        extra = ""
        if output_is_nonempty(output):
            extra = "\n\nThe output folder already has files. wfs-extract overwrites files it writes and leaves the rest."
        answer = QMessageBox.question(
            self,
            "Extract WFS",
            "Read the input and write files into the output folder?\n\n"
            "The input image is not modified." + extra,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._persist()
        output.mkdir(parents=True, exist_ok=True)
        request = ExtractRequest(
            binary=binary,
            input_path=Path(input_text),
            image_type=image_type,
            output_path=output,
            dump_path=self.dump_edit.text().strip() or "/",
            otp=otp if image_type != "plain" else None,
            seeprom=seeprom if image_type == "usb" else None,
            dump_usr_dir=self.recovery_box.isChecked(),
        )
        args = build_args(request)
        self.extract_log.clear()
        self.extract_log.appendPlainText(format_command(args))
        self._extract_buffer = ""
        self._files_started = 0
        self.extract_progress.setRange(0, 0)
        self.extract_label.setText("Starting")
        self.extract_button.setEnabled(False)
        self.cancel_extract_button.setEnabled(True)
        process = QProcess(self)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.readyReadStandardOutput.connect(self._extract_output)
        process.finished.connect(self._extract_finished)
        process.errorOccurred.connect(self._extract_error)
        self._process = process
        program, *program_args = args
        process.start(program, program_args)

    def _extract_output(self) -> None:
        if self._process is None:
            return
        data = bytes(self._process.readAllStandardOutput()).decode("utf-8", errors="replace")
        if self._closing:
            return
        self._extract_buffer, lines = append_extract_chunk(self._extract_buffer, data)
        for line in lines:
            self._handle_extract_line(line)

    def _handle_extract_line(self, line: str) -> None:
        if len(line) > 4096:
            line = line[:4096]
        event = parse_extract_line(line)
        if event["event"] == "blank":
            return
        self.extract_log.appendPlainText(line)
        if event["event"] == "file":
            self._files_started += 1
            self.extract_label.setText(
                self._elide(f"File {self._files_started} · {event['path']}", self.extract_label)
            )
            self.extract_label.setToolTip(event["path"])
        elif event["event"] == "start":
            self.extract_label.setText("Reading the filesystem")
        elif event["event"] == "error":
            self.extract_label.setText(event["path"])

    def _extract_finished(self, code: int, _status) -> None:
        if self._closing:
            self._extract_buffer = ""
            return
        if self._extract_buffer.strip():
            self._handle_extract_line(self._extract_buffer.strip())
            self._extract_buffer = ""
        self.extract_progress.setRange(0, 1)
        self.extract_progress.setValue(1 if code == 0 else 0)
        self.extract_button.setEnabled(True)
        self.cancel_extract_button.setEnabled(False)
        if code == 0:
            self.extract_label.setText(f"Finished. {self._files_started} paths reported.")
            self.statusBar().showMessage("Extract finished")
        else:
            self.extract_label.setText(f"wfs-extract exited with status {code}.")
            self.statusBar().showMessage("Extract failed")

    def _extract_error(self, _error) -> None:
        if self._closing or self._process is None:
            return
        message = self._process.errorString()
        if message:
            self.extract_log.appendPlainText(message)

    def _stop_extract(self) -> None:
        if self._process is not None and self._process.state() != QProcess.ProcessState.NotRunning:
            self._process.kill()
            self.extract_label.setText("Stopped. Files already written were left in the output folder.")

    def _elide(self, text: str, label: QLabel | None = None) -> str:
        widget = label or self.copy_label
        width = max(widget.width() - 12, 240)
        return QFontMetrics(widget.font()).elidedText(text, Qt.TextElideMode.ElideMiddle, width)

    def _warn(self, message: str) -> None:
        QMessageBox.warning(self, "WFS Studio", message)

    def _about_text(self) -> str:
        return (
            "WFS Studio " + __version__ + "\n\n"
            "A GUI for your own Wii U WFS dumps. Title names come from meta.xml. "
            "GameTDB (https://www.gametdb.com/) is a second lookup. "
            "That list and its artwork stay in the cache on this computer.\n\n"
            "wfs-extract is the official MIT-licensed tool by koolkdev, pinned at v1.2.3. "
            "Those tools are built on koolkdev's wfslib.\n\n"
            "Save backups use the folder layout from SaveMii "
            "(https://github.com/w3irDv/savemii). This program does not include SaveMii's source.\n\n"
            "The window toolkit is PySide6, which is Qt, under the LGPL. "
            "WFS Studio's own source stays MIT. License files: " + str(license_dir(self.root)) + "\n\n"
            "otp.bin and seeprom.bin stay on your machine. This program does not upload them.\n\n"
            "Crash log: " + str(log_path(self.data)) + "\n\n"
            + MENU_CREDIT
        )

    def _about(self) -> None:
        QMessageBox.information(self, "About WFS Studio", self._about_text())

    def _on_menu_music(self, checked: bool) -> None:
        if checked:
            self._start_menu_music()
        else:
            self._stop_menu_music()

    def _start_menu_music(self) -> None:
        """Play the menu track from the start of a loop. Offscreen tests stay quiet."""
        if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
            return
        if not self.menu_music_action.isChecked():
            return
        quiet_ffmpeg_logs()
        path = menu_track()
        if path is None:
            return
        if self._player is not None:
            self._play_menu_track(self._player, path)
            return
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        except ImportError:
            return
        audio = QAudioOutput(self)
        audio.setVolume(MENU_VOLUME)
        player = QMediaPlayer(self)
        player.setAudioOutput(audio)
        player.errorOccurred.connect(self._on_menu_music_error)
        self._audio = audio
        self._player = player
        self._play_menu_track(player, path)

    def _play_menu_track(self, player, path: Path) -> None:
        quiet_ffmpeg_logs()
        player.setSource(QUrl.fromLocalFile(str(path)))
        player.setLoops(type(player).Loops.Infinite)
        player.play()

    def _on_menu_music_error(self, error, _message: str = "") -> None:
        from PySide6.QtMultimedia import QMediaPlayer

        if error == QMediaPlayer.Error.NoError:
            return
        self._stop_menu_music()

    def _stop_menu_music(self) -> None:
        """Release the track without ``QMediaPlayer.stop()``.

        ``stop()`` returns at once, and then quitting the application does
        not. On a Mac that holds the process for more than 20 seconds after
        the window is gone. Clearing the source ends the sound and lets the
        process exit with the window.
        """
        player = self._player
        if player is None or self._releasing_music:
            return
        self._releasing_music = True
        try:
            source = player.source()
            if source.isEmpty():
                return
            player.setSource(QUrl())
        finally:
            self._releasing_music = False

    def closeEvent(self, event) -> None:
        if self._closing:
            event.accept()
            return
        copying = self._busy
        extracting = (
            self._process is not None and self._process.state() != QProcess.ProcessState.NotRunning
        )
        interrupted = bool(getattr(QApplication.instance(), "_interrupt", False))
        if (copying or extracting) and not interrupted:
            answer = QMessageBox.question(
                self,
                "Quit",
                "A job is still running. Stop it and quit?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self._closing = True
        self._stop_menu_music()
        self._cancel_copy.set()
        self._cancel_saves.set()
        self._cancel_sizes.set()
        self._cancel_covers.set()
        if self._process is not None and self._process.state() != QProcess.ProcessState.NotRunning:
            self._process.kill()
            self._process.waitForFinished(3000)
        try:
            self._persist()
        except OSError:
            pass
        self._join_workers()
        event.accept()

    def _join_workers(self) -> None:
        """Let worker threads finish before Qt destroys them.

        Waiting on the GUI thread does not deliver queued signals. Signals
        are blocked first so a late result cannot open a dialog or start
        another worker. One blocking call, such as the current copy block
        or a cover download, is given a few seconds. If a thread is still
        running after that, the process exits. Destroying a running
        QThread aborts, and terminating a thread that is inside Python
        is unsafe.
        """
        running = [worker for worker in list(self._workers) if worker.isRunning()]
        for worker in running:
            worker.blockSignals(True)
        deadline = time.monotonic() + 12
        while running and time.monotonic() < deadline:
            if not any(worker.isRunning() for worker in running):
                break
            time.sleep(0.05)
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        if any(worker.isRunning() for worker in running):
            os._exit(0)


def apply_theme(app: QApplication) -> None:
    """White menu, soft gray panels, and the Wii U blue accent.

    The blue is the logo color, ``#009AC7``. It is reserved for the selected
    tab, primary buttons, progress, and focus. Body text stays a soft dark
    gray so the window reads as the system menu rather than a blue page.
    """
    app.setStyle("Fusion")
    white = QColor("#ffffff")
    desk = QColor("#f2f5f6")
    panel = QColor("#e6ebed")
    ink = QColor("#2c3336")
    muted = QColor("#5c676c")
    blue = QColor("#009ac7")
    wash = QColor("#d7f1f8")
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, desk)
    palette.setColor(QPalette.ColorRole.WindowText, ink)
    palette.setColor(QPalette.ColorRole.Base, white)
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#f4f8f9"))
    palette.setColor(QPalette.ColorRole.Text, ink)
    palette.setColor(QPalette.ColorRole.Button, white)
    palette.setColor(QPalette.ColorRole.ButtonText, ink)
    palette.setColor(QPalette.ColorRole.Light, panel)
    palette.setColor(QPalette.ColorRole.Midlight, desk)
    palette.setColor(QPalette.ColorRole.Highlight, wash)
    palette.setColor(QPalette.ColorRole.HighlightedText, ink)
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#8c8c8c"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, white)
    palette.setColor(QPalette.ColorRole.ToolTipText, ink)
    palette.setColor(QPalette.ColorRole.Link, blue)
    disabled = QPalette.ColorGroup.Disabled
    palette.setColor(disabled, QPalette.ColorRole.Text, muted)
    palette.setColor(disabled, QPalette.ColorRole.WindowText, muted)
    palette.setColor(disabled, QPalette.ColorRole.ButtonText, QColor("#8c8c8c"))
    app.setPalette(palette)
    app.setStyleSheet(
        """
        QMainWindow, QDialog, QMessageBox { background: #f2f5f6; color: #2c3336; }
        QWidget { color: #2c3336; }
        QLabel#version { color: #5c676c; background: transparent; padding: 6px 14px 0 0; }
        QMenuBar { background: #ffffff; color: #2c3336; border-bottom: 1px solid #d5dcdf; }
        QMenuBar::item { padding: 4px 10px; background: transparent; }
        QMenuBar::item:selected { background: #e5f6fb; color: #009ac7; }
        QMenu { background: #ffffff; color: #2c3336; border: 1px solid #d5dcdf; }
        QMenu::item { padding: 6px 18px; }
        QMenu::item:selected { background: #e5f6fb; color: #2c3336; }
        QStatusBar {
            background: #ffffff;
            color: #5c676c;
            border-top: 1px solid #d5dcdf;
        }
        QTabWidget::pane {
            background: #ffffff;
            border: 1px solid #d5dcdf;
            border-radius: 10px;
            top: 1px;
        }
        QTabBar::tab {
            background: #e6ebed;
            color: #5c676c;
            border: 1px solid #d5dcdf;
            border-bottom: 3px solid transparent;
            border-top-left-radius: 8px;
            border-top-right-radius: 8px;
            padding: 8px 18px;
            margin-right: 4px;
        }
        QTabBar::tab:selected {
            background: #ffffff;
            color: #009ac7;
            border-bottom: 3px solid #009ac7;
            font-weight: 600;
        }
        QTabBar::tab:hover { color: #007ea6; }
        QPushButton {
            background: #ffffff;
            color: #2c3336;
            border: 1px solid #d0d8dc;
            border-radius: 10px;
            padding: 7px 16px;
        }
        QPushButton:hover { border-color: #009ac7; color: #007ea6; }
        QPushButton:pressed { background: #e5f6fb; }
        QPushButton:disabled { color: #8c8c8c; background: #f4f7f8; border-color: #e0e6e8; }
        QPushButton#primary {
            background: #009ac7;
            color: #ffffff;
            border: 1px solid #009ac7;
        }
        QPushButton#primary:hover { background: #00aad4; border-color: #00aad4; color: #ffffff; }
        QPushButton#primary:pressed { background: #007ea6; border-color: #007ea6; color: #ffffff; }
        QPushButton#primary:disabled { background: #b7dfe9; color: #f7fbfc; border-color: #b7dfe9; }
        QLineEdit, QPlainTextEdit {
            background: #ffffff;
            color: #2c3336;
            border: 1px solid #d0d8dc;
            border-radius: 8px;
            padding: 5px 8px;
            selection-background-color: #009ac7;
            selection-color: #ffffff;
        }
        QLineEdit:focus, QPlainTextEdit:focus { border: 1px solid #009ac7; }
        QTableWidget {
            background: #ffffff;
            alternate-background-color: #f4f8f9;
            color: #2c3336;
            gridline-color: #e6eef1;
            border: 1px solid #d5dcdf;
            border-radius: 8px;
            selection-background-color: #d7f1f8;
            selection-color: #2c3336;
        }
        QTableWidget::item:selected { background: #d7f1f8; color: #2c3336; }
        QHeaderView::section {
            background: #f4f7f8;
            color: #5c676c;
            padding: 6px;
            border: 0;
            border-bottom: 1px solid #d5dcdf;
        }
        QProgressBar {
            background: #e6ebed;
            color: #2c3336;
            border: 0;
            border-radius: 9px;
            min-height: 18px;
            max-height: 18px;
            text-align: center;
        }
        QProgressBar::chunk {
            background: #009ac7;
            border-radius: 8px;
            margin: 1px;
        }
        QLabel#cover {
            background: #ffffff;
            color: #8c8c8c;
            border: 1px solid #d5dcdf;
            border-radius: 16px;
        }
        QCheckBox, QRadioButton { spacing: 6px; }
        QScrollBar:vertical, QScrollBar:horizontal { background: #f2f5f6; border: 0; }
        QScrollBar:vertical { width: 12px; }
        QScrollBar:horizontal { height: 12px; }
        QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
            background: #c5d0d4;
            border-radius: 4px;
        }
        QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover { background: #009ac7; }
        QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
        QSplitter::handle { background: #f2f5f6; }
        QToolTip { background: #ffffff; color: #2c3336; border: 1px solid #009ac7; }
        """
    )


class WfsApplication(QApplication):
    def __init__(self, argv: list[str]) -> None:
        super().__init__(argv)
        self._interrupt = False

    def notify(self, receiver, event):
        try:
            return super().notify(receiver, event)
        except KeyboardInterrupt:
            # Ctrl+C in the terminal arrives here. Leaving it uncaught makes
            # Qt print "Error calling Python override of QApplication::notify".
            request_interrupt(self)
            return False
        except Exception:
            log_failure("Unhandled error in the window")
            return False


def request_interrupt(app) -> None:
    """Ask the window to close. A second Ctrl+C stops the process immediately."""
    if getattr(app, "_interrupt", False):
        os._exit(130)
    app._interrupt = True
    quit_app = getattr(app, "quit", None)
    if quit_app is not None:
        quit_app()


def main() -> None:
    try:
        install_crash_log(data_dir(repo_root()))
    except Exception:
        sys.__excepthook__(*sys.exc_info())
    app = WfsApplication([])
    apply_theme(app)
    window = MainWindow()
    window.show()

    def _on_sigint(_signum, _frame) -> None:
        request_interrupt(app)

    signal.signal(signal.SIGINT, _on_sigint)
    # The Qt loop waits in C. This timer returns to Python so Ctrl+C is seen.
    wake = QTimer()
    wake.start(200)
    wake.timeout.connect(lambda: None)
    try:
        code = app.exec()
    except KeyboardInterrupt:
        request_interrupt(app)
        code = 130
    raise SystemExit(130 if app._interrupt else code)
