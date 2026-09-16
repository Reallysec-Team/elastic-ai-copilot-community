"""RST Elastic AI Copilot backend package.

The vendored RST license SDK files (``rstlic_*.py``) are written with FLAT,
top-level imports (``from rstlic_client import ...``) on purpose — that is what
lets them be vendored verbatim from ``rst-platform/license-server/sdk/python``
and re-synced one file at a time without edits (see that repo's
``sdk/AGENTS.md`` Recipe A). The app, however, runs as the ``backend`` package
(``backend.main:app`` with ``PYTHONPATH=/app``), so this directory is not on
``sys.path`` by default and those flat sibling imports would not resolve.

Putting this directory on ``sys.path`` here fixes that AND ensures every
importer — product code and SDK code alike — resolves ``rstlic_client`` /
``rstlic_verifier`` to a SINGLE module identity. (If product code imported
``.rstlic_client`` relatively while the SDK lifecycle imported it flat, the two
would be distinct module objects with distinct ``RSTLicRevoked`` classes, and
``except RSTLicRevoked`` in one would silently miss the other's exception.)
So all ``rstlic_*`` imports across this package use the flat form.
"""
import os as _os
import sys as _sys

_HERE = _os.path.dirname(_os.path.abspath(__file__))
if _HERE not in _sys.path:
    _sys.path.insert(0, _HERE)
