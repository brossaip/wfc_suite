"""
Export the grid to a Tiled map (TMX) with an embedded tileset spritesheet.
"""

import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter

from ..core.tile import TileAtlas
from ..core.wfc_engine import WFCEngine

MAX_COLUMNS = 16


def export_grid_to_tiled(filepath: str, engine: WFCEngine, atlas: TileAtlas) -> Dict[str, object]:
    """
    Write <filepath> (a TMX map) and a spritesheet PNG beside it.

    Every enabled tile variant goes into the tileset in sorted id order, so tile
    numbers stay the same between exports of the same atlas. Each variant is drawn
    with TileVariant.get_pixmap, so rotations and flips match the viewer.

    Returns:
        Summary with map size, tile count and the paths written.

    Raises:
        ValueError: no enabled tiles, or tiles that are not square or differ in size.
    """
    tile_ids = sorted(atlas.get_enabled_tile_ids())
    if not tile_ids:
        raise ValueError("The atlas has no enabled tiles to export.")

    sizes = set()
    for tile_id in tile_ids:
        base = atlas.base_tiles.get(atlas.tiles[tile_id].base_tile_id)
        if base is not None:
            sizes.add((base.width, base.height))
    if len(sizes) != 1:
        raise ValueError(f"Tiled needs one tile size; the atlas has {len(sizes)} different sizes.")
    (tile_w, tile_h), = sizes
    if tile_w != tile_h:
        raise ValueError(f"Tiled tiles must be square; the atlas uses {tile_w}×{tile_h}.")
    tile_size = tile_w

    path = Path(filepath)
    stem = path.stem
    png_path = path.with_name(f"{stem}_tileset.png")

    count = len(tile_ids)
    columns = min(MAX_COLUMNS, count)
    rows = math.ceil(count / columns)
    sheet_w, sheet_h = columns * tile_size, rows * tile_size

    sheet = QImage(sheet_w, sheet_h, QImage.Format_ARGB32)
    sheet.fill(QColor(0, 0, 0, 0))
    painter = QPainter(sheet)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
    for index, tile_id in enumerate(tile_ids):
        pixmap = atlas.tiles[tile_id].get_pixmap(atlas.base_tiles, tile_size)
        col, row = index % columns, index // columns
        painter.drawPixmap(col * tile_size, row * tile_size, pixmap)
    painter.end()
    if not sheet.save(str(png_path), "PNG"):
        raise ValueError(f"Could not write {png_path.name}")

    gid_of = {tile_id: index + 1 for index, tile_id in enumerate(tile_ids)}
    csv_rows = []
    for y in range(engine.height):
        cells = []
        for x in range(engine.width):
            cell = engine.get_cell(x, y)
            cells.append(str(gid_of.get(cell.collapsed_tile, 0)) if cell and cell.is_collapsed else "0")
        csv_rows.append(",".join(cells))

    map_el = ET.Element(
        "map",
        version="1.10",
        orientation="orthogonal",
        renderorder="right-down",
        width=str(engine.width),
        height=str(engine.height),
        tilewidth=str(tile_size),
        tileheight=str(tile_size),
        infinite="0",
    )
    tileset_el = ET.SubElement(
        map_el, "tileset",
        firstgid="1",
        name=f"{stem}_tiles",
        tilewidth=str(tile_size),
        tileheight=str(tile_size),
        tilecount=str(count),
        columns=str(columns),
    )
    ET.SubElement(
        tileset_el, "image",
        source=png_path.name,
        width=str(sheet_w),
        height=str(sheet_h),
    )
    for index, tile_id in enumerate(tile_ids):
        tile_el = ET.SubElement(tileset_el, "tile", id=str(index))
        props_el = ET.SubElement(tile_el, "properties")
        ET.SubElement(props_el, "property", name="tile_id", value=tile_id)

    layer_el = ET.SubElement(
        map_el, "layer",
        id="1", name="Tiles",
        width=str(engine.width), height=str(engine.height),
    )
    data_el = ET.SubElement(layer_el, "data", encoding="csv")
    data_el.text = "\n" + ",\n".join(csv_rows) + "\n"

    ET.indent(map_el, space=" ")
    ET.ElementTree(map_el).write(str(path), encoding="UTF-8", xml_declaration=True)

    return {
        "width": engine.width,
        "height": engine.height,
        "tiles": count,
        "tmx": str(path),
        "tileset": str(png_path),
    }
