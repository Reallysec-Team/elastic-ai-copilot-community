"""license_verifier — thin shim over the shared rstlic SDK verifier.

This product no longer maintains its own verifier fork. The crypto + token
checks now live in the shared, security-audited SDK module ``rstlic_verifier``
(vendored next to this file, kept in sync from
``rst-platform/license-server/sdk/python/`` via the standalone
``rst-license-sdk/`` copy).

``license_state.py`` imports these four names from here; they are re-exported
unchanged from the shared module so the import keeps working byte-for-byte:

    from license_verifier import (
        verify_token, verify_session_token, session_token_expiry, InvalidLicense,
    )

Why a shim instead of editing this file directly: future SDK security fixes
land in ``rstlic_verifier.py`` only — re-copy that one file and this shim never
changes. ``InvalidLicense`` is the shared module's back-compat alias for
``LicenseError``.

The previous standalone implementation is preserved as
``license_verifier.py.fork-pre-converge`` for reference.
"""
from rstlic_verifier import (  # noqa: F401  (flat: see backend/__init__.py)
    verify_token,
    verify_session_token,
    session_token_expiry,
    LicenseError,
    InvalidLicense,
)
