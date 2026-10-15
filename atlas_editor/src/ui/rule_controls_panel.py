"""
Rule controls panel - side sections for adding/editing adjacency rules.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QComboBox
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QWheelEvent
from PIL import Image
from typing import Optional, Dict, List

from ..models import Atlas, Tile
from ..core import SIDES
from .widgets import TileThumbnail, PercentageSpinBox
from .tile_picker_dialog import TilePickerDialog


class NoScrollComboBox(QComboBox):
    """ComboBox that ignores mouse wheel events to prevent accidental changes."""
    def wheelEvent(self, event: QWheelEvent) -> None:
        # Ignore wheel events - let parent scroll area handle them
        event.ignore()


class NeighborRow(QWidget):
    """Row for a neighbor with thumbnail, variant selector, weight, remove."""
    weight_changed = Signal(str, float)
    remove_requested = Signal(str)
    variant_changed = Signal(str, str)
    
    def __init__(self, neighbor_id: str, weight: float, image: Optional[Image.Image],
                 auto_generated: bool = False, available_variants: Optional[List[str]] = None,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.neighbor_id = neighbor_id
        self.available_variants = available_variants or []
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 3, 4, 3)
        layout.setSpacing(6)
        
        # Thumbnail
        self.thumbnail = TileThumbnail(neighbor_id)
        self.thumbnail.THUMBNAIL_SIZE = 36
        self.thumbnail.setFixedSize(42, 42)
        if image:
            self.thumbnail.set_image(image)
        layout.addWidget(self.thumbnail)
        
        # Variant selector or name
        if len(self.available_variants) > 1:
            self.variant_combo = NoScrollComboBox()
            self.variant_combo.setStyleSheet("""
                QComboBox {
                    background-color: #383838;
                    color: #ddd;
                    border: 1px solid #4a4a4a;
                    border-radius: 3px;
                    padding: 3px 6px;
                    font-size: 11px;
                    min-width: 90px;
                }
                QComboBox:hover { border-color: #5a5a5a; }
                QComboBox::drop-down { border: none; width: 18px; }
                QComboBox QAbstractItemView {
                    background-color: #383838;
                    color: #ddd;
                    selection-background-color: #4a90d9;
                }
            """)
            for v in self.available_variants:
                self.variant_combo.addItem(self._variant_display(v), v)
            idx = self.variant_combo.findData(neighbor_id)
            if idx >= 0:
                self.variant_combo.setCurrentIndex(idx)
            self.variant_combo.currentIndexChanged.connect(self._on_variant_changed)
            layout.addWidget(self.variant_combo, 1)
        else:
            name_lbl = QLabel(neighbor_id)
            name_lbl.setStyleSheet("color: #ccc; font-size: 11px;")
            name_lbl.setWordWrap(True)
            layout.addWidget(name_lbl, 1)
        
        if auto_generated:
            auto_lbl = QLabel("⚡")
            auto_lbl.setToolTip("Auto-generated rule")
            auto_lbl.setStyleSheet("color: #777;")
            layout.addWidget(auto_lbl)
        
        # Weight
        self.weight_spin = PercentageSpinBox()
        self.weight_spin.setValue(weight)
        self.weight_spin.valueChanged.connect(lambda v: self.weight_changed.emit(self.neighbor_id, v))
        layout.addWidget(self.weight_spin)
        
        # Remove button
        rm_btn = QPushButton("×")
        rm_btn.setFixedSize(22, 22)
        rm_btn.setStyleSheet("""
            QPushButton {
                background-color: #4a3535;
                color: #caa;
                border: none;
                border-radius: 11px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #5a4545; }
        """)
        rm_btn.clicked.connect(lambda: self.remove_requested.emit(self.neighbor_id))
        layout.addWidget(rm_btn)
    
    def _variant_display(self, vid: str) -> str:
        parts = vid.split('_')
        if len(parts) == 1:
            return "Original"
        transforms = []
        for p in parts[1:]:
            if p.startswith('r'):
                transforms.append(f"↻{p[1:]}°")
            elif p == 'fx':
                transforms.append("↔")
            elif p == 'fy':
                transforms.append("↕")
        return " ".join(transforms) if transforms else vid
    
    def _on_variant_changed(self, index: int):
        if hasattr(self, 'variant_combo'):
            new_id = self.variant_combo.itemData(index)
            if new_id and new_id != self.neighbor_id:
                old_id = self.neighbor_id
                self.neighbor_id = new_id
                self.variant_changed.emit(old_id, new_id)


class SideSection(QFrame):
    """Section for editing neighbors on one side of a tile."""
    rule_changed = Signal()
    neighbors_updated = Signal(str, list)
    
    def __init__(self, side: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.side = side
        self._atlas: Optional[Atlas] = None
        self._tile_id: Optional[str] = None
        self._get_image_fn = None

        self.setStyleSheet("""
            SideSection {
                background-color: #2d2d2d;
                border: 1px solid #3d3d3d;
                border-radius: 4px;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)
        
        # Header
        header = QHBoxLayout()
        side_lbl = QLabel(f"{side.upper()}")
        side_lbl.setStyleSheet("font-weight: bold; color: #999; font-size: 12px;")
        header.addWidget(side_lbl)
        header.addStretch()
        
        self.total_lbl = QLabel("0%")
        self.total_lbl.setStyleSheet("color: #777; font-size: 11px;")
        header.addWidget(self.total_lbl)
        
        self.warn_lbl = QLabel("⚠")
        self.warn_lbl.setStyleSheet("color: #e0a030; font-size: 12px;")
        self.warn_lbl.hide()
        header.addWidget(self.warn_lbl)
        
        layout.addLayout(header)
        
        # Neighbors
        self.neighbors_widget = QWidget()
        self.neighbors_layout = QVBoxLayout(self.neighbors_widget)
        self.neighbors_layout.setContentsMargins(0, 0, 0, 0)
        self.neighbors_layout.setSpacing(2)
        layout.addWidget(self.neighbors_widget)
        
        # Add button
        self.add_btn = QPushButton("+ Add Neighbor")
        self.add_btn.setStyleSheet("""
            QPushButton {
                background-color: #2a3a2a;
                color: #8ab08a;
                border: 1px dashed #3a4a3a;
                border-radius: 3px;
                padding: 5px;
                font-size: 11px;
            }
            QPushButton:hover { background-color: #3a4a3a; color: #a0c0a0; }
        """)
        self.add_btn.clicked.connect(self._on_add)
        layout.addWidget(self.add_btn)
    
    def set_context(self, atlas: Optional[Atlas], tile_id: Optional[str], get_image_fn):
        tiles_count = len(atlas.tiles) if atlas else 0
        print(f"[SideSection.set_context] side={self.side}, atlas_tiles={tiles_count}, tile_id={tile_id}")
        self._atlas = atlas
        self._tile_id = tile_id
        self._get_image_fn = get_image_fn
        self._refresh()
    
    def _get_variants(self, tile_id: str) -> List[str]:
        if not self._atlas:
            return [tile_id]
        tile = self._atlas.get_tile(tile_id)
        if not tile:
            return [tile_id]
        return [t.id for t in self._atlas.get_tiles_for_base(tile.base_tile_id)]
    
    def _refresh(self):
        # Remove every old row from the layout, including any not tied to a unique rule id
        while self.neighbors_layout.count():
            item = self.neighbors_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
                item.widget().deleteLater()

        if not self._atlas or not self._tile_id:
            self.total_lbl.setText("0%")
            self.warn_lbl.hide()
            self.neighbors_updated.emit(self.side, [])
            return
        
        rules = self._atlas.get_rules_for_tile(self._tile_id, self.side)
        total = 0.0
        neighbor_ids = []
        
        for rule in rules:
            neighbor_ids.append(rule.neighbor_id)
            img = self._get_image_fn(rule.neighbor_id) if self._get_image_fn else None
            variants = self._get_variants(rule.neighbor_id)
            
            row = NeighborRow(rule.neighbor_id, rule.weight, img, rule.auto_generated, variants)
            row.weight_changed.connect(self._on_weight_changed)
            row.remove_requested.connect(self._on_remove)
            row.variant_changed.connect(self._on_variant_changed)
            
            self.neighbors_layout.addWidget(row)
            total += rule.weight
        
        self.total_lbl.setText(f"{total:.0f}%")
        
        if rules and abs(total - 100.0) > 0.1:
            self.warn_lbl.show()
            self.warn_lbl.setToolTip(f"Total: {total:.1f}% (should be 100%)")
            self.total_lbl.setStyleSheet("color: #e0a030; font-size: 11px;")
        elif not rules:
            self.warn_lbl.show()
            self.warn_lbl.setToolTip("No neighbors defined")
            self.total_lbl.setStyleSheet("color: #c06060; font-size: 11px;")
        else:
            self.warn_lbl.hide()
            self.total_lbl.setStyleSheet("color: #70a070; font-size: 11px;")
        
        self.neighbors_updated.emit(self.side, neighbor_ids)
    
    def _on_add(self):
        if not self._atlas or not self._tile_id:
            print(f"[SideSection._on_add] Aborted: atlas={self._atlas is not None}, tile_id={self._tile_id}")
            return
        
        print(f"[SideSection._on_add] Opening picker. Atlas has {len(self._atlas.tiles)} tiles")
        
        # Get SPECIFIC tiles already used for THIS side (exclude only these exact tiles)
        exclude = set()
        for r in self._atlas.get_rules_for_tile(self._tile_id, self.side):
            exclude.add(r.neighbor_id)
        
        # Get all tiles that are already neighbors on OTHER sides (highlight these)
        already_neighbor_ids = set()
        all_sides = ['top', 'right', 'bottom', 'left']
        for other_side in all_sides:
            if other_side == self.side:
                continue
            for r in self._atlas.get_rules_for_tile(self._tile_id, other_side):
                already_neighbor_ids.add(r.neighbor_id)
        
        # Also highlight tiles that are neighbors on THIS side (already added)
        for r in self._atlas.get_rules_for_tile(self._tile_id, self.side):
            already_neighbor_ids.add(r.neighbor_id)
        
        dialog = TilePickerDialog(
            self._atlas, 
            self._get_image_fn, 
            exclude_ids=exclude,
            already_neighbor_ids=already_neighbor_ids,
            side_name=self.side,
            tile_name=self._tile_id,
            parent=self.window()
        )
        if dialog.exec():
            selected_tiles = dialog.get_selected_tiles()
            if selected_tiles:
                for tile_id in selected_tiles:
                    self._atlas.add_rule(self._tile_id, self.side, tile_id, 100.0, False)
                self._refresh()
                self.rule_changed.emit()
    
    def _on_weight_changed(self, neighbor_id: str, weight: float):
        if not self._atlas or not self._tile_id:
            return
        rule = self._atlas.get_rule(self._tile_id, self.side, neighbor_id)
        if rule:
            rule.weight = weight
            self._atlas.modified = True
            self._update_total()
            self.rule_changed.emit()
    
    def _on_remove(self, neighbor_id: str):
        if not self._atlas or not self._tile_id:
            return
        self._atlas.remove_rule(self._tile_id, self.side, neighbor_id)
        self._refresh()
        self.rule_changed.emit()
    
    def _on_variant_changed(self, old_id: str, new_id: str):
        if not self._atlas or not self._tile_id:
            return
        
        old_rule = self._atlas.get_rule(self._tile_id, self.side, old_id)
        if not old_rule:
            return
        
        if not self._atlas.get_tile(new_id):
            tile = self._atlas.get_tile(old_id)
            if tile:
                parts = new_id.split('_')
                base_id = parts[0]
                rotation, flip_x, flip_y = 0, False, False
                for p in parts[1:]:
                    if p.startswith('r'):
                        rotation = int(p[1:])
                    elif p == 'fx':
                        flip_x = True
                    elif p == 'fy':
                        flip_y = True
                self._atlas.add_tile_variant(base_id, rotation, flip_x, flip_y)
        
        weight, auto = old_rule.weight, old_rule.auto_generated
        self._atlas.remove_rule(self._tile_id, self.side, old_id)
        self._atlas.add_rule(self._tile_id, self.side, new_id, weight, auto)
        self._refresh()
        self.rule_changed.emit()
    
    def _update_total(self):
        if not self._atlas or not self._tile_id:
            return
        rules = self._atlas.get_rules_for_tile(self._tile_id, self.side)
        total = sum(r.weight for r in rules)
        self.total_lbl.setText(f"{total:.0f}%")
        
        if abs(total - 100.0) > 0.1:
            self.warn_lbl.show()
            self.total_lbl.setStyleSheet("color: #e0a030; font-size: 11px;")
        else:
            self.warn_lbl.hide()
            self.total_lbl.setStyleSheet("color: #70a070; font-size: 11px;")


class RuleControlsPanel(QWidget):
    """
    Panel with side sections for adding/editing adjacency rules.
    """
    rules_changed = Signal()
    neighbors_updated = Signal(str, list)  # side, neighbor_ids
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._atlas: Optional[Atlas] = None
        self._selected_tile_id: Optional[str] = None
        self._get_image_fn = None
        
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)
        
        # Header
        header = QLabel("ADJACENCY RULES")
        header.setStyleSheet("font-weight: bold; font-size: 12px; color: #888;")
        layout.addWidget(header)
        
        # Scroll area for side sections
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        sides_widget = QWidget()
        sides_layout = QVBoxLayout(sides_widget)
        sides_layout.setContentsMargins(0, 0, 0, 0)
        sides_layout.setSpacing(6)
        
        self.side_sections: Dict[str, SideSection] = {}
        for side in SIDES:
            section = SideSection(side)
            section.rule_changed.connect(self._on_rule_changed)
            section.neighbors_updated.connect(self._on_neighbors_updated)
            self.side_sections[side] = section
            sides_layout.addWidget(section)
        
        sides_layout.addStretch()
        scroll.setWidget(sides_widget)
        layout.addWidget(scroll, 1)
        
        # Normalize button
        self.normalize_btn = QPushButton("Normalize All Weights to 100%")
        self.normalize_btn.setStyleSheet("""
            QPushButton {
                background-color: #3a3a4a;
                color: #a0a0c0;
                border: 1px solid #4a4a5a;
                border-radius: 3px;
                padding: 6px;
                font-size: 11px;
            }
            QPushButton:hover { background-color: #4a4a5a; }
        """)
        self.normalize_btn.clicked.connect(self._on_normalize)
        layout.addWidget(self.normalize_btn)
    
    def set_atlas(self, atlas: Optional[Atlas]) -> None:
        self._atlas = atlas
        self._selected_tile_id = None
        self._update_ui()
    
    def set_image_getter(self, fn) -> None:
        self._get_image_fn = fn
    
    def set_selected_tile(self, tile_id: Optional[str]) -> None:
        self._selected_tile_id = tile_id
        self._update_ui()
    
    def _update_ui(self):
        tiles_count = len(self._atlas.tiles) if self._atlas else 0
        print(f"[RuleControlsPanel._update_ui] atlas_tiles={tiles_count}, selected_tile_id={self._selected_tile_id}")
        if not self._atlas or not self._selected_tile_id:
            print(f"[RuleControlsPanel._update_ui] Setting sections to None context")
            for section in self.side_sections.values():
                section.set_context(None, None, None)
            return
        
        for side, section in self.side_sections.items():
            section.set_context(self._atlas, self._selected_tile_id, self._get_image_fn)
    
    def _on_neighbors_updated(self, side: str, neighbor_ids: list):
        self.neighbors_updated.emit(side, neighbor_ids)
    
    def _on_rule_changed(self):
        self.rules_changed.emit()
    
    def _on_normalize(self):
        if not self._atlas or not self._selected_tile_id:
            return
        
        from ..core.validation import normalize_side_weights
        for side in SIDES:
            normalize_side_weights(self._atlas, self._selected_tile_id, side)
        
        self._update_ui()
        self.rules_changed.emit()
    
    def refresh(self):
        self._update_ui()

