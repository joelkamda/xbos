from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.domain.finance import m6_acceptance
from core.domain.finance.m4_acceptance import (
    HistoricalLineageError,
    validate_historical_lineage_prefix,
)

ROOT = Path(__file__).resolve().parents[2]
FROZEN = m6_acceptance.EXPECTED_LINEAGE
DESCENDANT = "pc1_structural_context_021"


def test_exact_frozen_lineage_passes() -> None:
    assert validate_historical_lineage_prefix(FROZEN, FROZEN) == FROZEN


def test_valid_descendant_lineage_passes_and_returns_frozen_evidence() -> None:
    live = FROZEN + (DESCENDANT,)
    assert validate_historical_lineage_prefix(live, FROZEN) == FROZEN


def test_missing_historical_revision_fails() -> None:
    live = FROZEN[:7] + FROZEN[8:] + (DESCENDANT,)
    with pytest.raises(HistoricalLineageError, match="historical lineage mismatch"):
        validate_historical_lineage_prefix(live, FROZEN)


@pytest.mark.parametrize(
    "live",
    (
        FROZEN[:4] + (FROZEN[5], FROZEN[4]) + FROZEN[6:],
        FROZEN[:4] + ("replaced_historical_revision",) + FROZEN[5:],
    ),
)
def test_reordered_or_replaced_historical_revision_fails(live: tuple[str, ...]) -> None:
    with pytest.raises(HistoricalLineageError, match="historical lineage mismatch"):
        validate_historical_lineage_prefix(live, FROZEN)


def test_shorter_live_lineage_fails_explicitly() -> None:
    with pytest.raises(HistoricalLineageError, match="live lineage is shorter"):
        validate_historical_lineage_prefix(FROZEN[:-1], FROZEN)


@pytest.mark.parametrize(
    ("field", "replacement", "expected_code"),
    (
        ("canonical_head", DESCENDANT, "unexpected_head"),
        (
            "canonical_migration_lineage",
            list(FROZEN[:-1]) + [DESCENDANT],
            "manifest_lineage_changed",
        ),
    ),
)
def test_altered_frozen_manifest_head_or_lineage_still_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    replacement: object,
    expected_code: str,
) -> None:
    source = ROOT / "contracts/finance/v1/m6_release_manifest.json"
    manifest = json.loads(source.read_text(encoding="utf-8"))
    manifest[field] = replacement
    target = tmp_path / "contracts/finance/v1/m6_release_manifest.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(manifest), encoding="utf-8")

    monkeypatch.setattr(
        m6_acceptance,
        "live_migration_lineage",
        lambda _root: FROZEN + (DESCENDANT,),
    )
    monkeypatch.setattr(m6_acceptance, "semantic_sha256", lambda _path: "unused")

    with pytest.raises(m6_acceptance.M6AcceptanceError) as raised:
        m6_acceptance.validate_release_manifest(tmp_path)
    assert raised.value.code == expected_code
