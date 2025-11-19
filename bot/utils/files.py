import os
import os
import re


def sanitize_name(name: str) -> str:
    """Sanitize item or category name for filesystem paths."""
    return re.sub(r"\W+", "_", name)


def ensure_item_folder(item_name: str) -> str:
    folder = os.path.join('assets', 'uploads', sanitize_name(item_name))
    os.makedirs(folder, exist_ok=True)
    return folder


def get_next_file_path(item_name: str, extension: str = 'jpg') -> str:
    folder = ensure_item_folder(item_name)
    existing = [f for f in os.listdir(folder) if f.endswith(f'.{extension}')]
    numbers = [int(os.path.splitext(f)[0]) for f in existing if os.path.splitext(f)[0].isdigit()]
    next_num = max(numbers) + 1 if numbers else 1
    return os.path.join(folder, f'{next_num}.{extension}')


def cleanup_item_file(file_path: str) -> None:
    """Remove file and clean up its folder if empty."""
    if os.path.isfile(file_path):
        os.remove(file_path)
        folder = os.path.dirname(file_path)
        if os.path.isdir(folder) and not os.listdir(folder):
            os.rmdir(folder)
