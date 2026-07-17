# Reports Generator

Reports Generator creates shift reports for Electro Steel pipe production.
It exports raw pipe CSV files from each caster SQLite database, creates verified
client CSV files, builds diagnosis XLSX files, generates videos, uploads selected
artifacts with `rclone`, sends emails, and cleans source history only after a
successful full-shift video.

## Quick Start

Run the scheduled workflow:

```bash
uv run python -m cli.report_workflow
```

Run one shift manually:

```bash
uv run python -m cli.report_workflow --date 13-07-2026 --shift C --caster caster2
```

Run all enabled casters:

```bash
uv run python -m cli.report_workflow --date 13-07-2026 --shift C --all-casters
```

Validate configuration without running reports:

```bash
uv run python -m cli.report_workflow --validate-config
```

Run tests:

```bash
uv run pytest -q
```

## Schedule

When no `--date` and `--shift` are provided, the workflow runs only inside the
scheduled trigger window. A 5 minute slack is allowed.

| Trigger time | Run date | Shift |
| --- | --- | --- |
| 06:00 | Previous day | `Shift_C` |
| 14:00 | Same day | `Shift_A` |
| 22:00 | Same day | `Shift_B` |

## Useful Commands

Full workflow:

```bash
uv run python -m cli.report_workflow --date 13-07-2026 --shift C --caster caster2
```

Multiple casters:

```bash
uv run python -m cli.report_workflow --date 13-07-2026 --shift C --casters caster2,caster3
```

Verified CSV only:

```bash
uv run python -m cli.report_workflow --date 13-07-2026 --shift C --verified-only --caster caster2
```

Verified CSV for a custom time window:

```bash
uv run python -m cli.report_workflow --date 13-07-2026 --start 01:00 --stop 13:00 --verified-only --test --caster caster2
```

Use `--start` and `--stop` only with `--verified-only`; do not combine them with `--shift`.

Diagnosis XLSX only:

```bash
uv run python -m cli.report_workflow --date 13-07-2026 --shift C --diagnosis-only --caster caster2
```

Test email routing:

```bash
uv run python -m cli.report_workflow --date 13-07-2026 --shift C --test --caster caster2
```

`--test` sends every workflow email only to `email.test_recipients`.

Generate a full-shift video directly:

```bash
uv run python -m reports.video.video_generator --date 13-07-2026 --shift C --caster caster2
```

Delete old generated videos:

```bash
uv run python -m reports.video.delete_old_videos --dry-run
uv run python -m reports.video.delete_old_videos
```

Export gate cycles for debugging:

```bash
uv run python -m reports.pipes.gate_cycles_exporter --date 13-07-2026 --shift C --caster caster2
```

Check Jetson storage:

```bash
uv run python -m reports.check_jetson_storage
```

## Outputs

The output folders are configured in `config/runtime.yaml`.

```text
outputs/{caster_id}/raw-csv
outputs/{caster_id}/verified-csv
outputs/{caster_id}/videos
outputs/{caster_id}/overlay-videos
outputs/logs/app.log
outputs/logs/error.log
outputs/state
```

Artifact rules:

| Artifact | Local folder |
| --- | --- |
| Raw pipe CSV | `outputs/{caster_id}/raw-csv` |
| Verified pipe CSV | `outputs/{caster_id}/verified-csv` |
| Diagnosis XLSX | `outputs/{caster_id}/verified-csv` unless `diagnosis_dir` is configured |
| Full-shift video | `outputs/{caster_id}/videos` |
| Missing-loadcell normal video | `outputs/{caster_id}/videos` |
| Missing-loadcell overlay video | `outputs/{caster_id}/overlay-videos` |
| Application log | `outputs/logs/app.log` |
| Error log | `outputs/logs/error.log` |
| Run state JSON | `outputs/state` |

Raw CSV files are deleted locally only after a successful Google Drive upload.
Missing-loadcell videos are deleted after upload only when
`missing_loadcell_video.delete_after_upload` is true.

## Configuration

Main config stays at:

```text
config/runtime.yaml
```

Do not move `config/runtime.yaml` or `config/video.yaml`.

Important sections:

| Section | Purpose |
| --- | --- |
| `history.shifts` | Shift start and end times |
| `outputs` | Base output, log, and state folders |
| `casters.defaults` | Shared caster templates |
| `casters.items` | Caster IDs, numbers, enabled flags, var dirs, ROI files |
| `database.path` | Per-caster SQLite database path after resolution |
| `history.image_root` | Per-caster image/text history root after resolution |
| `rois` | ROI YAML path and coordinate source resolution |
| `verified_pipes_mode` | `loadcell` or `all` verification mode |
| `missing_loadcell_video` | Clip window and delete-after-upload settings |
| `diagnosis` | Abnormal t-origin gap thresholds |
| `gdrive` | `rclone` remote and Drive folder names |
| `email` | SMTP sender, recipients, test recipients, password env var |
| `video_retention` | Old video cleanup settings |
| `jetson_storage_alert` | Disk usage alert settings |

Per-caster output templates should look like this:

```yaml
casters:
  defaults:
    outputs:
      raw_csv_dir_template: outputs/{caster_id}/raw-csv
      verified_csv_dir_template: outputs/{caster_id}/verified-csv
      diagnosis_dir_template: outputs/{caster_id}/verified-csv
      video_dir_template: outputs/{caster_id}/videos
      overlay_video_dir_template: outputs/{caster_id}/overlay-videos
```

## Architecture

Business implementation now lives under `src/`.

```text
src/domain
src/application
src/infrastructure
src/interfaces
```

Layer responsibilities:

| Layer | Contains |
| --- | --- |
| `src/domain` | Typed models and pure business concepts |
| `src/application` | Workflow orchestration and use cases |
| `src/infrastructure` | Config, SMTP, rclone, filesystem, and other adapters |
| `src/interfaces` | CLI parsing and command entrypoints |

Compatibility wrappers remain in `cli/` and `reports/` so existing commands and
imports keep working. Do not add new business logic to those wrappers. Put new
implementation under `src/` and make wrappers delegate to it.

Main entrypoint:

```text
cli/report_workflow.py -> src/interfaces/cli/report_workflow_cli.py
```

Main workflow:

```text
src/application/workflows/shift_report_workflow.py
```

## Full Workflow Order

For each enabled or selected caster, the full workflow does this:

1. Load `config/runtime.yaml`.
2. Resolve caster-specific config from `casters.defaults` and `casters.items`.
3. Create or update run state under `outputs/state`.
4. Export raw pipe CSV.
5. Send raw CSV email when enabled.
6. Export verified pipe CSV.
7. Send verified CSV email.
8. Upload raw CSV with `rclone`.
9. Delete local raw CSV only after successful upload.
10. Export diagnosis XLSX.
11. Build missing-loadcell video windows from verified results.
12. Generate overlay and normal missing-loadcell videos.
13. Upload missing-loadcell videos with `rclone`.
14. Send diagnosis email with XLSX and video links.
15. Generate full-shift video.
16. Clean source history folders only after full-shift video success.
17. Mark caster state as `success` or `partial_failure`.

## Source Cleanup Rules

Source cleanup deletes history image/text folders only after full-shift video
generation succeeds.

It removes these folders for the completed shift:

```text
history/YYYY_MM_DD/Shift_X_img
history/YYYY_MM_DD/Shift_X_text
```

For `Shift_C`, cleanup handles both date folders because the shift crosses
midnight. Empty date folders are pruned after shift folders are removed.

If video generation fails, source history is kept.

## Production Requirements

Before running in production, make sure these are available:

- SQLite pipe database for each enabled caster.
- History images under `history/YYYY_MM_DD/Shift_X_img`.
- YOLO text files under `history/YYYY_MM_DD/Shift_X_text`.
- ROI YAML files for overlay and Gate2 diagnostics.
- `rclone` configured for the `gdrive.remote` value.
- SMTP password through `email.password_env`, usually `EMAIL_APP_PASSWORD`.

Set the email password in the shell or service environment:

```bash
set EMAIL_APP_PASSWORD=your_app_password
```

On Linux or Jetson:

```bash
export EMAIL_APP_PASSWORD=your_app_password
```

## Maintenance Guide

Use this checklist when changing the project:

1. Keep production behavior first. Refactor in small steps.
2. Put new logic under `src/`, not in `reports/` wrappers.
3. Keep `config/runtime.yaml` and `config/video.yaml` at the repository root.
4. Use `pathlib.Path` for filesystem paths.
5. Add or update tests for output paths, email routing, uploads, cleanup, and videos.
6. Run `uv run pytest -q` before deploying.
7. Use `--test` before changing email behavior in production.
8. Use `--validate-config` after changing caster paths.
9. Check `outputs/state` after a run to see what completed or failed.
10. Check `outputs/logs/error.log` first when production fails.

Common safe checks:

```bash
uv run python -m cli.report_workflow --validate-config
uv run pytest -q
uv run python -m reports.video.delete_old_videos --dry-run
```

## Troubleshooting

No workflow runs:

- If no `--date` and `--shift` are passed, the command only runs during the
  scheduled 06:00, 14:00, or 22:00 trigger windows.

No email is sent:

- Check `email.password_env` and the environment variable value.
- Use `--test` and confirm `email.test_recipients` is configured.
- Check `outputs/logs/error.log`.

No Drive link is created:

- Confirm `rclone` is installed.
- Confirm the remote in `gdrive.remote` exists.
- Run `rclone lsd gdrive:` manually on the machine.

No video is generated:

- Confirm history image folders exist for the requested date and shift.
- Confirm images are readable by OpenCV.
- For `Shift_C`, check both the run date and the next date folder.

Unexpected cleanup:

- Cleanup runs only after full-shift video success.
- Check the caster state JSON in `outputs/state` for `normal_shift_source_cleanup`.

