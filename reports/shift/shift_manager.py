from __future__ import annotations

import importlib
import runpy
import sys

_impl = importlib.import_module("src.domain.services.shift_manager")

if __name__ == "__main__":
    runpy.run_module(_impl.__name__, run_name="__main__")
else:
    sys.modules[__name__] = _impl
