"""Command-line interface for the Automated Tool Manager."""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from config import AppConfig, ConfigError, get_tool_by_name, load_config
from dependency_checker import DependencyChecker, DependencyReport
from detector import InstallStatus, ToolDetector, ToolStatus
from installer import Installer
from logger import setup_logger

logger = setup_logger(__name__)


def _status_icon(status: InstallStatus) -> str:
    """Return a short symbol for a tool install status."""
    return {
        InstallStatus.INSTALLED: "[OK]",
        InstallStatus.NOT_INSTALLED: "[MISSING]",
        InstallStatus.VERSION_UNKNOWN: "[UNKNOWN]",
        InstallStatus.ERROR: "[ERROR]",
    }.get(status, "[?]")


def format_tool_status(status: ToolStatus) -> str:
    """
    Format a single tool status line for display.

    Args:
        status: Tool check result.

    Returns:
        Multi-line formatted string.
    """
    lines = [
        f"{_status_icon(status.status)} {status.name}",
        f"    Status:   {status.status.value}",
    ]
    if status.executable_path:
        lines.append(f"    Path:     {status.executable_path}")
    if status.installed_version:
        lines.append(f"    Version:  {status.installed_version}")
    if status.expected_version:
        lines.append(f"    Expected: {status.expected_version}")
    if status.message and status.status != InstallStatus.INSTALLED:
        lines.append(f"    Note:     {status.message}")
    return "\n".join(lines)


def format_dependency_report(report: DependencyReport) -> str:
    """
    Format a dependency report for display.

    Args:
        report: Dependency check results for one scope.

    Returns:
        Multi-line formatted string.
    """
    lines = [f"\n--- Dependencies: {report.scope} ---"]
    if not report.results:
        lines.append("  (none configured)")
        return "\n".join(lines)

    for result in report.results:
        mark = "OK" if result.present else "MISSING"
        lines.append(f"  [{mark}] {result.kind.value}: {result.name} — {result.detail}")

    missing_count = len(report.missing)
    if missing_count:
        lines.append(f"  => {missing_count} missing, {len(report.present)} present")
    else:
        lines.append(f"  => All {len(report.present)} dependencies satisfied")
    return "\n".join(lines)


class ToolManagerCLI:
    """Parse arguments and dispatch CLI commands."""

    def __init__(
        self,
        config: Optional[AppConfig] = None,
        detector: Optional[ToolDetector] = None,
        dep_checker: Optional[DependencyChecker] = None,
        installer: Optional[Installer] = None,
    ) -> None:
        """
        Initialize CLI handlers.

        Args:
            config: Pre-loaded config (loaded from default path if None).
            detector: Tool detector instance.
            dep_checker: Dependency checker instance.
            installer: Package installer instance.
        """
        self.config = config
        self.detector = detector or ToolDetector()
        self.dep_checker = dep_checker or DependencyChecker()
        self.installer = installer or Installer()

    def _ensure_config(self) -> AppConfig:
        """Load config if not already provided."""
        if self.config is None:
            self.config = load_config()
        return self.config

    def cmd_list(self) -> int:
        """
        Show all managed tools and their installation status.

        Returns:
            Process exit code (0 on success).
        """
        config = self._ensure_config()
        logger.info("Running 'list' command")
        print("\n=== Managed Tools ===\n")

        statuses = self.detector.check_all(config.tools)
        for status in statuses:
            print(format_tool_status(status))
            print()

        installed = sum(1 for s in statuses if s.status == InstallStatus.INSTALLED)
        print(f"Summary: {installed}/{len(statuses)} tools installed\n")
        return 0

    def cmd_check(self, offer_install: bool = False) -> int:
        """
        Run tool detection and dependency checks, print a full report.

        Args:
            offer_install: If True, prompt to install missing tools/deps.

        Returns:
            Process exit code (0 if all OK, 1 if anything missing).
        """
        config = self._ensure_config()
        logger.info("Running 'check' command")
        print("\n=== Tool Status ===\n")

        tool_statuses = self.detector.check_all(config.tools)
        all_ok = True

        for status in tool_statuses:
            print(format_tool_status(status))
            print()
            if status.status != InstallStatus.INSTALLED:
                all_ok = False

        print("=== Dependency Status ===")
        dep_reports = self.dep_checker.check_all(config)
        for scope, report in dep_reports.items():
            print(format_dependency_report(report))
            if not report.all_present:
                all_ok = False

        if offer_install and not all_ok:
            self._offer_remediation(config, tool_statuses, dep_reports)

        print()
        if all_ok:
            print("All tools and dependencies are satisfied.")
            return 0

        print("Some tools or dependencies are missing — see report above.")
        return 1

    def _offer_remediation(
        self,
        config: AppConfig,
        tool_statuses: List[ToolStatus],
        dep_reports: dict,
    ) -> None:
        """
        Optionally prompt to install missing tools and system dependencies.

        Args:
            config: Application configuration.
            tool_statuses: Results from tool detection.
            dep_reports: Results from dependency checking.
        """
        missing_tools = [
            get_tool_by_name(config, s.name)
            for s in tool_statuses
            if s.status == InstallStatus.NOT_INSTALLED
        ]
        missing_tools = [t for t in missing_tools if t is not None]

        if missing_tools:
            print("\n=== Missing Tools ===")
            for tool in missing_tools:
                print(f"  - {tool.name} (apt: {tool.apt_package})")
            if self.installer.prompt_confirm("Install all missing tools?"):
                for tool in missing_tools:
                    ok, msg = self.installer.install_tool(tool)
                    print(f"  {tool.name}: {msg}")

        for scope, report in dep_reports.items():
            sys_missing = [d for d in report.missing if d.kind.value == "system"]
            if sys_missing:
                print(f"\n=== Missing system deps ({scope}) ===")
                for dep in sys_missing:
                    print(f"  - {dep.name}")
                ok, msg = self.installer.install_missing_system_deps(scope, sys_missing)
                print(f"  Result: {msg}")

    def cmd_install(self, tool_name: str, include_deps: bool = True) -> int:
        """
        Install a specific managed tool via apt.

        Args:
            tool_name: Name of the tool (e.g. ``ngspice``, ``kicad``).
            include_deps: Also install declared system dependencies.

        Returns:
            Process exit code.
        """
        config = self._ensure_config()
        tool = get_tool_by_name(config, tool_name)
        if tool is None:
            print(f"Error: Unknown tool '{tool_name}'. Managed tools: "
                  f"{', '.join(t.name for t in config.tools)}")
            return 1

        logger.info("Running 'install' for %s", tool.name)
        print(f"\nInstalling tool: {tool.name}\n")
        ok, msg = self.installer.install_tool(tool, include_dependencies=include_deps)
        print(msg)
        return 0 if ok else 1

    def cmd_install_deps(self, tool_name: Optional[str] = None) -> int:
        """
        Install missing system dependencies only.

        Args:
            tool_name: Scope to fix (tool name or omit for global+all).

        Returns:
            Process exit code.
        """
        config = self._ensure_config()
        dep_reports = self.dep_checker.check_all(config)
        scopes = [tool_name] if tool_name else list(dep_reports.keys())
        exit_code = 0

        for scope in scopes:
            report = dep_reports.get(scope)
            if report is None:
                print(f"Error: Unknown scope '{scope}'")
                exit_code = 1
                continue
            sys_missing = [d for d in report.missing if d.kind.value == "system"]
            if not sys_missing:
                print(f"{scope}: no missing system dependencies")
                continue
            ok, msg = self.installer.install_missing_system_deps(scope, sys_missing)
            print(f"{scope}: {msg}")
            if not ok:
                exit_code = 1
        return exit_code


def build_parser() -> argparse.ArgumentParser:
    """
    Build the argparse parser for the CLI.

    Returns:
        Configured ``ArgumentParser``.
    """
    parser = argparse.ArgumentParser(
        prog="tool-manager",
        description=(
            "Automated Tool Manager for eSim — check, install, and manage "
            "external tools (Ngspice, KiCad) and their dependencies on Ubuntu."
        ),
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to tools_config.json (default: alongside project files)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug logging",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="Show all managed tools and their status")

    check_parser = subparsers.add_parser("check", help="Run tool and dependency checks")
    check_parser.add_argument(
        "--fix",
        action="store_true",
        help="Offer to install missing tools and system dependencies",
    )

    install_parser = subparsers.add_parser("install", help="Install a managed tool via apt")
    install_parser.add_argument("tool", help="Tool name (e.g. ngspice, kicad)")
    install_parser.add_argument(
        "--no-deps",
        action="store_true",
        help="Install only the tool package, not its system dependencies",
    )

    deps_parser = subparsers.add_parser(
        "install-deps",
        help="Install missing system dependencies",
    )
    deps_parser.add_argument(
        "scope",
        nargs="?",
        default=None,
        help="Scope: tool name or 'global' (default: all scopes with missing deps)",
    )

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """
    CLI entry point.

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Process exit code.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.verbose:
        import logging
        logging.getLogger("tool_manager").setLevel(logging.DEBUG)

    try:
        config = load_config(args.config) if args.config else load_config()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    cli = ToolManagerCLI(config=config)

    try:
        if args.command == "list":
            return cli.cmd_list()
        if args.command == "check":
            return cli.cmd_check(offer_install=args.fix)
        if args.command == "install":
            return cli.cmd_install(args.tool, include_deps=not args.no_deps)
        if args.command == "install-deps":
            return cli.cmd_install_deps(args.scope)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130
    except Exception as exc:
        logger.exception("Unexpected error")
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    parser.print_help()
    return 1
