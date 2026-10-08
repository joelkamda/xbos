"""G02-C3-R1 static envelope verification plus disposable PostgreSQL acceptance."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import fields
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.domain.finance.payment_intent_contract import PaymentCommandIdempotencyConflict
from core.persistence.database_config import resolve_database_url
from core.platform.structure import ProvisionTenant, SQLStructuralRepository, StructuralAuthority
from restaurant.c3 import (
    CustomerSafeCheckoutPaymentRequestService,
    NeutralFinancePaymentRequestAdapter,
    TrustedCheckoutContext,
)
from restaurant.c3.contracts import CustomerSafePaymentRequestProjection
from restaurant.r1.contracts import (
    ObligationHandoff,
    ObligationHandoffLine,
    OrderLine,
    OrderStatus,
    RestaurantOrder,
    TargetType,
)

BASE = "0e5185083ede8f92f9ef6a5181bb03d0eaf20fa9"
BASE_TREE = "bb003952ed1d833596cab017dcdc3ad2b3ed937e"
MIGRATION_HEAD = "r1_restaurant_order_line_lifecycle_046"
TEST_DB = "xbos_g02_c3_r1_test"
AUTHORIZED = (
    "restaurant/c3/__init__.py",
    "restaurant/c3/contracts.py",
    "restaurant/c3/service.py",
    "restaurant/c3/adapters.py",
    "contracts/restaurant/v1/c3_customer_safe_checkout_payment_request.json",
    "contracts/restaurant/v1/c3_release_manifest.json",
    "scripts/verify_c3_customer_safe_checkout_payment_request.py",
    "tests/contracts/test_c3_customer_safe_checkout_payment_request.py",
)
PROJECTION_FIELDS = (
    "payment_request_ref",
    "order_ref",
    "merchant_reference",
    "correlation_ref",
    "canonical_amount",
    "currency",
    "permitted_methods",
    "policy_ref",
    "expires_at",
    "payment_request_state",
    "wallet_handoff_context",
    "safe_next_action",
    "receipt_ref",
)


def _git(*args: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()


def _changed_paths() -> tuple[str, ...]:
    tracked = {line.strip().replace("\\", "/") for line in _git("diff", "--name-only", BASE, "--").splitlines() if line.strip()}
    untracked = {line.strip().replace("\\", "/") for line in _git("ls-files", "--others", "--exclude-standard").splitlines() if line.strip()}
    return tuple(sorted(tracked | untracked))


def verify_static() -> None:
    if _git("rev-parse", f"{BASE}^{{tree}}") != BASE_TREE:
        raise RuntimeError("C3_BASE_TREE_DRIFT")
    changed = _changed_paths()
    if changed != tuple(sorted(AUTHORIZED)):
        raise RuntimeError(f"C3_CHANGED_PATH_ENVELOPE={changed}")
    if any(path.startswith(("restaurant/r1/", "restaurant/r2/", "restaurant/r5/", "core/domain/finance/", "core/platform/", "core/middleware/")) for path in changed):
        raise RuntimeError("C3_FROZEN_PRIMITIVE_CHANGED")
    if any(path.startswith("alembic_neutral/") for path in changed):
        raise RuntimeError("C3_MIGRATION_CHANGED")

    cfg = Config(str(ROOT / "alembic_neutral.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic_neutral"))
    heads = tuple(ScriptDirectory.from_config(cfg).get_heads())
    if heads != (MIGRATION_HEAD,):
        raise RuntimeError(f"C3_MIGRATION_HEAD={heads}")

    contract = json.loads((ROOT / "contracts/restaurant/v1/c3_customer_safe_checkout_payment_request.json").read_text(encoding="utf-8-sig"))
    manifest = json.loads((ROOT / "contracts/restaurant/v1/c3_release_manifest.json").read_text(encoding="utf-8-sig"))
    actual_projection = tuple(field.name for field in fields(CustomerSafePaymentRequestProjection))
    if actual_projection != PROJECTION_FIELDS or tuple(contract["projection_fields"]) != PROJECTION_FIELDS:
        raise RuntimeError("C3_PROJECTION_CONTRACT_MISMATCH")
    if tuple(manifest["authorized_paths"]) != AUTHORIZED or manifest["authorized_path_count"] != 8:
        raise RuntimeError("C3_RELEASE_MANIFEST_PATH_MISMATCH")
    if contract["migration"] or contract["schema_change"] or manifest["migration"] or manifest["schema_change"]:
        raise RuntimeError("C3_SCHEMA_OR_MIGRATION_EXPANSION")
    if contract["public_id"]["seed"] != "xbos:restaurant:c3:payment-request:{tenant_id}:{organization_unit_id}:{order_public_id}:v{row_version}":
        raise RuntimeError("C3_PUBLIC_ID_MODEL_DRIFT")
    if contract["idempotency"]["key"] != "order:{order_public_id}:v{row_version}":
        raise RuntimeError("C3_IDEMPOTENCY_MODEL_DRIFT")

    production = "\n".join((ROOT / path).read_text(encoding="utf-8-sig").lower() for path in AUTHORIZED[:4])
    forbidden = (
        "core.integrations.xafpay",
        "xafpay_core",
        "httpx",
        "requests.",
        "socket.",
        "create_intent(",
        "payment_settlement",
        "insert into",
        "sqlalchemy",
    )
    hits = [token for token in forbidden if token in production]
    if hits:
        raise RuntimeError(f"C3_FORBIDDEN_PRODUCTION_TOKENS={hits}")
    if "transactionalpaymentintentengine.create_request" not in production:
        raise RuntimeError("C3_NEUTRAL_FINANCE_CREATE_REQUEST_MISSING")
    if "transactionalpaymentintentengine.create_intent" in production:
        raise RuntimeError("C3_PAYMENT_INTENT_CREATION_FORBIDDEN")

    print("C3_STATIC_CHANGED_PATH_COUNT=8")
    print("C3_STATIC_UNKNOWN_CHANGED_PATH_COUNT=0")
    print(f"C3_MIGRATION_HEAD={MIGRATION_HEAD}")
    print("C3_SCHEMA_CHANGE=NO")
    print("C3_MIGRATION=NO")
    print("C3_CONTRACT_PROJECTION=PASS")
    print("C3_RELEASE_MANIFEST=PASS")
    print("C3_STATIC_FORBIDDEN_INTEGRATIONS=PASS")


class _Restaurant:
    def __init__(self, tenant_id: int):
        self.tenant_id = tenant_id
        self.order_id = UUID("c3111111-1111-1111-1111-111111111111")
        target = UUID("c3222222-2222-2222-2222-222222222222")
        price = UUID("c3333333-3333-3333-3333-333333333333")
        line_id = UUID("c3444444-4444-4444-4444-444444444444")
        self.order_value = RestaurantOrder(
            public_id=self.order_id,
            tenant_id=tenant_id,
            order_code="C3-DB-SMOKE",
            mode_code="takeaway",
            source_channel_code="verification",
            status=OrderStatus.SUBMITTED,
            opened_at=datetime(2026, 9, 22, 9, 0, tzinfo=timezone.utc),
            submitted_at=datetime(2026, 9, 22, 9, 5, tzinfo=timezone.utc),
            party_public_id=None,
            lines=(OrderLine(line_id, tenant_id, self.order_id, TargetType.ATOMIC_UNIT, target, price, Decimal("2"), Decimal("1500"), "XAF"),),
            row_version=7,
        )
        self.handoff_value = ObligationHandoff(
            tenant_id,
            "restaurant_order",
            self.order_id,
            "takeaway",
            None,
            "XAF",
            (ObligationHandoffLine(line_id, TargetType.ATOMIC_UNIT, target, Decimal("2"), Decimal("1500"), "XAF", Decimal("3000")),),
            Decimal("3000"),
        )

    def order(self, tenant_id, order_public_id):
        if tenant_id != self.tenant_id or order_public_id != self.order_id:
            raise RuntimeError("C3_DB_ORDER_SCOPE")
        return self.order_value

    def obligation_handoff(self, tenant_id, order_public_id):
        if tenant_id != self.tenant_id or order_public_id != self.order_id:
            raise RuntimeError("C3_DB_HANDOFF_SCOPE")
        return self.handoff_value


class _Structure:
    def __init__(self, organization_id: int):
        self.organization_id = organization_id

    def resolve(self, *, tenant_id, branch_id):
        if branch_id != 1:
            raise RuntimeError("C3_DB_BRANCH_SCOPE")
        return SimpleNamespace(organization_unit=SimpleNamespace(id=self.organization_id))


class _Policy:
    def resolve(self, *, tenant_id, as_of):
        return SimpleNamespace(value={"settlement_methods": ["cash", "mtn", "orange"]}, version=1)


def _database_url() -> str:
    selected = os.environ.get("C3_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if selected:
        return selected
    env_file = os.environ.get("C3_ENV_FILE")
    if env_file:
        return resolve_database_url(env_file=Path(env_file))
    raise RuntimeError("C3_DATABASE_URL_OR_ENV_FILE_REQUIRED")


def _engine(url, *, isolation_level=None):
    return create_engine(url, isolation_level=isolation_level, pool_pre_ping=True)


def verify_database() -> None:
    base_url = make_url(_database_url())
    admin_url = base_url.set(database="postgres")
    test_url = base_url.set(database=TEST_DB)
    admin = _engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            exists = connection.execute(text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": TEST_DB}).scalar_one_or_none()
            if exists:
                raise RuntimeError("C3_DISPOSABLE_DATABASE_PREEXISTS")
            connection.exec_driver_sql(f'CREATE DATABASE "{TEST_DB}"')
    finally:
        admin.dispose()

    engine = None
    old_database_url = os.environ.get("DATABASE_URL")
    try:
        os.environ["DATABASE_URL"] = test_url.render_as_string(hide_password=False)
        cfg = Config(str(ROOT / "alembic_neutral.ini"))
        cfg.set_main_option("script_location", str(ROOT / "alembic_neutral"))
        command.upgrade(cfg, "head")

        engine = _engine(test_url)
        with Session(engine) as session, session.begin():
            context = StructuralAuthority(SQLStructuralRepository(session)).provision(
                ProvisionTenant(
                    command_key="c3-r1-db-provision",
                    tenant_code="c3-r1-test",
                    tenant_name="C3 R1 Test",
                    country_code="CM",
                    currency="XAF",
                    locale="fr-CM",
                    timezone="Africa/Douala",
                    legal_entity_code="C3-CM",
                    legal_entity_name="C3 Test Cameroon",
                    root_organization_code="C3",
                    root_organization_name="C3 Test",
                    primary_location_code="C3-LOC",
                    primary_location_name="C3 Test Location",
                )
            )
            session.execute(text("INSERT INTO currency_assets(code,asset_kind,display_name,minor_unit_scale,maximum_storage_scale,active) VALUES('XAF','fiat','Central African CFA franc',0,8,true) ON CONFLICT(code) DO NOTHING"))
            tenant_id = context.tenant.id
            organization_id = context.organization_unit.id
            restaurant = _Restaurant(tenant_id)
            service = CustomerSafeCheckoutPaymentRequestService(
                restaurant=restaurant,
                structure=_Structure(organization_id),
                payment_policy=_Policy(),
                finance=NeutralFinancePaymentRequestAdapter(),
            )
            trusted = TrustedCheckoutContext(tenant_id, 1, None)
            first = service.create_payment_request(session, context=trusted, order_public_id=restaurant.order_id)
            second = service.create_payment_request(session, context=trusted, order_public_id=restaurant.order_id)
            if first.payment_request_ref != second.payment_request_ref or first.payment_request_state != "open":
                raise RuntimeError("C3_DB_REPLAY_PROJECTION_FAILED")
            request_count = session.execute(text("SELECT count(*) FROM canonical_payment_requests")).scalar_one()
            intent_count = session.execute(text("SELECT count(*) FROM canonical_payment_intents")).scalar_one()
            settlement_count = session.execute(text("SELECT count(*) FROM payment_settlements")).scalar_one()
            if (request_count, intent_count, settlement_count) != (1, 0, 0):
                raise RuntimeError(f"C3_DB_FINANCIAL_BOUNDARY={(request_count,intent_count,settlement_count)}")
            row = session.execute(text("SELECT idempotency_key,source_component,source_record_id,request_state,metadata FROM canonical_payment_requests")).mappings().one()
            if row["idempotency_key"] != f"order:{restaurant.order_id}:v7" or row["source_component"] != "restaurant.c3" or row["request_state"] != "open":
                raise RuntimeError("C3_DB_PAYMENT_REQUEST_IDENTITY_FAILED")
            if row["metadata"].get("order_row_version") != 7:
                raise RuntimeError("C3_DB_ROW_VERSION_METADATA_FAILED")
        print("C3_DISPOSABLE_POSTGRES=PASS")
        print("C3_DB_PAYMENT_REQUEST_COUNT=1")
        print("C3_DB_PAYMENT_INTENT_COUNT=0")
        print("C3_DB_SETTLEMENT_COUNT=0")
    finally:
        if engine is not None:
            engine.dispose()
        if old_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = old_database_url
        cleanup = _engine(admin_url, isolation_level="AUTOCOMMIT")
        try:
            with cleanup.connect() as connection:
                connection.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:name AND pid<>pg_backend_pid()"), {"name": TEST_DB})
                connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{TEST_DB}"')
        finally:
            cleanup.dispose()
        print("C3_DISPOSABLE_POSTGRES_CLEANUP=PASS")


def main() -> int:
    verify_static()
    if "--database" in sys.argv:
        verify_database()
    print("C3_VERIFY=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
