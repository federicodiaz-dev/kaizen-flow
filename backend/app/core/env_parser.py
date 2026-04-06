from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any


ENV_LINE_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$")


def _normalize_env_value(raw_value: str) -> str:
    value = raw_value.strip()
    if not value:
        return ""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        try:
            normalized = ast.literal_eval(value)
            return str(normalized)
        except (SyntaxError, ValueError):
            return value[1:-1]
    return value


def _parse_json_blocks(lines: list[str]) -> list[dict[str, Any]]:
    json_blocks: list[dict[str, Any]] = []
    collecting = False
    buffer: list[str] = []
    depth = 0

    for raw_line in lines:
        stripped = raw_line.strip()
        if not collecting:
            if stripped.startswith("{"):
                collecting = True
                buffer = [raw_line]
                depth = raw_line.count("{") - raw_line.count("}")
                if depth <= 0:
                    try:
                        parsed = json.loads("\n".join(buffer))
                    except json.JSONDecodeError:
                        parsed = None
                    if isinstance(parsed, dict):
                        json_blocks.append(parsed)
                    collecting = False
                    buffer = []
                continue
        else:
            buffer.append(raw_line)
            depth += raw_line.count("{") - raw_line.count("}")
            if depth <= 0:
                try:
                    parsed = json.loads("\n".join(buffer))
                except json.JSONDecodeError:
                    parsed = None
                if isinstance(parsed, dict):
                    json_blocks.append(parsed)
                collecting = False
                buffer = []
                depth = 0

    return json_blocks


def parse_env_file(path: Path) -> tuple[dict[str, str], list[dict[str, Any]]]:
    if not path.exists():
        return {}, []

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    values: dict[str, str] = {}
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = ENV_LINE_RE.match(raw_line)
        if match:
            values[match.group(1)] = _normalize_env_value(match.group(2))

    return values, _parse_json_blocks(lines)
