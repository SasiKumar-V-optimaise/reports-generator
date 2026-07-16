# Reports Generator

Clean architecture Python application for caster shift reports, videos, uploads and notifications.

## Architecture

Code lives under `src/reports_generator`:

- `domain/` contains pure shift, pipe, gate and video rules.
- `application/` contains typed models, services and workflows.
- `infrastructure/` contains configuration, database, report, video, storage and email adapters.
- `shared/` contains paths, time and retry utilities.
- `cli/` provides thin command adapters; dependency wiring is in `bootstrap.py`.

## Configuration

`config/runtime.yaml` defines paths and dynamic caster definitions. `config/video.yaml` defines video settings. Casters are never hard-coded; bootstrap validates configuration and creates output directories for every active caster.

## Outputs

Artifacts are written to `outputs/{caster_id}/raw_csv`, `verified_csv`, `diagnosis`, `videos`, `overlay_videos` and `metadata`. Names use `DD-MM-YYYY_shift_A` (for example `14-07-2026_shift_A_verified.csv` and `14-07-2026_shift_A.mp4`). Runtime state is stored under `runtime/state`; logs under `logs`.

## CLI

```bash
PYTHONPATH=src python -m reports_generator.cli.main --help
PYTHONPATH=src python -m reports_generator.cli.main report --date 2026-07-14 --shift A
```

## Development

Run tests with `PYTHONPATH=src uv run pytest`. Use Ruff and mypy for linting and type checking.

Cleanup is only allowed after successful full-shift video generation; skipped or failed video stages never trigger source deletion. External integrations are injectable and can be replaced with fakes for tests.

Compatibility: legacy modules are retired; use the typed application workflows and infrastructure adapters.
