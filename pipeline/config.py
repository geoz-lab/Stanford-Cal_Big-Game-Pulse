"""Season definitions loaded from seasons.yaml."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache

import yaml

from .env import DATA_DIR, ROOT

PT = "America/Los_Angeles"


@dataclass(frozen=True)
class Season:
    year: int
    date: date
    espn_id: int
    venue: str
    home: str
    note: str
    start: date
    end: date

    @property
    def upcoming(self) -> bool:
        return self.date >= date.today()

    @property
    def study(self) -> str:
        return f"{self.year}_biggame"

    @property
    def dir(self):
        return DATA_DIR / self.study


@lru_cache
def raw() -> dict:
    return yaml.safe_load((ROOT / "seasons.yaml").read_text())


def seasons() -> dict[int, Season]:
    cfg = raw()
    out = {}
    for year, s in cfg["seasons"].items():
        d = s["date"]
        out[int(year)] = Season(
            year=int(year), date=d, espn_id=int(s["espn_id"]), venue=s["venue"], home=s["home"],
            note=s.get("note", ""),
            start=d - timedelta(days=cfg["window_before_days"]),
            # Collection can't run past today; an ongoing season's window grows on each re-run.
            end=min(d + timedelta(days=cfg["window_after_days"]), date.today()),
        )
    return out
