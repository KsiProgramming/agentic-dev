from typing import Any

from langchain_core.runnables import RunnableConfig

class Interrupt:
    value: Any
    id: str

class PregelTask:
    id: str
    name: str
    interrupts: tuple[Interrupt, ...]

class StateSnapshot:
    values: dict[str, Any]
    config: RunnableConfig
    next: tuple[str, ...]
    tasks: tuple[PregelTask, ...]
    interrupts: tuple[Interrupt, ...]

class Send:
    node: str
    arg: Any
    def __init__(self, /, node: str, arg: Any) -> None: ...

class Command[N]:
    def __init__(self, *, resume: Any | None = None) -> None: ...

def interrupt(value: Any) -> Any: ...
