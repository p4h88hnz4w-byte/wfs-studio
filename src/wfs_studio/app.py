"""WFS Studio desktop window."""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import Qt, QProcess, QThread, Signal
from PySide6.QtGui import QAction, QColor, QFontMetrics, QPalette, QPixmap
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
from wfs_studio.copy_job import CopyResult, copy_titles
from wfs_studio.extract import (
    ExtractRequest,
    build_args,
    format_command,
    parse_extract_line,
    recovery_warning,
)
from wfs_studio.gametdb import (
    annotate,
    disc_urls,
    download_bytes,
    download_titles,
    load_cached,
)
from wfs_studio.paths import PathIssue, output_is_nonempty, validate_copy, validate_extract_paths
from wfs_studio.settings import load_settings, save_settings
from wfs_studio.titles import TitleRecord, directory_size, scan_titles
from wfs_studio.util import format_bytes

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
            self.failed.emit(str(exc))


class SizeWorker(QThread):
    sized = Signal(str, int)

    def __init__(self, records: list[TitleRecord], cancel: threading.Event):
        super().__init__()
        self.records = records
        self.cancel = cancel

    def run(self) -> None:
        for record in self.records:
            if self.cancel.is_set():
                return
            self.sized.emit(str(record.path), directory_size(record.path, self.cancel))


class CopyWorker(QThread):
    progress = Signal(object)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, jobs, dest: Path, skip_same_size: bool, cancel: threading.Event):
        super().__init__()
        self.jobs = jobs
        self.dest = dest
        self.skip_same_size = skip_same_size
        self.cancel = cancel

    def run(self) -> None:
        try:
            result = copy_titles(
                self.jobs,
                self.dest,
                skip_same_size=self.skip_same_size,
                cancel=self.cancel,
                on_progress=self.progress.emit,
            )
            self.succeeded.emit(result)
        except Exception as exc:
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
            self.failed.emit(str(exc))


class CoverWorker(QThread):
    ready = Signal(int, object)

    def __init__(self, generation: int, urls: list[str], cache_file: Path):
        super().__init__()
        self.generation = generation
        self.urls = urls
        self.cache_file = cache_file

    def run(self) -> None:
        if self.cache_file.is_file():
            data = self.cache_file.read_bytes()
            if data.startswith(b"\x89PNG"):
                self.ready.emit(self.generation, data)
                return
        for url in self.urls:
            data = download_bytes(url)
            if data:
                self.cache_file.parent.mkdir(parents=True, exist_ok=True)
                self.cache_file.write_bytes(data)
                self.ready.emit(self.generation, data)
                return
        self.ready.emit(self.generation, None)


class SizeItem(QTableWidgetItem):
    def __lt__(self, other: QTableWidgetItem) -> bool:
        left = self.data(Qt.ItemDataRole.UserRole)
        right = other.data(Qt.ItemDataRole.UserRole)
        return (left if isinstance(left, int) else -1) < (right if isinstance(right, int) else -1)


class MainWindow(QMainWindow):
    def __init__(self, root: Path | None = None):
        super().__init__()
        self.root = root or repo_root()
        self.settings = load_settings(self.root)
        self.records: list[TitleRecord] = []
        self.sizes: dict[str, int] = {}
        self.database = load_cached(self.root / "cache")
        self._cancel_sizes = threading.Event()
        self._cancel_copy = threading.Event()
        self._busy = False
        self._process: QProcess | None = None
        self._extract_buffer = ""
        self._files_started = 0
        self._cover_generation = 0
        self._workers: list[QThread] = []
        self.setWindowTitle("WFS Studio")
        self.resize(1180, 760)
        self._build()
        self._load_fields()
        self._refresh_binary_label()
        self._refresh_db_label()
        self._refresh_command()

    def _build(self) -> None:
        tabs = QTabWidget()
        tabs.addTab(self._build_titles_tab(), "Titles")
        tabs.addTab(self._build_extract_tab(), "Extract")
        self.setCentralWidget(tabs)
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Ready")

        file_menu = self.menuBar().addMenu("File")
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

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
        filter_row.addWidget(QLabel("Search"))
        filter_row.addWidget(self.search_edit, 1)
        filter_row.addWidget(self.db_label)
        filter_row.addWidget(self.db_button)
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
        self.table.setSortingEnabled(True)
        body.addWidget(self.table)

        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        self.cover_label = QLabel("No disc image")
        self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_label.setFixedSize(180, 180)
        self.cover_label.setFrameShape(QFrame.Shape.StyledPanel)
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
        all_button = QPushButton("Check visible")
        all_button.clicked.connect(lambda: self._set_visible_checks(True))
        none_button = QPushButton("Uncheck visible")
        none_button.clicked.connect(lambda: self._set_visible_checks(False))
        self.checked_label = QLabel("0 checked")
        check_row.addWidget(all_button)
        check_row.addWidget(none_button)
        check_row.addWidget(self.checked_label)
        check_row.addStretch(1)
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

        action_row = QHBoxLayout()
        self.copy_button = QPushButton("Copy checked")
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
            radio.toggled.connect(self._on_type_changed)
        self.mlc_radio.setChecked(True)
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
        self.input_edit.setText(self.settings["input"])
        self.otp_edit.setText(self.settings["otp"])
        self.seeprom_edit.setText(self.settings["seeprom"])
        self.output_edit.setText(self.settings["output"])
        self.dump_edit.setText(self.settings["dump_path"] or "/")
        self.recovery_box.setChecked(bool(self.settings["dump_usr_dir"]))
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
            "input": self.input_edit.text().strip(),
            "extract_type": self._image_type(),
            "otp": self.otp_edit.text().strip(),
            "seeprom": self.seeprom_edit.text().strip(),
            "output": self.output_edit.text().strip(),
            "dump_path": self.dump_edit.text().strip() or "/",
            "dump_usr_dir": self.recovery_box.isChecked(),
        }

    def _persist(self) -> None:
        self.settings = self._collect_settings()
        save_settings(self.root, self.settings)

    def _image_type(self) -> str:
        if self.usb_radio.isChecked():
            return "usb"
        if self.plain_radio.isChecked():
            return "plain"
        return "mlc"

    def _on_type_changed(self) -> None:
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
        self.statusBar().showMessage("Scan failed")
        self._warn(message)

    def _scan_finished(self, records: list[TitleRecord]) -> None:
        self.scan_button.setEnabled(True)
        self.records = annotate(records, self.database)
        self.sizes.clear()
        self._fill_table()
        self.statusBar().showMessage(f"{len(self.records)} titles")
        if not self.records:
            self.detail_label.setText(
                "No title folders found. Point the source at a dump that contains usr/title, "
                "or at a single title folder with meta/meta.xml."
            )
            return
        self._cancel_sizes = threading.Event()
        worker = SizeWorker(list(self.records), self._cancel_sizes)
        worker.sized.connect(self._size_ready)
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
            self.table.setItem(row, NAME_COL, name)
            self.table.setItem(row, ID_COL, QTableWidgetItem(record.title_id))
            self.table.setItem(row, PRODUCT_COL, QTableWidgetItem(record.product_code))
            self.table.setItem(row, REGION_COL, QTableWidgetItem(record.region))
            size_item = SizeItem("…")
            size_item.setData(Qt.ItemDataRole.UserRole, -1)
            self.table.setItem(row, SIZE_COL, size_item)
            self.table.setItem(row, DB_COL, QTableWidgetItem(record.gametdb_name))
        self.table.blockSignals(False)
        self.table.setSortingEnabled(True)
        self._update_checked_label()
        self._apply_filter()

    def _record_for_row(self, row: int) -> TitleRecord | None:
        item = self.table.item(row, NAME_COL)
        if item is None:
            return None
        path = item.data(Qt.ItemDataRole.UserRole)
        for record in self.records:
            if str(record.path) == path:
                return record
        return None

    def _size_ready(self, path: str, size: int) -> None:
        self.sizes[path] = size
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

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() == CHECK_COL:
            self._update_checked_label()

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
            f"{record.kind} · {record.region or 'region unknown'} · version {record.version or '?'}",
        ]
        if record.publisher:
            lines.append(record.publisher)
        if record.gametdb_id:
            lines.append(f"GameTDB {record.gametdb_id}: {record.gametdb_name}")
        elif self.database is not None and record.product_code:
            lines.append("No GameTDB match for this product code.")
        lines.append(str(record.path))
        self.detail_label.setText("\n".join(lines))
        self._load_cover(record)

    def _load_cover(self, record: TitleRecord) -> None:
        self._cover_generation += 1
        generation = self._cover_generation
        self.cover_label.setPixmap(QPixmap())
        if not record.gametdb_id:
            self.cover_label.setText("No disc image")
            return
        self.cover_label.setText("Loading disc")
        cache_file = self.root / "cache" / "covers" / f"{record.gametdb_id}.png"
        worker = CoverWorker(generation, disc_urls(record.gametdb_id, record.region), cache_file)
        worker.ready.connect(self._cover_ready)
        self._track(worker)

    def _cover_ready(self, generation: int, data: object) -> None:
        if generation != self._cover_generation:
            return
        if not isinstance(data, (bytes, bytearray)):
            self.cover_label.setText("No disc image")
            self.cover_label.setPixmap(QPixmap())
            return
        pixmap = QPixmap()
        if not pixmap.loadFromData(bytes(data)):
            self.cover_label.setText("No disc image")
            return
        scaled = pixmap.scaled(
            self.cover_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.cover_label.setText("")
        self.cover_label.setPixmap(scaled)

    def _download_db(self) -> None:
        self.db_button.setEnabled(False)
        self.statusBar().showMessage("Downloading GameTDB")
        worker = FetchWorker(lambda: download_titles(self.root / "cache"))
        worker.succeeded.connect(self._db_ready)
        worker.failed.connect(self._db_failed)
        self._track(worker)

    def _db_ready(self, database) -> None:
        self.database = database
        self.db_button.setEnabled(True)
        self.records = annotate(self.records, database)
        self._refresh_db_cells()
        self._refresh_db_label()
        self._show_details()
        self.statusBar().showMessage(f"GameTDB loaded, {len(database)} titles")

    def _db_failed(self, message: str) -> None:
        self.db_button.setEnabled(True)
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
        answer = QMessageBox.question(
            self,
            "Copy titles",
            f"Copy {len(chosen)} titles ({size_text}) into {dest}?\n\n"
            "Files are written only inside the destination. The source is not changed or deleted.",
        )
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
        jobs = [(record.source_root, record.path) for record in chosen]
        worker = CopyWorker(jobs, dest, self.skip_box.isChecked(), self._cancel_copy)
        worker.progress.connect(self._copy_progress)
        worker.succeeded.connect(self._copy_finished)
        worker.failed.connect(self._copy_failed)
        self._track(worker)

    def _copy_progress(self, progress) -> None:
        if progress.total_bytes > 0:
            value = int(progress.copied_bytes * 1000 / progress.total_bytes)
            self.copy_progress.setValue(min(value, 1000))
        else:
            self.copy_progress.setValue(0)
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
        self.copy_button.setEnabled(True)
        self.cancel_copy_button.setEnabled(False)
        if result.cancelled:
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
        if not result.errors and not result.cancelled:
            self.copy_log.appendPlainText("Copy finished.")

    def _copy_failed(self, message: str) -> None:
        self._busy = False
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
        binary = installed_binary(self.root)
        if binary is None:
            self.binary_label.setText("wfs-extract is not downloaded yet.")
        else:
            self.binary_label.setText(str(binary))

    def _download_binary(self) -> None:
        self.binary_button.setEnabled(False)
        self.statusBar().showMessage("Downloading wfs-tools")
        worker = FetchWorker(lambda: ensure_binary(self.root))
        worker.succeeded.connect(self._binary_ready)
        worker.failed.connect(self._binary_failed)
        self._track(worker)

    def _binary_ready(self, path: Path) -> None:
        self.binary_button.setEnabled(True)
        self._refresh_binary_label()
        self._refresh_command()
        self.statusBar().showMessage(f"wfs-extract ready at {path}")

    def _binary_failed(self, message: str) -> None:
        self.binary_button.setEnabled(True)
        self.statusBar().showMessage("wfs-tools download failed")
        self._warn(message)

    def _current_request(self) -> ExtractRequest | None:
        binary = installed_binary(self.root)
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
        binary = installed_binary(self.root)
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
        self._extract_buffer += data
        while "\n" in self._extract_buffer:
            line, self._extract_buffer = self._extract_buffer.split("\n", 1)
            self._handle_extract_line(line.rstrip("\r"))

    def _handle_extract_line(self, line: str) -> None:
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
        if self._process is None:
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

    def _about(self) -> None:
        QMessageBox.information(
            self,
            "About WFS Studio",
            "WFS Studio " + __version__ + "\n\n"
            "A GUI for your own Wii U WFS dumps. Title names come from meta.xml, "
            "with GameTDB used as a second lookup.\n\n"
            "wfs-extract is the official MIT-licensed tool by koolkdev, pinned at v1.2.3.\n\n"
            "otp.bin and seeprom.bin stay on your machine. This program does not upload them.",
        )

    def closeEvent(self, event) -> None:
        copying = self._busy
        extracting = (
            self._process is not None and self._process.state() != QProcess.ProcessState.NotRunning
        )
        if copying or extracting:
            answer = QMessageBox.question(
                self,
                "Quit",
                "A job is still running. Stop it and quit?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._cancel_copy.set()
            self._cancel_sizes.set()
            if extracting and self._process is not None:
                self._process.kill()
        else:
            self._cancel_sizes.set()
        self._persist()
        for worker in list(self._workers):
            worker.wait(1500)
        event.accept()


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    palette = QPalette()
    base = QColor("#1b1e22")
    panel = QColor("#24282e")
    text = QColor("#e7e9ee")
    muted = QColor("#a3aab4")
    accent = QColor("#1f7a6d")
    palette.setColor(QPalette.ColorRole.Window, base)
    palette.setColor(QPalette.ColorRole.WindowText, text)
    palette.setColor(QPalette.ColorRole.Base, QColor("#14171a"))
    palette.setColor(QPalette.ColorRole.AlternateBase, panel)
    palette.setColor(QPalette.ColorRole.Text, text)
    palette.setColor(QPalette.ColorRole.Button, panel)
    palette.setColor(QPalette.ColorRole.ButtonText, text)
    palette.setColor(QPalette.ColorRole.Highlight, accent)
    palette.setColor(QPalette.ColorRole.HighlightedText, text)
    palette.setColor(QPalette.ColorRole.PlaceholderText, muted)
    palette.setColor(QPalette.ColorRole.ToolTipBase, panel)
    palette.setColor(QPalette.ColorRole.ToolTipText, text)
    app.setPalette(palette)
    app.setStyleSheet(
        """
        QPushButton { padding: 6px 12px; border-radius: 6px; border: 1px solid #3c444e; }
        QPushButton#primary { background: #1f7a6d; border-color: #2f9e8f; }
        QLineEdit, QPlainTextEdit { border: 1px solid #343a42; border-radius: 6px; padding: 4px; }
        QProgressBar { border: 1px solid #343a42; border-radius: 4px; text-align: center; }
        QProgressBar::chunk { background: #2f9e8f; }
        QHeaderView::section { background: #24282e; padding: 4px; border: 0; }
        """
    )


def main() -> None:
    app = QApplication([])
    apply_theme(app)
    window = MainWindow()
    window.show()
    raise SystemExit(app.exec())
