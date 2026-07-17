import argparse
from datetime import date, datetime

from reports_generator.application.models import WorkflowRequest
from reports_generator.bootstrap import create_application
from reports_generator.domain.shifts.models import Shift


def _date(value: str) -> date:
    try:
        return datetime.strptime(value, "%d-%m-%Y").date()
    except ValueError:
        return date.fromisoformat(value)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="reports-generator")
    s = p.add_subparsers(dest="command")
    for name in ("report", "video"):
        x = s.add_parser(name)
        x.add_argument("--date", dest="production_date", default=date.today().isoformat())
        x.add_argument("--shift", default="A")
        x.add_argument("--caster", action="append", default=[])
        x.add_argument("--casters", nargs="+")
        x.add_argument("--all-casters", action="store_true")
        x.add_argument("--test", action="store_true")
        x.add_argument("--verified-only", action="store_true")
        x.add_argument("--diagnosis-only", action="store_true")
        x.set_defaults(func=run_report)
    s.add_parser("storage").set_defaults(func=run_storage)
    return p


def run_report(args: argparse.Namespace) -> int:
    ids = tuple(args.casters or args.caster or ())
    _, wf = create_application(caster_ids=ids)
    r = wf.run(
        WorkflowRequest(_date(args.production_date), Shift.parse(args.shift), ids, args.test)
    )
    for caster in r.caster_results:
        for stage in caster.stages:
            status = "OK" if stage.success else "FAILED"
            print(f"{caster.caster_id} | {stage.stage} | {status}")
            for artifact in stage.artifacts:
                print(f"  artifact: {artifact.path}")
            for warning in stage.warnings:
                print(f"  warning: {warning}")
            for error in stage.errors:
                print(f"  error: {error}")
    print(r.success)
    return 0 if r.success else 1


def run_storage(args: argparse.Namespace) -> int:
    print("storage check requested")
    return 0


def main(argv=None) -> int:
    p = build_parser()
    a = p.parse_args(argv)
    if hasattr(a, "func"):
        return a.func(a)
    p.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
