import uuid


def generate_internal_name(base: str) -> str:
    """Return a unique internal name for an item."""
    return f"{base}__{uuid.uuid4().hex[:8]}"


def display_name(internal: str) -> str:
    """Return user-facing name from internal item name."""
    return internal.split('__', 1)[0]
