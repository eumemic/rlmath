"""Lean backends (DIRECTION.md §5.3).

`kimina` is deliberately NOT re-exported here: it is the HTTP/GPU-box path and
importing it must never be a precondition for using the local REPL pool.
Reach it through `factory.get_backend("kimina", ...)`.
"""
from .factory import BACKENDS, get_backend
from .repl_pool import ReplConfig, ReplPool, ReplWorker

__all__ = ["BACKENDS", "ReplConfig", "ReplPool", "ReplWorker", "get_backend"]
