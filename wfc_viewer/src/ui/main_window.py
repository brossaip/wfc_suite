"""
Main application window.
"""

from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QToolBar,
    QLabel, QSpinBox, QPushButton, QSlider, QFileDialog,
    QMessageBox, QStatusBar, QSizePolicy
)
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtCore import Qt, Slot

from ..core.tile import TileAtlas
from ..core.tr_loader import TRLoader
from ..core.tm_saver import TMSaver, GridState
from ..core.wfc_engine import WFCEngine, EngineState
from ..utils.png_export import export_grid_to_png

from .grid_canvas import GridCanvas
from .tile_dialog import TileDialog


class MainWindow(QMainWindow):
    """Main application window for WFC Viewer."""
    
    def __init__(self):
        super().__init__()
        
        self._atlas: Optional[TileAtlas] = None
        self._tr_path: Optional[str] = None
        self._engine = WFCEngine(self)
        
        self._setup_ui()
        self._connect_signals()
        self._update_ui_state()
    
    def _setup_ui(self):
        self.setWindowTitle("WFC Viewer")
        self.setMinimumSize(800, 600)
        self.resize(1200, 800)
        
        # Dark theme
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1e1e22;
            }
            QToolBar {
                background-color: #252528;
                border: none;
                border-bottom: 1px solid #303035;
                spacing: 6px;
                padding: 4px;
            }
            QToolBar QLabel {
                color: #b0b0b0;
                font-size: 11px;
            }
            QToolBar QPushButton {
                background-color: #2a2a30;
                border: 1px solid #404045;
                border-radius: 4px;
                padding: 4px 10px;
                color: #e0e0e0;
                font-size: 11px;
                min-width: 60px;
            }
            QToolBar QPushButton:hover {
                background-color: #353540;
                border-color: #505055;
            }
            QToolBar QPushButton:pressed {
                background-color: #404050;
            }
            QToolBar QPushButton:disabled {
                background-color: #1a1a1f;
                color: #606060;
                border-color: #303035;
            }
            QToolBar QPushButton:checked {
                background-color: #405570;
                border-color: #5080b0;
            }
            QSpinBox {
                background-color: #2a2a30;
                border: 1px solid #404045;
                border-radius: 3px;
                padding: 2px 4px;
                color: #e0e0e0;
                min-width: 50px;
            }
            QSpinBox:focus {
                border-color: #5080b0;
            }
            QSlider::groove:horizontal {
                background: #303035;
                height: 6px;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #6090c0;
                width: 14px;
                margin: -4px 0;
                border-radius: 7px;
            }
            QSlider::handle:horizontal:hover {
                background: #80b0e0;
            }
            QStatusBar {
                background-color: #252528;
                border-top: 1px solid #303035;
                color: #909090;
                font-size: 11px;
            }
            QStatusBar QLabel {
                color: #909090;
            }
        """)
        
        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Toolbar
        self._create_toolbar()
        
        # Canvas (takes all available space)
        self._canvas = GridCanvas()
        self._canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self._canvas, 1)
        
        # Status bar
        self._create_status_bar()
        
        # Connect canvas to engine
        self._canvas.set_engine(self._engine)
    
    def _create_toolbar(self):
        toolbar = QToolBar()
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        self.addToolBar(toolbar)
        
        # File buttons
        self._open_btn = QPushButton("📂 Open .tr")
        self._open_btn.clicked.connect(self._on_open_tr)
        toolbar.addWidget(self._open_btn)
        
        self._save_tm_btn = QPushButton("💾 Save .tm")
        self._save_tm_btn.clicked.connect(self._on_save_tm)
        toolbar.addWidget(self._save_tm_btn)
        
        self._export_png_btn = QPushButton("🖼 Export PNG")
        self._export_png_btn.clicked.connect(self._on_export_png)
        toolbar.addWidget(self._export_png_btn)
        
        toolbar.addSeparator()
        
        # Grid size
        toolbar.addWidget(QLabel(" Grid: "))
        
        self._width_spin = QSpinBox()
        self._width_spin.setRange(1, 100)
        self._width_spin.setValue(10)
        toolbar.addWidget(self._width_spin)
        
        toolbar.addWidget(QLabel(" × "))
        
        self._height_spin = QSpinBox()
        self._height_spin.setRange(1, 100)
        self._height_spin.setValue(10)
        toolbar.addWidget(self._height_spin)
        
        self._apply_size_btn = QPushButton("Apply")
        self._apply_size_btn.clicked.connect(self._on_apply_size)
        toolbar.addWidget(self._apply_size_btn)
        
        toolbar.addSeparator()
        
        # Speed slider
        toolbar.addWidget(QLabel(" Speed: "))
        
        self._speed_slider = QSlider(Qt.Horizontal)
        self._speed_slider.setRange(1, 200)  # 1ms to 200ms delay (inverted for "speed")
        self._speed_slider.setValue(150)  # Start at medium-slow
        self._speed_slider.setFixedWidth(100)
        self._speed_slider.valueChanged.connect(self._on_speed_changed)
        toolbar.addWidget(self._speed_slider)
        
        toolbar.addSeparator()
        
        # Control buttons
        self._play_btn = QPushButton("▶ Play")
        self._play_btn.setCheckable(True)
        self._play_btn.clicked.connect(self._on_play_pause)
        toolbar.addWidget(self._play_btn)
        
        self._step_btn = QPushButton("⏭ Step")
        self._step_btn.clicked.connect(self._on_step)
        toolbar.addWidget(self._step_btn)
        
        self._restart_btn = QPushButton("↺ Restart")
        self._restart_btn.clicked.connect(self._on_restart)
        toolbar.addWidget(self._restart_btn)
        
        self._clear_all_btn = QPushButton("🗑 Clear All")
        self._clear_all_btn.clicked.connect(self._on_clear_all)
        toolbar.addWidget(self._clear_all_btn)
    
    def _create_status_bar(self):
        status = QStatusBar()
        self.setStatusBar(status)
        
        self._status_label = QLabel("Ready")
        status.addWidget(self._status_label)
        
        status.addWidget(QLabel(" │ "))
        
        self._progress_label = QLabel("Cells: 0/0")
        status.addWidget(self._progress_label)
        
        status.addWidget(QLabel(" │ "))
        
        self._file_label = QLabel("No file loaded")
        status.addPermanentWidget(self._file_label)
    
    def _connect_signals(self):
        # Canvas signals
        self._canvas.cell_clicked.connect(self._on_cell_clicked)
        self._canvas.cell_right_clicked.connect(self._on_cell_right_clicked)
        
        # Engine signals
        self._engine.state_changed.connect(self._on_engine_state_changed)
        self._engine.progress_updated.connect(self._on_progress_updated)
        self._engine.finished.connect(self._on_collapse_finished)
    
    def _update_ui_state(self):
        """Update UI enabled states based on current state."""
        has_atlas = self._atlas is not None
        is_running = self._engine.state == EngineState.RUNNING
        is_idle_or_paused = self._engine.state in (EngineState.IDLE, EngineState.PAUSED)
        
        self._save_tm_btn.setEnabled(has_atlas)
        self._export_png_btn.setEnabled(has_atlas)
        self._apply_size_btn.setEnabled(has_atlas)
        self._play_btn.setEnabled(has_atlas and self._engine.state != EngineState.FINISHED)
        self._step_btn.setEnabled(has_atlas and is_idle_or_paused)
        self._restart_btn.setEnabled(has_atlas)
        self._clear_all_btn.setEnabled(has_atlas)
        
        # Update play button state
        self._play_btn.setChecked(is_running)
        self._play_btn.setText("⏸ Pause" if is_running else "▶ Play")
    
    # === Slots ===
    
    @Slot()
    def _on_open_tr(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Open Tile Rules or Map",
            "", "Tile Rules (*.tr);;Tile Map (*.tm);;All Files (*)"
        )
        if not filepath:
            return
        
        try:
            if filepath.endswith('.tm'):
                # Load .tm file
                grid_state, atlas = TMSaver.load(filepath)
                self._atlas = atlas
                self._tr_path = grid_state.source_tr
                self._canvas.set_atlas(self._atlas)
                
                # Set grid size from loaded state
                self._width_spin.setValue(grid_state.width)
                self._height_spin.setValue(grid_state.height)
                
                # Initialize engine
                self._engine.initialize(self._atlas, grid_state.width, grid_state.height)
                self._canvas.setup_grid(grid_state.width, grid_state.height)
                
                # Restore locked cells
                for pos, cell_data in grid_state.cells.items():
                    if cell_data.tile_id:
                        self._engine.lock_cell(pos[0], pos[1], cell_data.tile_id)
                
                self._canvas.update_all_cells()
                self._file_label.setText(Path(filepath).name)
                self._status_label.setText("Map loaded")
            else:
                # Load .tr file
                self._atlas = TRLoader.load(filepath)
                self._tr_path = filepath
                self._canvas.set_atlas(self._atlas)
                
                # Initialize engine with current grid size
                width = self._width_spin.value()
                height = self._height_spin.value()
                self._engine.initialize(self._atlas, width, height)
                self._canvas.setup_grid(width, height)
                
                self._file_label.setText(Path(filepath).name)
                self._status_label.setText("File loaded")
            
            self._update_ui_state()
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load file:\n{e}")
    
    @Slot()
    def _on_save_tm(self):
        if self._atlas is None:
            return
        
        filepath, _ = QFileDialog.getSaveFileName(
            self, "Save Tile Map",
            "", "Tile Map (*.tm);;All Files (*)"
        )
        if not filepath:
            return
        
        if not filepath.endswith('.tm'):
            filepath += '.tm'
        
        try:
            # Build grid state from engine
            grid_state = GridState(
                width=self._engine.width,
                height=self._engine.height,
                source_tr=self._tr_path or ""
            )
            
            for pos, cell in self._engine.cells.items():
                if cell.is_collapsed:
                    grid_state.set_cell(
                        pos[0], pos[1],
                        cell.collapsed_tile,
                        cell.locked
                    )
            
            TMSaver.save(filepath, grid_state, self._atlas, self._tr_path)
            self._status_label.setText(f"Saved to {Path(filepath).name}")
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save file:\n{e}")
    
    @Slot()
    def _on_export_png(self):
        if self._atlas is None:
            return
        
        filepath, _ = QFileDialog.getSaveFileName(
            self, "Export PNG",
            "", "PNG Image (*.png);;All Files (*)"
        )
        if not filepath:
            return
        
        if not filepath.endswith('.png'):
            filepath += '.png'
        
        try:
            success = export_grid_to_png(filepath, self._engine, self._atlas)
            if success:
                self._status_label.setText(f"Exported to {Path(filepath).name}")
            else:
                QMessageBox.warning(self, "Warning", "Export completed but grid may be empty")
                
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to export:\n{e}")
    
    @Slot()
    def _on_apply_size(self):
        if self._atlas is None:
            return
        
        width = self._width_spin.value()
        height = self._height_spin.value()
        
        self._engine.initialize(self._atlas, width, height)
        self._canvas.setup_grid(width, height)
        self._status_label.setText(f"Grid set to {width}×{height}")
        self._update_ui_state()
    
    @Slot(int)
    def _on_speed_changed(self, value: int):
        # Invert: high slider value = low delay = fast
        delay = 201 - value  # 1 to 200
        self._engine.set_speed(delay)
    
    @Slot()
    def _on_play_pause(self):
        if self._engine.state == EngineState.RUNNING:
            self._engine.pause()
        else:
            self._engine.start()
        self._update_ui_state()
    
    @Slot()
    def _on_step(self):
        self._engine.step()
    
    @Slot()
    def _on_restart(self):
        self._engine.reset()
        self._canvas.update_all_cells()
        self._status_label.setText("Reset (locked cells kept)")
        self._update_ui_state()
    
    @Slot()
    def _on_clear_all(self):
        self._engine.clear_all()
        self._canvas.update_all_cells()
        self._status_label.setText("All cells cleared")
        self._update_ui_state()
    
    @Slot(int, int)
    def _on_cell_clicked(self, x: int, y: int):
        """Handle cell click - open tile selector."""
        if self._atlas is None:
            return
        
        # Pause if running
        was_running = self._engine.state == EngineState.RUNNING
        if was_running:
            self._engine.pause()
        
        # Get valid tiles for this position
        valid_tiles = self._engine.get_valid_tiles_for_cell(x, y)
        cell = self._engine.get_cell(x, y)
        is_cross = cell is not None and not cell.is_collapsed and len(cell.possibilities) == 0

        # Show dialog
        result = TileDialog.get_tile(
            self._atlas, x, y, valid_tiles, self
        )

        if result is not None:
            if result:  # tile_id selected (non-empty string)
                if is_cross:
                    self._engine.force_place(x, y, result)
                else:
                    self._engine.lock_cell(x, y, result)
                self._canvas.update_all_cells()
            else:  # Clear requested (empty string "")
                self._engine.unlock_cell(x, y)
                self._canvas.update_cell(x, y)
        # result is None = cancelled, do nothing
        
        # Resume if was running
        if was_running:
            self._engine.start()
        
        self._update_ui_state()
    
    @Slot(int, int)
    def _on_cell_right_clicked(self, x: int, y: int):
        """Handle right-click - clear cell (collapsed or contradiction)."""
        cell = self._engine.get_cell(x, y)
        if cell and (cell.is_collapsed or len(cell.possibilities) == 0):
            self._engine.unlock_cell(x, y)
            self._canvas.update_cell(x, y)
            self._update_ui_state()
    
    @Slot(EngineState)
    def _on_engine_state_changed(self, state: EngineState):
        state_names = {
            EngineState.IDLE: "Ready",
            EngineState.RUNNING: "Collapsing...",
            EngineState.PAUSED: "Paused",
            EngineState.FINISHED: "Complete",
            EngineState.CONTRADICTION: "Contradiction!"
        }
        self._status_label.setText(state_names.get(state, "Unknown"))
        self._update_ui_state()
    
    @Slot(int, int)
    def _on_progress_updated(self, collapsed: int, total: int):
        self._progress_label.setText(f"Cells: {collapsed}/{total}")
    
    @Slot(bool)
    def _on_collapse_finished(self, success: bool):
        if success:
            # Validate the result
            errors = self._engine.validate_grid()
            if errors:
                self._status_label.setText(f"Complete but {len(errors)} rule violations!")
                # Print first few errors to console for debugging
                print("=== VALIDATION ERRORS ===")
                for err in errors[:20]:
                    print(err)
                if len(errors) > 20:
                    print(f"... and {len(errors) - 20} more")
            else:
                self._status_label.setText("Collapse complete! (valid)")
        else:
            self._status_label.setText(
                f"Contradiction after {self._engine.backtracks} retries. Click the ✖ cell to fix it."
            )
        self._update_ui_state()
    
    def keyPressEvent(self, event):
        """Handle keyboard shortcuts."""
        if event.key() == Qt.Key_Space:
            self._on_play_pause()
        elif event.key() == Qt.Key_R:
            self._on_restart()
        elif event.key() == Qt.Key_S and event.modifiers() & Qt.ControlModifier:
            self._on_save_tm()
        elif event.key() == Qt.Key_O and event.modifiers() & Qt.ControlModifier:
            self._on_open_tr()
        else:
            super().keyPressEvent(event)

