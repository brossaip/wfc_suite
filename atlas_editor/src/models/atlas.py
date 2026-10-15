from dataclasses import dataclass, field
from typing import Optional, Iterator
from .base_tile import BaseTile
from .tile import Tile
from .rule import AdjacencyRule, Side
from .settings import Settings


@dataclass
class Atlas:
    """
    Root container for all tile and rule data.
    """
    version: str = "1.0"
    settings: Settings = field(default_factory=Settings)
    base_tiles: list[BaseTile] = field(default_factory=list)
    tiles: list[Tile] = field(default_factory=list)
    rules: list[AdjacencyRule] = field(default_factory=list)
    
    # Runtime state (not serialized)
    file_path: Optional[str] = field(default=None, repr=False)
    modified: bool = field(default=False, repr=False)
    duplicates_merged: int = field(default=0, repr=False)

    # --- Base Tile Operations ---
    
    def add_base_tile(self, base_tile: BaseTile) -> None:
        """Add a base tile and create its original (untransformed) Tile."""
        if self.get_base_tile(base_tile.id):
            raise ValueError(f"Base tile '{base_tile.id}' already exists")
        self.base_tiles.append(base_tile)
        # Create the original tile variant
        original_tile = Tile.from_base(base_tile.id)
        self.tiles.append(original_tile)
        self.modified = True
    
    def get_base_tile(self, base_id: str) -> Optional[BaseTile]:
        """Get a base tile by ID."""
        for bt in self.base_tiles:
            if bt.id == base_id:
                return bt
        return None
    
    def remove_base_tile(self, base_id: str) -> None:
        """Remove a base tile and all its variants and rules."""
        # Remove base tile
        self.base_tiles = [bt for bt in self.base_tiles if bt.id != base_id]
        # Remove all tile variants
        tile_ids_to_remove = {t.id for t in self.tiles if t.base_tile_id == base_id}
        self.tiles = [t for t in self.tiles if t.base_tile_id != base_id]
        # Remove all rules involving those tiles
        self.rules = [r for r in self.rules 
                      if r.tile_id not in tile_ids_to_remove 
                      and r.neighbor_id not in tile_ids_to_remove]
        self.modified = True
    
    # --- Tile Operations ---
    
    def get_tile(self, tile_id: str) -> Optional[Tile]:
        """Get a tile by ID."""
        for t in self.tiles:
            if t.id == tile_id:
                return t
        return None
    
    def get_tiles_for_base(self, base_id: str) -> list[Tile]:
        """Get all tile variants for a base tile."""
        return [t for t in self.tiles if t.base_tile_id == base_id]
    
    def add_tile_variant(self, base_id: str, rotation: int = 0, 
                         flip_x: bool = False, flip_y: bool = False) -> Tile:
        """Add a transformed variant of a base tile."""
        tile_id = Tile.create_id(base_id, rotation, flip_x, flip_y)
        existing = self.get_tile(tile_id)
        if existing:
            return existing  # Already exists, return it
        
        tile = Tile.from_base(base_id, rotation, flip_x, flip_y)
        self.tiles.append(tile)
        self.modified = True
        return tile
    
    def remove_tile(self, tile_id: str) -> None:
        """Remove a tile variant (cannot remove original)."""
        tile = self.get_tile(tile_id)
        if tile and tile.is_original:
            raise ValueError("Cannot remove original tile variant. Remove the base tile instead.")
        self.tiles = [t for t in self.tiles if t.id != tile_id]
        # Remove rules involving this tile
        self.rules = [r for r in self.rules 
                      if r.tile_id != tile_id and r.neighbor_id != tile_id]
        self.modified = True
    
    # --- Rule Operations ---
    
    def add_rule(self, tile_id: str, side: Side, neighbor_id: str, 
                 weight: float = 100.0, auto_generated: bool = False) -> AdjacencyRule:
        """Add or update an adjacency rule."""
        # Check if rule already exists
        for rule in self.rules:
            if rule.tile_id == tile_id and rule.side == side and rule.neighbor_id == neighbor_id:
                rule.weight = weight
                rule.auto_generated = auto_generated
                self.modified = True
                return rule
        
        # Create new rule
        rule = AdjacencyRule(
            tile_id=tile_id,
            side=side,
            neighbor_id=neighbor_id,
            weight=weight,
            auto_generated=auto_generated
        )
        self.rules.append(rule)
        self.modified = True
        return rule
    
    def get_rules_for_tile(self, tile_id: str, side: Optional[Side] = None) -> list[AdjacencyRule]:
        """Get all rules for a tile, optionally filtered by side."""
        rules = [r for r in self.rules if r.tile_id == tile_id]
        if side:
            rules = [r for r in rules if r.side == side]
        return rules
    
    def get_rule(self, tile_id: str, side: Side, neighbor_id: str) -> Optional[AdjacencyRule]:
        """Get a specific rule."""
        for rule in self.rules:
            if rule.tile_id == tile_id and rule.side == side and rule.neighbor_id == neighbor_id:
                return rule
        return None
    
    def remove_rule(self, tile_id: str, side: Side, neighbor_id: str) -> None:
        """Remove a specific rule."""
        self.rules = [r for r in self.rules 
                      if not (r.tile_id == tile_id and r.side == side and r.neighbor_id == neighbor_id)]
        self.modified = True
    
    def remove_auto_rules(self) -> int:
        """Remove all auto-generated rules. Returns count removed."""
        original_count = len(self.rules)
        self.rules = [r for r in self.rules if not r.auto_generated]
        removed = original_count - len(self.rules)
        if removed > 0:
            self.modified = True
        return removed

    def merge_duplicate_rules(self) -> int:
        """Keep one rule per (tile, side, neighbor); the last occurrence wins. Returns count removed."""
        unique: dict = {}
        for rule in self.rules:
            unique[rule.key] = rule
        removed = len(self.rules) - len(unique)
        if removed > 0:
            self.rules = list(unique.values())
            self.modified = True
        return removed

    # --- Serialization ---
    
    def to_dict(self) -> dict:
        return {
            'version': self.version,
            'settings': self.settings.to_dict(),
            'base_tiles': [bt.to_dict() for bt in self.base_tiles],
            'tiles': [t.to_dict() for t in self.tiles],
            'rules': [r.to_dict() for r in self.rules]
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'Atlas':
        return cls(
            version=data.get('version', '1.0'),
            settings=Settings.from_dict(data.get('settings', {})),
            base_tiles=[BaseTile.from_dict(bt) for bt in data.get('base_tiles', [])],
            tiles=[Tile.from_dict(t) for t in data.get('tiles', [])],
            rules=[AdjacencyRule.from_dict(r) for r in data.get('rules', [])]
        )

