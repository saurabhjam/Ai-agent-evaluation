"""Small JSONPath resolver for backend validation assertions."""

from __future__ import annotations

import re
from typing import Any


MISSING = object()


def resolve_jsonpath(data: Any, path: str) -> Any:
    if path == "$":
        return data
    if not path.startswith("$."):
        path = f"$.{path}"
    current = data
    for token in _tokens(path):
        if isinstance(token, str):
            if not isinstance(current, dict) or token not in current:
                return MISSING
            current = current[token]
        else:
            if not isinstance(current, list) or token >= len(current):
                return MISSING
            current = current[token]
    return current


def _tokens(path: str) -> list[str | int]:
    if not path.startswith("$"):
        raise ValueError(f"Invalid JSONPath: {path}")
    path = path[1:]
    tokens: list[str | int] = []
    pattern = re.compile(r"(?:\.([A-Za-z_][A-Za-z0-9_]*))|(?:\[(\d+)\])")
    position = 0
    while position < len(path):
        match = pattern.match(path, position)
        if not match:
            raise ValueError(f"Invalid JSONPath: ${path}")
        key, index = match.groups()
        tokens.append(key if key is not None else int(index))
        position = match.end()
    return tokens
