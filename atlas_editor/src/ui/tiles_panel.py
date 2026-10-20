"""
Tiles panel - displays imported tiles and allows creating transform variants.
Supports multi-selection with Ctrl+click and Alt+click for transform-only selection.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QScrollArea,
    QLabel, QLineEdit, QFileDialog, QMessageBox, QFrame, QGridLayout,
    QMenu, QSizePolicy, QToolButton
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap, QImage, QAction, QCursor, QKeySequence, QShortcut
from PIL import Image
from pathlib import Path
import re
from typing import Optional, Dict, Set

from ..models import Atlas, BaseTile, Tile
from ..core import Transform
from ..core.tiled_import import read_tileset
from .widgets import TileThumbnail, CollapsibleSection


class TilesPanel(QWidget):
    """
    Panel for managing tiles: import, view, create transforms.
    """
    tile_selected = Signal(str)  # Emits tile_id when editing tile changes
    atlas_modified = Signal()    # Emits when atlas is modified
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._atlas: Optional[Atlas] = None
        self._image_cache: Dict[str, Image.Image] = {}
        self._selected_tile_ids: Set[str] = set()
        self._editing_tile_id: Optional[str] = None
        self._thumbnails: Dict[str, TileThumbnail] = {}
        
        self._setup_ui()
        self._setup_shortcuts()
    
    def _setup_shortcuts(self):
        self.select_all_shortcut = QShortcut(QKeySequence.StandardKey.SelectAll, self)
        self.select_all_shortcut.activated.connect(self._on_select_all)
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(3)
        
        # Header with selection count
        header_layout = QHBoxLayout()
        header = QLabel("TILES")
        header.setStyleSheet("font-weight: bold; font-size: 11px; color: #aaa;")
        header_layout.addWidget(header)
        header_layout.addStretch()
        self.selection_label = QLabel("")
        self.selection_label.setStyleSheet("color: #888; font-size: 10px;")
        header_layout.addWidget(self.selection_label)
        layout.addLayout(header_layout)
        
        # Import buttons (compact)
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(3)
        
        self.btn_import_file = QPushButton("+ File")
        self.btn_import_file.setToolTip("Import single tile image")
        self.btn_import_file.clicked.connect(self._on_import_file)
        btn_layout.addWidget(self.btn_import_file)
        
        self.btn_import_folder = QPushButton("+ Folder")
        self.btn_import_folder.setToolTip("Import all images from folder")
        self.btn_import_folder.clicked.connect(self._on_import_folder)
        btn_layout.addWidget(self.btn_import_folder)
        
        layout.addLayout(btn_layout)
        
        # Filter
        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("Filter...")
        self.filter_input.setStyleSheet("font-size: 10px; padding: 3px;")
        self.filter_input.textChanged.connect(self._on_filter_changed)
        layout.addWidget(self.filter_input)
        
        # Tiles scroll area (main content - gets most space)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet("""
            QScrollArea { border: 1px solid #3a3a3a; background-color: #2a2a2a; }
        """)
        
        self.tiles_container = QWidget()
        self.tiles_layout = QGridLayout(self.tiles_container)
        self.tiles_layout.setSpacing(4)
        self.tiles_layout.setContentsMargins(4, 4, 4, 4)
        self.tiles_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        
        self.scroll_area.setWidget(self.tiles_container)
        layout.addWidget(self.scroll_area, 1)  # Stretch factor 1 = takes remaining space
        
        # --- Collapsible: Create Variants ---
        self.variants_section = CollapsibleSection("Create Variants", collapsed=False)
        
        # Transform buttons row
        transform_btns = QHBoxLayout()
        transform_btns.setSpacing(2)
        
        btn_style_small = """
            QPushButton {
                background-color: #404040;
                color: #ccc;
                border: 1px solid #505050;
                border-radius: 2px;
                padding: 3px 6px;
                font-size: 10px;
            }
            QPushButton:hover { background-color: #505050; }
            QPushButton:pressed { background-color: #353535; }
        """
        
        self.btn_rotate = QPushButton("⟳90°")
        self.btn_rotate.setToolTip("Create 90°, 180°, 270° rotations")
        self.btn_rotate.clicked.connect(self._on_create_rotations)
        self.btn_rotate.setStyleSheet(btn_style_small)
        transform_btns.addWidget(self.btn_rotate)
        
        self.btn_flip_x = QPushButton("↔")
        self.btn_flip_x.setToolTip("Flip horizontally")
        self.btn_flip_x.clicked.connect(self._on_create_flip_x)
        self.btn_flip_x.setStyleSheet(btn_style_small)
        transform_btns.addWidget(self.btn_flip_x)
        
        self.btn_flip_y = QPushButton("↕")
        self.btn_flip_y.setToolTip("Flip vertically")
        self.btn_flip_y.clicked.connect(self._on_create_flip_y)
        self.btn_flip_y.setStyleSheet(btn_style_small)
        transform_btns.addWidget(self.btn_flip_y)
        
        self.btn_all_variants = QPushButton("ALL")
        self.btn_all_variants.setToolTip("Create all 8 variants")
        self.btn_all_variants.clicked.connect(self._on_create_all_variants)
        self.btn_all_variants.setStyleSheet("""
            QPushButton {
                background-color: #3a4a3a;
                color: #a0c0a0;
                border: 1px solid #4a5a4a;
                border-radius: 2px;
                padding: 3px 6px;
                font-size: 10px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #4a5a4a; }
        """)
        transform_btns.addWidget(self.btn_all_variants)
        
        self.variants_section.add_layout(transform_btns)
        
        # All tiles button
        self.btn_all_variants_global = QPushButton("✦ ALL for ALL Tiles")
        self.btn_all_variants_global.setToolTip("Create all variants for every tile")
        self.btn_all_variants_global.clicked.connect(self._on_create_all_variants_global)
        self.btn_all_variants_global.setStyleSheet("""
            QPushButton {
                background-color: #3a3a4a;
                color: #a0a0c0;
                border: 1px solid #4a4a5a;
                border-radius: 2px;
                padding: 3px 6px;
                font-size: 10px;
            }
            QPushButton:hover { background-color: #4a4a5a; }
        """)
        self.variants_section.add_widget(self.btn_all_variants_global)
        
        layout.addWidget(self.variants_section)
        
        # --- Collapsible: Delete ---
        self.delete_section = CollapsibleSection("Delete", collapsed=True)
        
        self.btn_delete = QPushButton("🗑 Delete Selected")
        self.btn_delete.setToolTip("Delete selected tile(s)")
        self.btn_delete.clicked.connect(self._on_delete_tiles)
        self.btn_delete.setStyleSheet("""
            QPushButton {
                background-color: #4a3535;
                color: #c0a0a0;
                border: 1px solid #5a4545;
                border-radius: 2px;
                padding: 3px 6px;
                font-size: 10px;
            }
            QPushButton:hover { background-color: #5a4545; }
        """)
        self.delete_section.add_widget(self.btn_delete)
        
        layout.addWidget(self.delete_section)
        
        # Validation summary (always visible, compact)
        self.validation_label = QLabel("")
        self.validation_label.setStyleSheet("color: #f0a030; font-size: 9px;")
        self.validation_label.setWordWrap(True)
        layout.addWidget(self.validation_label)
        
        # Hint (very small)
        hint_label = QLabel("Ctrl+click: multi • Alt+click: no edit • Ctrl+A: all")
        hint_label.setStyleSheet("color: #444; font-size: 8px;")
        layout.addWidget(hint_label)
        
        # Style import buttons
        import_btn_style = """
            QPushButton {
                background-color: #404040;
                color: #ccc;
                border: 1px solid #505050;
                border-radius: 2px;
                padding: 3px 8px;
                font-size: 10px;
            }
            QPushButton:hover { background-color: #505050; }
            QPushButton:pressed { background-color: #353535; }
        """
        self.btn_import_file.setStyleSheet(import_btn_style)
        self.btn_import_folder.setStyleSheet(import_btn_style)
    
    def _update_selection_label(self):
        count = len(self._selected_tile_ids)
        if count == 0:
            self.selection_label.setText("")
        elif count == 1:
            self.selection_label.setText("1 sel")
        else:
            self.selection_label.setText(f"{count} sel")
    
    def set_atlas(self, atlas: Optional[Atlas]) -> None:
        self._atlas = atlas
        self._image_cache.clear()
        self._thumbnails.clear()
        self._selected_tile_ids.clear()
        self._editing_tile_id = None
        self._refresh_tiles()
        self._update_selection_label()
    
    def _refresh_tiles(self) -> None:
        while self.tiles_layout.count():
            item = self.tiles_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._thumbnails.clear()
        
        if not self._atlas:
            return
        
        filter_text = self.filter_input.text().lower()
        row = 0
        col = 0
        max_cols = 4
        
        for base_tile in self._atlas.base_tiles:
            variants = self._atlas.get_tiles_for_base(base_tile.id)
            
            for tile in variants:
                if filter_text and filter_text not in tile.id.lower():
                    continue
                
                thumbnail = TileThumbnail(tile.id)
                thumbnail.clicked.connect(self._on_tile_clicked)
                thumbnail.right_clicked.connect(self._on_tile_right_clicked)
                
                image = self._get_tile_image(tile)
                if image:
                    thumbnail.set_image(image)
                
                if tile.id in self._selected_tile_ids:
                    thumbnail.set_selected(True)
                
                self._thumbnails[tile.id] = thumbnail
                self.tiles_layout.addWidget(thumbnail, row, col)
                
                col += 1
                if col >= max_cols:
                    col = 0
                    row += 1
        
        self.tiles_layout.setRowStretch(row + 1, 1)
    
    def _get_tile_image(self, tile: Tile) -> Optional[Image.Image]:
        if not self._atlas:
            return None
        
        if tile.base_tile_id not in self._image_cache:
            base_tile = self._atlas.get_base_tile(tile.base_tile_id)
            if not base_tile:
                return None
            
            try:
                source_path = Path(base_tile.source_path)
                
                # If path is already absolute, use it directly
                if source_path.is_absolute():
                    image_path = source_path
                else:
                    # Otherwise, resolve relative to atlas location
                    atlas_dir = Path(self._atlas.file_path).parent if self._atlas.file_path else Path('.')
                    image_path = atlas_dir / source_path
                
                if image_path.exists():
                    self._image_cache[tile.base_tile_id] = Image.open(image_path).convert('RGBA')
                else:
                    print(f"Image not found: {image_path}")
                    return None
            except Exception as e:
                print(f"Failed to load image {base_tile.source_path}: {e}")
                return None
        
        image = self._image_cache.get(tile.base_tile_id)
        if not image:
            return None
        
        result = image.copy()
        
        if tile.rotation != 0:
            result = result.rotate(-tile.rotation, expand=False)
        
        if tile.flip_x:
            result = result.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        
        if tile.flip_y:
            result = result.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        
        return result
    
    def _on_tile_clicked(self, tile_id: str, ctrl_held: bool, alt_held: bool) -> None:
        if ctrl_held:
            if tile_id in self._selected_tile_ids:
                self._selected_tile_ids.remove(tile_id)
                if tile_id in self._thumbnails:
                    self._thumbnails[tile_id].set_selected(False)
            else:
                self._selected_tile_ids.add(tile_id)
                if tile_id in self._thumbnails:
                    self._thumbnails[tile_id].set_selected(True)
        elif alt_held:
            for tid in self._selected_tile_ids:
                if tid in self._thumbnails:
                    self._thumbnails[tid].set_selected(False)
            self._selected_tile_ids.clear()
            self._selected_tile_ids.add(tile_id)
            if tile_id in self._thumbnails:
                self._thumbnails[tile_id].set_selected(True)
        else:
            for tid in self._selected_tile_ids:
                if tid in self._thumbnails:
                    self._thumbnails[tid].set_selected(False)
            self._selected_tile_ids.clear()
            
            self._selected_tile_ids.add(tile_id)
            self._editing_tile_id = tile_id
            if tile_id in self._thumbnails:
                self._thumbnails[tile_id].set_selected(True)
            
            self.tile_selected.emit(tile_id)
        
        self._update_selection_label()
    
    def _on_select_all(self) -> None:
        for tile_id, thumbnail in self._thumbnails.items():
            self._selected_tile_ids.add(tile_id)
            thumbnail.set_selected(True)
        self._update_selection_label()
    
    def _on_tile_right_clicked(self, tile_id: str) -> None:
        if not self._atlas:
            return
        
        if tile_id not in self._selected_tile_ids:
            for tid in self._selected_tile_ids:
                if tid in self._thumbnails:
                    self._thumbnails[tid].set_selected(False)
            self._selected_tile_ids.clear()
            self._selected_tile_ids.add(tile_id)
            if tile_id in self._thumbnails:
                self._thumbnails[tile_id].set_selected(True)
            self._update_selection_label()
        
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background-color: #3a3a3a; color: #e0e0e0; border: 1px solid #555; }
            QMenu::item:selected { background-color: #4a90d9; }
        """)
        
        all_variants_action = menu.addAction("✦ Create ALL Variants")
        all_variants_action.triggered.connect(self._on_create_all_variants)
        
        menu.addSeparator()
        
        count = len(self._selected_tile_ids)
        if count > 1:
            delete_action = menu.addAction(f"🗑 Delete {count} Selected")
        else:
            tile = self._atlas.get_tile(tile_id)
            if tile and tile.is_original:
                delete_action = menu.addAction("🗑 Delete Base Tile")
            else:
                delete_action = menu.addAction("🗑 Delete Variant")
        delete_action.triggered.connect(self._on_delete_tiles)
        
        menu.exec(QCursor.pos())
    
    def _on_filter_changed(self, text: str) -> None:
        self._refresh_tiles()
    
    def _on_import_file(self) -> None:
        if not self._atlas:
            QMessageBox.warning(self, "No Atlas", "Create or open an atlas first.")
            return
        
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Import Tile", "", "Images (*.png *.jpg *.jpeg *.bmp *.gif)"
        )
        if file_path:
            self._import_image(file_path)
    
    def _on_import_folder(self) -> None:
        if not self._atlas:
            QMessageBox.warning(self, "No Atlas", "Create or open an atlas first.")
            return
        
        folder_path = QFileDialog.getExistingDirectory(self, "Import Folder")
        if folder_path:
            folder = Path(folder_path)
            extensions = {'.png', '.jpg', '.jpeg', '.bmp', '.gif'}
            imported = 0
            for file_path in folder.iterdir():
                if file_path.suffix.lower() in extensions:
                    if self._import_image(str(file_path), show_errors=False):
                        imported += 1
            
            if imported > 0:
                QMessageBox.information(self, "Done", f"Imported {imported} tiles.")
            else:
                QMessageBox.warning(self, "No Tiles", "No valid images found.")
    
    def _import_image(self, file_path: str, show_errors: bool = True) -> bool:
        try:
            path = Path(file_path)
            image = Image.open(path)
            
            if image.width != image.height:
                if show_errors:
                    QMessageBox.warning(self, "Invalid", f"Must be square. Got {image.width}x{image.height}.")
                return False
            
            base_id = path.stem
            
            if self._atlas.get_base_tile(base_id):
                if show_errors:
                    QMessageBox.warning(self, "Duplicate", f"'{base_id}' already exists.")
                return False
            
            if self._atlas.file_path:
                atlas_dir = Path(self._atlas.file_path).parent
                try:
                    relative_path = path.relative_to(atlas_dir)
                except ValueError:
                    relative_path = path
            else:
                relative_path = path
            
            base_tile = BaseTile(
                id=base_id,
                source_path=str(relative_path),
                width=image.width,
                height=image.height
            )
            
            self._atlas.add_base_tile(base_tile)
            self._image_cache[base_id] = image.convert('RGBA')
            
            self._refresh_tiles()
            self.atlas_modified.emit()
            return True
            
        except Exception as e:
            if show_errors:
                QMessageBox.critical(self, "Error", f"Failed: {e}")
            return False
    
    def import_tiled_dialog(self) -> None:
        if not self._atlas:
            QMessageBox.warning(self, "No Atlas", "Create or open an atlas first.")
            return
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Import Tiled Tileset",
            "", "Tiled (*.tsx *.tmx *.tsj *.json);;All Files (*)"
        )
        if file_path:
            self.import_tiled_tileset(file_path)

    def import_tiled_tileset(self, file_path: str) -> None:
        """Create one base tile per tile in a Tiled tileset; each tile is saved as a PNG beside it."""
        if not self._atlas:
            QMessageBox.warning(self, "No Atlas", "Create or open an atlas first.")
            return
        try:
            tiles = read_tileset(file_path)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to read Tiled tileset:\n{e}")
            return

        source = Path(file_path)
        out_dir = source.parent / f"{source.stem}_tiles"
        out_dir.mkdir(exist_ok=True)

        added = skipped = 0
        for tile in tiles:
            if self._atlas.get_base_tile(tile.id):
                skipped += 1
                continue
            safe_name = re.sub(r"[^\w.-]", "_", tile.id)
            image_path = out_dir / f"{safe_name}.png"
            tile.image.save(image_path, "PNG")

            relative_path = image_path
            if self._atlas.file_path:
                try:
                    relative_path = image_path.relative_to(Path(self._atlas.file_path).parent)
                except ValueError:
                    pass

            self._atlas.add_base_tile(BaseTile(
                id=tile.id,
                source_path=str(relative_path),
                width=tile.image.width,
                height=tile.image.height,
            ))
            self._image_cache[tile.id] = tile.image.convert('RGBA')
            added += 1

        if added:
            self._refresh_tiles()
            self.atlas_modified.emit()

        message = f"Imported {added} tile(s) from {source.name}."
        if skipped:
            message += f" Skipped {skipped} already in the atlas."
        QMessageBox.information(self, "Tiled Tileset", message)

    def _get_first_selected_tile(self) -> Optional[Tile]:
        if not self._atlas or not self._selected_tile_ids:
            return None
        tile_id = self._editing_tile_id if self._editing_tile_id in self._selected_tile_ids else next(iter(self._selected_tile_ids))
        return self._atlas.get_tile(tile_id)
    
    def _on_create_rotations(self) -> None:
        tile = self._get_first_selected_tile()
        if not self._atlas or not tile:
            return
        
        for rotation in [90, 180, 270]:
            self._atlas.add_tile_variant(tile.base_tile_id, rotation=rotation, flip_x=tile.flip_x, flip_y=tile.flip_y)
        
        print(f"[TilesPanel] Created rotations. Atlas now has {len(self._atlas.tiles)} tiles")
        self._refresh_tiles()
        self.atlas_modified.emit()
    
    def _on_create_flip_x(self) -> None:
        tile = self._get_first_selected_tile()
        if not self._atlas or not tile:
            return
        
        self._atlas.add_tile_variant(tile.base_tile_id, rotation=tile.rotation, flip_x=not tile.flip_x, flip_y=tile.flip_y)
        self._refresh_tiles()
        self.atlas_modified.emit()
    
    def _on_create_flip_y(self) -> None:
        tile = self._get_first_selected_tile()
        if not self._atlas or not tile:
            return
        
        self._atlas.add_tile_variant(tile.base_tile_id, rotation=tile.rotation, flip_x=tile.flip_x, flip_y=not tile.flip_y)
        self._refresh_tiles()
        self.atlas_modified.emit()
    
    def _on_create_all_variants(self) -> None:
        tile = self._get_first_selected_tile()
        if not self._atlas or not tile:
            return
        
        created = self._create_all_variants_for_base(tile.base_tile_id)
        if created > 0:
            self._refresh_tiles()
            self.atlas_modified.emit()
    
    def _create_all_variants_for_base(self, base_id: str) -> int:
        created = 0
        for rotation in [0, 90, 180, 270]:
            for flip_x in [False, True]:
                if rotation == 0 and not flip_x:
                    continue
                tile_id = Tile.create_id(base_id, rotation, flip_x, False)
                if not self._atlas.get_tile(tile_id):
                    self._atlas.add_tile_variant(base_id, rotation, flip_x, False)
                    created += 1
        return created
    
    def _on_create_all_variants_global(self) -> None:
        if not self._atlas or not self._atlas.base_tiles:
            return
        
        result = QMessageBox.question(
            self, "Create All",
            f"Create variants for all {len(self._atlas.base_tiles)} tiles?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        
        total = 0
        for base_tile in self._atlas.base_tiles:
            total += self._create_all_variants_for_base(base_tile.id)
        
        if total > 0:
            self._refresh_tiles()
            self.atlas_modified.emit()
    
    def _on_delete_tiles(self) -> None:
        if not self._atlas or not self._selected_tile_ids:
            return
        
        base_tile_ids = set()
        variant_ids = set()
        
        for tile_id in self._selected_tile_ids:
            tile = self._atlas.get_tile(tile_id)
            if tile:
                if tile.is_original:
                    base_tile_ids.add(tile.base_tile_id)
                else:
                    variant_ids.add(tile_id)
        
        variant_ids = {vid for vid in variant_ids 
                       if self._atlas.get_tile(vid) and 
                       self._atlas.get_tile(vid).base_tile_id not in base_tile_ids}
        
        msg_parts = []
        if base_tile_ids:
            msg_parts.append(f"{len(base_tile_ids)} base tile(s)")
        if variant_ids:
            msg_parts.append(f"{len(variant_ids)} variant(s)")
        
        if not msg_parts:
            return
        
        result = QMessageBox.warning(
            self, "Delete",
            f"Delete {', '.join(msg_parts)}?\n\nAll rules will be removed.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        
        for base_id in base_tile_ids:
            if base_id in self._image_cache:
                del self._image_cache[base_id]
            self._atlas.remove_base_tile(base_id)
        
        for tile_id in variant_ids:
            self._atlas.remove_tile(tile_id)
        
        self._selected_tile_ids.clear()
        self._editing_tile_id = None
        
        self._refresh_tiles()
        self._update_selection_label()
        self.tile_selected.emit("")
        self.atlas_modified.emit()
    
    def update_validation(self, warnings: list[str]) -> None:
        if warnings:
            self.validation_label.setText(f"⚠ {len(warnings)} issues")
        else:
            self.validation_label.setText("")
    
    def select_tile(self, tile_id: str) -> None:
        if tile_id:
            self._on_tile_clicked(tile_id, False, False)
        else:
            for tid in self._selected_tile_ids:
                if tid in self._thumbnails:
                    self._thumbnails[tid].set_selected(False)
            self._selected_tile_ids.clear()
            self._editing_tile_id = None
            self._update_selection_label()
    
    def get_tile_image(self, tile_id: str) -> Optional[Image.Image]:
        if not self._atlas:
            return None
        tile = self._atlas.get_tile(tile_id)
        if tile:
            return self._get_tile_image(tile)
        return None
