"""
Validation utilities for checking atlas completeness.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from .transform import SIDES

if TYPE_CHECKING:
    from ..models import Atlas


@dataclass
class TileValidation:
    """Validation result for a single tile."""
    tile_id: str
    missing_sides: list[str] = field(default_factory=list)
    incomplete_sides: dict[str, float] = field(default_factory=dict)  # side -> total weight
    
    @property
    def is_valid(self) -> bool:
        return len(self.missing_sides) == 0 and len(self.incomplete_sides) == 0
    
    @property
    def has_warnings(self) -> bool:
        return len(self.incomplete_sides) > 0
    
    @property
    def has_errors(self) -> bool:
        return len(self.missing_sides) > 0


@dataclass
class ValidationResult:
    """Overall validation result for an atlas."""
    tile_results: dict[str, TileValidation] = field(default_factory=dict)
    orphan_tiles: list[str] = field(default_factory=list)  # tiles with no rules at all
    
    @property
    def is_valid(self) -> bool:
        return all(tr.is_valid for tr in self.tile_results.values()) and len(self.orphan_tiles) == 0
    
    @property
    def error_count(self) -> int:
        count = len(self.orphan_tiles)
        for tr in self.tile_results.values():
            count += len(tr.missing_sides)
        return count
    
    @property
    def warning_count(self) -> int:
        count = 0
        for tr in self.tile_results.values():
            count += len(tr.incomplete_sides)
        return count
    
    def get_tiles_with_issues(self) -> list[str]:
        """Get list of tile IDs that have any issues."""
        issues = set(self.orphan_tiles)
        for tile_id, tr in self.tile_results.items():
            if not tr.is_valid:
                issues.add(tile_id)
        return sorted(issues)


def validate_atlas(atlas: 'Atlas', enabled_only: bool = True) -> ValidationResult:
    """
    Validate an atlas for completeness.
    
    Checks:
    1. Every tile has at least one neighbor on each side
    2. Weights for each side sum to 100%
    
    Args:
        atlas: The atlas to validate
        enabled_only: If True, only validate enabled tiles
        
    Returns:
        ValidationResult with details about any issues
    """
    result = ValidationResult()
    
    # Get tiles to validate
    tiles_to_check = [t for t in atlas.tiles if not enabled_only or t.enabled]
    
    for tile in tiles_to_check:
        tile_result = TileValidation(tile_id=tile.id)
        has_any_rules = False
        
        for side in SIDES:
            rules = atlas.get_rules_for_tile(tile.id, side)
            
            if not rules:
                tile_result.missing_sides.append(side)
            else:
                has_any_rules = True
                total_weight = sum(r.weight for r in rules)
                
                # Check if weights don't sum to 100% (with small tolerance)
                if abs(total_weight - 100.0) > 0.01:
                    tile_result.incomplete_sides[side] = total_weight
        
        if not has_any_rules:
            result.orphan_tiles.append(tile.id)
        
        result.tile_results[tile.id] = tile_result
    
    return result


def get_side_weight_total(atlas: 'Atlas', tile_id: str, side: str) -> float:
    """Get the total weight for a tile's side."""
    rules = atlas.get_rules_for_tile(tile_id, side)
    return sum(r.weight for r in rules)


def normalize_side_weights(atlas: 'Atlas', tile_id: str, side: str) -> None:
    """
    Split a tile's side equally among its neighbours: each gets 100 / N percent.
    
    Args:
        atlas: The atlas
        tile_id: The tile to normalize
        side: The side to normalize
    """
    rules = atlas.get_rules_for_tile(tile_id, side)
    if not rules:
        return
    
    equal = 100.0 / len(rules)
    for rule in rules:
        rule.weight = equal
    
    atlas.modified = True


def normalize_all_weights(atlas: 'Atlas') -> int:
    """
    Split every tile's sides equally among their neighbours, not only the selected tile.

    Returns:
        Number of sides that were changed
    """
    changed = 0
    for tile in atlas.tiles:
        for side in SIDES:
            rules = atlas.get_rules_for_tile(tile.id, side)
            if not rules:
                continue
            equal = 100.0 / len(rules)
            if any(abs(r.weight - equal) > 0.01 for r in rules):
                normalize_side_weights(atlas, tile.id, side)
                changed += 1
    return changed

