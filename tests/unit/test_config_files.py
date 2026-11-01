"""Unit tests for src/config/files.py (base file, per-environment overlay, APP_ENV)."""

from pathlib import Path

import pytest

from src.config import files
from src.config.errors import ConfigError
from src.config.files import load_config
from src.config.settings import Settings
from tests.unit.conftest import TEST_IDENTITY

BASE = '[playlist]\ndefault_size = 16\nmax_size = 30\n\n[spotify]\nmarket = "IT"\n'  # Fake base


@pytest.fixture
def config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the loader at an empty temporary folder holding only a fake base.toml.

    Args:
        tmp_path: Pytest temporary directory.
        monkeypatch: Pytest fixture used to patch the folder and APP_ENV.

    Returns:
        The temporary configuration folder.
    """
    monkeypatch.setattr(files, "CONFIG_DIR", tmp_path)
    monkeypatch.delenv("APP_ENV", raising=False)
    (tmp_path / "base.toml").write_text(BASE)
    return tmp_path


def test_base_file_alone_is_loaded(config_dir: Path) -> None:
    """Without APP_ENV, the local environment has no overlay: the base file is returned."""
    assert load_config() == {
        "playlist": {"default_size": 16, "max_size": 30},
        "spotify": {"market": "IT"},
    }


def test_overlay_overrides_single_keys(config_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """APP_ENV=production overrides only the keys listed in production.toml."""
    (config_dir / "production.toml").write_text(
        "[playlist]\nmax_size = 20\n\n[gcp]\nproject_id = 'p'\n"
    )
    monkeypatch.setenv("APP_ENV", "production")
    sections = load_config()
    assert sections["playlist"] == {"default_size": 16, "max_size": 20}
    assert sections["spotify"] == {"market": "IT"}
    assert sections["gcp"] == {"project_id": "p"}


def test_explicit_environment_wins_over_app_env(
    config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """load_config("production") applies the overlay whatever APP_ENV says."""
    (config_dir / "production.toml").write_text("[spotify]\nmarket = 'US'\n")
    monkeypatch.setenv("APP_ENV", "local")
    assert load_config("production")["spotify"]["market"] == "US"


def test_unknown_app_env_raises(config_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A typo in APP_ENV is an error, never a silent fallback to the base values."""
    monkeypatch.setenv("APP_ENV", "prod")
    with pytest.raises(ConfigError, match="APP_ENV"):
        load_config()


def test_missing_base_file_raises(config_dir: Path) -> None:
    (config_dir / "base.toml").unlink()
    with pytest.raises(ConfigError, match=r"Missing configuration file .*base\.toml"):
        load_config()


@pytest.mark.parametrize(
    ("content", "match"), [("[playlist\n", "not valid TOML"), ("max_size = 30\n", "outside a")]
)
def test_malformed_files_raise(config_dir: Path, content: str, match: str) -> None:
    """Invalid TOML and keys outside a [section] are reported with the file name."""
    (config_dir / "base.toml").write_text(content)
    with pytest.raises(ConfigError, match=rf"base\.toml .*{match}"):
        load_config()


@pytest.mark.parametrize("app_env", ["local", "production"])
def test_committed_files_are_valid(app_env: str) -> None:
    """The repository's config files validate once the blank identity keys are filled in."""
    sections = load_config(app_env)
    for name, values in TEST_IDENTITY.items():
        sections[name] = {**values, **{k: v for k, v in sections[name].items() if v}}
    assert isinstance(Settings.model_validate(sections), Settings)
