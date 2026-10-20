# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

- Install: `pip install -r requirements.txt` (PySide6, Pillow; Python 3.10+)
- Run the Atlas Editor: `python atlas_editor/main.py`
- Run the WFC Viewer: `python wfc_viewer/main.py`
- Slice a tileset image into tiles: `python split_image_block.py <image> <block_w> <block_h>` (writes `<stem>_N.<ext>` next to the source)
- There is no test suite, linter, or build config. There is no `.gitignore`, so `__pycache__` shows as untracked.

## Architecture

Two independent PySide6 desktop apps. They share no code and communicate only through files:

```
atlas_editor  --.tr (ZIP: atlas.json + tiles/)-->  wfc_viewer  --.tm (ZIP: map.json, source_atlas.json, tiles/) / PNG-->
```

- Each app has its own top-level `src` package. Keep imports within the app; do not import across apps.
- The `.tr` format is specified in `atlas_editor/TR_FORMAT.md`. The writer is `save_atlas` in `atlas_editor/src/core/serialization.py`, and the reader is `wfc_viewer/src/core/tr_loader.py`. Change both together when the format changes.

### atlas_editor

- `models/`: `BaseTile` (imported image), `Tile` (a variant of a base tile with rotation and flip_x/flip_y, id such as `grass_r90_fx`), `AdjacencyRule` (tile, side, neighbor, weight 0-100, `auto` flag), `Atlas`, `Settings`.
- `core/transform.py`: rotation and flip group math (`Transform` with compose/inverse, plus side mapping).
- `core/propagation.py`: when a rule is added, derives equivalent rules for every transformed variant of both tiles by applying the relative transform to the source side and target. Derived rules have `auto=True`.
- `core/validation.py`: finds incomplete rule sets. `core/serialization.py`: `.tr` load/save.
- `ui/main_window.py` wires the panels together (tiles, rule editor, rule controls, cross preview, validation).

### wfc_viewer

- `core/tile.py`: `TileAtlas`, which builds an adjacency lookup (`build_adjacency_lookup`, `get_valid_neighbors`, `get_tiles_allowing_neighbor`).
- `core/wfc_engine.py`: `WFCEngine(QObject)` runs one collapse per `QTimer` tick and exposes a state machine (IDLE / RUNNING / PAUSED / FINISHED) through Qt signals. Each step picks an open cell (the one nearest a start point first, then lowest entropy), collapses it, and propagates constraints by BFS. User-placed cells are `locked`.
- Backtracking: a random choice is recorded as a `Decision` and undone on contradiction, with at most `MAX_BACKTRACKS` retries per episode.
- Crosses: a cell the run cannot fill is marked as a cross (`_dead`) and skipped, so the run continues elsewhere. `force_place` fills a cross.
- Stuck pause: after `STUCK_RETRIES` retries without a new maximum of placed cells, the run pauses and emits `stuck(x, y)`.
- Start points: tiles placed while paused become start points. `_start_dist` holds each cell's distance to the nearest one, and the solver collapses nearer cells first.
- `core/tm_saver.py`: `TMSaver` for `.tm` save/load. `utils/png_export.py`: PNG render. `utils/tiled_export.py`: Tiled map export (TMX plus a tileset spritesheet). `ui/grid_canvas.py`: zoom/pan canvas.

Known gaps in the engine:
- Choice is uniform random. Rule weights are stored but unused: `_weighted_choice` is defined but never called.
