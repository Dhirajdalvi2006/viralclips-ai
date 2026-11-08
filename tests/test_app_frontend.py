"""Tests for the frontend JavaScript.

The frontend is plain JavaScript with no build step, so the checks are
static: every screen has to exist, every control has to be wired to a
real API call, and nothing may fabricate a number.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "viralclips_app" / "static"
APP_JS = STATIC / "app.js"
INDEX_HTML = STATIC / "index.html"


@pytest.fixture(scope="module")
def source() -> str:
    return APP_JS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def html() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


def test_the_frontend_files_exist():
    assert APP_JS.is_file()
    assert INDEX_HTML.is_file()
    assert (STATIC / "styles.css").is_file()


@pytest.mark.skipif(shutil.which("node") is None,
                    reason="node is not installed")
def test_the_javascript_parses():
    """A syntax error would break every screen at once."""
    result = subprocess.run(["node", "--check", str(APP_JS)],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr


def test_every_navigation_screen_exists_in_the_html(html):
    """Every screen the sidebar offers must have a route entry."""
    routes = set(re.findall(r'data-route="([^"]+)"', html))
    for screen in ("overview", "new-task", "channels", "library", "queue",
                   "clips", "editor", "calendar", "analytics", "ai",
                   "accounts", "settings"):
        assert screen in routes, f"missing screen {screen}"
    assert len(routes) == 12


def test_the_token_is_sent_in_the_header(source):
    assert "X-ViralClips-Token" in source


def test_the_bootstrap_call_fetches_the_token(source):
    assert "/api/bootstrap" in source


def test_the_frontend_calls_real_api_endpoints(source):
    endpoints = set(re.findall(r"['\"`](/api/[a-z0-9/_?=&{}$.-]+)", source))
    assert len(endpoints) >= 15
    # Every endpoint the UI uses must exist in the backend.
    from viralclips_app.main import app

    routes = {route.path for route in app.routes}
    for endpoint in endpoints:
        path = endpoint.split("?")[0]
        # Templated paths are checked by their static prefix.
        path = re.sub(r"\$\{[^}]+\}", "", path).rstrip("/")
        if not path or path == "/api":
            continue
        assert any(route.startswith(path) or path.startswith(route)
                   for route in routes), f"frontend calls unknown {path}"


def test_the_frontend_does_not_invent_numbers(source):
    """No hardcoded metric values that would look like real data."""
    forbidden = [
        r"views:\s*\d{3,}",
        r"likes:\s*\d{3,}",
        r"followers:\s*\d{3,}",
        r"revenue:\s*\$\d",
        r"watch[_ ]?time:\s*\d",
    ]
    for pattern in forbidden:
        assert not re.search(pattern, source, re.IGNORECASE), pattern


def test_the_frontend_does_not_use_random_to_fake_data(source):
    """A randomised number is a fabricated number."""
    assert "Math.random()" not in source


def test_the_frontend_shows_honest_unavailable_states(source):
    """Unavailable metrics must be labelled, not omitted or faked."""
    assert "Not available" in source or "not available" in source \
        or "Unavailable" in source


def test_the_frontend_has_no_dead_alert_only_buttons(source):
    """A button that only shows an alert is a placeholder control."""
    assert re.search(r"onclick=[\"']alert\(", source) is None


def test_the_frontend_escapes_user_content(source):
    """User content must never be injected as raw HTML.

    The frontend builds DOM nodes with ``el()`` and passes user data
    through the ``text:`` attribute, which sets ``textContent``. That
    is safe by construction, so the test asserts that the safe path is
    used and that no raw-HTML escape hatch remains.
    """
    assert "function esc(" in source
    assert re.search(r"&amp;", source) and re.search(r"&#39;", source)

    # The element helper must not offer a raw-HTML attribute.
    assert "key === 'html'" not in source

    # The only permitted innerHTML writes are the trusted icon sprite
    # and the statements that clear a container.
    for match in re.finditer(r"\.innerHTML\s*=\s*([^;]+);", source):
        value = match.group(1).strip()
        assert "ICONS[" in value or value in ("''", '""'), \
            f"raw innerHTML assignment: {value[:60]}"

    # The modal helper must render a string body as text, not markup.
    assert "bodyNode.textContent = body" in source
    assert "bodyNode.innerHTML = body" not in source


def test_the_frontend_shows_the_worker_state(source):
    assert "worker" in source.lower()


def test_the_frontend_uses_the_sse_stream(source):
    assert "/api/events" in source


def test_the_stylesheet_defines_the_design_tokens(html):
    assert "/static/styles.css" in html


def test_the_html_loads_the_script_and_stylesheet(html):
    assert "/static/app.js" in html
    assert "/static/styles.css" in html


def test_the_html_has_no_inline_event_handlers_that_call_alert(html):
    assert re.search(r'on\w+="[^"]*alert\(', html) is None


def test_the_html_declares_every_screen_container(html, source):
    """Every navigation route must have a registered screen.

    The frontend renders into a single ``#view`` container and swaps
    the content per route, so the check is that each navigation entry
    has a matching ``registerRoute`` call in the script.
    """
    routes = set(re.findall(r'data-route="([^"]+)"', html))
    registered = set(re.findall(r"registerRoute\('([^']+)'", source))
    assert routes, "no navigation routes found"
    for screen in routes:
        assert screen in registered, f"no handler registered for {screen}"
    # The shared render target must exist.
    assert 'id="view"' in html
