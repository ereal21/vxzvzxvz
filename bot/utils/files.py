import os
import re


def sanitize_name(name: str) -> str:
    """Sanitize item or category name for filesystem paths."""
    return re.sub(r"\W+", "_", name)


def _uploads_root() -> str:
    root = os.path.join('assets', 'uploads')
    os.makedirs(root, exist_ok=True)
    return root


def create_stock_folder(item_name: str) -> str:
    """Create a unique folder for a single stock unit under assets/uploads.

    Folders are named ``<product_name>_<n>`` so multiple stocks of the same
    product share the name but differ by a numeric suffix.
    """

    root = _uploads_root()
    base = sanitize_name(item_name)
    pattern = re.compile(rf"^{re.escape(base)}_(\d+)$")
    existing = [
        int(match.group(1))
        for match in (pattern.match(name) for name in os.listdir(root))
        if match
    ]
    next_index = max(existing) + 1 if existing else 1
    folder = os.path.join(root, f"{base}_{next_index}")
    os.makedirs(folder, exist_ok=True)
    return folder


def get_next_file_path(item_name: str, extension: str = 'jpg', folder: str | None = None) -> str:
    """Return the next sequential media path inside the provided stock folder."""

    target_folder = folder or create_stock_folder(item_name)
    os.makedirs(target_folder, exist_ok=True)

    existing = [
        f
        for f in os.listdir(target_folder)
        if os.path.splitext(f)[0].isdigit()
    ]
    numbers = [int(os.path.splitext(f)[0]) for f in existing]
    next_num = max(numbers) + 1 if numbers else 1
    return os.path.join(target_folder, f'{next_num}.{extension}')


def cleanup_item_file(file_path: str) -> None:
    """Remove file and clean up its folder if empty."""
    if os.path.isfile(file_path):
        os.remove(file_path)
        folder = os.path.dirname(file_path)
        if os.path.isdir(folder) and not os.listdir(folder):
            os.rmdir(folder)
