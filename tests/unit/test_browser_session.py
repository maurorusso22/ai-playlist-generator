"""Unit tests for src/session/browser_session.py (js-eval bridge and session_state patched)."""

import json
from typing import Any
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from src.session import browser_session
from tests.unit.session_factory import SID


@pytest.fixture
def bridge(mocker: MockerFixture) -> MagicMock:
    """Replace the js-eval component and st.session_state (a plain dict outside a run).

    Args:
        mocker: Pytest-mock fixture.

    Returns:
        The mocked `streamlit_js_eval` function.
    """
    mocker.patch("src.session.browser_session.st.session_state", {})
    mock: MagicMock = mocker.patch("src.session.browser_session.streamlit_js_eval")
    return mock


@pytest.fixture
def markdown(mocker: MockerFixture) -> MagicMock:
    """Replace st.markdown, which renders the fallback link.

    Args:
        mocker: Pytest-mock fixture.

    Returns:
        The mocked `st.markdown` function.
    """
    mock: MagicMock = mocker.patch("src.session.browser_session.st.markdown")
    return mock


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        (None, (False, None)),
        ("", (True, None)),
        (SID, (True, SID)),
        ("not-a-uuid", (True, None)),
        (browser_session.UNAVAILABLE, (True, None)),
        ("6ba7b810-9dad-11d1-80b4-00c04fd430c8", (True, None)),  # UUID1, not UUID4
        (SID.upper(), (True, None)),  # Not canonical
        (42, (True, None)),
    ],
)
def test_read_session_id_tri_state(
    bridge: MagicMock, answer: Any, expected: tuple[bool, str | None]
) -> None:
    bridge.return_value = answer
    assert browser_session.read_session_id() == expected


def test_read_expression_catches_storage_errors(bridge: MagicMock) -> None:
    browser_session.read_session_id()
    expression = bridge.call_args.kwargs["js_expressions"]
    assert json.dumps("apg_session_id") in expression
    assert "catch (e) { return " + json.dumps(browser_session.UNAVAILABLE) in expression


def test_writes_bump_generation_so_next_read_remounts(bridge: MagicMock) -> None:
    browser_session.read_session_id()
    first_key = bridge.call_args.kwargs["key"]
    browser_session.store_session_id(SID)
    store_call = bridge.call_args.kwargs
    assert (
        f"localStorage.setItem({json.dumps('apg_session_id')}, {json.dumps(SID)})"
        in (store_call["js_expressions"])
    )
    browser_session.read_session_id()
    assert bridge.call_args.kwargs["key"] not in (first_key, store_call["key"])
    browser_session.clear_session_id()
    clear_call = bridge.call_args.kwargs
    assert "localStorage.removeItem" in clear_call["js_expressions"]
    assert clear_call["key"] != store_call["key"]


def test_store_rejects_non_uuid(bridge: MagicMock) -> None:
    with pytest.raises(ValueError, match="UUID4"):
        browser_session.store_session_id("../other-doc")
    bridge.assert_not_called()


def test_redirect_runs_script_and_renders_escaped_fallback(
    bridge: MagicMock, markdown: MagicMock
) -> None:
    url = 'https://accounts.spotify.com/authorize?client_id=a&state=x"y'
    browser_session.redirect_same_tab(url)
    expression = bridge.call_args.kwargs["js_expressions"]
    assert json.dumps(url) in expression and "link.target = '_self'" in expression
    html = markdown.call_args.args[0]
    assert 'target="_self"' in html and "&amp;state=x&quot;y" in html
    assert markdown.call_args.kwargs["unsafe_allow_html"] is True


@pytest.mark.parametrize("url", ["javascript:alert(1)", "http://example.com/"])
def test_redirect_rejects_non_https(bridge: MagicMock, markdown: MagicMock, url: str) -> None:
    with pytest.raises(ValueError, match="https"):
        browser_session.redirect_same_tab(url)
    bridge.assert_not_called()
    markdown.assert_not_called()
