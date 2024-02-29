from __future__ import annotations

import dataclasses


@dataclasses.dataclass
class CorsConfiguration:
    allow_origins: list[str] = dataclasses.field(default_factory=lambda: ["*"])
    allow_methods: list[str] = dataclasses.field(default_factory=lambda: ["*"])
    allow_headers: list[str] = dataclasses.field(default_factory=lambda: ["*"])
    allow_credentials: bool = True
