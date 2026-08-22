"""Load and hold tool definitions from the JSON configuration file."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "tools_config.json"


@dataclass
class ToolDefinition:
    """Configuration for a single managed external tool."""

    name: str
    description: str
    executable: str
    apt_package: str
    version_command: List[str]
    version_pattern: str
    expected_version: str
    system_dependencies: List[str] = field(default_factory=list)
    python_dependencies: List[str] = field(default_factory=list)


@dataclass
class AppConfig:
    """Top-level configuration loaded from ``tools_config.json``."""

    tools: List[ToolDefinition]
    global_system_dependencies: List[str] = field(default_factory=list)
    global_python_dependencies: List[str] = field(default_factory=list)
    config_path: Path = DEFAULT_CONFIG_PATH


class ConfigError(Exception):
    """Raised when the configuration file is missing or invalid."""


def _parse_tool(raw: dict[str, Any]) -> ToolDefinition:
    """Parse a single tool entry from the JSON config."""
    required = ("name", "executable", "apt_package", "version_command", "expected_version")
    missing = [key for key in required if key not in raw]
    if missing:
        raise ConfigError(f"Tool entry missing required fields: {', '.join(missing)}")

    version_command = raw["version_command"]
    if not isinstance(version_command, list) or not version_command:
        raise ConfigError(f"Tool '{raw['name']}': version_command must be a non-empty list")

    return ToolDefinition(
        name=str(raw["name"]),
        description=str(raw.get("description", "")),
        executable=str(raw["executable"]),
        apt_package=str(raw["apt_package"]),
        version_command=[str(part) for part in version_command],
        version_pattern=str(raw.get("version_pattern", r"(\d[\d\w.+~-]*)")),
        expected_version=str(raw["expected_version"]),
        system_dependencies=list(raw.get("system_dependencies", [])),
        python_dependencies=list(raw.get("python_dependencies", [])),
    )


def load_config(config_path: Optional[Path] = None) -> AppConfig:
    """
    Load tool definitions from a JSON configuration file.

    Args:
        config_path: Path to the config file. Defaults to ``tools_config.json``
            alongside this module.

    Returns:
        Parsed ``AppConfig`` instance.

    Raises:
        ConfigError: If the file is missing, unreadable, or malformed.
    """
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH

    if not path.is_file():
        raise ConfigError(f"Configuration file not found: {path}")

    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON in {path}: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"Could not read {path}: {exc}") from exc

    if "tools" not in data or not isinstance(data["tools"], list):
        raise ConfigError("Configuration must contain a 'tools' list")

    tools = [_parse_tool(entry) for entry in data["tools"]]

    return AppConfig(
        tools=tools,
        global_system_dependencies=list(data.get("global_system_dependencies", [])),
        global_python_dependencies=list(data.get("global_python_dependencies", [])),
        config_path=path,
    )


def get_tool_by_name(config: AppConfig, name: str) -> Optional[ToolDefinition]:
    """
    Look up a tool definition by name (case-insensitive).

    Args:
        config: Loaded application configuration.
        name: Tool name to find.

    Returns:
        Matching ``ToolDefinition`` or ``None``.
    """
    lowered = name.lower()
    for tool in config.tools:
        if tool.name.lower() == lowered:
            return tool
    return None
