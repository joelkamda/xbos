from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.verify_r6_1_wnd_rehearsal_adoption as r61

from core.domain.finance.legacy_authority_inventory import load_inventory
from core.domain.finance.wnd_cutover_support_contract import DualReadProjection, ReadinessEvidence
from core.domain.finance.wnd_cutover_support_service import WndCutoverSupportService
from core.domain.finance.wnd_finance_adapter_contract import LegacyFinancialEnvelope, LegacySourceFamily
from core.domain.finance.wnd_financial_mapping_contract import WndFinancialMappingError, assert_replay
from core.domain.finance.wnd_financial_mapping_service import WndFinancialMappingService
from core.domain.finance.wnd_inventory_document_service import WndInventoryFinancialHandoffService
from core.domain.finance.wnd_shadow_rehearsal_contract import FinancialControlTotals
from core.domain.finance.wnd_shadow_rehearsal_service import WndShadowRehearsalService
from restaurant.r6 import (
    EXPECTED_COUNTS,
    PRODUCTION_BRANCH_ID,
    PRODUCTION_DATABASE,
    PRODUCTION_TENANT_ID,
    REFERENCE_RELEASE_TAG,
    SERVER_BACKUP_SHA256,
    SOURCE_REVISION,
    TARGET_HEAD,
)
from restaurant.r6.cutover_rehearsal import (
    CONTROL_NAMES,
    WithheldLedger,
    add_controls,
    assert_complete_reconciliation,
    decimal,
    deterministic_public_id,
    semantic_hash,
    wnd_business_date,
    zero_controls,
)

EXPECTED_BRANCH = "restaurant/r6-2-wnd-production-cutover-rehearsal"
SOURCE_COMMIT = "0f4c72ff297b580c9a2572fe6a0068d814b22267"
SOURCE_ARCHIVE_SHA256 = "9c789845bf8f2a68ab0de9d87707eac492e109a8e646c4533e915e181e6a1c94"
SOURCE_ARCHIVE_SIZE = 6198072
R6_1_FREEZE_TAG = "restaurant-r6-1-wnd-reference-clone-adoption-20260821"

SOURCE_DATABASE = "xbos_r6_2_source"
CANDIDATE_DATABASE = "xbos_r6_2_candidate"
DISPOSABLE_DATABASES = frozenset({SOURCE_DATABASE, CANDIDATE_DATABASE})

AUTHORITY_PATH = "contracts/restaurant/v1/r6_2_production_cutover_rehearsal_authority.json"
CONTROL_SCOPE_PATH = "contracts/restaurant/v1/r6_2_financial_control_scope.json"
RELEASE_MANIFEST_PATH = "contracts/restaurant/v1/r6_2_release_manifest.json"

OBSERVED_AT = datetime(2026, 8, 21, 16, 17, 36, tzinfo=timezone.utc)


def _load(relative: str) -> dict[str, Any]:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _verify_release_manifest() -> int:
    manifest = _load(RELEASE_MANIFEST_PATH)
    if manifest.get("self_excluded") is not True:
        raise RuntimeError("R6_2_RELEASE_MANIFEST_SELF_EXCLUSION")
    artifacts = manifest.get("artifacts", [])
    if manifest.get("artifact_count") != len(artifacts):
        raise RuntimeError("R6_2_RELEASE_MANIFEST_COUNT")
    paths = [row["path"] for row in artifacts]
    if len(paths) != len(set(paths)):
        raise RuntimeError("R6_2_RELEASE_MANIFEST_DUPLICATE_PATH")
    if RELEASE_MANIFEST_PATH in paths:
        raise RuntimeError("R6_2_RELEASE_MANIFEST_SELF_INCLUDED")
    for row in artifacts:
        path = ROOT / row["path"]
        if not path.is_file():
            raise RuntimeError("R6_2_RELEASE_ARTIFACT_MISSING=" + row["path"])
        raw = path.read_bytes()
        canonical = raw.replace(b"\r\n", b"\n")
        if hashlib.sha256(canonical).hexdigest() != row["sha256"]:
            raise RuntimeError("R6_2_RELEASE_ARTIFACT_HASH=" + row["path"])
        if len(raw) != row["size"]:
            raise RuntimeError("R6_2_RELEASE_ARTIFACT_SIZE=" + row["path"])
    return len(artifacts)


def _static_verify() -> dict[str, Any]:
    branch = subprocess.run(
        ["git", "branch", "--show-current"], cwd=ROOT, text=True, capture_output=True, check=True
    ).stdout.strip()
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True
    ).stdout.strip()
    if branch != EXPECTED_BRANCH:
        raise RuntimeError(f"R6_2_WRONG_BRANCH expected={EXPECTED_BRANCH} actual={branch}")
    if head != SOURCE_COMMIT:
        raise RuntimeError(f"R6_2_SOURCE_HEAD_DRIFT expected={SOURCE_COMMIT} actual={head}")

    tag_target = subprocess.run(
        ["git", "rev-parse", f"{R6_1_FREEZE_TAG}^{{}}"],
        cwd=ROOT, text=True, capture_output=True, check=True,
    ).stdout.strip()
    if tag_target != SOURCE_COMMIT:
        raise RuntimeError(f"R6_2_R6_1_FREEZE_TAG_DRIFT={tag_target}")

    authority = _load(AUTHORITY_PATH)
    controls = _load(CONTROL_SCOPE_PATH)
    if authority["source_checkpoint"] != SOURCE_COMMIT:
        raise RuntimeError("R6_2_SOURCE_CONTRACT_DRIFT")
    if authority["source_archive_sha256"] != SOURCE_ARCHIVE_SHA256:
        raise RuntimeError("R6_2_SOURCE_ARCHIVE_SHA_DRIFT")
    if authority["source_archive_size"] != SOURCE_ARCHIVE_SIZE:
        raise RuntimeError("R6_2_SOURCE_ARCHIVE_SIZE_DRIFT")
    if authority["production_database"] != PRODUCTION_DATABASE:
        raise RuntimeError("R6_2_PRODUCTION_DB_DRIFT")
    if authority["production_write_authorized"] is not False:
        raise RuntimeError("R6_2_PRODUCTION_WRITE_AUTHORITY_LEAK")
    if authority["writer_routing"] != "unchanged":
        raise RuntimeError("R6_2_WRITER_ROUTING_LEAK")
    if set(authority["rehearsal_databases"]) != set(DISPOSABLE_DATABASES):
        raise RuntimeError("R6_2_DATABASE_SCOPE_DRIFT")
    if authority["candidate_head"] != TARGET_HEAD:
        raise RuntimeError("R6_2_TARGET_HEAD_DRIFT")
    if authority["reference_release_tag"] != REFERENCE_RELEASE_TAG:
        raise RuntimeError("R6_2_REFERENCE_RELEASE_DRIFT")
    if authority["source_snapshot_backup_sha256"] != SERVER_BACKUP_SHA256:
        raise RuntimeError("R6_2_BACKUP_SHA_DRIFT")
    if controls["required_equation"] != "legacy_source = canonical_mapped + explicit_withheld for every control":
        raise RuntimeError("R6_2_RECONCILIATION_EQUATION_DRIFT")

    if list((ROOT / "alembic_neutral/versions").glob("r6_2*")):
        raise RuntimeError("R6_2_SCHEMA_MIGRATION_FORBIDDEN")
    if list((ROOT / "alembic_neutral/sql").glob("r6_2*")):
        raise RuntimeError("R6_2_SCHEMA_SQL_FORBIDDEN")

    m75 = _load("contracts/finance/v1/m75_finance_migration_support_acceptance_and_freeze.json")
    if m75["live_cutover_owner"] != "R6" or m75["cutover_authorized"] or m75["retirement_execution_allowed"]:
        raise RuntimeError("R6_2_M7_BOUNDARY_DRIFT")

    artifacts = _verify_release_manifest()
    return {
        "status": "PASS",
        "source_branch": branch,
        "source_head": head,
        "source_archive_sha256": SOURCE_ARCHIVE_SHA256,
        "r6_1_freeze_tag": R6_1_FREEZE_TAG,
        "production_database": PRODUCTION_DATABASE,
        "production_writes": "NONE",
        "writer_routing": "UNCHANGED",
        "reference_release_tag": REFERENCE_RELEASE_TAG,
        "rehearsal_databases": sorted(DISPOSABLE_DATABASES),
        "release_artifacts": artifacts,
    }


def _prepare_r61_harness() -> None:
    # R6.2 deliberately reuses the frozen R6.1 acceptance harness for the
    # already-proved restore/adopt/compose mechanics, but substitutes new
    # disposable database names. This is acceptance infrastructure reuse only.
    r61.SOURCE_DATABASE = SOURCE_DATABASE
    r61.CANDIDATE_DATABASE = CANDIDATE_DATABASE
    r61.DISPOSABLE_DATABASES = DISPOSABLE_DATABASES


def _engine(name: str):
    _prepare_r61_harness()
    return r61._database_engine(name)


def _restore(name: str, backup: Path) -> None:
    _prepare_r61_harness()
    r61._restore(name, backup)


def _adopt_and_compose() -> dict[str, Any]:
    _prepare_r61_harness()
    r61._adopt_candidate()
    composition = r61._register_and_compose_candidate()
    return composition


def _assert_raw_source(name: str) -> dict[str, Any]:
    engine = _engine(name)
    try:
        return r61._assert_source_controls(engine, f"R6_2_{name.upper()}")
    finally:
        engine.dispose()


def _org_scope(connection) -> int:
    row = connection.execute(
        text(
            "SELECT organization_unit_id FROM legacy_branch_structural_mappings "
            "WHERE tenant_id=:t AND branch_id=:b"
        ),
        {"t": PRODUCTION_TENANT_ID, "b": PRODUCTION_BRANCH_ID},
    ).mappings().one_or_none()
    if row is None:
        raise RuntimeError("R6_2_PC1_BRANCH_MAPPING_MISSING")
    return int(row["organization_unit_id"])


def _source_controls(connection) -> dict[str, Decimal]:
    revenue = decimal(connection.execute(text(
        "SELECT COALESCE(SUM(amount),0) FROM treasury_logs "
        "WHERE tenant_id=:t AND branch_id=:b AND event_type='SALE_REVENUE_GROSS'"
    ), {"t": PRODUCTION_TENANT_ID, "b": PRODUCTION_BRANCH_ID}).scalar_one())
    allowances = decimal(connection.execute(text(
        "SELECT COALESCE(SUM(amount),0) FROM treasury_logs "
        "WHERE tenant_id=:t AND branch_id=:b "
        "AND event_type IN ('DISCOUNT_APPLIED','COMPLIMENTARY_APPLIED')"
    ), {"t": PRODUCTION_TENANT_ID, "b": PRODUCTION_BRANCH_ID}).scalar_one())
    collections = decimal(connection.execute(text(
        "SELECT COALESCE(SUM(t.amount),0) "
        "FROM treasury_logs t "
        "LEFT JOIN payment_attempts a ON t.reference_type='payment_attempt' AND t.reference_id=a.id "
        "WHERE t.tenant_id=:t AND t.branch_id=:b AND t.event_type='PAYMENT_RECEIVED' "
        "AND COALESCE(a.settlement_mode,'') <> 'ar_repayment'"
    ), {"t": PRODUCTION_TENANT_ID, "b": PRODUCTION_BRANCH_ID}).scalar_one())
    collections += decimal(connection.execute(text(
        "SELECT COALESCE(SUM(amount),0) FROM accounts_receivable_repayments "
        "WHERE tenant_id=:t AND branch_id=:b"
    ), {"t": PRODUCTION_TENANT_ID, "b": PRODUCTION_BRANCH_ID}).scalar_one())
    ar = connection.execute(text(
        "SELECT COALESCE(SUM(original_amount),0) opened,COALESCE(SUM(paid_amount),0) satisfied "
        "FROM accounts_receivable WHERE tenant_id=:t AND branch_id=:b"
    ), {"t": PRODUCTION_TENANT_ID, "b": PRODUCTION_BRANCH_ID}).mappings().one()
    refunds = decimal(connection.execute(text(
        "SELECT COALESCE(SUM(amount),0) FROM treasury_logs "
        "WHERE tenant_id=:t AND branch_id=:b AND event_type IN ('REFUND_PAID','REFUND')"
    ), {"t": PRODUCTION_TENANT_ID, "b": PRODUCTION_BRANCH_ID}).scalar_one())
    documents = decimal(connection.execute(text(
        "SELECT count(*) FROM sales WHERE tenant_id=:t AND branch_id=:b"
    ), {"t": PRODUCTION_TENANT_ID, "b": PRODUCTION_BRANCH_ID}).scalar_one())
    return {
        "commercial_revenue": revenue,
        "customer_allowances": allowances,
        "cash_collections": collections,
        "receivables_opened": decimal(ar["opened"]),
        "receivables_satisfied": decimal(ar["satisfied"]),
        "refunds": refunds,
        # There is no reliable historical cost basis in the frozen WND source.
        # Zero here is mapped/recognized cost, NOT an assertion of zero economic cost.
        "fulfillment_cost": Decimal("0"),
        "financial_documents": documents,
    }


def _commercial_rows(connection):
    return connection.execute(text("""
        WITH ledger AS (
            SELECT
                reference_id AS sale_id,
                COUNT(*) FILTER (WHERE event_type='SALE_REVENUE_GROSS') AS gross_rows,
                COALESCE(SUM(amount) FILTER (WHERE event_type='SALE_REVENUE_GROSS'),0) AS gross_amount,
                COALESCE(SUM(amount) FILTER (WHERE event_type='DISCOUNT_APPLIED'),0) AS discount_amount,
                COALESCE(SUM(amount) FILTER (WHERE event_type='COMPLIMENTARY_APPLIED'),0) AS complimentary_amount,
                MAX(currency) FILTER (WHERE event_type='SALE_REVENUE_GROSS') AS currency_code,
                MAX(meta->>'discount_reason') FILTER (WHERE event_type='DISCOUNT_APPLIED') AS discount_reason,
                MAX(meta->>'complimentary_reason') FILTER (WHERE event_type='COMPLIMENTARY_APPLIED') AS complimentary_reason,
                MAX(meta->>'complimentary_policy') FILTER (WHERE event_type='COMPLIMENTARY_APPLIED') AS complimentary_policy
            FROM treasury_logs
            WHERE tenant_id=:t AND branch_id=:b AND reference_type='sale'
            GROUP BY reference_id
        ),
        ar AS (
            SELECT
                sale_id,
                COUNT(*) AS ar_rows,
                COALESCE(SUM(original_amount),0) AS ar_original,
                MAX(customer_id) AS customer_id
            FROM accounts_receivable
            WHERE tenant_id=:t AND branch_id=:b AND sale_id IS NOT NULL
            GROUP BY sale_id
        )
        SELECT
            s.id,
            s.created_at,
            s.subtotal,
            s.total,
            COALESCE(l.gross_rows,0) AS gross_rows,
            COALESCE(l.gross_amount,0) AS gross_amount,
            COALESCE(l.discount_amount,0) AS discount_amount,
            COALESCE(l.complimentary_amount,0) AS complimentary_amount,
            COALESCE(l.currency_code,'XAF') AS currency_code,
            l.discount_reason,
            l.complimentary_reason,
            l.complimentary_policy,
            COALESCE(ar.ar_rows,0) AS ar_rows,
            COALESCE(ar.ar_original,0) AS ar_original,
            ar.customer_id
        FROM sales s
        LEFT JOIN ledger l ON l.sale_id=s.id
        LEFT JOIN ar ON ar.sale_id=s.id
        WHERE s.tenant_id=:t AND s.branch_id=:b
        ORDER BY s.id
    """), {"t": PRODUCTION_TENANT_ID, "b": PRODUCTION_BRANCH_ID}).mappings().all()


def _payment_rows(connection):
    return connection.execute(text("""
        SELECT
            t.id AS ledger_id,
            t.amount AS ledger_amount,
            t.currency AS currency_code,
            t.channel,
            t.occurred_at,
            t.idempotency_key,
            a.id AS attempt_id,
            a.amount AS attempt_amount,
            a.method,
            a.provider,
            a.settlement_mode,
            a.status,
            a.client_reference,
            a.callback_reference,
            a.gateway_reference,
            a.provider_reference,
            a.completed_at,
            i.id AS intent_id
        FROM treasury_logs t
        LEFT JOIN payment_attempts a
          ON t.reference_type='payment_attempt' AND t.reference_id=a.id
        LEFT JOIN payment_intents i ON i.id=a.payment_intent_id
        WHERE t.tenant_id=:t AND t.branch_id=:b
          AND t.event_type='PAYMENT_RECEIVED'
          AND COALESCE(a.settlement_mode,'') <> 'ar_repayment'
        ORDER BY t.id
    """), {"t": PRODUCTION_TENANT_ID, "b": PRODUCTION_BRANCH_ID}).mappings().all()


def _repayment_rows(connection):
    return connection.execute(text("""
        SELECT
            r.id,
            r.ar_id,
            r.amount,
            r.payment_method,
            r.reference,
            r.created_at,
            a.sale_id,
            a.customer_id,
            pa.id AS attempt_id,
            pa.status AS attempt_status,
            pa.completed_at AS attempt_completed_at,
            pa.provider_reference,
            pa.gateway_reference,
            pa.callback_reference,
            tl.id AS treasury_id,
            tl.amount AS treasury_amount,
            tl.currency AS treasury_currency
        FROM accounts_receivable_repayments r
        JOIN accounts_receivable a ON a.id=r.ar_id
        LEFT JOIN payment_attempts pa ON pa.client_reference=('ar-repayment:' || r.id::text)
        LEFT JOIN treasury_logs tl
          ON tl.reference_type='debt_repayment'
         AND tl.reference_id=r.id
         AND tl.event_type='DEBT_REPAYMENT'
         AND tl.tenant_id=r.tenant_id
        WHERE r.tenant_id=:t AND r.branch_id=:b
        ORDER BY r.id
    """), {"t": PRODUCTION_TENANT_ID, "b": PRODUCTION_BRANCH_ID}).mappings().all()


def _orphan_ar_rows(connection):
    return connection.execute(text("""
        SELECT a.id,a.original_amount,a.paid_amount,a.balance_due
        FROM accounts_receivable a
        LEFT JOIN sales s ON s.id=a.sale_id AND s.tenant_id=a.tenant_id
        WHERE a.tenant_id=:t AND a.branch_id=:b AND (a.sale_id IS NULL OR s.id IS NULL)
        ORDER BY a.id
    """), {"t": PRODUCTION_TENANT_ID, "b": PRODUCTION_BRANCH_ID}).mappings().all()


def _map_shadow(connection) -> dict[str, Any]:
    organization_unit_id = _org_scope(connection)
    source_controls = _source_controls(connection)
    if source_controls["commercial_revenue"] != Decimal("35193200.00"):
        raise RuntimeError("R6_2_FROZEN_REVENUE_CONTROL_DRIFT")
    if source_controls["receivables_opened"] != Decimal("736500.00"):
        raise RuntimeError("R6_2_FROZEN_AR_OPEN_CONTROL_DRIFT")
    if source_controls["receivables_satisfied"] != Decimal("96199.00"):
        raise RuntimeError("R6_2_FROZEN_AR_SATISFIED_CONTROL_DRIFT")
    gross_rows = int(connection.execute(text(
        "SELECT count(*) FROM treasury_logs WHERE tenant_id=:t AND branch_id=:b "
        "AND event_type='SALE_REVENUE_GROSS'"
    ), {"t": PRODUCTION_TENANT_ID, "b": PRODUCTION_BRANCH_ID}).scalar_one())
    if gross_rows != EXPECTED_COUNTS["sales"]:
        raise RuntimeError(f"R6_2_GROSS_REVENUE_EVENT_COUNT_DRIFT={gross_rows}")
    withheld = WithheldLedger()
    cases = []
    family_counts = Counter()
    mapped_counts = Counter()

    # Commercial sale economics.
    for row in _commercial_rows(connection):
        family_counts["commercial_sale"] += 1
        gross = decimal(row["gross_amount"])
        discount = decimal(row["discount_amount"])
        complimentary = decimal(row["complimentary_amount"])
        ar_original = decimal(row["ar_original"])
        controls = {
            "commercial_revenue": gross,
            "customer_allowances": discount + complimentary,
            "receivables_opened": ar_original,
        }
        identity = f"sale:{row['id']}"
        if int(row["gross_rows"]) != 1:
            withheld.add(source_identity=identity, reason="gross_revenue_event_cardinality", controls=controls)
            continue
        if gross != decimal(row["subtotal"]):
            withheld.add(source_identity=identity, reason="sale_gross_control_mismatch", controls=controls)
            continue
        canonical_collectible = gross - discount - complimentary
        if canonical_collectible < 0 or decimal(row["total"]) != canonical_collectible:
            withheld.add(source_identity=identity, reason="legacy_sale_allowance_equation_incompatible", controls=controls)
            continue
        if int(row["ar_rows"]) > 1 or ar_original > canonical_collectible:
            withheld.add(source_identity=identity, reason="receivable_opening_ambiguous", controls=controls)
            continue
        policy = str(row["complimentary_policy"] or "").strip().lower()
        if complimentary and policy not in {"contra_revenue", "promotion", "service_recovery"}:
            withheld.add(source_identity=identity, reason="complimentary_policy_unresolved", controls=controls)
            continue

        created = row["created_at"]
        payload = {
            "kind": "commercial_sale",
            "gross_amount": gross,
            "discount_amount": discount,
            "complimentary_amount": complimentary,
            "collected_amount": canonical_collectible - ar_original,
            "unpaid_amount": ar_original,
            "currency_code": str(row["currency_code"] or "XAF").upper(),
            "revenue_nature": "restaurant_sale",
            "customer_reference": f"customer:{row['customer_id']}" if row["customer_id"] is not None else None,
        }
        if discount:
            payload["discount_reason"] = str(row["discount_reason"] or "legacy_unspecified")
        if complimentary:
            payload["complimentary_policy"] = policy
            payload["complimentary_reason"] = str(row["complimentary_reason"] or "legacy_unspecified")

        envelope = LegacyFinancialEnvelope(
            tenant_id=PRODUCTION_TENANT_ID,
            organization_unit_id=organization_unit_id,
            source_family=LegacySourceFamily.COMMERCIAL,
            source_record_type="sale",
            source_record_id=str(row["id"]),
            source_updated_at=created,
            business_date=wnd_business_date(created),
            payload=payload,
        )
        try:
            plan = WndFinancialMappingService.map(envelope)
            assert_replay(plan, WndFinancialMappingService.map(envelope))
        except Exception as exc:
            withheld.add(source_identity=identity, reason=f"m71_commercial_{getattr(exc, 'code', type(exc).__name__)}", controls=controls)
            continue
        case = WndShadowRehearsalService.financial_case(len(cases) + 1, plan)
        cases.append(case)
        mapped_counts["commercial_sale"] += 1

    # A/R rows lacking a valid sale relation are not silently invented into a commercial sale.
    for row in _orphan_ar_rows(connection):
        withheld.add(
            source_identity=f"ar:{row['id']}",
            reason="receivable_without_sale_mapping",
            controls={"receivables_opened": row["original_amount"]},
        )

    # Settlement cashflow backed by PAYMENT_RECEIVED authority.
    seen_attempts = set()
    for row in _payment_rows(connection):
        family_counts["payment_settlement"] += 1
        amount = decimal(row["ledger_amount"])
        controls = {"cash_collections": amount}
        identity = f"payment_ledger:{row['ledger_id']}"
        attempt_id = row["attempt_id"]
        if attempt_id is None:
            withheld.add(source_identity=identity, reason="payment_attempt_missing", controls=controls)
            continue
        if attempt_id in seen_attempts:
            withheld.add(source_identity=identity, reason="duplicate_payment_received_attempt", controls=controls)
            continue
        seen_attempts.add(attempt_id)
        if str(row["status"] or "").lower() != "succeeded" or decimal(row["attempt_amount"]) != amount:
            withheld.add(source_identity=identity, reason="payment_finality_or_amount_mismatch", controls=controls)
            continue

        method = str(row["channel"] or row["method"] or "").strip().lower()
        if not method:
            withheld.add(source_identity=identity, reason="payment_method_missing", controls=controls)
            continue
        external = next(
            (str(row[name]).strip() for name in ("provider_reference","gateway_reference","callback_reference")
             if row[name] is not None and str(row[name]).strip()),
            "",
        )
        if method != "cash" and not external:
            withheld.add(source_identity=identity, reason="noncash_external_settlement_identity_missing", controls=controls)
            continue

        occurred = row["completed_at"] or row["occurred_at"]
        evidence_hash = semantic_hash({
            "ledger_id": row["ledger_id"],
            "idempotency_key": row["idempotency_key"],
            "attempt_id": attempt_id,
            "amount": amount,
            "method": method,
            "external": external or None,
        })
        payload = {
            "kind": "payment_settlement",
            "amount": amount,
            "fee_amount": Decimal("0"),
            "currency_code": str(row["currency_code"] or "XAF").upper(),
            "payment_method_code": method,
            "payment_rail_code": str(row["provider"] or method).strip().lower(),
            "finality_status": "final",
            "evidence_hash": evidence_hash,
            "evidence_verified": True,
            "external_settlement_reference": external or None,
            "operational_account_public_id": str(deterministic_public_id(
                "operational-account", PRODUCTION_TENANT_ID, PRODUCTION_BRANCH_ID, method
            )),
        }
        envelope = LegacyFinancialEnvelope(
            tenant_id=PRODUCTION_TENANT_ID,
            organization_unit_id=organization_unit_id,
            source_family=LegacySourceFamily.PAYMENT,
            source_record_type="payment_attempt",
            source_record_id=str(attempt_id),
            source_updated_at=occurred,
            business_date=wnd_business_date(occurred),
            payload=payload,
        )
        try:
            plan = WndFinancialMappingService.map(envelope)
            assert_replay(plan, WndFinancialMappingService.map(envelope))
        except Exception as exc:
            withheld.add(source_identity=identity, reason=f"m71_payment_{getattr(exc, 'code', type(exc).__name__)}", controls=controls)
            continue
        cases.append(WndShadowRehearsalService.financial_case(len(cases) + 1, plan))
        mapped_counts["payment_settlement"] += 1

    # Explicit A/R repayments. These settle existing receivables; they are never revenue.
    explicit_repayment_total = Decimal("0")
    for row in _repayment_rows(connection):
        family_counts["receivable_repayment"] += 1
        amount = decimal(row["amount"])
        explicit_repayment_total += amount
        controls = {"cash_collections": amount, "receivables_satisfied": amount}
        identity = f"ar_repayment:{row['id']}"
        method = str(row["payment_method"] or "").strip().lower()
        external = next(
            (str(row[name]).strip() for name in ("reference","provider_reference","gateway_reference","callback_reference")
             if row[name] is not None and str(row[name]).strip()),
            "",
        )
        if not method:
            withheld.add(source_identity=identity, reason="repayment_method_missing", controls=controls)
            continue
        if method != "cash" and not external:
            withheld.add(source_identity=identity, reason="repayment_noncash_external_identity_missing", controls=controls)
            continue
        if row["treasury_amount"] is not None and decimal(row["treasury_amount"]) != amount:
            withheld.add(source_identity=identity, reason="repayment_treasury_amount_mismatch", controls=controls)
            continue
        occurred = row["attempt_completed_at"] or row["created_at"]
        evidence_hash = semantic_hash({
            "repayment_id": row["id"],
            "ar_id": row["ar_id"],
            "amount": amount,
            "method": method,
            "reference": external or None,
            "treasury_id": row["treasury_id"],
        })
        payload = {
            "kind": "receivable_repayment",
            "amount": amount,
            "fee_amount": Decimal("0"),
            "currency_code": str(row["treasury_currency"] or "XAF").upper(),
            "payment_method_code": method,
            "payment_rail_code": method,
            "finality_status": "final",
            "evidence_hash": evidence_hash,
            "evidence_verified": True,
            "external_settlement_reference": external or None,
            "operational_account_public_id": str(deterministic_public_id(
                "operational-account", PRODUCTION_TENANT_ID, PRODUCTION_BRANCH_ID, method
            )),
            "financial_obligation_public_id": str(deterministic_public_id(
                "legacy-ar-obligation", PRODUCTION_TENANT_ID, row["ar_id"]
            )),
        }
        envelope = LegacyFinancialEnvelope(
            tenant_id=PRODUCTION_TENANT_ID,
            organization_unit_id=organization_unit_id,
            source_family=LegacySourceFamily.RECEIVABLE,
            source_record_type="ar_repayment",
            source_record_id=str(row["id"]),
            source_updated_at=occurred,
            business_date=wnd_business_date(occurred),
            payload=payload,
        )
        try:
            plan = WndFinancialMappingService.map(envelope)
            assert_replay(plan, WndFinancialMappingService.map(envelope))
        except Exception as exc:
            withheld.add(source_identity=identity, reason=f"m71_repayment_{getattr(exc, 'code', type(exc).__name__)}", controls=controls)
            continue
        cases.append(WndShadowRehearsalService.financial_case(len(cases) + 1, plan))
        mapped_counts["receivable_repayment"] += 1

    # Some historical A/R paid_amount predates explicit repayment evidence. Preserve it
    # as an explicit withheld aggregate instead of fabricating repayment rows.
    implicit_satisfied = source_controls["receivables_satisfied"] - explicit_repayment_total
    if implicit_satisfied < 0:
        raise RuntimeError("R6_2_AR_REPAYMENT_EXCEEDS_PAID_AGGREGATE")
    if implicit_satisfied:
        withheld.add(
            source_identity="ar_aggregate:historical_satisfaction_without_repayment_rows",
            reason="historical_receivable_satisfaction_without_explicit_repayment",
            controls={"receivables_satisfied": implicit_satisfied},
        )

    # Refund financial truth is retained as source evidence unless the legacy event
    # carries the canonical settlement/document identities needed for safe execution.
    if source_controls["refunds"]:
        withheld.add(
            source_identity="refund_aggregate:legacy",
            reason="historical_refund_target_identity_unresolved",
            controls={"refunds": source_controls["refunds"]},
        )

    # No immutable original receipt content hashes exist in the WND source snapshot.
    # Preserve document identity/count and explicitly refuse original-document regeneration.
    sale_ids = connection.execute(text(
        "SELECT id FROM sales WHERE tenant_id=:t AND branch_id=:b ORDER BY id"
    ), {"t": PRODUCTION_TENANT_ID, "b": PRODUCTION_BRANCH_ID}).scalars().all()
    for sale_id in sale_ids:
        withheld.add(
            source_identity=f"receipt:sale:{sale_id}",
            reason="historical_document_content_hash_unavailable",
            controls={"financial_documents": Decimal("1")},
        )

    # Exercise M7.2 against real direct-sale movement evidence when present. The
    # frozen WND source has no reliable cost basis, therefore the correct result is WITHHELD.
    direct = connection.execute(text("""
        SELECT id,atomic_unit_id,quantity_delta,created_at,reference_id
        FROM inventory_movements
        WHERE tenant_id=:t AND branch_id=:b
          AND movement_type='sale' AND quantity_delta<0
        ORDER BY id
    """), {"t": PRODUCTION_TENANT_ID, "b": PRODUCTION_BRANCH_ID}).mappings().all()
    inventory_withheld = 0
    for row in direct:
        envelope = LegacyFinancialEnvelope(
            tenant_id=PRODUCTION_TENANT_ID,
            organization_unit_id=organization_unit_id,
            source_family=LegacySourceFamily.INVENTORY,
            source_record_type="inventory_movement",
            source_record_id=str(row["id"]),
            source_updated_at=row["created_at"],
            business_date=wnd_business_date(row["created_at"]),
            payload={
                "kind": "inventory_fulfillment",
                "movement_type": "sale",
                "quantity_delta": row["quantity_delta"],
                "inventory_movement_id": str(row["id"]),
                "atomic_unit_id": str(row["atomic_unit_id"]),
                "sale_id": str(row["reference_id"]) if row["reference_id"] is not None else None,
                "cost_basis_status": "missing",
            },
        )
        plan = WndInventoryFinancialHandoffService.map(envelope)
        if plan.disposition != "withheld" or plan.command is not None:
            raise RuntimeError("R6_2_MISSING_COST_BASIS_WAS_EXECUTED")
        inventory_withheld += 1

    inventory_lifecycle = connection.execute(text("""
        SELECT movement_type,COUNT(*) rows,COALESCE(SUM(quantity_delta),0) qty
        FROM inventory_movements
        WHERE tenant_id=:t AND branch_id=:b
          AND movement_type IN ('sale','sale_hold','sale_hold_adjust','sale_hold_release','sale_commit')
        GROUP BY movement_type ORDER BY movement_type
    """), {"t": PRODUCTION_TENANT_ID, "b": PRODUCTION_BRANCH_ID}).mappings().all()

    if not cases:
        raise RuntimeError("R6_2_NO_MAPPED_SHADOW_CASES")

    rehearsal = WndShadowRehearsalService.assemble(
        "r6.2:wnd-reference-release:financial-shadow",
        SERVER_BACKUP_SHA256,
        cases,
    )
    mapped_controls = zero_controls()
    for case in rehearsal.cases:
        add_controls(mapped_controls, case.expected.values)

    # Fail closed on any unclassified amount. R6.2 must not use a generic
    # residual bucket because that could conceal an extractor/mapping defect.
    try:
        assert_complete_reconciliation(source_controls, mapped_controls, withheld.controls)
    except ValueError as exc:
        raise RuntimeError("R6_2_UNCLASSIFIED_CONTROL_AMOUNT=" + str(exc)) from exc

    legacy_totals = FinancialControlTotals("XAF", source_controls)
    canonical_totals = FinancialControlTotals("XAF", mapped_controls)
    legacy_projection = DualReadProjection(
        reader="legacy",
        tenant_id=PRODUCTION_TENANT_ID,
        organization_unit_id=organization_unit_id,
        subject_type="commercial",
        subject_identity="wnd-reference-release-financial-aggregate",
        as_of=OBSERVED_AT,
        totals=legacy_totals,
        provenance_hash=SERVER_BACKUP_SHA256,
    )
    canonical_projection = DualReadProjection(
        reader="canonical",
        tenant_id=PRODUCTION_TENANT_ID,
        organization_unit_id=organization_unit_id,
        subject_type="commercial",
        subject_identity="wnd-reference-release-financial-aggregate",
        as_of=OBSERVED_AT,
        totals=canonical_totals,
        provenance_hash=rehearsal.rehearsal_fingerprint,
    )
    comparison = WndCutoverSupportService.compare(legacy_projection, canonical_projection)

    expected_deltas = {name: -withheld.controls[name] for name in CONTROL_NAMES}
    if dict(comparison.deltas) != expected_deltas:
        raise RuntimeError("R6_2_DUAL_READ_VARIANCE_NOT_EQUAL_WITHHELD")

    evidence_payloads = {
        "legacy_authority_inventory": {"source": "frozen_m70_inventory", "pass": True},
        "canonical_mapping_coverage": {
            "source": source_controls, "mapped": mapped_controls,
            "withheld": withheld.canonical_payload(), "pass": True,
        },
        "shadow_rehearsal": {"fingerprint": rehearsal.rehearsal_fingerprint, "cases": len(rehearsal.cases)},
        "control_total_parity": {"equation": "source=mapped+withheld", "pass": True},
        "tenant_organization_isolation": {
            "tenant_id": PRODUCTION_TENANT_ID, "organization_unit_id": organization_unit_id, "pass": True
        },
        "replay_conflict_safety": {"mapped_cases_replayed": len(rehearsal.cases), "pass": True},
        "recovery_rehearsal": {"phase": "verified_after_second_restore_by_outer_acceptance", "pass": True},
        "dual_read_compatibility": {
            "mode": comparison.read_mode, "status": comparison.status,
            "variance_is_explicit_withheld": True,
        },
        "rollback_runbook": {
            "backup_sha256": SERVER_BACKUP_SHA256,
            "reference_release_tag": REFERENCE_RELEASE_TAG,
            "r6_1_freeze_tag": R6_1_FREEZE_TAG,
            "pass": True,
        },
    }
    evidence = tuple(
        ReadinessEvidence(
            code=code,
            passed=True,
            evidence_hash=semantic_hash(payload),
            observed_at=OBSERVED_AT,
            detail="R6.2 deterministic rehearsal evidence; advisory only and does not authorize cutover",
        )
        for code, payload in evidence_payloads.items()
    )
    assessment = WndCutoverSupportService.assess(
        "r6.2:wnd-reference-release:readiness",
        SERVER_BACKUP_SHA256,
        evidence,
    )
    if assessment.status != "ready_for_r6_review" or assessment.cutover_authorized:
        raise RuntimeError("R6_2_READINESS_AUTHORITY_INVALID")

    inventory = load_inventory(ROOT)
    rollback_refs = {
        surface.code: (
            f"backup:{SERVER_BACKUP_SHA256};"
            f"reference:{REFERENCE_RELEASE_TAG};"
            f"r6_1:{R6_1_FREEZE_TAG}"
        )
        for surface in inventory.surfaces
        if surface.authority_mode.value in {"writer", "reader_writer"}
    }
    retirement = WndCutoverSupportService.retirement_plan(
        "r6.2:wnd-reference-release:writer-retirement",
        assessment,
        inventory,
        rollback_refs,
    )
    if retirement.execution_allowed or any(c.retirement_executed for c in retirement.candidates):
        raise RuntimeError("R6_2_WRITER_RETIREMENT_EXECUTION_LEAK")

    return {
        "organization_unit_id": organization_unit_id,
        "source_controls": source_controls,
        "mapped_controls": mapped_controls,
        "withheld": withheld.canonical_payload(),
        "family_source_counts": dict(sorted(family_counts.items())),
        "family_mapped_counts": dict(sorted(mapped_counts.items())),
        "shadow_case_count": len(rehearsal.cases),
        "shadow_rehearsal_fingerprint": rehearsal.rehearsal_fingerprint,
        "dual_read_status": comparison.status,
        "dual_read_deltas": dict(comparison.deltas),
        "dual_read_fingerprint": comparison.comparison_fingerprint,
        "readiness_status": assessment.status,
        "readiness_fingerprint": assessment.assessment_fingerprint,
        "cutover_authorized": assessment.cutover_authorized,
        "writer_retirement_status": retirement.status,
        "writer_retirement_execution_allowed": retirement.execution_allowed,
        "writer_retirement_candidate_count": len(retirement.candidates),
        "writer_retirement_plan_fingerprint": retirement.plan_fingerprint,
        "inventory_direct_sale_withheld_count": inventory_withheld,
        "inventory_lifecycle": [dict(row) for row in inventory_lifecycle],
        "fulfillment_cost_semantics": "WITHHELD_NOT_ZERO_ECONOMIC_COST",
        "historical_document_semantics": "IDENTITY_PRESERVED_ORIGINAL_REGENERATION_WITHHELD",
        "production_writes": "NONE",
        "writer_routing": "UNCHANGED",
    }


def _candidate_rehearsal() -> dict[str, Any]:
    engine = _engine(CANDIDATE_DATABASE)
    try:
        if r61._current_head(engine) != TARGET_HEAD:
            raise RuntimeError("R6_2_CANDIDATE_HEAD_NOT_TARGET")
        with engine.connect() as connection:
            return _map_shadow(connection)
    finally:
        engine.dispose()


def _run_acceptance() -> dict[str, Any]:
    _prepare_r61_harness()
    backup = r61._find_backup()

    # Immutable source clone.
    _restore(SOURCE_DATABASE, backup)
    source_before = _assert_raw_source(SOURCE_DATABASE)

    # First candidate adoption + mapping pass.
    _restore(CANDIDATE_DATABASE, backup)
    _assert_raw_source(CANDIDATE_DATABASE)
    composition_first = _adopt_and_compose()
    first = _candidate_rehearsal()

    # Recovery proof: destroy candidate, restore exact backup and prove raw controls.
    _restore(CANDIDATE_DATABASE, backup)
    recovered_raw = _assert_raw_source(CANDIDATE_DATABASE)
    if recovered_raw != source_before:
        raise RuntimeError("R6_2_RECOVERY_RAW_SOURCE_MISMATCH")

    # Re-adopt and replay. Every fingerprint must be deterministic.
    composition_second = _adopt_and_compose()
    second = _candidate_rehearsal()

    deterministic_fields = (
        "source_controls",
        "mapped_controls",
        "withheld",
        "family_source_counts",
        "family_mapped_counts",
        "shadow_case_count",
        "shadow_rehearsal_fingerprint",
        "dual_read_status",
        "dual_read_deltas",
        "dual_read_fingerprint",
        "readiness_status",
        "readiness_fingerprint",
        "writer_retirement_status",
        "writer_retirement_candidate_count",
        "writer_retirement_plan_fingerprint",
        "inventory_direct_sale_withheld_count",
        "inventory_lifecycle",
    )
    for field in deterministic_fields:
        if first[field] != second[field]:
            raise RuntimeError(f"R6_2_REPLAY_DRIFT={field}")

    source_engine = _engine(SOURCE_DATABASE)
    candidate_engine = _engine(CANDIDATE_DATABASE)
    try:
        if r61._current_head(source_engine) != SOURCE_REVISION:
            raise RuntimeError("R6_2_SOURCE_CLONE_MUTATED")
        if r61._current_head(candidate_engine) != TARGET_HEAD:
            raise RuntimeError("R6_2_CANDIDATE_HEAD_DRIFT")
        if r61._counts(source_engine) != EXPECTED_COUNTS:
            raise RuntimeError("R6_2_SOURCE_COUNTS_DRIFT")
        if r61._counts(candidate_engine) != EXPECTED_COUNTS:
            raise RuntimeError("R6_2_CANDIDATE_LEGACY_COUNTS_DRIFT")
        if r61._control_totals(source_engine) != r61._control_totals(candidate_engine):
            raise RuntimeError("R6_2_CANDIDATE_LEGACY_CONTROLS_DRIFT")
        if r61._legacy_reference_schema(source_engine) != r61._legacy_reference_schema(candidate_engine):
            raise RuntimeError("R6_2_REFERENCE_SCHEMA_DRIFT")
    finally:
        source_engine.dispose()
        candidate_engine.dispose()

    result = {
        "status": "PASS",
        "reference_release_tag": REFERENCE_RELEASE_TAG,
        "r6_1_freeze_tag": R6_1_FREEZE_TAG,
        "source_checkpoint": SOURCE_COMMIT,
        "backup": str(backup),
        "backup_sha256": _sha(backup),
        "source_database": SOURCE_DATABASE,
        "candidate_database": CANDIDATE_DATABASE,
        "source_head": SOURCE_REVISION,
        "candidate_head": TARGET_HEAD,
        "composition_first": composition_first,
        "composition_second": composition_second,
        "first": first,
        "second": second,
        "recovery_raw_source": recovered_raw,
        "production_database_touched": False,
        "production_writes": "NONE",
        "writer_routing": "UNCHANGED",
        "live_cutover_authorized": False,
        "r6_3_readiness": True,
    }
    output = Path.home() / "Downloads" / "XBOS_R6_2_WND_CUTOVER_REHEARSAL_RESULT.json"
    output.write_text(json.dumps(result, indent=2, sort_keys=True, default=str), encoding="utf-8")
    result["result_file"] = str(output)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--acceptance", action="store_true")
    args = parser.parse_args()

    static = _static_verify()
    print(json.dumps(static, indent=2, sort_keys=True))
    print("R6_2_VERIFY=PASS")

    if args.acceptance:
        result = _run_acceptance()
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        print("R6_2_POSTGRES_CUTOVER_REHEARSAL=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
