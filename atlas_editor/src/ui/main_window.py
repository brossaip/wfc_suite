"""
Main application window for the WFC Atlas Editor.
"""

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QSplitter,
    QMenuBar, QMenu, QFileDialog, QMessageBox, QApplication,
    QStatusBar, QLabel, QCheckBox
)
from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QAction, QKeySequence, QCloseEvent
from pathlib import Path
from typing import Optional

from ..models import Atlas, Settings
from ..core import save_atlas, load_atlas, propagate_all_rules, cleanup_extraction
from .tiles_panel import TilesPanel
from .cross_preview_panel import CrossPreviewPanel
from .rule_controls_panel import RuleControlsPanel
from .validation_panel import ValidationPanel


class MainWindow(QMainWindow):
    """
    Main window for the WFC Atlas Editor.
    """
    
    APP_NAME = "WFC Atlas Editor"
    FILE_FILTER = "Tile Rules (*.tr);;All Files (*)"
    
    def __init__(self):
        super().__init__()
        self._atlas: Optional[Atlas] = None
        self._settings = QSettings("WFC", "AtlasEditor")
        
        self._setup_ui()
        self._setup_menu()
        self._setup_connections()
        self._restore_state()
        
        # Create new empty atlas
        self._new_atlas()
    
    def _setup_ui(self):
        self.setWindowTitle(self.APP_NAME)
        self.setMinimumSize(1000, 700)
        
        # Apply dark theme
        self.setStyleSheet("""
            QMainWindow {
                background-color: #2d2d2d;
            }
            QWidget {
                background-color: #2d2d2d;
                color: #e0e0e0;
            }
            QMenuBar {
                background-color: #353535;
                color: #e0e0e0;
                border-bottom: 1px solid #454545;
            }
            QMenuBar::item:selected {
                background-color: #454545;
            }
            QMenu {
                background-color: #353535;
                color: #e0e0e0;
                border: 1px solid #454545;
            }
            QMenu::item:selected {
                background-color: #4a90d9;
            }
            QStatusBar {
                background-color: #353535;
                color: #a0a0a0;
                border-top: 1px solid #454545;
            }
            QSplitter::handle {
                background-color: #454545;
            }
            QScrollBar:vertical {
                background-color: #2a2a2a;
                width: 12px;
                border: none;
            }
            QScrollBar::handle:vertical {
                background-color: #4a4a4a;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #5a5a5a;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }
            QLineEdit {
                background-color: #3a3a3a;
                color: #e0e0e0;
                border: 1px solid #555;
                border-radius: 3px;
                padding: 5px;
            }
            QLineEdit:focus {
                border-color: #4a90d9;
            }
            QCheckBox {
                color: #e0e0e0;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
            }
            QCheckBox::indicator:unchecked {
                background-color: #3a3a3a;
                border: 1px solid #555;
                border-radius: 3px;
            }
            QCheckBox::indicator:checked {
                background-color: #4a90d9;
                border: 1px solid #4a90d9;
                border-radius: 3px;
            }
        """)
        
        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Main splitter - 3 columns
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # COLUMN 1: Tiles + Validation
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)
        
        self.tiles_panel = TilesPanel()
        left_layout.addWidget(self.tiles_panel, 2)
        
        self.validation_panel = ValidationPanel()
        left_layout.addWidget(self.validation_panel, 1)
        
        self.splitter.addWidget(left_panel)
        
        # COLUMN 2: Cross Preview
        self.cross_preview_panel = CrossPreviewPanel()
        self.splitter.addWidget(self.cross_preview_panel)
        
        # COLUMN 3: Rule Controls
        self.rule_controls_panel = RuleControlsPanel()
        self.splitter.addWidget(self.rule_controls_panel)
        
        # Set splitter sizes: Tiles | Cross Preview | Rules
        self.splitter.setSizes([250, 500, 300])
        
        main_layout.addWidget(self.splitter)
        
        # Status bar
        self.statusBar().showMessage("Ready")
        
        # Settings bar in status
        self.auto_rotate_check = QCheckBox("Auto-propagate rotations")
        self.auto_rotate_check.setChecked(True)
        self.auto_rotate_check.stateChanged.connect(self._on_settings_changed)
        self.statusBar().addPermanentWidget(self.auto_rotate_check)
        
        self.auto_mirror_check = QCheckBox("Auto-propagate mirrors")
        self.auto_mirror_check.setChecked(True)
        self.auto_mirror_check.stateChanged.connect(self._on_settings_changed)
        self.statusBar().addPermanentWidget(self.auto_mirror_check)
    
    def _setup_menu(self):
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu("&File")
        
        new_action = QAction("&New", self)
        new_action.setShortcut(QKeySequence.StandardKey.New)
        new_action.triggered.connect(self._on_new)
        file_menu.addAction(new_action)
        
        open_action = QAction("&Open...", self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self._on_open)
        file_menu.addAction(open_action)
        
        file_menu.addSeparator()
        
        save_action = QAction("&Save", self)
        save_action.setShortcut(QKeySequence.StandardKey.Save)
        save_action.triggered.connect(self._on_save)
        file_menu.addAction(save_action)
        
        save_as_action = QAction("Save &As...", self)
        save_as_action.setShortcut(QKeySequence("Ctrl+Shift+S"))
        save_as_action.triggered.connect(self._on_save_as)
        file_menu.addAction(save_as_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("E&xit", self)
        exit_action.setShortcut(QKeySequence.StandardKey.Quit)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Edit menu
        edit_menu = menubar.addMenu("&Edit")
        
        propagate_action = QAction("&Propagate All Rules", self)
        propagate_action.setShortcut(QKeySequence("Ctrl+P"))
        propagate_action.triggered.connect(self._on_propagate_all)
        edit_menu.addAction(propagate_action)
        
        clear_auto_action = QAction("&Clear Auto-generated Rules", self)
        clear_auto_action.triggered.connect(self._on_clear_auto_rules)
        edit_menu.addAction(clear_auto_action)
    
    def _setup_connections(self):
        # Tiles panel -> other panels
        self.tiles_panel.tile_selected.connect(self._on_tile_selected)
        self.tiles_panel.atlas_modified.connect(self._on_atlas_modified)
        
        # Rule controls -> cross preview (update neighbor images)
        self.rule_controls_panel.neighbors_updated.connect(self._on_neighbors_updated)
        
        # Rule controls -> Validation
        self.rule_controls_panel.rules_changed.connect(self._on_rules_changed)
        
        # Validation -> Tiles panel
        self.validation_panel.tile_clicked.connect(self._on_validation_tile_clicked)
    
    def _restore_state(self):
        """Restore window state from settings."""
        geometry = self._settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        
        state = self._settings.value("windowState")
        if state:
            self.restoreState(state)
    
    def _save_state(self):
        """Save window state to settings."""
        self._settings.setValue("geometry", self.saveGeometry())
        self._settings.setValue("windowState", self.saveState())
    
    def _new_atlas(self):
        """Create a new empty atlas."""
        # Cleanup previous atlas extraction if any
        if self._atlas:
            cleanup_extraction(self._atlas)
        
        self._atlas = Atlas()
        self._update_title()
        self._update_panels()
    
    def _update_title(self):
        """Update window title."""
        if self._atlas:
            name = Path(self._atlas.file_path).name if self._atlas.file_path else "Untitled"
            modified = " *" if self._atlas.modified else ""
            self.setWindowTitle(f"{name}{modified} - {self.APP_NAME}")
        else:
            self.setWindowTitle(self.APP_NAME)
    
    def _update_panels(self):
        """Update all panels with current atlas."""
        self.tiles_panel.set_atlas(self._atlas)
        self.rule_controls_panel.set_atlas(self._atlas)
        self.rule_controls_panel.set_image_getter(self.tiles_panel.get_tile_image)
        self.cross_preview_panel.clear()
        self.validation_panel.set_atlas(self._atlas)
        
        # Update settings checkboxes
        if self._atlas:
            self.auto_rotate_check.setChecked(self._atlas.settings.auto_propagate_rotations)
            self.auto_mirror_check.setChecked(self._atlas.settings.auto_propagate_mirrors)
    
    def _check_unsaved(self) -> bool:
        """Check for unsaved changes. Returns True if OK to proceed."""
        if self._atlas and self._atlas.modified:
            result = QMessageBox.question(
                self, "Unsaved Changes",
                "You have unsaved changes. Do you want to save them?",
                QMessageBox.StandardButton.Save | 
                QMessageBox.StandardButton.Discard | 
                QMessageBox.StandardButton.Cancel
            )
            
            if result == QMessageBox.StandardButton.Save:
                return self._on_save()
            elif result == QMessageBox.StandardButton.Cancel:
                return False
        
        return True
    
    def _on_new(self):
        """Handle new atlas action."""
        if not self._check_unsaved():
            return
        self._new_atlas()
        self.statusBar().showMessage("Created new atlas", 3000)
    
    def _on_open(self):
        """Handle open atlas action."""
        if not self._check_unsaved():
            return
        
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Open Atlas",
            "",
            self.FILE_FILTER
        )
        
        if file_path:
            try:
                # Cleanup previous atlas extraction if any
                if self._atlas:
                    cleanup_extraction(self._atlas)
                
                self._atlas = load_atlas(file_path)
                self._update_title()
                self._update_panels()
                message = f"Opened {Path(file_path).name}"
                if self._atlas.duplicates_merged:
                    message += f" (merged {self._atlas.duplicates_merged} duplicate rules)"
                self.statusBar().showMessage(message, 3000)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to open file: {e}")
    
    def _on_save(self) -> bool:
        """Handle save atlas action. Returns True if saved."""
        if not self._atlas:
            return False
        
        if not self._atlas.file_path:
            return self._on_save_as()
        
        try:
            save_atlas(self._atlas, self._atlas.file_path)
            self._update_title()
            self.statusBar().showMessage(f"Saved {Path(self._atlas.file_path).name}", 3000)
            return True
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save file: {e}")
            return False
    
    def _on_save_as(self) -> bool:
        """Handle save as action. Returns True if saved."""
        if not self._atlas:
            return False
        
        file_path, selected_filter = QFileDialog.getSaveFileName(
            self, "Save Atlas As",
            "",
            self.FILE_FILTER
        )
        
        if file_path:
            # Add extension based on selected filter
            if "*.tr" in selected_filter and not file_path.endswith('.tr'):
                file_path += '.tr'
            elif "*.json" in selected_filter and not file_path.endswith('.json'):
                file_path += '.json'
            elif not file_path.endswith('.tr') and not file_path.endswith('.json'):
                file_path += '.tr'  # Default to .tr
            
            try:
                save_atlas(self._atlas, file_path)
                self._update_title()
                self.statusBar().showMessage(f"Saved {Path(file_path).name}", 3000)
                return True
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save file: {e}")
        
        return False
    
    def _on_tile_selected(self, tile_id: str):
        """Handle tile selection."""
        # Update cross preview
        if tile_id and self._atlas:
            tile = self._atlas.get_tile(tile_id)
            if tile:
                self.cross_preview_panel.set_selected_tile(tile.id)
                image = self.tiles_panel.get_tile_image(tile_id)
                self.cross_preview_panel.set_center(image)
            else:
                self.cross_preview_panel.clear()
        else:
            self.cross_preview_panel.clear()
        
        # Update rule controls
        self.rule_controls_panel.set_selected_tile(tile_id)
    
    def _on_neighbors_updated(self, side: str, neighbor_ids: list):
        """Handle neighbor list update from rule controls."""
        images = []
        for nid in neighbor_ids:
            img = self.tiles_panel.get_tile_image(nid)
            if img:
                images.append(img)
        self.cross_preview_panel.set_side_images(side, images)
    
    def _on_atlas_modified(self):
        """Handle atlas modification."""
        tiles_count = len(self._atlas.tiles) if self._atlas else 0
        print(f"[MainWindow._on_atlas_modified] Atlas has {tiles_count} tiles, refreshing panels")
        if self._atlas:
            self._atlas.modified = True
        self._update_title()
        self.rule_controls_panel.refresh()
        self.validation_panel.refresh()
    
    def _on_rules_changed(self):
        """Handle rules change."""
        if self._atlas:
            self._atlas.modified = True
        self._update_title()
        self.validation_panel.refresh()
    
    def _on_validation_tile_clicked(self, tile_id: str):
        """Handle click on validation item."""
        self.tiles_panel.select_tile(tile_id)
        self._on_tile_selected(tile_id)
    
    def _on_settings_changed(self):
        """Handle settings checkbox change."""
        if self._atlas:
            self._atlas.settings.auto_propagate_rotations = self.auto_rotate_check.isChecked()
            self._atlas.settings.auto_propagate_mirrors = self.auto_mirror_check.isChecked()
            self._atlas.modified = True
            self._update_title()
    
    def _on_propagate_all(self):
        """Propagate all rules to transform variants."""
        if not self._atlas:
            return
        
        count = propagate_all_rules(self._atlas)
        self._atlas.modified = True
        self._update_title()
        self.rule_controls_panel.refresh()
        self.validation_panel.refresh()
        
        QMessageBox.information(
            self, "Propagation Complete",
            f"Generated {count} auto-propagated rules."
        )
    
    def _on_clear_auto_rules(self):
        """Clear all auto-generated rules."""
        if not self._atlas:
            return
        
        result = QMessageBox.question(
            self, "Clear Auto Rules",
            "Are you sure you want to remove all auto-generated rules?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if result == QMessageBox.StandardButton.Yes:
            count = self._atlas.remove_auto_rules()
            self._update_title()
            self.rule_controls_panel.refresh()
            self.validation_panel.refresh()
            self.statusBar().showMessage(f"Removed {count} auto-generated rules", 3000)
    
    def closeEvent(self, event: QCloseEvent):
        """Handle window close."""
        if self._check_unsaved():
            self._save_state()
            # Cleanup extraction cache when closing
            if self._atlas:
                cleanup_extraction(self._atlas)
            event.accept()
        else:
            event.ignore()

