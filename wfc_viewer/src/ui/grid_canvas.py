"""
Zoomable, pannable grid canvas for WFC visualization.
"""

from typing import Optional, Dict, Tuple

from PySide6.QtWidgets import QWidget, QGraphicsView, QGraphicsScene, QGraphicsRectItem
from PySide6.QtGui import (
    QPainter, QColor, QBrush, QPen, QPixmap, QWheelEvent, 
    QMouseEvent, QTransform
)
from PySide6.QtCore import Qt, Signal, QRectF, QPointF

from ..core.tile import TileAtlas
from ..core.wfc_engine import WFCEngine, CellState, EngineState
from ..utils.image_utils import ImageUtils


class GridCanvas(QGraphicsView):
    """
    Zoomable and pannable canvas for displaying the WFC grid.
    
    Signals:
        cell_clicked(x, y): Emitted when a cell is left-clicked
        cell_right_clicked(x, y): Emitted when a cell is right-clicked
    """
    
    cell_clicked = Signal(int, int)
    cell_right_clicked = Signal(int, int)
    
    # Visual settings
    CELL_SIZE = 48  # Base cell size in pixels
    MIN_ZOOM = 0.1
    MAX_ZOOM = 5.0
    GRID_COLOR = QColor(100, 100, 100)
    LOCKED_BORDER_COLOR = QColor(50, 150, 255)
    CONTRADICTION_COLOR = QColor(255, 100, 100)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        
        # Setup view (no smooth transform for pixel art)
        self.setRenderHint(QPainter.Antialiasing, False)
        self.setRenderHint(QPainter.SmoothPixmapTransform, False)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setDragMode(QGraphicsView.NoDrag)
        
        # Dark background
        self.setBackgroundBrush(QBrush(QColor(30, 30, 35)))
        
        # State
        self._engine: Optional[WFCEngine] = None
        self._atlas: Optional[TileAtlas] = None
        self._grid_width = 0
        self._grid_height = 0
        self._zoom = 1.0
        
        # Panning state
        self._panning = False
        self._pan_start = QPointF()
        
        # Cell items cache
        self._cell_items: Dict[Tuple[int, int], QGraphicsRectItem] = {}
        
        # Cached pixmaps
        self._uncollapsed_pixmap: Optional[QPixmap] = None
        self._error_pixmap: Optional[QPixmap] = None
        
        # Contradiction position
        self._contradiction_pos: Optional[Tuple[int, int]] = None
    
    def set_engine(self, engine: WFCEngine):
        """Connect to a WFC engine."""
        self._engine = engine
        
        # Connect signals
        engine.cell_collapsed.connect(self._on_cell_collapsed)
        engine.cell_updated.connect(self._on_cell_updated)
        engine.contradiction_found.connect(self._on_contradiction)
        engine.state_changed.connect(self._on_state_changed)
    
    def set_atlas(self, atlas: TileAtlas):
        """Set the tile atlas."""
        self._atlas = atlas
        self._rebuild_cache()
    
    def setup_grid(self, width: int, height: int):
        """Setup the grid with given dimensions."""
        self._grid_width = width
        self._grid_height = height
        self._contradiction_pos = None
        
        # Clear scene
        self._scene.clear()
        self._cell_items.clear()
        
        # Calculate scene rect
        scene_width = width * self.CELL_SIZE
        scene_height = height * self.CELL_SIZE
        margin = self.CELL_SIZE
        self._scene.setSceneRect(
            -margin, -margin,
            scene_width + 2 * margin,
            scene_height + 2 * margin
        )
        
        # Create cell items
        pen = QPen(self.GRID_COLOR)
        pen.setWidth(1)
        
        for y in range(height):
            for x in range(width):
                rect = QGraphicsRectItem(
                    x * self.CELL_SIZE,
                    y * self.CELL_SIZE,
                    self.CELL_SIZE,
                    self.CELL_SIZE
                )
                rect.setPen(pen)
                rect.setBrush(QBrush(self._get_uncollapsed_pixmap()))
                rect.setData(0, (x, y))  # Store position
                self._scene.addItem(rect)
                self._cell_items[(x, y)] = rect
        
        # Center view
        self.centerOn(scene_width / 2, scene_height / 2)
    
    def update_cell(self, x: int, y: int):
        """Update visual for a specific cell."""
        if self._engine is None or self._atlas is None:
            return
        
        item = self._cell_items.get((x, y))
        if item is None:
            return

        item.setToolTip("")
        cell = self._engine.get_cell(x, y)
        if cell is None:
            return

        if cell.is_collapsed:
            # Get tile pixmap
            variant = self._atlas.tiles.get(cell.collapsed_tile)
            if variant:
                pixmap = variant.get_pixmap(self._atlas.base_tiles, self.CELL_SIZE)
                
                # Add locked border if needed
                if cell.locked:
                    pixmap = ImageUtils.add_locked_border(pixmap, self.LOCKED_BORDER_COLOR)
                
                item.setBrush(QBrush(pixmap))
            else:
                item.setBrush(QBrush(self._get_error_pixmap()))
        else:
            # Show uncollapsed state
            if self._contradiction_pos == (x, y):
                item.setBrush(QBrush(self._get_error_pixmap()))
                item.setToolTip(self._engine.describe_conflict(x, y))
            else:
                item.setBrush(QBrush(self._get_uncollapsed_pixmap()))
    
    def update_all_cells(self):
        """Update visuals for all cells."""
        for y in range(self._grid_height):
            for x in range(self._grid_width):
                self.update_cell(x, y)
    
    def _rebuild_cache(self):
        """Rebuild cached pixmaps."""
        self._uncollapsed_pixmap = None
        self._error_pixmap = None
    
    def _get_uncollapsed_pixmap(self) -> QPixmap:
        """Get or create the uncollapsed cell pixmap."""
        if self._uncollapsed_pixmap is None:
            self._uncollapsed_pixmap = ImageUtils.create_question_mark(self.CELL_SIZE)
        return self._uncollapsed_pixmap
    
    def _get_error_pixmap(self) -> QPixmap:
        """Get or create the error pixmap."""
        if self._error_pixmap is None:
            self._error_pixmap = ImageUtils.create_error_pixmap(self.CELL_SIZE)
        return self._error_pixmap
    
    def _on_cell_collapsed(self, x: int, y: int, tile_id: str):
        """Handle cell collapse signal."""
        self.update_cell(x, y)
    
    def _on_cell_updated(self, x: int, y: int):
        """Handle cell update signal."""
        self.update_cell(x, y)
    
    def _on_contradiction(self, x: int, y: int):
        """Handle contradiction signal."""
        self._contradiction_pos = (x, y)
        self.update_cell(x, y)
    
    def _on_state_changed(self, state: EngineState):
        """Handle engine state change."""
        if state == EngineState.IDLE:
            self._contradiction_pos = None
            self.update_all_cells()
    
    # === Input handling ===
    
    def wheelEvent(self, event: QWheelEvent):
        """Handle mouse wheel for zooming."""
        factor = 1.15
        if event.angleDelta().y() > 0:
            # Zoom in
            if self._zoom < self.MAX_ZOOM:
                self._zoom *= factor
                self.scale(factor, factor)
        else:
            # Zoom out
            if self._zoom > self.MIN_ZOOM:
                self._zoom /= factor
                self.scale(1 / factor, 1 / factor)
    
    def mousePressEvent(self, event: QMouseEvent):
        """Handle mouse press."""
        if event.button() == Qt.MiddleButton or (
            event.button() == Qt.RightButton and event.modifiers() == Qt.NoModifier
        ):
            # Start panning
            self._panning = True
            self._pan_start = event.position()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        
        if event.button() == Qt.LeftButton:
            # Cell selection
            pos = self.mapToScene(event.position().toPoint())
            cell_x = int(pos.x() // self.CELL_SIZE)
            cell_y = int(pos.y() // self.CELL_SIZE)
            
            if 0 <= cell_x < self._grid_width and 0 <= cell_y < self._grid_height:
                self.cell_clicked.emit(cell_x, cell_y)
            event.accept()
            return
        
        if event.button() == Qt.RightButton:
            # Right-click to clear
            pos = self.mapToScene(event.position().toPoint())
            cell_x = int(pos.x() // self.CELL_SIZE)
            cell_y = int(pos.y() // self.CELL_SIZE)
            
            if 0 <= cell_x < self._grid_width and 0 <= cell_y < self._grid_height:
                self.cell_right_clicked.emit(cell_x, cell_y)
            event.accept()
            return
        
        super().mousePressEvent(event)
    
    def mouseMoveEvent(self, event: QMouseEvent):
        """Handle mouse move for panning."""
        if self._panning:
            delta = event.position() - self._pan_start
            self._pan_start = event.position()
            
            # Pan the view
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - int(delta.x())
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - int(delta.y())
            )
            event.accept()
            return
        
        super().mouseMoveEvent(event)
    
    def mouseReleaseEvent(self, event: QMouseEvent):
        """Handle mouse release."""
        if self._panning:
            self._panning = False
            self.setCursor(Qt.ArrowCursor)
            event.accept()
            return
        
        super().mouseReleaseEvent(event)
    
    def reset_view(self):
        """Reset zoom and center view."""
        self.resetTransform()
        self._zoom = 1.0
        if self._grid_width > 0 and self._grid_height > 0:
            self.centerOn(
                self._grid_width * self.CELL_SIZE / 2,
                self._grid_height * self.CELL_SIZE / 2
            )

