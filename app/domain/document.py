from dataclasses import dataclass, field
from typing import Any


@dataclass
class Document:
    path: str
    size: int
    category: str | None = None
    tags: list[str] = field(default_factory=list)
    encoding: str | None = "utf-8"
    loader_args: dict[str, Any] | None = field(default_factory=dict)
    id: str | None = None
