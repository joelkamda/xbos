from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "wnd_demo_cc_legacy_neutral_bridge.py"
ENV = ROOT / "alembic_neutral" / "env.py"


def load_bridge_module():
    spec = importlib.util.spec_from_file_location("wnd_demo_cc_bridge", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bridge_targets_are_exactly_049_and_050():
    bridge = load_bridge_module()
    assert bridge.ALLOWED_TARGETS == {
        "cc_catalog_binding_price_code_case_049",
        "cc_order_draft_facade_050",
    }


def test_bridge_requires_localhost_and_exact_disposable_database():
    bridge = load_bridge_module()
    bridge.validate_local_database_url(
        "postgresql://postgres@127.0.0.1:55434/wnd_demo_cc_compat_r1",
        expected_database="wnd_demo_cc_compat_r1",
    )
    with pytest.raises(bridge.BridgeRejected, match="localhost"):
        bridge.validate_local_database_url(
            "postgresql://postgres@db.example.test:5432/wnd_demo_cc_compat_r1",
            expected_database="wnd_demo_cc_compat_r1",
        )
    with pytest.raises(bridge.BridgeRejected, match="name_mismatch"):
        bridge.validate_local_database_url(
            "postgresql://postgres@127.0.0.1:55434/not_authorized",
            expected_database="wnd_demo_cc_compat_r1",
        )


def test_bridge_preserves_exact_legacy_revision_identity():
    bridge = load_bridge_module()
    assert bridge.LEGACY_REVISION == "5c706797029a"
    assert bridge.NEUTRAL_VERSION_TABLE == "alembic_neutral_bridge_version"
    assert bridge.NEUTRAL_BASELINE_REVISION == "m13_source_state_001"
    assert "VARCHAR(128)" in SCRIPT.read_text(encoding="utf-8")


def test_bridge_source_never_stamps_or_overwrites_legacy_revision():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "command.stamp" not in source
    assert ".stamp(" not in source
    assert "UPDATE alembic_version" not in source
    assert "DELETE FROM alembic_version" not in source
    assert "INSERT INTO alembic_version" not in source
    assert 'NEUTRAL_VERSION_TABLE = "alembic_neutral_bridge_version"' in source


def test_050_requires_observed_049_bridge_state():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "neutral_050_requires_049_gate" in source
    assert "neutral_before != NEUTRAL_049" in source


def test_neutral_env_defaults_to_canonical_version_table():
    source = ENV.read_text(encoding="utf-8")
    assert '"ALEMBIC_NEUTRAL_VERSION_TABLE"' in source
    assert '"alembic_version"' in source
    assert "version_table=neutral_version_table" in source
    assert "invalid_alembic_neutral_version_table" in source


def test_neutral_version_table_name_is_strictly_guarded():
    source = ENV.read_text(encoding="utf-8")
    assert r"[A-Za-z_][A-Za-z0-9_]{0,62}" in source


def test_bridge_script_has_no_hosted_or_render_target():
    source = SCRIPT.read_text(encoding="utf-8").casefold()
    assert "dpg-db3rd17lk1mc73ckrie0-a" not in source
    assert "render.com" not in source
    assert "dashboard.render" not in source
