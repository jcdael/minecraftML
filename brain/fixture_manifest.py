from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


REQUIRED_SCENARIOS = {
    "normal_bootstrap",
    "missing_materials",
    "full_inventory",
    "low_food_with_safe_food",
    "death_respawn",
}

REQUIRED_GAMERULES = {
    "doDaylightCycle",
    "doWeatherCycle",
    "keepInventory",
    "mobGriefing",
    "naturalRegeneration",
}

REQUIRED_BUDGETS = {"scenario", "per_skill"}
REQUIRED_SCENARIO_BUDGETS = {"max_ticks", "max_actions", "timeout_ms"}
REQUIRED_TERMINAL = {"outcome", "failure_code"}


class ManifestValidationError(ValueError):
    def __init__(self, code: str, path: str, message: str) -> None:
        super().__init__(f"{code} at {path}: {message}")
        self.code = code
        self.path = path
        self.message = message


def _fail(code: str, path: str, message: str) -> None:
    raise ManifestValidationError(code, path, message)


def _require_object(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail("invalid_object", path, "expected object")
    return value


def _require_list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        _fail("invalid_array", path, "expected array")
    return value


def _require_string(value: Any, path: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        _fail("invalid_string", path, "expected non-empty string")
    return value


def _require_int(value: Any, path: str, *, minimum: int | None = None) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        _fail("invalid_integer", path, "expected integer")
    if minimum is not None and value < minimum:
        _fail("integer_out_of_range", path, f"expected >= {minimum}")
    return value


def _require_number(value: Any, path: str) -> int | float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        _fail("invalid_number", path, "expected number")
    return value


def _require_bool(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        _fail("invalid_bool", path, "expected boolean")
    return value


def _require_keys(obj: dict[str, Any], keys: set[str], path: str) -> None:
    missing = sorted(keys - set(obj))
    if missing:
        _fail("missing_field", path, f"missing {', '.join(missing)}")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_path(path: Path) -> str:
    if path.is_file():
        return _sha256_file(path)
    digest = hashlib.sha256()
    for child in sorted(item for item in path.rglob("*") if item.is_file()):
        relative = child.relative_to(path).as_posix().encode("utf-8")
        digest.update(relative + b"\0")
        digest.update(_sha256_file(child).encode("ascii") + b"\0")
    return digest.hexdigest()


def _validate_template(entry: dict[str, Any], manifest_dir: Path, path: str) -> None:
    template = _require_object(entry.get("seed_template"), f"{path}.seed_template")
    _require_keys(template, {"path", "sha256"}, f"{path}.seed_template")
    rel_path = _require_string(template["path"], f"{path}.seed_template.path")
    expected_hash = _require_string(template["sha256"], f"{path}.seed_template.sha256").lower()
    if len(expected_hash) != 64 or any(char not in "0123456789abcdef" for char in expected_hash):
        _fail("invalid_checksum", f"{path}.seed_template.sha256", "expected lowercase sha256 hex")

    template_path = (manifest_dir / rel_path).resolve()
    try:
        template_path.relative_to(manifest_dir.resolve())
    except ValueError:
        _fail("path_outside_manifest_dir", f"{path}.seed_template.path", rel_path)
    if not template_path.exists():
        _fail("missing_seed_template", f"{path}.seed_template.path", rel_path)
    if template_path.is_dir() and not (template_path / "level.dat").is_file():
        _fail("invalid_world_template", f"{path}.seed_template.path", "world template directory must contain level.dat")

    actual_hash = _sha256_path(template_path)
    if actual_hash != expected_hash:
        _fail("checksum_mismatch", f"{path}.seed_template.sha256", f"expected {expected_hash}, got {actual_hash}")


def _validate_position(obj: Any, path: str) -> None:
    pos = _require_object(obj, path)
    _require_number(pos.get("x"), f"{path}.x")
    _require_number(pos.get("y"), f"{path}.y")
    _require_number(pos.get("z"), f"{path}.z")
    if "yaw" in pos:
        _require_number(pos["yaw"], f"{path}.yaw")
    if "pitch" in pos:
        _require_number(pos["pitch"], f"{path}.pitch")


def _validate_item_list(value: Any, path: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for index, item in enumerate(_require_list(value, path)):
        item_path = f"{path}[{index}]"
        item_obj = _require_object(item, item_path)
        _require_keys(item_obj, {"name", "count"}, item_path)
        _require_string(item_obj["name"], f"{item_path}.name")
        _require_int(item_obj["count"], f"{item_path}.count", minimum=0)
        if "slot" in item_obj:
            _require_int(item_obj["slot"], f"{item_path}.slot", minimum=0)
        items.append(item_obj)
    return items


def _validate_world_state(value: Any, path: str) -> None:
    world = _require_object(value, path)
    _require_keys(world, {"nearby_blocks", "nearby_entities", "hazards"}, path)
    blocks = _require_object(world["nearby_blocks"], f"{path}.nearby_blocks")
    for name, count in blocks.items():
        _require_string(name, f"{path}.nearby_blocks.<key>")
        _require_int(count, f"{path}.nearby_blocks.{name}", minimum=0)
    _require_list(world["nearby_entities"], f"{path}.nearby_entities")
    _require_list(world["hazards"], f"{path}.hazards")


def _validate_entry(entry: Any, manifest_dir: Path, index: int) -> str:
    path = f"fixtures[{index}]"
    obj = _require_object(entry, path)
    _require_keys(
        obj,
        {
            "id",
            "description",
            "mc_version",
            "server_version",
            "seed",
            "seed_template",
            "bot_spawn",
            "difficulty",
            "time",
            "weather",
            "gamerules",
            "expected_initial",
            "budgets",
            "expected_terminal",
        },
        path,
    )
    scenario_id = _require_string(obj["id"], f"{path}.id")
    _require_string(obj["description"], f"{path}.description")
    _require_string(obj["mc_version"], f"{path}.mc_version")
    _require_string(obj["server_version"], f"{path}.server_version")
    _require_int(obj["seed"], f"{path}.seed")
    _validate_template(obj, manifest_dir, path)
    _validate_position(obj["bot_spawn"], f"{path}.bot_spawn")
    if _require_string(obj["difficulty"], f"{path}.difficulty") not in {"peaceful", "easy", "normal", "hard"}:
        _fail("invalid_difficulty", f"{path}.difficulty", "expected peaceful, easy, normal, or hard")
    _require_int(obj["time"], f"{path}.time", minimum=0)
    if _require_string(obj["weather"], f"{path}.weather") not in {"clear", "rain", "thunder"}:
        _fail("invalid_weather", f"{path}.weather", "expected clear, rain, or thunder")

    gamerules = _require_object(obj["gamerules"], f"{path}.gamerules")
    _require_keys(gamerules, REQUIRED_GAMERULES, f"{path}.gamerules")
    for name in REQUIRED_GAMERULES:
        _require_bool(gamerules[name], f"{path}.gamerules.{name}")

    initial = _require_object(obj["expected_initial"], f"{path}.expected_initial")
    _require_keys(initial, {"inventory", "world_state", "health", "food"}, f"{path}.expected_initial")
    initial_inventory = _validate_item_list(initial["inventory"], f"{path}.expected_initial.inventory")
    _validate_world_state(initial["world_state"], f"{path}.expected_initial.world_state")
    _require_int(initial["health"], f"{path}.expected_initial.health", minimum=0)
    _require_int(initial["food"], f"{path}.expected_initial.food", minimum=0)
    if scenario_id == "full_inventory":
        slots = [item.get("slot") for item in initial_inventory]
        if len(slots) != 36 or sorted(slots) != list(range(36)):
            _fail("invalid_full_inventory_fixture", f"{path}.expected_initial.inventory", "expected slots 0 through 35")

    budgets = _require_object(obj["budgets"], f"{path}.budgets")
    _require_keys(budgets, REQUIRED_BUDGETS, f"{path}.budgets")
    scenario_budget = _require_object(budgets["scenario"], f"{path}.budgets.scenario")
    _require_keys(scenario_budget, REQUIRED_SCENARIO_BUDGETS, f"{path}.budgets.scenario")
    for name in REQUIRED_SCENARIO_BUDGETS:
        _require_int(scenario_budget[name], f"{path}.budgets.scenario.{name}", minimum=1)
    per_skill = _require_object(budgets["per_skill"], f"{path}.budgets.per_skill")
    if not per_skill:
        _fail("missing_skill_budget", f"{path}.budgets.per_skill", "expected at least one skill budget")
    for skill_name, skill_budget in per_skill.items():
        _require_string(skill_name, f"{path}.budgets.per_skill.<key>")
        skill_obj = _require_object(skill_budget, f"{path}.budgets.per_skill.{skill_name}")
        _require_keys(skill_obj, {"max_attempts", "timeout_ms"}, f"{path}.budgets.per_skill.{skill_name}")
        _require_int(skill_obj["max_attempts"], f"{path}.budgets.per_skill.{skill_name}.max_attempts", minimum=1)
        _require_int(skill_obj["timeout_ms"], f"{path}.budgets.per_skill.{skill_name}.timeout_ms", minimum=1)

    terminal = _require_object(obj["expected_terminal"], f"{path}.expected_terminal")
    _require_keys(terminal, REQUIRED_TERMINAL, f"{path}.expected_terminal")
    if _require_string(terminal["outcome"], f"{path}.expected_terminal.outcome") not in {"success", "failed", "unsafe"}:
        _fail("invalid_terminal_outcome", f"{path}.expected_terminal.outcome", "expected success, failed, or unsafe")
    failure_code = _require_string(terminal["failure_code"], f"{path}.expected_terminal.failure_code")
    if terminal["outcome"] == "success" and failure_code != "none":
        _fail("invalid_terminal_failure_code", f"{path}.expected_terminal.failure_code", "success must use none")
    if terminal["outcome"] != "success" and failure_code == "none":
        _fail("invalid_terminal_failure_code", f"{path}.expected_terminal.failure_code", "failed or unsafe must use a failure code")
    return scenario_id


def validate_manifest(path: Path) -> dict[str, Any]:
    manifest_path = path.resolve()
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        _fail("invalid_json", str(manifest_path), exc.msg)
    manifest = _require_object(data, "$")
    _require_keys(manifest, {"manifest_version", "fixtures"}, "$")
    _require_string(manifest["manifest_version"], "$.manifest_version")
    fixtures = _require_list(manifest["fixtures"], "$.fixtures")
    if not fixtures:
        _fail("missing_fixture", "$.fixtures", "expected at least one fixture")

    seen: set[str] = set()
    for index, fixture in enumerate(fixtures):
        scenario_id = _validate_entry(fixture, manifest_path.parent, index)
        if scenario_id in seen:
            _fail("duplicate_fixture_id", f"fixtures[{index}].id", scenario_id)
        seen.add(scenario_id)

    missing_scenarios = sorted(REQUIRED_SCENARIOS - seen)
    if missing_scenarios:
        _fail("missing_required_scenario", "$.fixtures", ", ".join(missing_scenarios))
    return manifest


def default_manifest_path() -> Path:
    return Path(__file__).resolve().parents[1] / "fixtures" / "bootstrap" / "manifest.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate deterministic bootstrap fixture manifests.")
    parser.add_argument("manifest", nargs="?", type=Path, default=default_manifest_path())
    args = parser.parse_args()
    try:
        manifest = validate_manifest(args.manifest)
    except ManifestValidationError as exc:
        print(json.dumps({"ok": False, "code": exc.code, "path": exc.path, "message": exc.message}, sort_keys=True))
        return 1
    print(json.dumps({"ok": True, "fixtures": len(manifest["fixtures"])}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
