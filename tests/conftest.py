"""Shared test setup.

The repository keeps the Ollama model store in ./ollama, which shadows the
installed package when tests run outside the container. The classification code
only needs ``ollama.Client`` to exist, so a stub keeps imports working either
way.
"""

from __future__ import annotations

import sys
import types

if not hasattr(sys.modules.get("ollama", None), "Client"):
    _ollama_stub = types.ModuleType("ollama")
    _ollama_stub.Client = object  # type: ignore[attr-defined]
    sys.modules["ollama"] = _ollama_stub
