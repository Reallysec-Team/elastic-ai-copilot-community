"""Cython compile step — runs ONLY inside the Docker image build.

Compiles the license-enforcement modules — plus ``main.py``, which owns the
FastAPI ``app`` object and registers ``LicenseGateMiddleware`` — into native
``.so`` extensions, then deletes the plaintext ``.py`` source. The shipped
image therefore cannot have its license gate patched out (e.g. by deleting
the ``app.add_middleware(LicenseGateMiddleware)`` line) without native-binary
reverse engineering.

The source tree under ``poc/`` stays plaintext Python: local development,
the eval suite and the Playwright E2E suite all run against the readable
source. Only the Docker image is obfuscated.

Invoked by the Dockerfile's ``compiler`` stage:

    python backend/_cython_build.py

Requires Cython, setuptools and a C toolchain — all build-time only (see
poc/requirements-build.txt). See docs/SECURITY.md for the threat model and
the boundary of what this does and does not protect.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from setuptools import Extension, setup
from Cython.Build import cythonize

HERE = Path(__file__).resolve().parent

# Modules compiled to native .so. main.py is included on purpose: it builds
# the FastAPI `app` and registers LicenseGateMiddleware, so leaving it as
# plaintext would let an attacker disable the gate by editing one line.
TARGETS = [
    "main.py",
    "license_gate.py",
    "license_state.py",
    "license_verifier.py",
    "heartbeat.py",
    "server_guid.py",
    "rstlic_client.py",
]

# binding=True is REQUIRED: FastAPI introspects route-handler signatures
# (inspect.signature + annotations) to build request models. Cython's
# non-binding functions are not introspectable, so FastAPI would fail to
# wire up the routes. language_level=3 refuses Python-2 idioms.
COMPILER_DIRECTIVES = {
    "language_level": "3",
    "binding": True,
    "always_allow_keywords": True,
    "embedsignature": False,
}


def main() -> None:
    # build_ext --inplace drops each <module>.<abi>.so next to its source,
    # which means "in the current working directory" for loose (non-package)
    # files — so run from the backend/ directory.
    os.chdir(HERE)
    os.environ.setdefault("SETUPTOOLS_USE_DISTUTILS", "stdlib")

    missing = [t for t in TARGETS if not (HERE / t).is_file()]
    if missing:
        print(f"FAIL: target source(s) not found: {missing}", file=sys.stderr)
        raise SystemExit(2)

    sys.argv = [sys.argv[0], "build_ext", "--inplace"]
    # Bare-stem Extension names ("main", not "backend.main"). backend/ has an
    # __init__.py, so passing plain paths would make Cython auto-name each
    # extension "backend.<stem>" — and `build_ext --inplace` would then drop
    # the .so into a nested backend/backend/ directory. A bare name keeps
    # --inplace placing each .so directly next to its source. The runtime
    # dotted name (backend.<stem>) is assigned by the import system, so the
    # relative imports inside the compiled modules still resolve correctly.
    extensions = [Extension(Path(t).stem, [str(HERE / t)]) for t in TARGETS]
    setup(
        name="rst_copilot_obfuscated",
        ext_modules=cythonize(
            extensions,
            compiler_directives=COMPILER_DIRECTIVES,
            quiet=False,
            nthreads=0,
        ),
        script_args=sys.argv[1:],
    )

    # Confirm every target produced a .so BEFORE deleting any source — a
    # failed compile must leave the tree intact so the build fails loudly.
    produced: list[str] = []
    for t in TARGETS:
        stem = Path(t).stem
        sos = sorted(HERE.glob(f"{stem}*.so"))
        if not sos:
            print(f"FAIL: Cython produced no .so for {t}", file=sys.stderr)
            raise SystemExit(2)
        produced.extend(p.name for p in sos)

    # Strip the plaintext source and the Cython .c intermediate of every
    # compiled module — defence-in-depth: ship exactly one artefact.
    for t in TARGETS:
        stem = Path(t).stem
        (HERE / t).unlink(missing_ok=True)
        (HERE / f"{stem}.c").unlink(missing_ok=True)

    build_dir = HERE / "build"
    if build_dir.is_dir():
        shutil.rmtree(build_dir)
    for egg_info in HERE.glob("*.egg-info"):
        shutil.rmtree(egg_info, ignore_errors=True)

    print(f"[cython-build] compiled + stripped {len(TARGETS)} module(s):")
    for name in produced:
        print(f"  - {name}")

    # The build script itself is build-time only — don't ship it in the image.
    (HERE / "_cython_build.py").unlink(missing_ok=True)


if __name__ == "__main__":
    main()
