"""Unit tests for the WidgetConfig VO."""
import pytest

from tfm_rag.domain.errors.common import ValidationError
from tfm_rag.domain.value_objects.widget_config import (
    WidgetConfig,
)

# --- happy path ----------------------------------------------------------------


def test_defaults_are_sane() -> None:
    cfg = WidgetConfig.default()
    assert cfg.theme == "light"
    assert cfg.position == "bottom-right"
    assert cfg.primary_color == "#3b82f6"
    assert cfg.title  # non-empty
    assert cfg.welcome_message  # non-empty
    assert cfg.placeholder  # non-empty
    assert cfg.allowed_origins == ()


def test_round_trip_to_dict_and_back() -> None:
    cfg = WidgetConfig(
        theme="dark",
        primary_color="#10B981",
        position="bottom-left",
        title="Help",
        welcome_message="Hi!",
        placeholder="Ask...",
        allowed_origins=("https://example.com", "https://other.example.com"),
    )
    data = cfg.to_dict()
    assert data == {
        "theme": "dark",
        "primary_color": "#10B981",
        "position": "bottom-left",
        "title": "Help",
        "welcome_message": "Hi!",
        "placeholder": "Ask...",
        "allowed_origins": ["https://example.com", "https://other.example.com"],
    }
    assert WidgetConfig.from_dict(data) == cfg


def test_from_dict_with_missing_keys_falls_back_to_defaults() -> None:
    # Backwards compat: existing rows in DB may carry partial dicts.
    cfg = WidgetConfig.from_dict({"theme": "dark"})
    assert cfg.theme == "dark"
    assert cfg.position == "bottom-right"  # default
    assert cfg.primary_color == "#3b82f6"  # default


def test_from_dict_with_empty_dict_returns_default() -> None:
    cfg = WidgetConfig.from_dict({})
    assert cfg == WidgetConfig.default()


def test_typed_enums_via_dataclass_field() -> None:
    # Literal types narrowed via type aliases (no runtime check needed)
    cfg = WidgetConfig.default()
    assert isinstance(cfg.theme, str)
    assert isinstance(cfg.position, str)


# --- validation: theme + position ---------------------------------------------


def test_invalid_theme_raises_validation_error() -> None:
    with pytest.raises(ValidationError) as exc_info:
        WidgetConfig.from_dict({"theme": "neon"})
    assert "theme" in str(exc_info.value).lower()


def test_invalid_position_raises_validation_error() -> None:
    with pytest.raises(ValidationError) as exc_info:
        WidgetConfig.from_dict({"position": "top-right"})
    assert "position" in str(exc_info.value).lower()


# --- validation: primary_color hex --------------------------------------------


@pytest.mark.parametrize(
    "color",
    [
        "#3b82f6",
        "#3B82F6",
        "#FFFFFF",
        "#000000",
        "#ABC",  # 3-digit shorthand allowed
    ],
)
def test_valid_hex_colors_accepted(color: str) -> None:
    cfg = WidgetConfig.from_dict({"primary_color": color})
    assert cfg.primary_color == color


@pytest.mark.parametrize(
    "color",
    [
        "3b82f6",     # missing '#'
        "#GGGGGG",    # non-hex chars
        "#12345",     # 5-digit
        "#1234567",   # 7-digit
        "blue",       # name
        "",
    ],
)
def test_invalid_hex_colors_rejected(color: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        WidgetConfig.from_dict({"primary_color": color})
    assert "primary_color" in str(exc_info.value).lower() or "color" in str(exc_info.value).lower()


# --- validation: string lengths -----------------------------------------------


def test_title_too_long_rejected() -> None:
    with pytest.raises(ValidationError):
        WidgetConfig.from_dict({"title": "x" * 100})  # cap at 60 chars


def test_welcome_message_too_long_rejected() -> None:
    with pytest.raises(ValidationError):
        WidgetConfig.from_dict({"welcome_message": "x" * 1000})  # cap at 500


def test_placeholder_too_long_rejected() -> None:
    with pytest.raises(ValidationError):
        WidgetConfig.from_dict({"placeholder": "x" * 200})  # cap at 100


def test_empty_title_rejected() -> None:
    with pytest.raises(ValidationError):
        WidgetConfig.from_dict({"title": ""})


# --- validation: allowed_origins ----------------------------------------------


@pytest.mark.parametrize(
    "origin",
    [
        "https://example.com",
        "http://localhost:3000",
        "https://sub.example.co.uk",
        "*",  # wildcard allowed
    ],
)
def test_valid_origins_accepted(origin: str) -> None:
    cfg = WidgetConfig.from_dict({"allowed_origins": [origin]})
    assert origin in cfg.allowed_origins


@pytest.mark.parametrize(
    "origin",
    [
        "example.com",         # missing scheme
        "https://",            # empty host
        "ftp://example.com",   # disallowed scheme
        "https://example.com/path",  # path not allowed
        "https://example.com:",   # trailing colon
    ],
)
def test_invalid_origins_rejected(origin: str) -> None:
    with pytest.raises(ValidationError):
        WidgetConfig.from_dict({"allowed_origins": [origin]})


def test_too_many_origins_rejected() -> None:
    many = [f"https://h{i}.example.com" for i in range(60)]
    with pytest.raises(ValidationError):
        WidgetConfig.from_dict({"allowed_origins": many})  # cap at 50


def test_duplicate_origins_deduplicated() -> None:
    cfg = WidgetConfig.from_dict({
        "allowed_origins": ["https://a.example.com", "https://a.example.com"],
    })
    assert cfg.allowed_origins == ("https://a.example.com",)
