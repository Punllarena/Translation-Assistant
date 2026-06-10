from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

_CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "ta-python"
DEFAULT_SUBS_PATH = _CONFIG_DIR / "substitutions.json"


@dataclass
class SubRule:
    old: str
    new: str


@dataclass
class SubProfile:
    name: str
    rules: list[SubRule] = field(default_factory=list)


class SubstitutionStore:
    def __init__(self):
        self._profiles: dict[str, SubProfile] = {"*": SubProfile("*")}

    @classmethod
    def load(cls, path: Path = DEFAULT_SUBS_PATH) -> "SubstitutionStore":
        store = cls()
        if not path.exists():
            return store
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for pdata in data.get("profiles", []):
            name = pdata.get("name", "*")
            rules = [SubRule(r["old"], r["new"]) for r in pdata.get("rules", [])]
            store._profiles[name] = SubProfile(name, rules)
        return store

    def save(self, path: Path = DEFAULT_SUBS_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "profiles": [
                {
                    "name": p.name,
                    "rules": [{"old": r.old, "new": r.new} for r in p.rules],
                }
                for p in self._profiles.values()
            ]
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def apply(self, text: str, profile: str | None = None) -> str:
        for rule in self._profiles.get("*", SubProfile("*")).rules:
            text = text.replace(rule.old, rule.new)
        if profile and profile != "*" and profile in self._profiles:
            for rule in self._profiles[profile].rules:
                text = text.replace(rule.old, rule.new)
        return text

    def detect_active_profile(self) -> str | None:
        """Match running process names against profile names."""
        try:
            import psutil
            running = {p.name().lower() for p in psutil.process_iter(["name"])}
        except Exception:
            running = _proc_names_linux()

        for name in self._profiles:
            if name == "*":
                continue
            if name.lower() in running or name.lower().rstrip(".exe") in running:
                return name
        return None

    def profiles(self) -> list[str]:
        return list(self._profiles.keys())

    def get_profile(self, name: str) -> SubProfile | None:
        return self._profiles.get(name)

    def add_rule(self, profile: str, old: str, new: str) -> None:
        if profile not in self._profiles:
            self._profiles[profile] = SubProfile(profile)
        self._profiles[profile].rules.append(SubRule(old, new))

    def remove_rule(self, profile: str, old: str) -> None:
        p = self._profiles.get(profile)
        if p:
            p.rules = [r for r in p.rules if r.old != old]

    def add_profile(self, name: str) -> None:
        if name not in self._profiles:
            self._profiles[name] = SubProfile(name)

    def remove_profile(self, name: str) -> None:
        if name != "*":
            self._profiles.pop(name, None)


def _proc_names_linux() -> set[str]:
    names: set[str] = set()
    try:
        proc = Path("/proc")
        for pid_dir in proc.iterdir():
            if not pid_dir.name.isdigit():
                continue
            comm = pid_dir / "comm"
            if comm.exists():
                names.add(comm.read_text().strip().lower())
    except Exception:
        pass
    return names
