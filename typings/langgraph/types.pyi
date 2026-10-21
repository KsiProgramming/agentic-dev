from typing import Any

class StateSnapshot:
    values: dict[str, Any]
    next: tuple[str, ...]
