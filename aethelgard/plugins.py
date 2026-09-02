from __future__ import annotations

from importlib.metadata import entry_points
from typing import Any

from .errors import PluginNotFound


class PluginRegistry:
    """Tiny entry-point based extension registry.

    External packages can register under groups such as
    `aethelgard.extractors`, `aethelgard.materializers`, or
    `aethelgard.sources`. No inheritance from Aethelgard classes is required;
    plugins only need to satisfy the corresponding Protocol.
    """

    def __init__(self) -> None:
        self._builtins: dict[tuple[str, str], Any] = {}

    def register(self, group: str, name: str, factory: Any) -> None:
        self._builtins[(group, name)] = factory

    def resolve(self, group: str, name: str) -> Any:
        if (group, name) in self._builtins:
            return self._builtins[(group, name)]
        matches = entry_points().select(group=f'aethelgard.{group}', name=name)
        for entry in matches:
            return entry.load()
        raise PluginNotFound(f'No Aethelgard plugin {group}:{name}')
