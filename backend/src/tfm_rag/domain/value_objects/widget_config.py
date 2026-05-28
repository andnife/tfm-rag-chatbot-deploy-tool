"""WidgetConfig — typed shape for the embeddable chat widget settings.

Persisted as a JSONB column on the chatbots table. The chatbot owner edits
this from the panel; plan #16's widget runtime reads it from the public
chat endpoint response to style the embed.
"""
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from tfm_rag.domain.errors.common import ValidationError

WidgetTheme = Literal["light", "dark"]
WidgetPosition = Literal["bottom-right", "bottom-left"]

_THEMES: tuple[str, ...] = ("light", "dark")
_POSITIONS: tuple[str, ...] = ("bottom-right", "bottom-left")

_HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
# HTTPS-only origin matcher: scheme + host (+ optional port). No path,
# no fragment, no query. Wildcard '*' is accepted as a separate sentinel.
# HTTP origins are rejected to prevent credentials transit in cleartext.
_ORIGIN_RE = re.compile(
    r"^https://"
    r"(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?\.)*"
    r"[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?"
    r"(?::\d{1,5})?$"
)
# Also accept localhost with http for local development.
_ORIGIN_DEV_RE = re.compile(
    r"^https?://localhost(?::\d{1,5})?$"
)

_MAX_TITLE = 60
_MAX_WELCOME = 500
_MAX_PLACEHOLDER = 100
_MAX_ORIGINS = 50


@dataclass(frozen=True, slots=True)
class WidgetConfig:
    theme: WidgetTheme = "light"
    primary_color: str = "#3b82f6"
    position: WidgetPosition = "bottom-right"
    title: str = "Asistente"
    welcome_message: str = "¿En qué puedo ayudarte?"
    placeholder: str = "Escribe tu pregunta..."
    allowed_origins: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _validate_enum("theme", self.theme, _THEMES)
        _validate_enum("position", self.position, _POSITIONS)
        _validate_color(self.primary_color)
        _validate_str_len("title", self.title, 1, _MAX_TITLE)
        _validate_str_len("welcome_message", self.welcome_message, 1, _MAX_WELCOME)
        _validate_str_len("placeholder", self.placeholder, 1, _MAX_PLACEHOLDER)
        _validate_origins(self.allowed_origins)

    @classmethod
    def default(cls) -> "WidgetConfig":
        return cls()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WidgetConfig":
        """Build a WidgetConfig from a (possibly partial) dict.

        Missing keys fall back to defaults — important for old chatbots
        in DB that were stored with `widget_config={}` or `{"theme": "light"}`.
        Duplicates in allowed_origins are deduplicated.
        """
        defaults = cls.default()
        origins_raw = data.get("allowed_origins")
        origins: tuple[str, ...]
        if origins_raw is None:
            origins = defaults.allowed_origins
        else:
            if not isinstance(origins_raw, (list, tuple)):
                raise ValidationError(
                    f"allowed_origins must be a list, got {type(origins_raw).__name__}"
                )
            # Dedupe but preserve first-seen order.
            seen: dict[str, None] = {}
            for o in origins_raw:
                if not isinstance(o, str):
                    raise ValidationError("allowed_origins entries must be strings")
                seen.setdefault(o, None)
            origins = tuple(seen.keys())

        return cls(
            theme=data.get("theme", defaults.theme),
            primary_color=data.get("primary_color", defaults.primary_color),
            position=data.get("position", defaults.position),
            title=data.get("title", defaults.title),
            welcome_message=data.get("welcome_message", defaults.welcome_message),
            placeholder=data.get("placeholder", defaults.placeholder),
            allowed_origins=origins,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "theme": self.theme,
            "primary_color": self.primary_color,
            "position": self.position,
            "title": self.title,
            "welcome_message": self.welcome_message,
            "placeholder": self.placeholder,
            "allowed_origins": list(self.allowed_origins),
        }


def _validate_enum(field: str, value: Any, allowed: tuple[str, ...]) -> None:
    if value not in allowed:
        raise ValidationError(
            f"{field} must be one of {allowed!r}, got {value!r}"
        )


def _validate_color(value: Any) -> None:
    if not isinstance(value, str) or not _HEX_COLOR_RE.match(value):
        raise ValidationError(
            f"primary_color must be a hex string like '#3b82f6', got {value!r}"
        )


def _validate_str_len(field: str, value: Any, lo: int, hi: int) -> None:
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be a string, got {type(value).__name__}")
    n = len(value)
    if n < lo:
        raise ValidationError(f"{field} too short ({n} < {lo})")
    if n > hi:
        raise ValidationError(f"{field} too long ({n} > {hi})")


def _validate_origins(origins: tuple[str, ...]) -> None:
    if len(origins) > _MAX_ORIGINS:
        raise ValidationError(
            f"allowed_origins exceeds max of {_MAX_ORIGINS}: got {len(origins)}"
        )
    for o in origins:
        if o == "*":
            continue
        if _ORIGIN_RE.match(o) or _ORIGIN_DEV_RE.match(o):
            continue
        raise ValidationError(
            f"allowed_origins entry {o!r} is not a valid origin "
            f"(must be https://host or http://localhost:port, no path/query)"
        )
