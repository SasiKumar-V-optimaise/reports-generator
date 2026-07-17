from __future__ import annotations

import sys

from src.application.workflows import shift_report_workflow as _impl
from src.interfaces.cli import report_workflow_cli as _cli

_impl.main = _cli.main
_impl.build_parser = _cli.build_parser
_impl._selected_ids_from_args = _cli._selected_ids_from_args

if __name__ == "__main__":
    _cli.main()
else:
    sys.modules[__name__] = _impl
