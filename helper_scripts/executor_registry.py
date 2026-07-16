"""Load the canonical executor roster and resolve durable task requirements.

The JSON registry owns volatile executor facts. This module owns only deterministic
matching mechanics so roadmap task meaning remains vendor-independent.
"""

import json
from pathlib import Path

REGISTRY_PATH = Path(__file__).with_name("executor_registry.json")

MODE_ALIASES = {
    "human": "human-judgment",
    "human judgment": "human-judgment",
    "physical action": "human-physical",
    "human physical work": "human-physical",
    "deterministic tool": "deterministic-tooling",
    "deterministic tooling": "deterministic-tooling",
    "local ai": "local-ai",
    "network ai": "network-ai",
}


def load_registry(path: Path = REGISTRY_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def model_budgets(registry: dict | None = None) -> dict:
    registry = registry or load_registry()
    return {
        executor["id"]: executor["budget"]
        for executor in registry["executors"]
        if "budget" in executor
    }


def normalize_mode(value: str) -> str:
    normalized = value.strip().lower().replace("_", "-")
    return MODE_ALIASES.get(normalized, normalized)


def normalize_requirement(value: str) -> str:
    return value.strip().lower().replace("_", "-").replace(" ", "-")


def eligible_executors(mode="", capabilities=(), constraints=(), registry=None) -> list[str]:
    """Return eligible executor IDs in stable registry priority order."""
    registry = registry or load_registry()
    mode = normalize_mode(mode) if mode else ""
    required = {normalize_requirement(value) for value in capabilities if value.strip()}
    constraints = {normalize_requirement(value) for value in constraints if value.strip()}
    if "privacy" in constraints:
        required.add("privacy")
    if "paid-only-execution" in constraints:
        required.add("paid-only-execution")

    eligible = []
    for executor in registry["executors"]:
        if mode and mode not in executor["modes"]:
            continue
        if not required.issubset(set(executor["capabilities"])):
            continue
        eligible.append(executor)
    return [entry["id"] for entry in sorted(eligible, key=lambda item: item["priority"])]


def resolve_pool(route: str, registry=None) -> str:
    """Resolve a capability-tier route such as paid-ai to one concrete executor."""
    registry = registry or load_registry()
    members = registry.get("pools", {}).get(route)
    if not members:
        return route
    by_id = {entry["id"]: entry for entry in registry["executors"]}
    eligible = [by_id[member] for member in members if member in by_id]
    if not eligible:
        raise ValueError(f"executor pool {route!r} has no eligible roster entry")
    return min(eligible, key=lambda item: item["priority"])["id"]


def executor_has_capability(executor_id: str, capability: str, registry=None) -> bool:
    """Return whether one concrete executor advertises a capability."""
    registry = registry or load_registry()
    executor_id = resolve_pool(executor_id, registry)
    wanted = normalize_requirement(capability)
    return any(
        entry["id"] == executor_id and wanted in entry.get("capabilities", [])
        for entry in registry["executors"]
    )
