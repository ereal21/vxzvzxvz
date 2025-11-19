import json
import os
import shutil
from typing import Tuple, List

from bot.utils.files import cleanup_item_file


def _resolve_base_path(value: str) -> str:
    """Return an existing base path, preferring the Sold copy when available."""
    if os.path.isfile(value):
        return value
    sold_path = os.path.join(os.path.dirname(value), 'Sold', os.path.basename(value))
    if os.path.isfile(sold_path):
        return sold_path
    return value


def _normalize_media_paths(base_path: str, media: list[str]) -> list[str]:
    """Return existing media paths resolved relative to ``base_path``."""

    base_dir = os.path.dirname(base_path)
    normalized: list[str] = []
    seen: set[str] = set()
    for entry in media:
        if not entry:
            continue
        candidates = []
        if os.path.isabs(entry):
            candidates.append(entry)
        candidates.append(os.path.join(base_dir, entry))
        candidates.append(os.path.join(base_dir, os.path.basename(entry)))
        for candidate in candidates:
            if candidate in seen:
                break
            if os.path.isfile(candidate):
                normalized.append(candidate)
                seen.add(candidate)
                break
    return normalized


def load_media_bundle(value: str) -> Tuple[List[str], str]:
    """Return media paths and description for a stock value.

    Supports legacy single-file values as well as bundled media stored in a
    sidecar JSON file ``<value>.meta.json``.
    """

    attachments: list[str] = []
    description = ''
    if not value:
        return attachments, description

    base_path = _resolve_base_path(value)
    meta_path = f"{base_path}.meta.json"
    if os.path.isfile(meta_path):
        try:
            with open(meta_path, encoding='utf-8') as f:
                meta = json.load(f)
            raw_media = meta.get('media', [])
            attachments = _normalize_media_paths(base_path, raw_media)
            if len(attachments) < len(raw_media):
                base_dir = os.path.dirname(base_path)
                for entry in raw_media:
                    candidate = os.path.join(base_dir, os.path.basename(entry))
                    if candidate not in attachments and os.path.isfile(candidate):
                        attachments.append(candidate)
            description = meta.get('description') or ''
        except Exception:
            pass

    if not attachments:
        folder = os.path.dirname(base_path)
        if os.path.isdir(folder):
            attachments = sorted(
                [
                    os.path.join(folder, f)
                    for f in os.listdir(folder)
                    if f.lower().endswith(('.jpg', '.jpeg', '.png', '.mp4'))
                    and not f.endswith('.meta.json')
                    and not f.endswith('.txt')
                ]
            )

    if base_path and os.path.isfile(base_path) and base_path not in attachments:
        attachments.insert(0, base_path)

    if not description:
        desc_file = f"{base_path}.txt"
        if os.path.isfile(desc_file):
            with open(desc_file, encoding='utf-8') as f:
                description = f.read()

    return attachments, description


def write_media_meta(base_path: str, attachments: List[str], description: str) -> None:
    """Persist metadata for a stock entry.

    Media paths are stored relative to the base path directory to keep the
    bundle portable when it is moved to ``Sold``.
    """

    meta_path = f"{base_path}.meta.json"
    base_dir = os.path.dirname(base_path)
    media_entries: list[str] = []
    for path in attachments:
        if not path:
            continue
        try:
            media_entries.append(os.path.relpath(path, base_dir))
        except ValueError:
            media_entries.append(os.path.basename(path))
    meta_payload = {'media': media_entries, 'description': description}
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(meta_payload, f, ensure_ascii=False, indent=2)


def move_media_to_sold(base_path: str, attachments: List[str], description: str) -> List[str]:
    """Move all media (and description) to the Sold folder.

    Returns the list of moved attachment paths.
    """

    sold_paths: list[str] = []
    for path in attachments:
        if not os.path.isfile(path):
            continue
        sold_folder = os.path.join(os.path.dirname(path), 'Sold')
        os.makedirs(sold_folder, exist_ok=True)
        target = os.path.join(sold_folder, os.path.basename(path))
        shutil.move(path, target)
        sold_paths.append(target)

        desc_path = f"{path}.txt"
        if os.path.isfile(desc_path):
            shutil.move(desc_path, os.path.join(sold_folder, os.path.basename(desc_path)))
        cleanup_item_file(path)
        if os.path.isfile(desc_path):
            cleanup_item_file(desc_path)

    if sold_paths:
        sold_base = os.path.join(os.path.dirname(base_path), 'Sold', os.path.basename(base_path))
        os.makedirs(os.path.dirname(sold_base), exist_ok=True)
        write_media_meta(sold_base, sold_paths, description)

    return sold_paths
