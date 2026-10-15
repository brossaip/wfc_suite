"""
Serialization for Atlas files.
Uses .tr (tiles rules) ZIP format with bundled tile images.
All tile images are stored inside the archive.
"""

import json
import zipfile
import shutil
import tempfile
from pathlib import Path
from typing import Union

from ..models import Atlas


def save_atlas(atlas: Atlas, file_path: Union[str, Path]) -> None:
    """
    Save an atlas to a .tr file (ZIP archive with tiles).
    
    Structure:
        archive.tr/
            atlas.json      - Atlas data with relative paths
            tiles/          - Folder containing tile images
                tile1.png
                tile2.png
                ...
    
    Args:
        atlas: The atlas to save
        file_path: Path to save to (.tr file)
    """
    file_path = Path(file_path)
    if not file_path.suffix == '.tr':
        file_path = file_path.with_suffix('.tr')
    
    # Determine where to find source images
    # If loaded from .tr, use extraction dir; otherwise use atlas file's directory
    if hasattr(atlas, '_extraction_dir') and atlas._extraction_dir:
        source_base = Path(atlas._extraction_dir)
    elif atlas.file_path:
        source_base = Path(atlas.file_path).parent
    else:
        source_base = Path('.')
    
    # Create a temporary directory to build the archive contents
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        tiles_dir = temp_path / 'tiles'
        tiles_dir.mkdir()
        
        # Copy tile images and build base_tiles list with archive-relative paths
        updated_base_tiles = []
        for base_tile in atlas.base_tiles:
            # Find the source image
            source_path = Path(base_tile.source_path)
            
            # Try different locations to find the image
            found_path = None
            if source_path.is_absolute() and source_path.exists():
                found_path = source_path
            elif (source_base / source_path).exists():
                found_path = source_base / source_path
            elif source_path.exists():
                found_path = source_path
            # Try just the filename in tiles subfolder
            elif (source_base / 'tiles' / source_path.name).exists():
                found_path = source_base / 'tiles' / source_path.name
            
            if found_path and found_path.exists():
                # Copy to tiles folder with just the filename
                dest_name = found_path.name
                # Handle duplicate names by adding counter
                dest_path = tiles_dir / dest_name
                counter = 1
                while dest_path.exists():
                    stem = found_path.stem
                    suffix = found_path.suffix
                    dest_name = f"{stem}_{counter}{suffix}"
                    dest_path = tiles_dir / dest_name
                    counter += 1
                
                shutil.copy2(found_path, dest_path)
                
                # Store ONLY archive-relative path (use 'source' key to match BaseTile.from_dict)
                updated_base_tiles.append({
                    'id': base_tile.id,
                    'source': f"tiles/{dest_name}",
                    'width': base_tile.width,
                    'height': base_tile.height
                })
            else:
                print(f"Warning: Tile image not found: {base_tile.source_path}")
                # Still save the entry but image won't be available
                updated_base_tiles.append({
                    'id': base_tile.id,
                    'source': f"tiles/{Path(base_tile.source_path).name}",
                    'width': base_tile.width,
                    'height': base_tile.height
                })
        
        # Build atlas data with relative paths only
        atlas_data = {
            'version': atlas.version,
            'settings': atlas.settings.to_dict(),
            'base_tiles': updated_base_tiles,
            'tiles': [t.to_dict() for t in atlas.tiles],
            'rules': [r.to_dict() for r in atlas.rules]
        }
        
        # Write atlas.json
        with open(temp_path / 'atlas.json', 'w', encoding='utf-8') as f:
            json.dump(atlas_data, f, indent=2, ensure_ascii=False)
        
        # Create ZIP archive
        with zipfile.ZipFile(file_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.write(temp_path / 'atlas.json', 'atlas.json')
            for tile_file in tiles_dir.iterdir():
                zf.write(tile_file, f'tiles/{tile_file.name}')
    
    atlas.file_path = str(file_path)
    atlas.modified = False


def load_atlas(file_path: Union[str, Path]) -> Atlas:
    """
    Load an atlas from a .tr file (ZIP archive with tiles).
    
    Args:
        file_path: Path to load from (.tr file)
        
    Returns:
        Loaded Atlas object
    """
    file_path = Path(file_path)
    
    if file_path.suffix != '.tr':
        raise ValueError(f"Unsupported file format: {file_path.suffix}. Only .tr files are supported.")
    
    # Create extraction directory next to the .tr file (hidden folder)
    extract_dir = file_path.parent / f".{file_path.stem}_cache"
    
    # Extract archive
    with zipfile.ZipFile(file_path, 'r') as zf:
        # Read atlas.json
        with zf.open('atlas.json') as f:
            data = json.load(f)
        
        # Extract ALL files (including tiles)
        zf.extractall(extract_dir)
    
    # Update base_tile paths to absolute paths pointing to extracted files
    for bt in data.get('base_tiles', []):
        source_path = bt.get('source', '')
        # Convert archive-relative path to absolute extracted path
        extracted_path = extract_dir / source_path
        bt['source'] = str(extracted_path)
    
    atlas = Atlas.from_dict(data)
    atlas.file_path = str(file_path)
    atlas.modified = False

    # Files may contain duplicate rules; keep one per key and offer to save the cleaned version
    atlas.duplicates_merged = atlas.merge_duplicate_rules()
    
    # Store extraction directory for cleanup and for saving later
    atlas._extraction_dir = str(extract_dir)
    
    return atlas


def cleanup_extraction(atlas: Atlas) -> None:
    """
    Clean up extracted tile files when closing an atlas.
    """
    if hasattr(atlas, '_extraction_dir') and atlas._extraction_dir:
        extract_dir = Path(atlas._extraction_dir)
        if extract_dir.exists():
            try:
                shutil.rmtree(extract_dir)
            except Exception:
                pass  # Ignore cleanup errors
