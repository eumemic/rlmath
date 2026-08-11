"""One place that turns a backend *name* into a `LeanBackend`.

Every entry point (bank builder, bench, episode runner, the verifiers env) takes
a `--backend` string, and the whole point of core/backend.py's protocol is that
the GPU-box migration is a constructor swap. Keeping the switch here means the
swap happens once rather than in each script.

Imports are lazy on purpose: `kimina` pulls httpx and assumes a server, `repl`
assumes a toolchain. Importing this module must cost nothing and must not fail
because the *other* backend's dependencies are absent.
"""
from __future__ import annotations

from rlmath.core.backend import LeanBackend

BACKENDS = ("repl", "kimina")


def get_backend(name: str, **kwargs) -> LeanBackend:
    """Construct a backend by name.

    repl   -> rlmath.lean.repl_pool.ReplPool (local warm-worker pool; macOS path)
    kimina -> rlmath.lean.kimina.KiminaClient (HTTP; the Linux/GPU-box path)
    """
    if name == "repl":
        from .repl_pool import ReplPool

        return ReplPool(**kwargs)
    if name == "kimina":
        # Lazy so that a missing/unfinished kimina module never breaks repl use.
        from .kimina import KiminaClient

        return KiminaClient(**kwargs)
    if name == "fake":
        raise ValueError(
            "no 'fake' backend is constructible from the factory: offline tests use "
            "tests/conftest.py::FakeBackend (or tests/test_repl_pool.py's fake transport "
            "for REPL-protocol tests), and scripts inject their own stub "
            "(scripts/build_bank.py FAKE_BACKEND_FACTORY). A factory-built fake would let "
            "a real run silently 'verify' nothing."
        )
    raise ValueError(f"unknown backend {name!r}; expected one of {BACKENDS}")
