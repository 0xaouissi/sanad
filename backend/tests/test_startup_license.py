from unittest.mock import Mock

import pytest

import app.main as main
from app.core.config import Settings


def test_startup_warns_for_research_license_3b(monkeypatch: pytest.MonkeyPatch) -> None:
    log = Mock()
    monkeypatch.setattr(main, "log", log)
    main._warn_model_license(Settings())  # small-tier default = qwen2.5:3b
    log.warning.assert_called_once()
    args, kwargs = log.warning.call_args
    assert args[0] == "llm_model_research_license"
    assert kwargs["model"] == "qwen2.5:3b-instruct-q4_K_M"
    assert "docs/models.md" in kwargs["hint"]


def test_startup_silent_for_apache_tier(monkeypatch: pytest.MonkeyPatch) -> None:
    log = Mock()
    monkeypatch.setattr(main, "log", log)
    main._warn_model_license(Settings(model_tier="medium"))
    log.warning.assert_not_called()


def test_startup_warns_for_3b_override_on_large_tier(monkeypatch: pytest.MonkeyPatch) -> None:
    log = Mock()
    monkeypatch.setattr(main, "log", log)
    main._warn_model_license(Settings(model_tier="large", llm_model="qwen2.5:3b-instruct-q8_0"))
    log.warning.assert_called_once()
    assert log.warning.call_args.kwargs["model"] == "qwen2.5:3b-instruct-q8_0"


def test_startup_silent_for_openai_gpt_model(monkeypatch: pytest.MonkeyPatch) -> None:
    log = Mock()
    monkeypatch.setattr(main, "log", log)
    main._warn_model_license(
        Settings(llm_provider="openai", openai_api_key="sk-test", openai_model="gpt-4o-mini")
    )
    log.warning.assert_not_called()


def test_startup_warns_for_research_licensed_api_model(monkeypatch: pytest.MonkeyPatch) -> None:
    log = Mock()
    monkeypatch.setattr(main, "log", log)
    main._warn_model_license(
        Settings(
            llm_provider="openai",
            openai_api_key="sk-test",
            openai_model="Qwen/Qwen2.5-3B-Instruct",
        )
    )
    log.warning.assert_called_once()