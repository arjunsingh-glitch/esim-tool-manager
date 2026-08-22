# eSim Automated Tool Manager

A CLI-based Python prototype that automates checking, installing, and managing external tools that [eSim](https://esim.fossee.in/) depends on — primarily **Ngspice** and **KiCad** on Ubuntu/Debian systems. It detects installed tools, reports versions against configurable expectations, verifies system and Python dependencies, and offers guided installation via `apt` (always with explicit user confirmation before any `sudo` command).

## Installation

```bash
# Clone or copy this project
cd "Fossee- esim - task"

# Optional: create a virtual environment
python3 -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate    # Windows (for development only)

# Install optional Python dependencies
pip install -r requirements.txt
```

**Note:** Tool installation (`install` command) requires **Ubuntu/Debian** with `apt-get` and `dpkg`. Detection and Python dependency checks work on any OS where the tools are on PATH.

## Usage

Run via `main.py` or `python -m cli`:

```bash
python main.py --help
python main.py list
python main.py check
python main.py check --fix          # offer to install missing items
python main.py install ngspice
python main.py install kicad
python main.py install-deps         # install all missing system deps
python main.py install-deps ngspice # deps for one tool only
```

### `list` — show managed tools and status

```bash
$ python main.py list

=== Managed Tools ===

[MISSING] ngspice
    Status:   not_installed
    Expected: 36+
    Note:     ngspice is not installed or not on PATH

[OK] kicad
    Status:   installed
    Path:     /usr/bin/kicad
    Version:  7.0.11
    Expected: 7.0.0

Summary: 1/2 tools installed
```

### `check` — full tool + dependency report

```bash
$ python main.py check

=== Tool Status ===

[OK] ngspice
    Status:   installed
    Path:     /usr/bin/ngspice
    Version:  36+ds-1
    Expected: 36+

[OK] kicad
    ...

=== Dependency Status ===

--- Dependencies: global ---
  [OK] system: python3-pip — installed (version 24.0-1)
  [OK] system: build-essential — installed (version 12.10ubuntu1)
  [MISSING] python: scipy — not installed
  => 1 missing, 3 present

--- Dependencies: ngspice ---
  [OK] system: libngspice0 — installed (version 42+ds-3build1)
  ...

All tools and dependencies are satisfied.
```

Exit code is `0` when everything is present, `1` when anything is missing.

### `install <tool>` — install with confirmation

```bash
$ python main.py install ngspice

Installing tool: ngspice

Install ngspice (ngspice) and its system dependencies
The following command will be executed:

  sudo apt-get update && sudo apt-get install -y libngspice0 libngspice0-dev build-essential ngspice

Proceed? [y/N]: y
Successfully installed: libngspice0, libngspice0-dev, build-essential, ngspice
```

Installation is **never** run without typing `y` at the prompt.

## Project Structure

```
.
├── main.py                 # Entry point
├── cli.py                  # argparse CLI (list, check, install)
├── config.py               # Load tools_config.json into dataclasses
├── detector.py             # ToolDetector — PATH + version checks
├── dependency_checker.py   # DependencyChecker — dpkg + importlib/pip
├── installer.py            # Installer + AptInstallBackend (isolated apt logic)
├── logger.py               # Console + file logging (tool_manager.log)
├── tools_config.json       # Tool definitions (NOT hardcoded in Python)
├── requirements.txt
├── README.md
└── DESIGN.md
```

## Configuration

Edit `tools_config.json` to change expected versions, apt package names, version commands, or dependency lists — no Python code changes required.

| Field | Purpose |
|-------|---------|
| `executable` | Binary name checked on PATH |
| `apt_package` | Ubuntu package for installation |
| `version_command` | argv list for version query (no shell) |
| `version_pattern` | Regex capture group for version parsing |
| `expected_version` | Documented/supported version reference |
| `system_dependencies` | apt packages required per tool |

## Logging

All actions are logged to `tool_manager.log` in the working directory with timestamps, and echoed to the console.

## Platform Support

| Feature | Ubuntu/Debian | Windows/macOS |
|---------|---------------|---------------|
| Tool detection (PATH) | Yes | Yes |
| Version parsing | Yes | Yes |
| System dep check (`dpkg`) | Yes | Reports unavailable |
| apt install | Yes | Not supported (prototype) |
| Python dep check | Yes | Yes |

See `DESIGN.md` for architecture details and future work (choco/brew support, GUI, upgrade checks).
