from typing import Protocol

from pydantic import BaseModel


class ArchitectureRequest(BaseModel):
    project_id: str
    requirement_version: int


class ArchitectureGateway(Protocol):
    async def request_review(self, request: ArchitectureRequest) -> str:
        """Return an external review ID; approval remains a backend responsibility."""
        ...
