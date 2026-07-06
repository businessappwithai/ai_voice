"""mcp-servers/* are standalone deployable services (own requirements,
own working directory) — not part of the installable saap package.
Each one's internal modules use plain top-level imports (`from store
import ...`, not `from .store import ...`), matching how they actually
run in production (`python server.py` from within their own
directory/container).

Both `calendar` and `sql-readonly` happen to each have a module
literally named `server.py` — a real production deployment never
imports both in the same process, but a test session does, so this
loader purges any stale same-named module from `sys.modules` before
loading a sibling server's module of the same name, avoiding a cache
collision that would silently return the wrong server's code.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]


def load_server_module(server_dir_name: str, module_filename: str) -> ModuleType:
    server_dir = REPO_ROOT / "mcp-servers" / server_dir_name
    module_name = module_filename.removesuffix(".py")

    sys.modules.pop(module_name, None)
    path_entry = str(server_dir)
    if path_entry in sys.path:
        sys.path.remove(path_entry)
    sys.path.insert(0, path_entry)

    spec = importlib.util.spec_from_file_location(module_name, server_dir / module_filename)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load {module_filename} from {server_dir}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module
