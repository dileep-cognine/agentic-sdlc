from typing import Protocol, TypeVar

from pydantic import BaseModel

from app.analysis_schemas import Usage

T = TypeVar("T", bound=BaseModel)


class StructuredLLM(Protocol):
    def check(self) -> dict:
        """Check remote connectivity and configured model availability."""
        ...

    def generate(self, schema: type[T], instructions: str, payload: dict) -> tuple[T, Usage]:
        """Return untrusted schema-validated output and usage for deterministic validation."""
        ...
