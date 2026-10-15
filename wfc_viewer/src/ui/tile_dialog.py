"""
Tile selector dialog for placing tiles on the grid.
"""

from typing import Optional, Set

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, 
    QPushButton, QCheckBox, QScrollArea, QWidget, QFrame
)
from PySide6.QtGui import QPixmap, QColor, QPainter
from PySide6.QtCore import Qt, Signal

from ..core.tile import TileAtlas, TileVariant


class TileButton(QFrame):
    """Button displaying a tile variant with its name."""
    
    TILE_SIZE = 64
    clicked = Signal()
    
    def __init__(self, variant: TileVariant, atlas: TileAtlas, parent=None):
        super().__init__(parent)
        self.variant = variant
        self.atlas = atlas
        self._enabled = True
        
        self.setFixedSize(self.TILE_SIZE + 16, self.TILE_SIZE + 28)
        self.setCursor(Qt.PointingHandCursor)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 2)
        layout.setSpacing(2)
        
        # Tile image
        pixmap = variant.get_pixmap(atlas.base_tiles, self.TILE_SIZE)
        img_label = QLabel()
        img_label.setPixmap(pixmap)
        img_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(img_label)
        
        # Tile name (truncated if too long)
        name = variant.id
        if len(name) > 10:
            name = name[:9] + "…"
        name_label = QLabel(name)
        name_label.setAlignment(Qt.AlignCenter)
        name_label.setStyleSheet("font-size: 9px; color: #a0a0a0;")
        layout.addWidget(name_label)
        
        # Tooltip with full variant info
        tooltip = f"{variant.id}"
        if variant.rotation != 0:
            tooltip += f"\nRotation: {variant.rotation}°"
        if variant.flip_x:
            tooltip += "\nFlipped X"
        if variant.flip_y:
            tooltip += "\nFlipped Y"
        self.setToolTip(tooltip)
        
        self._update_style()
    
    def _update_style(self):
        if self._enabled:
            self.setStyleSheet("""
                TileButton {
                    background-color: #2a2a2f;
                    border: 2px solid #404045;
                    border-radius: 4px;
                }
                TileButton:hover {
                    border-color: #6090c0;
                    background-color: #353540;
                }
            """)
        else:
            self.setStyleSheet("""
                TileButton {
                    background-color: #1a1a1f;
                    border: 2px solid #303035;
                    border-radius: 4px;
                }
            """)
            self.setCursor(Qt.ForbiddenCursor)
    
    def setEnabled(self, enabled: bool):
        self._enabled = enabled
        self._update_style()
    
    def mousePressEvent(self, event):
        if self._enabled and event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class TileDialog(QDialog):
    """
    Dialog for selecting a tile to place on a cell.
    
    Shows all available tiles, with option to filter by validity
    based on adjacent cells.
    """
    
    tile_selected = Signal(str)  # Emits tile_id
    
    def __init__(
        self, 
        atlas: TileAtlas,
        cell_x: int,
        cell_y: int,
        valid_tiles: Optional[Set[str]] = None,
        parent=None
    ):
        super().__init__(parent)
        
        self.atlas = atlas
        self.cell_x = cell_x
        self.cell_y = cell_y
        self.valid_tiles = valid_tiles or set()
        self.all_tiles = atlas.get_enabled_tile_ids()
        self._filter_valid = len(self.valid_tiles) > 0 and self.valid_tiles != self.all_tiles
        
        self.selected_tile_id: Optional[str] = None
        
        self._setup_ui()
    
    def _setup_ui(self):
        self.setWindowTitle(f"Select Tile for Cell ({self.cell_x}, {self.cell_y})")
        self.setMinimumSize(400, 300)
        self.setMaximumSize(800, 600)
        
        # Dark theme
        self.setStyleSheet("""
            QDialog {
                background-color: #1e1e22;
                color: #e0e0e0;
            }
            QLabel {
                color: #e0e0e0;
            }
            QCheckBox {
                color: #e0e0e0;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
            }
            QPushButton {
                background-color: #2a2a30;
                border: 1px solid #404045;
                border-radius: 4px;
                padding: 6px 12px;
                color: #e0e0e0;
            }
            QPushButton:hover {
                background-color: #353540;
                border-color: #505055;
            }
            QPushButton:pressed {
                background-color: #404050;
            }
            QScrollArea {
                border: 1px solid #303035;
                background-color: #1a1a1e;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        
        # Header
        header = QLabel(f"Cell ({self.cell_x}, {self.cell_y})")
        header.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(header)
        
        # Filter checkbox
        if self.valid_tiles and self.valid_tiles != self.all_tiles:
            self._filter_checkbox = QCheckBox("Show only valid tiles for neighbors")
            self._filter_checkbox.setChecked(True)
            self._filter_checkbox.toggled.connect(self._on_filter_changed)
            layout.addWidget(self._filter_checkbox)
            
            # Info label
            info = QLabel(f"{len(self.valid_tiles)} of {len(self.all_tiles)} tiles valid")
            info.setStyleSheet("color: #808080; font-size: 11px;")
            layout.addWidget(info)
        else:
            self._filter_checkbox = None
            if not self.valid_tiles:
                # Cross cell: no tile fits, picking one clears conflicting neighbors
                note = QLabel("No tile fits the neighbors. Your pick will clear conflicting neighbors.")
                note.setStyleSheet("color: #d08080; font-size: 11px;")
                note.setWordWrap(True)
                layout.addWidget(note)

        # Scroll area for tiles
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        self._tiles_container = QWidget()
        self._tiles_layout = QGridLayout(self._tiles_container)
        self._tiles_layout.setSpacing(8)
        self._tiles_layout.setContentsMargins(8, 8, 8, 8)
        
        scroll.setWidget(self._tiles_container)
        layout.addWidget(scroll, 1)
        
        # Populate tiles
        self._populate_tiles()
        
        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)
        
        clear_btn = QPushButton("Clear Cell")
        clear_btn.clicked.connect(self._on_clear)
        btn_layout.addWidget(clear_btn)
        
        btn_layout.addStretch()
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        
        layout.addLayout(btn_layout)
    
    def _populate_tiles(self):
        """Populate the tile grid."""
        # Clear existing
        while self._tiles_layout.count():
            item = self._tiles_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # Determine which tiles to show
        if self._filter_checkbox and self._filter_checkbox.isChecked():
            tiles_to_show = self.valid_tiles
        else:
            tiles_to_show = self.all_tiles
        
        # Sort tiles by base_tile_id, then by variant
        sorted_ids = sorted(tiles_to_show, key=lambda tid: (
            self.atlas.tiles[tid].base_tile_id if tid in self.atlas.tiles else "",
            self.atlas.tiles[tid].rotation if tid in self.atlas.tiles else 0,
            self.atlas.tiles[tid].flip_x if tid in self.atlas.tiles else False,
            self.atlas.tiles[tid].flip_y if tid in self.atlas.tiles else False
        ))
        
        # Calculate columns based on dialog width
        cols = 5
        
        row = 0
        col = 0
        
        for tile_id in sorted_ids:
            variant = self.atlas.tiles.get(tile_id)
            if variant is None:
                continue
            
            btn = TileButton(variant, self.atlas)
            btn.clicked.connect(lambda tid=tile_id: self._on_tile_clicked(tid))
            
            # Disable if not valid (when showing all)
            if self._filter_checkbox and not self._filter_checkbox.isChecked():
                if tile_id not in self.valid_tiles and self.valid_tiles:
                    btn.setEnabled(False)
            
            self._tiles_layout.addWidget(btn, row, col)
            
            col += 1
            if col >= cols:
                col = 0
                row += 1
        
        # Add spacer
        self._tiles_layout.setRowStretch(row + 1, 1)
    
    def _on_filter_changed(self, checked: bool):
        """Handle filter checkbox change."""
        self._populate_tiles()
    
    def _on_tile_clicked(self, tile_id: str):
        """Handle tile button click."""
        self.selected_tile_id = tile_id
        self.tile_selected.emit(tile_id)
        self.accept()
    
    def _on_clear(self):
        """Handle clear cell button."""
        self.selected_tile_id = ""  # Empty string = clear
        self.accept()
    
    @staticmethod
    def get_tile(
        atlas: TileAtlas,
        cell_x: int,
        cell_y: int,
        valid_tiles: Optional[Set[str]] = None,
        parent=None
    ) -> Optional[str]:
        """
        Static method to show dialog and get selected tile.
        
        Returns:
            tile_id if selected, empty string "" if cleared, None if cancelled
        """
        dialog = TileDialog(atlas, cell_x, cell_y, valid_tiles, parent)
        result = dialog.exec()
        
        if result == QDialog.Accepted:
            # Returns tile_id, "" for clear, or None if not set
            return dialog.selected_tile_id if dialog.selected_tile_id is not None else ""
        return None  # Cancelled

