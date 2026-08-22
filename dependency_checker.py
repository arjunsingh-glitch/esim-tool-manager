"""Check system (apt/dpkg) and Python package dependencies."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Set

from config import AppConfig, ToolDefinition
from logger import setup_logger

logger = setup_logger(__name__)


class DependencyKind(str, Enum):
    """Category of a dependency."""

    SYSTEM = "system"
    PYTHON = "python"


@dataclass
class DependencyResult:
    """Outcome of checking a single dependency."""

    name: str
    kind: DependencyKind
    present: bool
    detail: str = ""


@dataclass
class DependencyReport:
    """Aggregated dependency check results for one scope."""

    scope: str
    results: List[DependencyResult] = field(default_factory=list)

    @property
    def present(self) -> List[DependencyResult]:
        """Dependencies that are satisfied."""
        return [r for r in self.results if r.present]

    @property
    def missing(self) -> List[DependencyResult]:
        """Dependencies that are not satisfied."""
        return [r for r in self.results if not r.present]

    @property
    def all_present(self) -> bool:
        """True when every dependency in this report is present."""
        return len(self.missing) == 0


class AptQueryBackend:
    """
    Ubuntu/Debian-specific package queries via ``dpkg``.

    OS-specific logic is isolated here so a future ``BrewBackend`` or
    ``ChocoBackend`` could be swapped in without changing ``DependencyChecker``.
    """

    @staticmethod
    def is_available() -> bool:
        """Return True if ``dpkg`` is available on this system."""
        return shutil.which("dpkg") is not None

    @staticmethod
    def is_package_installed(package: str) -> tuple[bool, str]:
        """
        Check whether an apt package is installed using ``dpkg -s``.

        Args:
            package: Debian package name.

        Returns:
            Tuple of (installed, detail message).
        """
        try:
            result = subprocess.run(
                ["dpkg", "-s", package],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            if result.returncode == 0:
                version_line = next(
                    (line for line in result.stdout.splitlines() if line.startswith("Version:")),
                    None,
                )
                version = version_line.split(":", 1)[1].strip() if version_line else "unknown"
                return True, f"installed (version {version})"
            return False, "not installed"
        except FileNotFoundError:
            return False, "dpkg not available (not a Debian/Ubuntu system?)"
        except subprocess.TimeoutExpired:
            return False, "dpkg query timed out"
        except OSError as exc:
            return False, f"OS error: {exc}"


class DependencyChecker:
    """
    Verify system and Python dependencies required by eSim tools.

    System packages are checked via ``dpkg`` on Ubuntu. Python packages are
    checked via ``importlib`` first, then ``pip show`` as a fallback.
    """

    def __init__(self, apt_backend: type[AptQueryBackend] | None = None) -> None:
        """
        Initialize the checker.

        Args:
            apt_backend: Injectable backend for OS package queries (testing/extension).
        """
        self._apt = apt_backend or AptQueryBackend

    def check_system_package(self, package: str) -> DependencyResult:
        """
        Check a single system (apt) package.

        Args:
            package: Debian package name.

        Returns:
            ``DependencyResult`` with presence and detail.
        """
        logger.info("Checking system package: %s", package)
        if not self._apt.is_available():
            return DependencyResult(
                name=package,
                kind=DependencyKind.SYSTEM,
                present=False,
                detail="dpkg unavailable — system dependency checks require Ubuntu/Debian",
            )

        installed, detail = self._apt.is_package_installed(package)
        return DependencyResult(
            name=package,
            kind=DependencyKind.SYSTEM,
            present=installed,
            detail=detail,
        )

    def check_python_package(self, package: str) -> DependencyResult:
        """
        Check whether a Python package is importable or installed via pip.

        Args:
            package: PyPI/import name (e.g. ``PyQt6``).

        Returns:
            ``DependencyResult`` with presence and detail.
        """
        logger.info("Checking Python package: %s", package)
        import_name = package.replace("-", "_").split("[")[0]

        if importlib.util.find_spec(import_name) is not None:
            return DependencyResult(
                name=package,
                kind=DependencyKind.PYTHON,
                present=True,
                detail="importable",
            )

        pip_detail = self._check_via_pip(package)
        if pip_detail:
            return DependencyResult(
                name=package,
                kind=DependencyKind.PYTHON,
                present=True,
                detail=pip_detail,
            )

        return DependencyResult(
            name=package,
            kind=DependencyKind.PYTHON,
            present=False,
            detail="not installed",
        )

    def _check_via_pip(self, package: str) -> str:
        """
        Fall back to ``pip show`` when import fails (e.g. namespace packages).

        Args:
            package: Package name for pip.

        Returns:
            Detail string if found, empty string otherwise.
        """
        pip_exe = shutil.which("pip3") or shutil.which("pip")
        if pip_exe is None:
            return ""

        try:
            result = subprocess.run(
                [pip_exe, "show", package],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if line.startswith("Version:"):
                        return f"installed via pip ({line.split(':', 1)[1].strip()})"
                return "installed via pip"
        except (subprocess.TimeoutExpired, OSError):
            pass
        return ""

    def check_tool_dependencies(self, tool: ToolDefinition) -> DependencyReport:
        """
        Check all dependencies declared for a single tool.

        Args:
            tool: Tool definition from configuration.

        Returns:
            ``DependencyReport`` scoped to the tool name.
        """
        results: List[DependencyResult] = []
        for pkg in tool.system_dependencies:
            results.append(self.check_system_package(pkg))
        for pkg in tool.python_dependencies:
            results.append(self.check_python_package(pkg))
        return DependencyReport(scope=tool.name, results=results)

    def check_global_dependencies(self, config: AppConfig) -> DependencyReport:
        """
        Check global system and Python dependencies from config.

        Args:
            config: Loaded application configuration.

        Returns:
            ``DependencyReport`` scoped to ``global``.
        """
        results: List[DependencyResult] = []
        seen_system: Set[str] = set()
        seen_python: Set[str] = set()

        for pkg in config.global_system_dependencies:
            if pkg not in seen_system:
                seen_system.add(pkg)
                results.append(self.check_system_package(pkg))

        for pkg in config.global_python_dependencies:
            if pkg not in seen_python:
                seen_python.add(pkg)
                results.append(self.check_python_package(pkg))

        return DependencyReport(scope="global", results=results)

    def check_all(self, config: AppConfig) -> Dict[str, DependencyReport]:
        """
        Run dependency checks for global deps and every managed tool.

        Args:
            config: Loaded application configuration.

        Returns:
            Mapping of scope name to ``DependencyReport``.
        """
        reports: Dict[str, DependencyReport] = {"global": self.check_global_dependencies(config)}
        for tool in config.tools:
            reports[tool.name] = self.check_tool_dependencies(tool)
        return reports
