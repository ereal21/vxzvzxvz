import math
import time
from collections import defaultdict
from typing import DefaultDict, List


_RESERVED: DefaultDict[str, List[float]] = defaultdict(list)


def _cleanup(item_name: str | None = None) -> None:
    now = time.time()
    names = [item_name] if item_name else list(_RESERVED.keys())
    for name in names:
        entries = [ts for ts in _RESERVED.get(name, []) if ts > now]
        if entries:
            _RESERVED[name] = entries
        elif name in _RESERVED:
            _RESERVED.pop(name, None)


def add_reservation(item_name: str, expires_at: float) -> None:
    _cleanup(item_name)
    _RESERVED[item_name].append(expires_at)


def remove_reservation(item_name: str, expires_at: float | None = None) -> None:
    if expires_at is None:
        _RESERVED.pop(item_name, None)
        return
    entries = _RESERVED.get(item_name, [])
    try:
        entries.remove(expires_at)
    except ValueError:
        pass
    if entries:
        _RESERVED[item_name] = entries
    else:
        _RESERVED.pop(item_name, None)


def has_active_reservation(item_name: str) -> bool:
    _cleanup(item_name)
    return bool(_RESERVED.get(item_name))


def reservation_eta_minutes(item_name: str) -> int | None:
    _cleanup(item_name)
    entries = _RESERVED.get(item_name) or []
    if not entries:
        return None
    remaining = min(entries) - time.time()
    if remaining <= 0:
        _cleanup(item_name)
        return None
    return max(1, int(math.ceil(remaining / 60)))


def clear_all_reservations(item_name: str | None = None) -> None:
    if item_name:
        _RESERVED.pop(item_name, None)
        return
    _RESERVED.clear()
