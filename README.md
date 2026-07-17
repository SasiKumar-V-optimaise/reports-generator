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

### Safe local end-to-end run

~~~bash
uv run reports-generator report \
  --date 2026-07-15 \
  --shift C \
  --casters caster2 caster3 \
  --test
~~~

This reads the configured caster SQLite databases and history images, applies
verification and diagnosis rules, writes CSV/XLSX reports, generates MP4
videos, and saves workflow state. External uploads, email notifications, and
source cleanup are skipped in test mode. The CLI prints every stage, artifact,
warning, and error before the final True or False result.

### Verified CSV and email only

Set the SMTP password environment variable, then run without `--test`:

~~~bash
export EMAIL_APP_PASSWORD='your-gmail-app-password'
uv run reports-generator report \
  --date 17-07-2026 \
  --shift A \
  --casters caster2 caster3 \
  --verified-only
~~~

This mode creates only each caster's verified CSV and emails it to
`email.verified_recipients`. It skips raw CSV, diagnosis, video, upload,
cleanup, and workflow-state output. Adding `--test` keeps the same local CSV
behavior but deliberately skips email delivery.

## Development

Run the CLI-level local workflow test with:

~~~bash
uv run pytest tests/integration/test_workflow_e2e.py -v
~~~

Run tests with `PYTHONPATH=src uv run pytest`. Use Ruff and mypy for linting and type checking.

Cleanup is only allowed after successful full-shift video generation; skipped or failed video stages never trigger source deletion. External integrations are injectable and can be replaced with fakes for tests.

Compatibility: legacy modules are retired; use the typed application workflows and infrastructure adapters.
