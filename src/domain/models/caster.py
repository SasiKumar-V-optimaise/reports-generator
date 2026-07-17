from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CasterConfig:
    id: str
    number: int | str | None
    name: str
    enabled: bool
    cfg: dict
    is_legacy: bool = False

    @property
    def file_token(self) -> str | None:
        return None if self.is_legacy else self.id

    @property
    def display_name(self) -> str:
        if self.name:
            return self.name
        if self.number not in (None, ""):
            return f"Caster {self.number}"
        return self.id


