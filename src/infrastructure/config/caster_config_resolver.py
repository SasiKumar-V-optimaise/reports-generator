from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any


from src.domain.models.caster import CasterConfig


def deep_merge(base: dict | None, override: dict | None) -> dict:
    result = deepcopy(base or {})
    for key, value in (override or {}).items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _without_keys(data: dict, keys: set[str]) -> dict:
    return {key: deepcopy(value) for key, value in data.items() if key not in keys}


def _as_bool(value: Any, *, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return bool(value)


def _format_template(template: str, context: dict[str, Any]) -> str:
    return str(template).format(**context)


def _join_path(left: str | Path, right: str | Path) -> str:
    return str(Path(str(left)) / str(right))


def _nested_get(data: dict, path: tuple[str, ...]) -> Any:
    current = data
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def _nested_set(data: dict, path: tuple[str, ...], value: Any):
    current = data
    for key in path[:-1]:
        current = current.setdefault(key, {})
    current[path[-1]] = value


def _template_value(defaults: dict, section: str, key: str) -> Any:
    value = defaults.get(section, {})
    if not isinstance(value, dict):
        return None
    return value.get(key)


def _strip_default_helpers(defaults: dict) -> dict:
    stripped = _without_keys(defaults, {"enabled", "var_root", "database_file", "history_dir"})

    outputs = stripped.get("outputs")
    if isinstance(outputs, dict):
        for key in (
            "csv_dir_template",
            "raw_csv_dir_template",
            "verified_csv_dir_template",
            "diagnosis_dir_template",
            "video_dir_template",
            "overlay_video_dir_template",
        ):
            outputs.pop(key, None)
        if not outputs:
            stripped.pop("outputs", None)

    gdrive = stripped.get("gdrive")
    if isinstance(gdrive, dict):
        for key in ("pipes_csv_dir_template", "videos_dir_template"):
            gdrive.pop(key, None)
        if not gdrive:
            stripped.pop("gdrive", None)

    return stripped


def _item_has_path(item: dict, path: tuple[str, ...]) -> bool:
    return _nested_get(item, path) is not None


def build_caster_runtime_config(base_cfg: dict, caster_item: dict, defaults: dict | None = None) -> dict:
    defaults = deepcopy(defaults or {})
    item = deepcopy(caster_item or {})

    if not item.get("id"):
        raise ValueError("Each caster item must include an id")

    caster_id = str(item["id"]).strip()
    number = item.get("number")
    name = str(item.get("name") or (f"Caster {number}" if number not in (None, "") else caster_id))

    cfg = _without_keys(base_cfg or {}, {"casters"})
    cfg = deep_merge(cfg, _strip_default_helpers(defaults))
    cfg = deep_merge(
        cfg,
        _without_keys(item, {"id", "number", "name", "enabled", "var_dir"}),
    )

    var_root = defaults.get("var_root")
    var_dir = item.get("var_dir")
    if not var_dir and var_root:
        var_dir = _join_path(var_root, caster_id)

    context = {
        "caster_id": caster_id,
        "id": caster_id,
        "number": number,
        "caster_number": number,
        "name": name,
        "var_dir": var_dir or "",
    }

    if var_dir:
        database_file = _format_template(defaults.get("database_file", "pipes.db"), context)
        history_dir = defaults.get("history_dir", "history")
        if not _item_has_path(item, ("database", "path")) and _nested_get(defaults, ("database", "path")) is None:
            _nested_set(cfg, ("database", "path"), _join_path(var_dir, database_file))
        if not _item_has_path(item, ("history", "image_root")) and _nested_get(defaults, ("history", "image_root")) is None:
            _nested_set(cfg, ("history", "image_root"), _join_path(var_dir, history_dir))

    template_mappings = (
        ("outputs", "csv_dir_template", ("outputs", "csv_dir")),
        ("outputs", "raw_csv_dir_template", ("outputs", "raw_csv_dir")),
        ("outputs", "verified_csv_dir_template", ("outputs", "verified_csv_dir")),
        ("outputs", "diagnosis_dir_template", ("outputs", "diagnosis_dir")),
        ("outputs", "video_dir_template", ("video", "output_dir")),
        ("outputs", "overlay_video_dir_template", ("video", "overlay_output_dir")),
        ("gdrive", "pipes_csv_dir_template", ("gdrive", "pipes_csv_dir")),
        ("gdrive", "videos_dir_template", ("gdrive", "videos_dir")),
    )
    for section, template_key, target_path in template_mappings:
        if _item_has_path(item, target_path):
            continue
        template = _template_value(defaults, section, template_key)
        if template is not None:
            _nested_set(cfg, target_path, _format_template(template, context))

    cfg["caster_id"] = caster_id
    cfg["caster_number"] = number
    cfg["caster_name"] = name
    cfg["caster_enabled"] = _as_bool(item.get("enabled", defaults.get("enabled")), default=True)
    if var_dir:
        cfg["caster_var_dir"] = str(var_dir)

    return cfg


def _legacy_caster(base_cfg: dict) -> CasterConfig:
    number = (
        (base_cfg or {}).get("caster_number")
        or (base_cfg or {}).get("Caster number")
        or (base_cfg or {}).get("caster number")
    )
    name = f"Caster {number}" if number not in (None, "") else "Legacy Caster"
    return CasterConfig(
        id="legacy",
        number=number,
        name=name,
        enabled=True,
        cfg=deepcopy(base_cfg or {}),
        is_legacy=True,
    )


def resolve_enabled_casters(base_cfg: dict, selected_ids: list[str] | None = None) -> list[CasterConfig]:
    casters_cfg = (base_cfg or {}).get("casters")
    selected = [str(value).strip() for value in (selected_ids or []) if str(value).strip()]

    if not isinstance(casters_cfg, dict):
        if selected and selected not in (["legacy"], ["caster"]):
            raise ValueError("runtime.yaml does not define casters; remove --caster/--casters or add casters.items")
        return [_legacy_caster(base_cfg or {})]

    defaults = casters_cfg.get("defaults") or {}
    items = casters_cfg.get("items") or []
    if not isinstance(items, list):
        raise ValueError("casters.items must be a list")

    by_id = {str(item.get("id", "")).strip(): item for item in items if isinstance(item, dict)}
    missing = [caster_id for caster_id in selected if caster_id not in by_id]
    if missing:
        raise ValueError(f"Unknown caster id(s): {', '.join(missing)}")

    resolved: list[CasterConfig] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        caster_id = str(item.get("id", "")).strip()
        if not caster_id:
            raise ValueError("Each caster item must include an id")
        if selected and caster_id not in selected:
            continue

        enabled = _as_bool(item.get("enabled", defaults.get("enabled")), default=True)
        if not enabled:
            if selected:
                raise ValueError(f"Caster {caster_id} is disabled")
            continue

        cfg = build_caster_runtime_config(base_cfg, item, defaults)
        resolved.append(CasterConfig(
            id=caster_id,
            number=item.get("number"),
            name=str(item.get("name") or cfg.get("caster_name") or caster_id),
            enabled=True,
            cfg=cfg,
            is_legacy=False,
        ))

    if not resolved:
        raise ValueError("No enabled casters are configured")

    return resolved


def caster_label(caster: CasterConfig | None, cfg: dict | None = None) -> str:
    if caster is not None:
        if caster.number not in (None, ""):
            return f"Caster {caster.number}"
        return caster.id
    value = (cfg or {}).get("caster_number")
    return f"Caster {value}" if value not in (None, "") else "Caster N/A"






