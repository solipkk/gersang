# Legacy DirectX RPA Toolkit

Portable Python-based automation tool for legacy DirectX applications. The project is split into a **launcher/updater** and a **core macro** module to simplify distribution via GitHub Releases and packaging with Nuitka.

## Components
- **Launcher** (`src/launcher/`): downloads the latest `core.zip` from GitHub Releases, extracts it to `core/`, and optionally starts the macro.
- **Core** (`src/core/`): PySide6 GUI that previews template matches, powered by OpenCV and `pydirectinput` for input dispatch.
- **Common** (`src/common/`): shared utilities such as semantic version parsing and persistence.

## Development
1. Install dependencies with `pip install -r requirements.txt` (Python 3.10+).
2. Run the GUI directly: `python -m core.main`.
3. Execute the launcher: `python -m launcher.main --owner <org> --repo <repo>`.

### Quick validation
- Run a bytecode compilation sweep to catch syntax issues early: `python -m compileall src build_launcher.py build_core.py build_final.py`.

## Packaging
Nuitka defaults are defined in `pyproject.toml` to create portable binaries (`standalone` mode). Build commands can be wired into GitHub Actions to publish zipped assets (`core.zip`) consumed by the launcher.
