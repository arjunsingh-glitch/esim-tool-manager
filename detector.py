"""Detect installed tools and parse their version strings."""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

from config import ToolDefinition
from logger import setup_logger

logger = setup_logger(__name__)


class InstallStatus(str, Enum):
    """Installation state of a managed tool."""

    INSTALLED = "installed"
    NOT_INSTALLED = "not_installed"
    VERSION_UNKNOWN = "version_unknown"
    ERROR = "error"


@dataclass
class ToolStatus:
    """Result of checking a single tool on the system."""

    name: str
    status: InstallStatus
    installed_version: Optional[str] = None
    expected_version: Optional[str] = None
    executable_path: Optional[str] = None
    message: str = ""


class ToolDetector:
    """
    Check whether managed tools exist on PATH and retrieve their versions.

    Uses ``shutil.which`` for presence detection and runs the configured
    version command via ``subprocess`` (never with ``shell=True``).
    """

    def __init__(self) -> None:
        """Initialize the detector."""

    def is_on_path(self, executable: str) -> Optional[str]:
        """
        Return the full path to *executable* if it is on PATH.

        Args:
            executable: Binary name to look up.

        Returns:
            Absolute path string, or ``None`` if not found.
        """
        return shutil.which(executable)

    def run_version_command(self, command: List[str]) -> tuple[bool, str]:
        """
        Run a version query command safely.

        Args:
            command: argv list passed to ``subprocess.run``.

        Returns:
            Tuple of (success, combined stdout/stderr output).
        """
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            output = (result.stdout or "") + (result.stderr or "")
            output = output.strip()
            if result.returncode != 0 and not output:
                return False, f"Command exited with code {result.returncode}"
            return True, output
        except FileNotFoundError:
            return False, f"Command not found: {command[0]}"
        except subprocess.TimeoutExpired:
            return False, "Version command timed out after 30 seconds"
        except PermissionError:
            return False, "Permission denied while running version command"
        except OSError as exc:
            return False, f"OS error: {exc}"

    def parse_version(self, output: str, pattern: str) -> Optional[str]:
        """
        Extract a version string from command output using *pattern*.

        Args:
            output: Raw text from the version command.
            pattern: Regular expression with one capture group for the version.

        Returns:
            Captured version string, or ``None`` if no match.
        """
        match = re.search(pattern, output)
        if match:
            return match.group(1)
        return None

    def check_tool(self, tool: ToolDefinition) -> ToolStatus:
        """
        Determine installation status and version for a single tool.

        Args:
            tool: Tool definition from configuration.

        Returns:
            ``ToolStatus`` describing the current state.
        """
        logger.info("Checking tool: %s", tool.name)
        executable_path = self.is_on_path(tool.executable)

        if executable_path is None:
            logger.info("%s: not found on PATH", tool.name)
            return ToolStatus(
                name=tool.name,
                status=InstallStatus.NOT_INSTALLED,
                expected_version=tool.expected_version,
                message=f"{tool.executable} is not installed or not on PATH",
            )

        ok, output = self.run_version_command(tool.version_command)
        if not ok:
            logger.warning("%s: version check failed — %s", tool.name, output)
            return ToolStatus(
                name=tool.name,
                status=InstallStatus.VERSION_UNKNOWN,
                executable_path=executable_path,
                expected_version=tool.expected_version,
                message=output,
            )

        version = self.parse_version(output, tool.version_pattern)
        if version is None:
            logger.warning("%s: could not parse version from: %s", tool.name, output[:120])
            return ToolStatus(
                name=tool.name,
                status=InstallStatus.VERSION_UNKNOWN,
                executable_path=executable_path,
                expected_version=tool.expected_version,
                message=f"Could not parse version. Raw output: {output[:200]}",
            )

        logger.info("%s: installed (version %s)", tool.name, version)
        return ToolStatus(
            name=tool.name,
            status=InstallStatus.INSTALLED,
            installed_version=version,
            expected_version=tool.expected_version,
            executable_path=executable_path,
            message="OK",
        )

    def check_all(self, tools: List[ToolDefinition]) -> List[ToolStatus]:
        """
        Check every tool in *tools*.

        Args:
            tools: List of tool definitions.

        Returns:
            List of ``ToolStatus`` results, one per tool.
        """
        return [self.check_tool(tool) for tool in tools]
