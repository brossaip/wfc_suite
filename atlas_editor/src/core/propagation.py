"""
Auto-propagation of adjacency rules across tile transforms.

When a rule is created between two tiles, this module can automatically
generate equivalent rules for all transformed variants of those tiles.
"""

from typing import TYPE_CHECKING
from .transform import Transform, SIDES, get_all_transforms, get_opposite_side

if TYPE_CHECKING:
    from ..models import Atlas, AdjacencyRule, Tile


def propagate_rule(atlas: 'Atlas', rule: 'AdjacencyRule') -> list['AdjacencyRule']:
    """
    Propagate a single rule to all applicable tile transform variants.
    
    Given a rule like "tile_A (right) -> tile_B", this will generate rules for
    all existing transform variants of both tiles.
    
    Args:
        atlas: The atlas containing all tiles
        rule: The rule to propagate
        
    Returns:
        List of newly created rules (not including the original)
    """
    from ..models import Tile
    
    # Get the source and target tiles
    source_tile = atlas.get_tile(rule.tile_id)
    target_tile = atlas.get_tile(rule.neighbor_id)
    
    if not source_tile or not target_tile:
        return []
    
    # Get all variants of both base tiles
    source_variants = atlas.get_tiles_for_base(source_tile.base_tile_id)
    target_variants = atlas.get_tiles_for_base(target_tile.base_tile_id)
    
    # Build transform objects for source and target
    source_transform = Transform(source_tile.rotation, source_tile.flip_x, source_tile.flip_y)
    target_transform = Transform(target_tile.rotation, target_tile.flip_x, target_tile.flip_y)
    
    new_rules = []
    
    for src_variant in source_variants:
        if src_variant.id == rule.tile_id:
            continue  # Skip the original
        
        # Get the transform for this source variant
        src_var_transform = Transform(src_variant.rotation, src_variant.flip_x, src_variant.flip_y)
        
        # Compute the relative transform: what transform takes source_tile to src_variant?
        # relative_transform = src_var_transform • inverse(source_transform)
        relative_transform = source_transform.inverse().compose(src_var_transform)
        
        # The side in the variant's frame
        # Original rule is on rule.side in source_transform's frame
        # Find the corresponding side in src_var_transform's frame
        new_side = _transform_side_between(
            rule.side, 
            source_transform, 
            src_var_transform
        )
        
        # Apply the same relative transform to the target
        # target_var_transform = relative_transform • target_transform
        target_var_transform = target_transform.compose(relative_transform)
        
        # Find the target variant with this transform
        target_variant = None
        for tv in target_variants:
            if (tv.rotation == target_var_transform.rotation and 
                tv.flip_x == target_var_transform.flip_x and 
                tv.flip_y == target_var_transform.flip_y):
                target_variant = tv
                break
        
        if target_variant:
            # Create the propagated rule
            new_rule = atlas.add_rule(
                tile_id=src_variant.id,
                side=new_side,
                neighbor_id=target_variant.id,
                weight=rule.weight,
                auto_generated=True
            )
            new_rules.append(new_rule)
    
    return new_rules


def propagate_all_rules(atlas: 'Atlas') -> int:
    """
    Propagate all manual rules to their transform variants.
    
    Args:
        atlas: The atlas to process
        
    Returns:
        Number of new rules created
    """
    # Get all manual rules
    manual_rules = [r for r in atlas.rules if not r.auto_generated]
    
    # Remove existing auto-generated rules
    atlas.remove_auto_rules()
    
    # Propagate each manual rule
    total_new = 0
    for rule in manual_rules:
        new_rules = propagate_rule(atlas, rule)
        total_new += len(new_rules)
    
    return total_new


def ensure_tile_variants_for_rule(atlas: 'Atlas', rule: 'AdjacencyRule') -> list['Tile']:
    """
    Ensure all necessary tile variants exist for propagating a rule.
    Creates missing variants as needed based on atlas settings.
    
    Args:
        atlas: The atlas
        rule: The rule to propagate
        
    Returns:
        List of newly created tiles
    """
    source_tile = atlas.get_tile(rule.tile_id)
    target_tile = atlas.get_tile(rule.neighbor_id)
    
    if not source_tile or not target_tile:
        return []
    
    new_tiles = []
    transforms_to_create = []
    
    # Determine which transforms to create based on settings
    if atlas.settings.auto_propagate_rotations:
        transforms_to_create.extend([
            Transform(90, False, False),
            Transform(180, False, False),
            Transform(270, False, False),
        ])
    
    if atlas.settings.auto_propagate_mirrors:
        transforms_to_create.extend([
            Transform(0, True, False),
            Transform(0, False, True),
        ])
    
    if atlas.settings.auto_propagate_rotations and atlas.settings.auto_propagate_mirrors:
        # Add combined transforms
        for rot in [90, 180, 270]:
            transforms_to_create.append(Transform(rot, True, False))
            transforms_to_create.append(Transform(rot, False, True))
        transforms_to_create.append(Transform(0, True, True))
        for rot in [90, 180, 270]:
            transforms_to_create.append(Transform(rot, True, True))
    
    # Create missing variants for both tiles
    for base_id in [source_tile.base_tile_id, target_tile.base_tile_id]:
        for t in transforms_to_create:
            tile_id = f"{base_id}_{t.suffix}" if t.suffix else base_id
            if not atlas.get_tile(tile_id):
                new_tile = atlas.add_tile_variant(
                    base_id, 
                    rotation=t.rotation, 
                    flip_x=t.flip_x, 
                    flip_y=t.flip_y
                )
                new_tiles.append(new_tile)
    
    return new_tiles


def _transform_side_between(side: str, from_transform: Transform, to_transform: Transform) -> str:
    """
    Calculate which side in to_transform's frame corresponds to 'side' in from_transform's frame.
    
    Both transforms are relative to the base tile.
    """
    # Find the original side (in base tile frame) that becomes 'side' in from_transform
    original_side = from_transform.inverse_side(side)
    
    # Apply to_transform to get the side in the new frame
    return to_transform.apply_to_side(original_side)


def add_reciprocal_rules(atlas: 'Atlas') -> int:
    """
    Add the missing reverse of every one-way rule.

    If A allows B on its right, B must allow A on its left. Each missing reverse
    rule copies the forward rule's weight and is saved as a manual rule.

    Returns:
        Number of rules added
    """
    existing = {r.key for r in atlas.rules}
    added = 0
    for rule in list(atlas.rules):
        reverse = (rule.neighbor_id, get_opposite_side(rule.side), rule.tile_id)
        if reverse in existing:
            continue
        if atlas.get_tile(rule.tile_id) is None or atlas.get_tile(rule.neighbor_id) is None:
            continue
        atlas.add_rule(reverse[0], reverse[1], reverse[2], rule.weight, auto_generated=False)
        existing.add(reverse)
        added += 1
    return added

