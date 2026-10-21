from langgraph.checkpoint.serde.base import SerializerProtocol

class BaseCheckpointSaver[V]:
    serde: SerializerProtocol
