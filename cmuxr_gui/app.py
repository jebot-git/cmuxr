# SPDX-License-Identifier: GPL-2.0-or-later
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import threading

from PySide6.QtCore import (QAbstractListModel, QModelIndex, Qt, QTimer, Signal, QObject)
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QKeySequence, QPainter, QPixmap, QPalette
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QHBoxLayout,
    QFileDialog, QLabel, QLineEdit, QListView, QMenu, QMenuBar, QMessageBox,
    QPushButton, QStyle, QSystemTrayIcon, QVBoxLayout, QWidget)
from . import backend


class Events(QObject):
    done = Signal(object, object)


class Tasks:
    def __init__(self):
        self.pool = ThreadPoolExecutor(max_workers=2)
        self.events = Events()
        self.events.done.connect(lambda callback, result: callback(result))

    def run(self, function, callback):
        def work():
            try:
                value = function()
            except Exception as error:
                value = error
            self.events.done.emit(callback, value)
        self.pool.submit(work)


class Tracks(QAbstractListModel):
    """Virtual list: at most eight 128-entry pages, independent of library size."""
    error = Signal(str)
    def __init__(self, tasks):
        super().__init__()
        self.tasks, self.source, self.total = tasks, 'playlist', 0
        self.cache, self.pending, self.generation = OrderedDict(), set(), 0
        self.directory = None
        self.files = []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else self.total

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        path = self.path(index.row())
        if role == Qt.ItemDataRole.DisplayRole:
            if path is None:
                return 'Loading…'
            return ('▸ ' if Path(path).is_dir() else '') + Path(path).name
        if role == Qt.ItemDataRole.ToolTipRole:
            return path

    def path(self, row):
        if self.directory is not None:
            return self.files[row] if 0 <= row < len(self.files) else None
        start = row // 128 * 128
        if start not in self.cache:
            self.fetch(start)
            return None
        self.cache.move_to_end(start)
        return self.cache[start].get(row)

    def fetch(self, start):
        if start in self.pending:
            return
        self.pending.add(start)
        generation, source = self.generation, self.source
        def received(value):
            if generation != self.generation:
                return
            self.pending.discard(start)
            if isinstance(value, Exception):
                self.error.emit(str(value))
                return
            total, rows = value
            if total != self.total:
                self.beginResetModel()
                self.total = total
                self.cache.clear()
                self.endResetModel()
            self.cache[start] = rows
            while len(self.cache) > 8:
                self.cache.popitem(last=False)
            if rows:
                self.dataChanged.emit(self.index(min(rows)), self.index(max(rows)))
        self.tasks.run(lambda: backend.page(source, start), received)

    def open(self, source='playlist', directory=None):
        self.beginResetModel()
        self.generation += 1
        self.source, self.directory = source, directory
        self.cache.clear()
        self.pending.clear()
        self.total, self.files = 0, []
        self.endResetModel()
        if directory is None:
            self.fetch(0)
        else:
            generation = self.generation
            def scan():
                extensions = {'.mp3','.flac','.ogg','.opus','.wav','.m4a','.aac','.wma','.aiff','.wv'}
                with os.scandir(directory) as entries:
                    return sorted([e.path for e in entries if e.is_dir() or Path(e.name).suffix.lower() in extensions],
                                  key=lambda p: (not Path(p).is_dir(), Path(p).name.casefold()))
            def received(value):
                if generation != self.generation:
                    return
                if isinstance(value, Exception):
                    self.error.emit(str(value))
                    return
                self.beginResetModel()
                self.files, self.total = value, len(value)
                self.endResetModel()
            self.tasks.run(scan, received)


class ListView(QListView):
    navigate = Signal(int)
    pause = Signal()
    play = Signal()
    def wheelEvent(self, event):
        bar = self.verticalScrollBar()
        delta = event.angleDelta().y()
        if self.model().rowCount() and bar.maximum() > 0:
            if delta < 0 and bar.value() == bar.maximum():
                self.scrollToTop()
                event.accept()
                return
            if delta > 0 and bar.value() == 0:
                self.scrollToBottom()
                event.accept()
                return
        super().wheelEvent(event)

    def keyPressEvent(self, event):
        key = event.key()
        if event.modifiers() & (Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier):
            super().keyPressEvent(event)
        elif key == Qt.Key.Key_Space:
            self.pause.emit()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.play.emit()
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            self.navigate.emit(-1 if key == Qt.Key.Key_Left else 1)
        elif key in (Qt.Key.Key_Up, Qt.Key.Key_Down) and self.model().rowCount():
            row = (self.currentIndex().row() + (-1 if key == Qt.Key.Key_Up else 1)) % self.model().rowCount()
            self.setCurrentIndex(self.model().index(row))
            self.scrollTo(self.currentIndex())
        else:
            super().keyPressEvent(event)


class Player(QWidget):
    def __init__(self, app, tasks):
        super().__init__()
        self.app, self.tasks = app, tasks
        self.setWindowTitle('cmuxr · Music')
        self.current, self.polling, self.appearance_text = {}, False, None
        self.preferences = backend.settings()
        self.history, self.history_position = [], -1
        self.model = Tracks(tasks)
        self.model.error.connect(self.show_error)
        layout = QVBoxLayout(self)
        self.menubar = QMenuBar(self)
        layout.setMenuBar(self.menubar)
        self.now = QLabel('Connecting to cmuxr…')
        self.now.setWordWrap(True)
        layout.addWidget(self.now)
        controls = QHBoxLayout()
        for label, command in [('Previous','player-prev'),('Play / Pause','player-pause'),('Stop','player-stop'),('Next','player-next')]:
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, c=command: self.command(c))
            controls.addWidget(button)
        layout.addLayout(controls)
        self.source = QComboBox()
        self.source.addItems(['Current playlist', 'Library', 'Playing directory', 'Browse directory'])
        self.source.currentIndexChanged.connect(self.change_source)
        layout.addWidget(self.source)
        navigation = QHBoxLayout()
        self.location = QLineEdit()
        self.location.setAccessibleName('Directory location')
        self.location.setPlaceholderText('Enter a directory path')
        self.location.returnPressed.connect(self.enter_location)
        self.navigation_layout = navigation
        layout.addLayout(navigation)
        self.list = ListView()
        self.list.setModel(self.model)
        self.list.setUniformItemSizes(True)
        self.list.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.list.pause.connect(lambda: self.command('player-pause'))
        self.list.play.connect(self.play)
        self.list.navigate.connect(self.navigate)
        self.list.doubleClicked.connect(lambda _: self.play())
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self.context_menu)
        layout.addWidget(self.list)
        self.floor = QCheckBox('Disco floor in XR')
        self.floor.setChecked(bool(self.preferences.get('floor_enabled', True)))
        self.floor.toggled.connect(self.toggle_floor)
        layout.addWidget(self.floor)
        self.message = QLabel('Space · pause   Enter · play   ← / → · browse   ↑ / ↓ · wrap')
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.create_menus()
        self.list.selectionModel().currentChanged.connect(lambda *_: self.update_actions())
        self.model.modelReset.connect(self.update_actions)
        self.model.dataChanged.connect(lambda *_: self.update_actions())
        self.resize(560, 440)
        self.tray = QSystemTrayIcon(app.windowIcon(), self)
        self.menu = QMenu()
        for label, callback in [('Play / Pause',lambda: self.command('player-pause')),('Stop',lambda: self.command('player-stop')),('List',self.show_list)]:
            self.menu.addAction(label, callback)
        floor_action = self.menu.addAction('Disco floor in XR')
        floor_action.setCheckable(True)
        floor_action.setChecked(self.floor.isChecked())
        floor_action.toggled.connect(self.floor.setChecked)
        self.floor.toggled.connect(floor_action.setChecked)
        self.menu.addSeparator()
        self.menu.addAction('Quit cmuxr', self.quit)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(lambda reason: self.show_list() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(750)
        self.poll()
        self.apply_appearance()
        self.show_source('playlist')

    def action(self, menu, text, callback, shortcut=None):
        action = QAction(text, self)
        action.triggered.connect(lambda checked=False: callback())
        if shortcut is not None:
            action.setShortcut(QKeySequence(shortcut))
        self.addAction(action)
        menu.addAction(action)
        return action

    def create_menus(self):
        file_menu = self.menubar.addMenu('&File')
        self.action(file_menu, '&Open Files…', self.open_files, QKeySequence.StandardKey.Open)
        self.action(file_menu, 'Open &Folder…', self.choose_directory, 'Ctrl+Shift+O')
        file_menu.addSeparator()
        self.action(file_menu, '&Quit', self.quit, QKeySequence.StandardKey.Quit)
        playback = self.menubar.addMenu('&Playback')
        self.action(playback, '&Play Selection', self.play)
        for text, command in [('&Play / Pause', 'player-pause'), ('&Stop', 'player-stop'),
                              ('Pre&vious', 'player-prev'), ('&Next', 'player-next')]:
            self.action(playback, text, lambda c=command: self.command(c))
        go = self.menubar.addMenu('&Go')
        self.back_action = self.action(go, '&Back', lambda: self.go_history(-1), 'Alt+Left')
        self.forward_action = self.action(go, '&Forward', lambda: self.go_history(1), 'Alt+Right')
        self.up_action = self.action(go, '&Up', lambda: self.navigate(-1), 'Alt+Up')
        go.addSeparator()
        self.action(go, '&Home', lambda: self.open_directory(Path.home()), 'Alt+Home')
        self.action(go, '&Music', lambda: self.open_directory(Path.home() / 'Music'))
        self.action(go, '&Playing Directory', lambda: self.change_source(2))
        location = self.action(go, '&Location', self.focus_location)
        location.setShortcuts([QKeySequence('Ctrl+L'), QKeySequence('Alt+D')])
        library = self.menubar.addMenu('&Library')
        self.action(library, 'Show &Library', lambda: self.show_source('library'), 'Ctrl+1')
        library.addSeparator()
        self.action(library, 'Add &Files…', self.add_files)
        self.action(library, 'Add F&older…', self.add_folder)
        self.add_action = self.action(library, '&Add Selection to Library', self.add_selection)
        self.add_directory_action = self.action(library, 'Add Current &Directory to Library', self.add_directory)
        self.remove_action = self.action(library, '&Remove from Library', self.remove_selection, 'Delete')
        self.removeAction(self.remove_action)
        self.list.addAction(self.remove_action)
        self.remove_action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        library.addSeparator()
        self.action(library, '&Update Library', lambda: self.library_task(lambda: backend.request('update-cache')))
        self.action(library, '&Clear Library…', self.clear_library)
        view = self.menubar.addMenu('&View')
        self.action(view, 'Current &Playlist', lambda: self.show_source('playlist'), 'Ctrl+2')
        self.action(view, '&Refresh', self.refresh, QKeySequence.StandardKey.Refresh)
        view.addSeparator()
        floor = view.addAction('Disco &Floor in XR')
        floor.setCheckable(True)
        floor.setChecked(self.floor.isChecked())
        floor.toggled.connect(self.floor.setChecked)
        self.floor.toggled.connect(floor.setChecked)
        for action, icon in [(self.back_action, QStyle.StandardPixmap.SP_ArrowBack),
                             (self.forward_action, QStyle.StandardPixmap.SP_ArrowForward),
                             (self.up_action, QStyle.StandardPixmap.SP_ArrowUp)]:
            action.setIcon(self.style().standardIcon(icon))
            button = QPushButton()
            button.setIcon(action.icon())
            button.setToolTip(f'{action.text().replace("&", "")} ({action.shortcut().toString()})')
            button.setAccessibleName(action.text().replace('&', ''))
            button.clicked.connect(action.trigger)
            action.changed.connect(lambda a=action, b=button: b.setEnabled(a.isEnabled()))
            self.navigation_layout.addWidget(button)
        self.navigation_layout.addWidget(self.location, 1)

    def update_actions(self):
        self.back_action.setEnabled(self.history_position > 0)
        self.forward_action.setEnabled(self.history_position + 1 < len(self.history))
        directory = self.model.directory
        self.up_action.setEnabled(directory is not None and directory.parent != directory)
        selected = self.list.currentIndex().isValid()
        self.add_action.setEnabled(selected)
        self.add_directory_action.setEnabled(directory is not None)
        self.remove_action.setEnabled(selected and directory is None and self.model.source == 'library')

    def focus_location(self):
        self.location.setFocus()
        self.location.selectAll()

    def enter_location(self):
        self.open_directory(self.location.text())

    def choose_directory(self):
        directory = QFileDialog.getExistingDirectory(self, 'Open Folder', self.dialog_directory())
        if directory:
            self.open_directory(directory)

    def dialog_directory(self):
        return str(self.model.directory or Path.home())

    def open_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, 'Open Audio Files', self.dialog_directory())
        if files:
            self.tasks.run(lambda: backend.open_files(backend.media_paths(files)), self.operation_done)

    def operation_done(self, value):
        if isinstance(value, Exception):
            self.show_error(str(value))
        else:
            self.poll()

    def library_task(self, function):
        def received(value):
            if isinstance(value, Exception):
                self.show_error(str(value))
            else:
                self.message.setText('Library updated. Folder scans continue in the background.')
                if self.model.directory is None and self.model.source == 'library':
                    self.refresh()
        self.tasks.run(function, received)

    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, 'Add Files to Library', self.dialog_directory())
        if files:
            self.library_task(lambda: backend.add_to_library(files))

    def add_folder(self):
        directory = QFileDialog.getExistingDirectory(self, 'Add Folder to Library', self.dialog_directory())
        if directory:
            self.library_task(lambda: backend.add_to_library([directory]))

    def selected_path(self):
        index = self.list.currentIndex()
        return self.model.path(index.row()) if index.isValid() else None

    def add_selection(self):
        path = self.selected_path()
        if path:
            self.library_task(lambda: backend.add_to_library([path]))

    def add_directory(self):
        directory = self.model.directory
        if directory is not None:
            self.library_task(lambda: backend.add_to_library([directory]))

    def remove_selection(self):
        if not self.remove_action.isEnabled():
            return
        path = self.selected_path()
        if path:
            self.library_task(lambda: backend.remove_from_library(path))

    def clear_library(self):
        if QMessageBox.question(self, 'Clear Library',
                'Remove all tracks from the library? Audio files will stay on disk.',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel) == QMessageBox.StandardButton.Yes:
            self.library_task(lambda: backend.request('clear -l'))

    def context_menu(self, position):
        index = self.list.indexAt(position)
        if not index.isValid():
            return
        self.list.setCurrentIndex(index)
        menu = QMenu(self)
        menu.addAction('Open' if self.selected_path() and Path(self.selected_path()).is_dir() else 'Play', self.play)
        menu.addAction('Open Containing Folder', lambda: self.navigate(1))
        menu.addSeparator()
        menu.addAction(self.add_action)
        if self.remove_action.isEnabled():
            menu.addAction(self.remove_action)
        menu.exec(self.list.viewport().mapToGlobal(position))

    def show_error(self, value):
        self.message.setText(value)

    def command(self, command):
        self.tasks.run(lambda: backend.request(command), lambda value: self.show_error(str(value)) if isinstance(value, Exception) else self.poll())

    def toggle_floor(self, enabled):
        self.preferences['floor_enabled'] = enabled
        try:
            backend.save_settings(self.preferences)
        except OSError as error:
            self.show_error(str(error))

    def poll(self):
        self.preferences = backend.settings()
        if self.floor.isChecked() != bool(self.preferences.get('floor_enabled', True)):
            self.floor.setChecked(bool(self.preferences.get('floor_enabled', True)))
        self.apply_appearance()
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
        elif not self.isVisible():
            self.show_list()
        if self.polling:
            return
        self.polling = True
        def received(value):
            self.polling = False
            if isinstance(value, Exception):
                self.now.setText('Player unavailable · ' + str(value))
                return
            changed = value.get('file') != self.current.get('file')
            self.current = value
            text = f"{value.get('status','stopped').capitalize()} · {Path(value.get('file','No track')).name}"
            self.now.setText(text)
            self.tray.setToolTip(text[:120])
            if changed and self.source.currentIndex() == 0 and value.get('play_library') == 'true' and value.get('file'):
                self.source.setCurrentIndex(2)
            if changed and self.source.currentIndex() == 2:
                self.change_source(2)
            if not self.model.pending and self.model.directory is None:
                first = self.list.indexAt(self.list.viewport().rect().topLeft()).row()
                self.model.fetch(max(0, first) // 128 * 128)
        self.tasks.run(backend.status, received)

    def change_source(self, index):
        if index == 2:
            directory = Path(self.current.get('file', str(Path.home() / 'Music/track'))).parent
            self.open_directory(directory)
        elif index == 3:
            self.open_directory(self.model.directory or Path.home())
        else:
            self.show_source('playlist' if index == 0 else 'library')

    def open_directory(self, directory):
        directory = Path(directory).expanduser()
        if not directory.is_absolute():
            directory = (self.model.directory or Path.home()) / directory
        directory = Path(os.path.abspath(directory))
        if not directory.is_dir():
            self.show_error(f'Directory does not exist: {directory}')
            return
        self.show_source('directory', directory)

    def show_source(self, source, directory=None, record=True):
        location = (source, directory)
        if record and (self.history_position < 0 or self.history[self.history_position] != location):
            del self.history[self.history_position + 1:]
            self.history.append(location)
            self.history_position = len(self.history) - 1
        self.source.blockSignals(True)
        self.source.setCurrentIndex(3 if directory is not None else (0 if source == 'playlist' else 1))
        self.source.blockSignals(False)
        self.location.setText(str(directory) if directory is not None else '')
        self.location.setPlaceholderText('Current playlist' if source == 'playlist' else 'Library')
        self.model.open(source, directory)
        self.update_actions()

    def go_history(self, direction):
        position = self.history_position + direction
        if 0 <= position < len(self.history):
            self.history_position = position
            self.show_source(*self.history[position], record=False)

    def refresh(self):
        self.show_source(self.model.source, self.model.directory, record=False)

    def navigate(self, direction):
        path = self.model.path(self.list.currentIndex().row()) if self.list.currentIndex().isValid() else None
        if direction < 0:
            if self.model.directory:
                self.open_directory(self.model.directory.parent)
            else:
                self.source.setCurrentIndex(1)
        elif path:
            self.open_directory(Path(path) if Path(path).is_dir() else Path(path).parent)

    def play(self):
        index = self.list.currentIndex()
        if not index.isValid():
            return
        path = self.model.path(index.row())
        if not path:
            return
        if Path(path).is_dir():
            self.open_directory(Path(path))
        elif self.model.directory is None:
            self.command(f'cmuxr-play {self.model.source} {index.row()}')
        else:
            # Remote player-play accepts the complete filename as its argument.
            self.tasks.run(lambda: backend.play_directory(path), lambda value: self.show_error(str(value)) if isinstance(value, Exception) else self.poll())

    def show_list(self):
        self.show()
        self.raise_()
        self.activateWindow()
        self.list.setFocus()

    def closeEvent(self, event):
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.hide()
            event.ignore()
        else:
            self.app.quit()

    def quit(self):
        self.tasks.run(lambda: backend.request('quit'), lambda _: self.app.quit())

    def apply_appearance(self):
        try:
            text = (backend.config_root() / 'dome/appearance.json').read_text()
        except OSError:
            text = '{}'
        if text == self.appearance_text:
            return
        try:
            appearance = json.loads(text)
        except ValueError:
            return
        self.appearance_text = text
        light = appearance.get('light', False)
        bg = QColor(229,233,239) if light else QColor(31,37,45)
        fg = QColor(30,37,46) if light else QColor(231,235,241)
        accent = QColor(appearance.get('accent','#6babff'))
        if not accent.isValid():
            accent = QColor('#6babff')
        palette = self.app.palette()
        for role in (QPalette.ColorRole.Window, QPalette.ColorRole.Base, QPalette.ColorRole.Button):
            palette.setColor(role,bg)
        for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
            palette.setColor(role,fg)
            palette.setColor(QPalette.ColorGroup.Disabled, role,
                             QColor('#707985') if light else QColor('#929dab'))
        palette.setColor(QPalette.ColorRole.PlaceholderText,
                         QColor('#707985') if light else QColor('#929dab'))
        palette.setColor(QPalette.ColorRole.Highlight,accent)
        palette.setColor(QPalette.ColorRole.HighlightedText,QColor('#101820'))
        self.app.setPalette(palette)
        font = QFont(appearance.get('font','GNU Unifont / Sans-Serif').split(' / ')[0])
        font.setPixelSize(max(8,min(24,int(appearance.get('font_size',16)))))
        self.app.setFont(font)
        self.setWindowOpacity(max(160,min(255,int(appearance.get('opacity',248)))) / 255)
        entries = max(4,min(20,int(self.preferences.get('visible_entries',10))))
        self.list.setFixedHeight((self.list.fontMetrics().height()+8)*entries)


def run(tray_only=False, listener=None):
    app = QApplication(['cmuxr'])
    app.setApplicationName('cmuxr')
    app.setDesktopFileName('org.domed.cmuxr')
    pixmap = QPixmap(32,32)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setPen(QColor('#6babff'))
    font = painter.font()
    font.setPixelSize(28)
    painter.setFont(font)
    painter.drawText(pixmap.rect(),Qt.AlignmentFlag.AlignCenter,'♫')
    painter.end()
    app.setWindowIcon(QIcon(pixmap))
    tasks = Tasks()
    player = Player(app,tasks)
    if not tray_only or not QSystemTrayIcon.isSystemTrayAvailable():
        player.show_list()
    if listener is not None:
        def incoming():
            try:
                client, _ = listener.accept()
                client.close()
                player.show_list()
            except BlockingIOError:
                pass
        wake = QTimer()
        wake.timeout.connect(incoming)
        wake.start(150)
    result = app.exec()
    tasks.pool.shutdown(wait=True,cancel_futures=True)
    return result
