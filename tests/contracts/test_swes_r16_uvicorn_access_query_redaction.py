"""R16 access-log controls, using only synthetic callback parameters."""
from __future__ import annotations

import io
import logging

from core.security.oidc_access_log_redaction import (
    QueryRedactionFilter,
    install_access_log_filter,
)


def test_synthetic_oauth_callback_query_is_never_formatted_in_access_log():
    logger = logging.getLogger("uvicorn.access")
    install_access_log_filter()
    install_access_log_filter()
    assert sum(isinstance(f, QueryRedactionFilter) for f in logger.filters) == 1

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    original_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        logger.info(
            '%s - "%s %s HTTP/%s" %d',
            "127.0.0.1:1234",
            "GET",
            "/internal/swes/pa/oidc/callback?code=SYNTH_CODE_A&state=SYNTH_STATE_B",
            "1.1",
            403,
        )
        logger.info(
            '%s - "%s %s HTTP/%s" %d',
            "127.0.0.1:1234",
            "GET",
            "/health?anything=NO_QUERY_VALUE",
            "1.1",
            200,
        )
    finally:
        logger.removeHandler(handler)
        logger.setLevel(original_level)

    result = stream.getvalue()
    assert "SYNTH_CODE_A" not in result
    assert "SYNTH_STATE_B" not in result
    assert "NO_QUERY_VALUE" not in result
    assert "code=" not in result and "state=" not in result
    assert "/internal/swes/pa/oidc/callback HTTP/1.1" in result
    assert "/health HTTP/1.1" in result


def test_source_main_installs_filter_before_app_factory():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "main.py").read_text(
        encoding="utf-8"
    )
    assert source.index("install_access_log_filter()") < source.index("create_app()")
