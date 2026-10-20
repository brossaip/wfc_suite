"""
Read Tiled tilesets (TSX, JSON tileset, or a tileset embedded in a TMX) and cut out their tiles.
"""

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from PIL import Image


@dataclass
class TilesetTile:
    """One tile cut from a Tiled tileset spritesheet."""
    id: str
    image: Image.Image  # RGBA


def read_tileset(filepath: str) -> List[TilesetTile]:
    """
    Read a Tiled tileset and return its tiles as images.

    Supported inputs: .tsx (XML tileset), .tmx (first embedded tileset), .tsj/.json (JSON tileset).
    Each tile is named from its `tile_id` property if it has one (as written by the viewer's
    Tiled export), otherwise `<tileset name>_<local id>`.

    Raises:
        ValueError: unsupported file, external tileset in a TMX, non-square tiles, or a tileset
                    without a single spritesheet image.
    """
    path = Path(filepath)
    suffix = path.suffix.lower()
    if suffix in (".tsj", ".json"):
        return _read_json_tileset(path)
    if suffix == ".tmx":
        root = ET.parse(path).getroot()
        embedded = [ts for ts in root.findall("tileset") if ts.get("source") is None]
        if not embedded:
            raise ValueError("The map has no embedded tileset. Open the .tsx file instead.")
        return _read_xml_tileset(embedded[0], path.parent)
    if suffix == ".tsx":
        root = ET.parse(path).getroot()
        if root.tag != "tileset":
            raise ValueError("Not a Tiled tileset file.")
        return _read_xml_tileset(root, path.parent)
    raise ValueError(f"Unsupported Tiled file: {path.suffix}. Use .tsx, .tsj, .json or .tmx.")


def _read_xml_tileset(ts: ET.Element, base_dir: Path) -> List[TilesetTile]:
    if ts.find("image") is None:
        raise ValueError("Each tile in a Tiled tileset must come from one spritesheet image.")
    image_el = ts.find("image")
    sheet_path = base_dir / image_el.get("source", "")
    sheet = Image.open(sheet_path).convert("RGBA")

    props_by_id = {}
    for tile in ts.findall("tile"):
        props_by_id[int(tile.get("id"))] = {
            p.get("name"): p.get("value") for p in tile.findall("properties/property")
        }

    tilecount = int(ts.get("tilecount", "0"))
    columns = int(ts.get("columns", "0"))
    return _cut_tiles(
        sheet=sheet,
        name=ts.get("name", sheet_path.stem),
        tile_w=int(ts.get("tilewidth", "0")),
        tile_h=int(ts.get("tileheight", "0")),
        spacing=int(ts.get("spacing", "0")),
        margin=int(ts.get("margin", "0")),
        columns=columns,
        tilecount=tilecount,
        props_by_id=props_by_id,
    )


def _read_json_tileset(path: Path) -> List[TilesetTile]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if "image" not in data:
        raise ValueError("Each tile in a Tiled tileset must come from one spritesheet image.")
    sheet = Image.open(path.parent / data["image"]).convert("RGBA")

    props_by_id = {}
    for tile in data.get("tiles", []):
        props_by_id[int(tile["id"])] = {
            p["name"]: str(p["value"]) for p in tile.get("properties", [])
        }

    return _cut_tiles(
        sheet=sheet,
        name=data.get("name", path.stem),
        tile_w=int(data["tilewidth"]),
        tile_h=int(data["tileheight"]),
        spacing=int(data.get("spacing", 0)),
        margin=int(data.get("margin", 0)),
        columns=int(data["columns"]),
        tilecount=int(data["tilecount"]),
        props_by_id=props_by_id,
    )


def _cut_tiles(
    sheet: Image.Image,
    name: str,
    tile_w: int,
    tile_h: int,
    spacing: int,
    margin: int,
    columns: int,
    tilecount: int,
    props_by_id: dict,
) -> List[TilesetTile]:
    if tile_w <= 0 or tile_h <= 0 or columns <= 0 or tilecount <= 0:
        raise ValueError("The tileset has no tile size, column count or tile count.")
    if tile_w != tile_h:
        raise ValueError(f"Tiles must be square; the tileset uses {tile_w}×{tile_h}.")

    tiles = []
    for local_id in range(tilecount):
        col, row = local_id % columns, local_id // columns
        x = margin + col * (tile_w + spacing)
        y = margin + row * (tile_h + spacing)
        if x + tile_w > sheet.width or y + tile_h > sheet.height:
            raise ValueError(f"Tile {local_id} lies outside the spritesheet image.")
        props = props_by_id.get(local_id, {})
        tile_id: Optional[str] = props.get("tile_id") or f"{name}_{local_id}"
        tiles.append(TilesetTile(id=tile_id, image=sheet.crop((x, y, x + tile_w, y + tile_h))))
    return tiles
