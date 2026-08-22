# Design Document — eSim Automated Tool Manager

## 1. Overview

This prototype automates two responsibilities from the eSim screening task:

1. **Tool Installation Management** — detect Ngspice/KiCad, report versions, offer apt-based installation with user confirmation.
2. **Dependency Checker** — verify system packages (`dpkg`) and Python packages (`importlib` / `pip show`), reporting present vs missing clearly.

The design prioritizes **separation of concerns**, **safe subprocess usage**, and **extensibility** for non-Linux platforms without implementing them yet.

## 2. Architecture

```
                    ┌─────────────────┐
                    │    main.py      │
                    │  (entry point)  │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │     cli.py      │
                    │ argparse dispatch│
                    └───┬───┬───┬─────┘
                        │   │   │
         ┌──────────────┘   │   └──────────────┐
         │                  │                  │
┌────────▼────────┐ ┌───────▼────────┐ ┌───────▼────────┐
│  detector.py    │ │ dependency_    │ │  installer.py  │
│ ToolDetector    │ │ checker.py     │ │  Installer     │
│ PATH + version  │ │ DependencyChk  │ │  + AptBackend  │
└────────┬────────┘ └───────┬────────┘ └───────┬────────┘
         │                  │                  │
         └──────────┬───────┴──────────────────┘
                    │
         ┌──────────▼──────────┐         ┌──────────────┐
         │     config.py       │         │   logger.py  │
         │  loads JSON config  │         │ file+console │
         └──────────┬──────────┘         └──────────────┘
                    │
         ┌──────────▼──────────┐
         │ tools_config.json   │
         └─────────────────────┘
```

### Data flow by command

| Command | Flow |
|---------|------|
| `list` | CLI → Config → ToolDetector → formatted output + Logger |
| `check` | CLI → ToolDetector + DependencyChecker → report; optional `--fix` → Installer |
| `install` | CLI → Config lookup → Installer → AptInstallBackend → Logger |

## 3. Module Responsibilities

### `config.py`
- Loads `tools_config.json` into typed `ToolDefinition` / `AppConfig` dataclasses.
- **Why separate:** Expected versions and package names must not be hardcoded; eSim releases can update the JSON without code changes.

### `detector.py`
- `ToolDetector` uses `shutil.which()` for presence and `subprocess.run([...])` for version commands.
- Version strings are parsed with configurable regex patterns per tool.
- **Why separate:** Detection is read-only and safe to run anywhere; installation is a distinct, privileged operation.

### `dependency_checker.py`
- `AptQueryBackend` wraps `dpkg -s <package>` — isolated from checker logic.
- `DependencyChecker` also validates Python packages via `importlib.util.find_spec` with `pip show` fallback.
- Reports are structured (`DependencyReport`) so the CLI can print clear present/missing lists.

### `installer.py`
- `AptInstallBackend` encapsulates all `apt-get` / `sudo` usage.
- `Installer.confirm_and_install()` always prompts unless explicitly overridden for tests.
- Implements the `PackageManagerBackend` protocol so future backends plug in cleanly:

```python
# Future (not implemented):
# class BrewInstallBackend: ...
# class ChocoInstallBackend: ...
# installer = Installer(backend=BrewInstallBackend())
```

### `logger.py`
- Single setup function; all modules share one logger writing to `tool_manager.log` and stdout.

### `cli.py`
- Thin orchestration layer: parse args, load config, delegate to services, format output, map results to exit codes.

## 4. Design Decisions

| Decision | Rationale |
|----------|-----------|
| JSON config file | Task requirement; supports version bumps without redeploying code |
| No `shell=True` | Prevents injection; argv lists only |
| apt logic in backend classes | Clear seam for Windows (choco) / macOS (brew) |
| User confirmation before sudo | Task requirement; prototype must not auto-elevate |
| Graceful error handling | `try/except` around subprocess; user-facing messages, not tracebacks |
| Exit code 1 on `check` when missing | Enables scripting/CI integration |

## 5. Ubuntu Package Choices

Verified against Ubuntu repositories (packages.ubuntu.com):

| Tool | apt package | Notes |
|------|-------------|-------|
| Ngspice | `ngspice` | SPICE simulator binary |
| Ngspice libs | `libngspice0`, `libngspice0-dev` | Runtime + dev headers |
| KiCad | `kicad` | Full EDA suite from universe |
| Build tools | `build-essential` | gcc, make, etc. |
| Python tooling | `python3-pip` | pip for Python deps |

**Known ecosystem note:** KiCad PPAs may ship `libngspice-kicad` which conflicts with system `ngspice`. This prototype installs from standard Ubuntu repos; production eSim installers handle PPA conflicts separately.

## 6. Current Limitations

- **Linux/Ubuntu-focused** for installation and system dependency checks.
- No version *comparison* logic (reports installed vs expected as strings; does not enforce semver matching).
- No rollback or uninstall support.
- No network mirror configuration for apt.
- Python dependency *installation* is reported but not auto-installed (only system packages via apt in this prototype).
- Single-user CLI; no daemon or GUI.

## 7. Future Work

1. **Windows support** — `ChocoInstallBackend` / `WingetBackend` for Ngspice and KiCad; registry or PATH-based detection already partially works.
2. **macOS support** — `BrewInstallBackend` (`brew install ngspice kicad`).
3. **Version comparison** — use `packaging.version` to warn when installed version is below expected.
4. **Python dep installation** — optional `pip install -r` with confirmation, mirroring apt flow.
5. **Upgrade checking** — `apt list --upgradable` integration; notify when newer KiCad/Ngspice is available.
6. **GUI** — PyQt6 panel integrated into eSim settings, reusing the same service classes.
7. **Plugin architecture** — register additional tools (GHDL, Makerchip) via config only.
8. **Dry-run mode** — print planned commands without executing.

## 8. Testing Notes

On non-Ubuntu systems (e.g. Windows development machines):

- `list` and `check` run successfully; tools report `[MISSING]` if not on PATH.
- System dependency checks report `dpkg unavailable`.
- `install` reports that apt-get is not available.

Full installation flow should be validated on Ubuntu 22.04/24.04 LTS with:

```bash
python3 main.py check
python3 main.py install ngspice   # confirm with 'y'
python3 main.py list
```
