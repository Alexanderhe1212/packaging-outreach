# Windows customer installer build

The NSIS EXE contains the official CPython 3.14.10 embeddable x64 runtime and Windows-only dependency wheels. No customer installs Python or pip.

## Reproduce
1. Create an isolated build directory outside the repository.
2. Download `https://www.python.org/ftp/python/3.14.10/python-3.14.10-embed-amd64.zip` into downloads; expected SHA256: `90905e64a840557d8c1bc4f5b74db3d7ee85e3ffb217611cac1c7813acea4159`.
3. Download dependency wheels using `pip download --only-binary=:all: --platform win_amd64 --python-version 314 --implementation cp --abi cp314 --dest BUILD/wheels -r distribution/windows/requirements-windows.txt`. Preserve dependency-hashes.json with the build. Version ranges resolve at build time; use archived wheels for an exact rebuild.
4. Run `python distribution/windows/prepare_installer.py BUILD` using a development Python with pip.
5. In BUILD run NSIS 3.11 `makensis installer.nsi` (a Linux/macOS host can compile the Windows installer).
6. Extract the EXE using 7-Zip and compare every payload-manifest.json entry against extracted bytes. Run isolated HTTP smoke and 20-company mock dry-run using extracted app code. Do not use personal data or credentials.
7. Run `python -m unittest discover -s distribution/windows/tests -v` and backend regression tests, with `NO_PROXY=127.0.0.1,localhost` for the local mock HTTP server.
8. On a clean Windows 10/11 x64 test machine, verify installation, Unicode/spaced paths, no system Python, first launch paused, account setup, stop, upgrade refusal while running, and uninstall preserving synthetic data. This step remains NOT EXECUTED for the 2026-10-28 build.

Only tracked runtime source is exported. Symbolic links inside the repository are materialized for Windows; external links are rejected. Customer project profiles, histories, credentials and runtime folders are excluded. The executable is unsigned; production signing needs a publisher certificate, not a self-signed assertion of trust.

Installer-specific adaptations: explicit embedded import path and UTF-8, customer-only environment, local single-instance mutex, no implicit send startup, source-only updater disabled, PDF interpreter uses bundled executable, pairing path follows customer environment. No sending/suppression/image/identity guard source is altered. Mac desktop/launchd and optional Codex/browser automation remain outside Windows acceptance.

Official runtime distribution documentation: https://docs.python.org/3.14/using/windows.html#the-embeddable-package
NSIS build documentation: https://nsis.sourceforge.io/Docs/AppendixG.html
