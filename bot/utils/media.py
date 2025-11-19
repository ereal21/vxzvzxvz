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
            attachments = [p for p in meta.get('media', []) if p]
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

    if not attachments and base_path and os.path.isfile(base_path):
        attachments = [base_path]

    if not description:
        desc_file = f"{base_path}.txt"
        if os.path.isfile(desc_file):
            with open(desc_file, encoding='utf-8') as f:
                description = f.read()

    return attachments, description


def write_media_meta(base_path: str, attachments: List[str], description: str) -> None:
    """Persist metadata for a stock entry."""

    meta_path = f"{base_path}.meta.json"
    meta_payload = {'media': attachments, 'description': description}
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
