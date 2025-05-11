import hashlib
import os
from pathlib import Path
from typing import Optional
from src.system.safety import require_safe_path
import logging

class MediaItem:
    def __init__(self, path: Path, source: str, root: Optional[Path] = None):
        self.path = path.resolve()
        self.source = source  # 'drag' or 'load'
        self.is_folder = self.path.is_dir()
        self.status = "Pending"
        self.extension = self.path.suffix.lower()
        self.basename = self.path.name
        self.parent_folder = self.path.parent

        self.relative_path = (
            self.path.relative_to(root) if root and root in self.path.parents else None
        )
        self.depth = len(self.relative_path.parts) if self.relative_path else 0

        self.group_path = None
        self.group_id = None
        if root and root in self.path.parents:
            try:
                if root and (self.path == root or root in self.path.parents):
                    relative = self.path.relative_to(root)
                    if relative.parts:
                        top_level = root / relative.parts[0]
                        self.group_path = top_level
                        self.group_id = hashlib.md5(str(top_level).encode()).hexdigest()
            except Exception:
                self.group_path = None
                self.group_id = None

    def to_dict(self) -> dict:
        return {
            "path": str(self.path),
            "source": self.source,
            "is_folder": self.is_folder,
            "status": self.status,
            "extension": self.extension,
            "basename": self.basename,
            "parent_folder": str(self.parent_folder) if self.parent_folder else None,
            "relative_path": str(self.relative_path) if self.relative_path else None,
            "depth": self.depth,
            "group_id": self.group_id,
            "group_path": str(self.group_path) if self.group_path else None,
        }

    def __repr__(self):
        return f"<MediaItem {self.basename} depth={self.depth} source={self.source}>"

def get_media_items(base_path: Path, source: str, logger=None) -> list[MediaItem]:
    items = []
    logger = logger or logging.getLogger(__name__)
    try:
        require_safe_path(base_path, "Media Input Root", logger=logger)
    except RuntimeError as e:
        logger.error(str(e))
        return []

    for root, dirs, files in os.walk(base_path):
        root_path = Path(root)

        # Include the current folder itself
        items.append(MediaItem(root_path, source=source, root=base_path))

        # Include immediate subfolders
        for d in dirs:
            folder_path = root_path / d
            items.append(MediaItem(folder_path, source=source, root=base_path))

        # Include files
        for f in files:
            file_path = root_path / f
            items.append(MediaItem(file_path, source=source, root=base_path))

    return items