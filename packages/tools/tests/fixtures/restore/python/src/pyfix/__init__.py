from pydantic import BaseModel


class Fixture(BaseModel):
    name: str = "pyfix"
