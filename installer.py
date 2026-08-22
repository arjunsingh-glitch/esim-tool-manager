"""Install tools and dependencies via apt with explicit user confirmation."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable, List, Optional, Protocol

from config import ToolDefinition
from dependency_checker import DependencyResult
from logger import setup_logger

logger = setup_logger(__name__)

ConfirmCallback = Callable[[str], bool]


class PackageManagerBackend(Protocol):
    """Protocol for OS-specific package installation backends."""

    def is_available(self) -> bool:
        """Return True if this backend can run on the current system."""

    def install_packages(self, packages: List[str], use_sudo: bool = True) -> tuple[bool, str]:
        """Install the given packages and return (success, message)."""


class AptInstallBackend:
    """
    Ubuntu/Debian package installation via ``apt-get``.

    All apt/sudo commands live in this class so Windows (choco) or macOS (brew)
    backends can be added alongside it without touching ``Installer`` logic.
    """

    def is_available(self) -> bool:
        """Return True if ``apt-get`` is on PATH."""
        return shutil.which("apt-get") is not None

    def install_packages(self, packages: List[str], use_sudo: bool = True) -> tuple[bool, str]:
        """
        Run ``apt-get update`` then ``apt-get install`` for *packages*.

        Args:
            packages: Debian package names to install.
            use_sudo: Prefix commands with ``sudo`` when True.

        Returns:
            Tuple of (success, human-readable message).
        """
        if not packages:
            return True, "Nothing to install"

        prefix: List[str] = ["sudo"] if use_sudo else []
        apt_get = shutil.which("apt-get") or "apt-get"

        try:
            update_cmd = prefix + [apt_get, "update"]
            logger.info("Running: %s", " ".join(update_cmd))
            update = subprocess.run(
                update_cmd,
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
            if update.returncode != 0:
                detail = (update.stderr or update.stdout or "").strip()
                return False, f"apt-get update failed: {detail[:500]}"

            install_cmd = prefix + [
                apt_get,
                "install",
                "-y",
                "--no-install-recommends",
                *packages,
            ]
            logger.info("Running: %s", " ".join(install_cmd))
            install = subprocess.run(
                install_cmd,
                capture_output=True,
                text=True,
                timeout=600,
                check=False,
            )
            if install.returncode != 0:
                detail = (install.stderr or install.stdout or "").strip()
                return False, f"apt-get install failed: {detail[:500]}"

            return True, f"Successfully installed: {', '.join(packages)}"
        except FileNotFoundError:
            return False, "apt-get not found — this installer requires Ubuntu/Debian"
        except subprocess.TimeoutExpired:
            return False, "Installation timed out"
        except PermissionError:
            return False, "Permission denied — try running with sudo or check permissions"
        except OSError as exc:
            return False, f"OS error during installation: {exc}"


@dataclass
class InstallPlan:
    """Packages queued for installation."""

    tool_name: str
    packages: List[str]
    description: str


class Installer:
    """
    Offer and perform apt installations after explicit user confirmation.

    Never runs sudo/apt commands without prompting unless ``auto_confirm`` is
    set (intended for testing only).
    """

    def __init__(
        self,
        backend: Optional[PackageManagerBackend] = None,
        confirm_callback: Optional[ConfirmCallback] = None,
        auto_confirm: bool = False,
    ) -> None:
        """
        Initialize the installer.

        Args:
            backend: OS package manager backend (defaults to ``AptInstallBackend``).
            confirm_callback: Callable that returns True to proceed with install.
            auto_confirm: Skip prompts when True (testing only).
        """
        self._backend = backend or AptInstallBackend()
        self._confirm = confirm_callback or self._default_confirm
        self._auto_confirm = auto_confirm

    def prompt_confirm(self, message: str) -> bool:
        """
        Ask the user for installation confirmation.

        Args:
            message: Prompt text to display.

        Returns:
            True if the user agreed to proceed.
        """
        if self._auto_confirm:
            return True
        return self._confirm(message)

    @staticmethod
    def _default_confirm(message: str) -> bool:
        """
        Prompt the user on stdin for y/N confirmation.

        Args:
            message: Prompt text to display.

        Returns:
            True if the user answered yes (y/yes).
        """
        print(message)
        try:
            answer = input("Proceed? [y/N]: ").strip().lower()
        except EOFError:
            return False
        return answer in ("y", "yes")

    def build_tool_plan(self, tool: ToolDefinition, include_dependencies: bool = True) -> InstallPlan:
        """
        Build an install plan for a managed tool.

        Args:
            tool: Tool to install.
            include_dependencies: Also include the tool's system dependencies.

        Returns:
            ``InstallPlan`` listing apt packages to install.
        """
        packages = [tool.apt_package]
        if include_dependencies:
            packages.extend(tool.system_dependencies)
        # Preserve order, remove duplicates
        seen: set[str] = set()
        unique: List[str] = []
        for pkg in packages:
            if pkg not in seen:
                seen.add(pkg)
                unique.append(pkg)
        return InstallPlan(
            tool_name=tool.name,
            packages=unique,
            description=f"Install {tool.name} ({tool.apt_package}) and its system dependencies",
        )

    def build_dependency_plan(
        self,
        scope: str,
        missing: List[DependencyResult],
    ) -> InstallPlan:
        """
        Build an install plan from missing system dependencies.

        Args:
            scope: Report scope label (tool name or ``global``).
            missing: Missing dependency results (system only).

        Returns:
            ``InstallPlan`` for the missing apt packages.
        """
        packages = [dep.name for dep in missing if dep.kind.value == "system"]
        return InstallPlan(
            tool_name=scope,
            packages=packages,
            description=f"Install missing system dependencies for {scope}",
        )

    def confirm_and_install(self, plan: InstallPlan) -> tuple[bool, str]:
        """
        Ask for confirmation, then install packages from *plan*.

        Args:
            plan: Installation plan to execute.

        Returns:
            Tuple of (success, message).
        """
        if not plan.packages:
            return True, "No packages to install"

        if not self._backend.is_available():
            return False, (
                "apt-get is not available on this system. "
                "This prototype supports Ubuntu/Debian only."
            )

        cmd_preview = f"sudo apt-get update && sudo apt-get install -y {' '.join(plan.packages)}"
        prompt = (
            f"\n{plan.description}\n"
            f"The following command will be executed:\n\n"
            f"  {cmd_preview}\n"
        )

        if not self.prompt_confirm(prompt):
            logger.info("User declined installation for %s", plan.tool_name)
            return False, "Installation cancelled by user"

        logger.info("Installing packages for %s: %s", plan.tool_name, plan.packages)
        success, message = self._backend.install_packages(plan.packages)
        if success:
            logger.info(message)
        else:
            logger.error(message)
        return success, message

    def install_tool(self, tool: ToolDefinition, include_dependencies: bool = True) -> tuple[bool, str]:
        """
        Install a managed tool and optionally its system dependencies.

        Args:
            tool: Tool definition to install.
            include_dependencies: Include declared system dependencies.

        Returns:
            Tuple of (success, message).
        """
        plan = self.build_tool_plan(tool, include_dependencies=include_dependencies)
        return self.confirm_and_install(plan)

    def install_missing_system_deps(
        self,
        scope: str,
        missing: List[DependencyResult],
    ) -> tuple[bool, str]:
        """
        Install missing system packages for a dependency report scope.

        Args:
            scope: Scope label for logging.
            missing: Missing dependencies from a report.

        Returns:
            Tuple of (success, message).
        """
        plan = self.build_dependency_plan(scope, missing)
        return self.confirm_and_install(plan)
