"""Stable catalog boundary for tools exposed by the project Agent."""

from __future__ import annotations

from copy import deepcopy


class AgentToolRegistry:
    """Index tool schemas and access policy independently from execution."""

    def __init__(self, specs: list[dict], read_only: set[str] | frozenset[str]):
        self._specs = deepcopy(list(specs))
        self._by_name = {
            str(spec.get("function", {}).get("name", "")): spec
            for spec in self._specs
            if str(spec.get("function", {}).get("name", ""))
        }
        self._read_only = frozenset(str(name) for name in read_only)

    @property
    def names(self) -> frozenset[str]:
        return frozenset(self._by_name)

    def contains(self, name: str) -> bool:
        return str(name) in self._by_name

    def is_read_only(self, name: str) -> bool:
        return str(name) in self._read_only

    def is_write(self, name: str) -> bool:
        return self.contains(name) and not self.is_read_only(name)

    def specs(self, names=None) -> list[dict]:
        # Model clients may normalize schemas in place, so callers get a copy.
        allowed = None if names is None else {str(name) for name in names}
        return deepcopy([
            spec for spec in self._specs
            if allowed is None or spec["function"]["name"] in allowed
        ])

    def function_specs(self, names=None) -> list[dict]:
        return [deepcopy(spec["function"]) for spec in self.specs(names)]
