"""
Read a Tiled map (TMX) exported by this viewer, or edited in Tiled.
"""

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

# Tiled stores flip flags in the top bits of a global tile id
GID_FLAGS = 0xE0000000
GID_MASK = 0x1FFFFFFF


@dataclass
class TiledMap:
    width: int
    height: int
    tile_w: int
    tile_h: int
    # (x, y) -> tile_id from the tile's `tile_id` property; None if the tile has no such property
    cells: Dict[Tuple[int, int], Optional[str]] = field(default_factory=dict)


def read_tmx(filepath: str) -> TiledMap:
    """
    Parse an orthogonal TMX map with an embedded tileset and CSV tile data.

    Raises:
        ValueError: unsupported map (not orthogonal, external tileset, non-CSV data)
    """
    root = ET.parse(filepath).getroot()
    if root.tag != "map":
        raise ValueError("Not a Tiled map file.")
    if root.get("orientation", "orthogonal") != "orthogonal":
        raise ValueError("Only orthogonal Tiled maps can be opened.")

    tilesets = root.findall("tileset")
    if not tilesets:
        raise ValueError("The map has no tileset.")
    if any(ts.get("source") for ts in tilesets):
        raise ValueError("External tilesets (.tsx) are not supported yet; embed the tileset in the map.")

    # Map every global id to its tile_id property, using the first tileset's firstgid
    gid_to_tile: Dict[int, Optional[str]] = {}
    for ts in tilesets:
        firstgid = int(ts.get("firstgid", "1"))
        for tile in ts.findall("tile"):
            local = int(tile.get("id"))
            tile_id = None
            for prop in tile.findall("properties/property"):
                if prop.get("name") == "tile_id":
                    tile_id = prop.get("value")
            gid_to_tile[firstgid + local] = tile_id

    layers = root.findall("layer")
    if not layers:
        raise ValueError("The map has no tile layer.")
    layer = layers[0]
    data = layer.find("data")
    if data is None or data.get("encoding") != "csv":
        raise ValueError("Only CSV tile data is supported; re-save the map with CSV encoding.")

    width = int(layer.get("width", root.get("width")))
    height = int(layer.get("height", root.get("height")))
    rows = [r for r in (data.text or "").replace("\n", "").split(",") if r.strip() != ""]
    if len(rows) != width * height:
        raise ValueError(f"Tile data has {len(rows)} values for a {width}×{height} layer.")

    cells: Dict[Tuple[int, int], Optional[str]] = {}
    for index, value in enumerate(rows):
        gid = int(value) & GID_MASK
        if gid == 0:
            continue
        x, y = index % width, index // width
        cells[(x, y)] = gid_to_tile.get(gid)

    return TiledMap(
        width=width,
        height=height,
        tile_w=int(root.get("tilewidth", "0")),
        tile_h=int(root.get("tileheight", "0")),
        cells=cells,
    )
