from __future__ import annotations

import argparse

from src.application.workflows.shift_report_workflow import (
    ShiftWorkflow,
    _now,
    detect_shift_for_trigger,
    logger,
    setup_logging,
)
from src.domain.models.run import ShiftRun
from src.infrastructure.config.runtime_config_loader import load_runtime_config


def _selected_ids_from_args(args) -> list[str] | None:
    selected = []
    if args.caster:
        selected.append(args.caster)
    if args.casters:
        selected.extend(part.strip() for part in args.casters.split(",") if part.strip())
    if args.all_casters:
        return None
    return selected or None



def _window_token(value: str) -> str:
    return str(value).strip().replace(":", "")


def _custom_shift_name(start_time: str, stop_time: str) -> str:
    return f"custom_{_window_token(start_time)}_{_window_token(stop_time)}"

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date")
    parser.add_argument("--shift")
    parser.add_argument("--start", help="Custom verified-only window start, HH:MM or HH:MM:SS")
    parser.add_argument("--stop", help="Custom verified-only window stop, HH:MM or HH:MM:SS")
    parser.add_argument("--diagnosis-only", action="store_true")
    parser.add_argument("--verified-only", action="store_true", help="Run raw pipe CSV and verified pipes only")
    parser.add_argument("--test", action="store_true", help="Send every workflow email only to email.test_recipients")
    parser.add_argument("--caster", help="Single caster id, for example caster1")
    parser.add_argument("--casters", help="Comma-separated caster ids, for example caster1,caster2,caster8")
    parser.add_argument("--all-casters", action="store_true")
    parser.add_argument("--validate-config", action="store_true")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    cfg = load_runtime_config()
    setup_logging(cfg)
    wf = ShiftWorkflow(cfg=cfg, selected_ids=_selected_ids_from_args(args), test_mode=args.test)

    if args.validate_config:
        print(wf.validate_config())
        return

    if args.diagnosis_only and args.verified_only:
        parser.error("--diagnosis-only and --verified-only cannot be used together")

    custom_window = bool(args.start or args.stop)
    if custom_window:
        if not args.start or not args.stop:
            parser.error("--start and --stop must be used together")
        if not args.date:
            parser.error("--start/--stop require --date")
        if args.shift:
            parser.error("--start/--stop cannot be combined with --shift")
        if not args.verified_only:
            parser.error("--start/--stop is supported only with --verified-only")
        run = ShiftRun(args.date, _custom_shift_name(args.start, args.stop), args.start, args.stop)
    elif args.date and args.shift:
        run = ShiftRun(args.date, ShiftWorkflow._normalize_shift_name(args.shift))
    else:
        run = detect_shift_for_trigger(_now())
        if not run:
            logger.info("Not a scheduled shift time. Exiting.")
            return

    if args.verified_only:
        wf.run_verified_only(run)
    elif args.diagnosis_only:
        wf.run_diagnosis_only(run)
    else:
        wf.run(run)

