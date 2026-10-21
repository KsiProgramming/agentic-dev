from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.serde.base import SerializerProtocol

class InMemorySaver(BaseCheckpointSaver[str]):
    def __init__(self, *, serde: SerializerProtocol | None = None) -> None: ...
