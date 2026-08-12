"""Disposable PostgreSQL verification for M8.2 external and infrastructure failures."""
from __future__ import annotations

import argparse
import hashlib
import hmac
import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.domain.finance.external_failure_resilience_contract import ProviderObservation
from core.domain.finance.external_failure_resilience_service import (
    classify_provider_observation,
    validate_existing_failure_authorities,
)
from core.domain.finance.m2_acceptance import validate_release_manifest as m2_manifest
from core.domain.finance.m3_acceptance import validate_release_manifest as m3_manifest
from core.domain.finance.m5_acceptance import validate_release_manifest as m5_manifest
from core.domain.finance.m6_acceptance import EXPECTED_HEAD, validate_frozen_m4_manifest, validate_release_manifest as m6_manifest
from core.domain.finance.m7_acceptance import validate_release_manifest as m7_manifest
from core.domain.finance.payment_attempt_engine import TransactionalPaymentAttemptEngine
from core.domain.finance.payment_intent_engine import TransactionalPaymentIntentEngine
from core.domain.finance.payment_settlement_engine import TransactionalPaymentSettlementEngine
from core.domain.finance.payment_tender_engine import TransactionalPaymentTenderEngine
from core.domain.finance.transactional_event_engine import TransactionalCanonicalFinancialEventEngine
from core.integrations.xafpay.contract import ProcessXafPayCallbackCommand, RecordXafPayInitiationCommand, XafPayIntegrationError
from core.integrations.xafpay.orchestration_service import XafPayOrchestrationService
from database import engine as application_engine
from scripts.verify_m21_canonical_event_engine import _event_command, _install_fixtures
from scripts.verify_m45_xafpay_orchestration import (
    BASE, TENANT_UUID, _FakeTransport, _attempt, _callback_command, _intent, _seed, _tender,
)

DEVELOPMENT_DATABASE_NAME = "xbos_track_b_dev"
TEST_DATABASE_NAME = "xbos_track_b_m82_failure_test"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
EMPTY_TABLES = (
    "idempotency_records", "financial_events", "outbox_messages", "journal_entries", "journal_lines",
    "financial_obligations", "value_sources", "payment_allocations", "allocation_reversals",
    "canonical_payment_attempts", "provider_callback_events", "payment_settlements",
)


def _url():
    value = make_url(application_engine.url)
    if value.host not in LOCAL_HOSTS:
        raise RuntimeError(f"refusing non-local PostgreSQL host={value.host!r}")
    return value


def _engine(name, isolation_level=None):
    return create_engine(_url().set(database=name), isolation_level=isolation_level, pool_pre_ping=True)


def _exists(name):
    selected = _engine("postgres", "AUTOCOMMIT")
    try:
        with selected.connect() as connection:
            return bool(connection.execute(text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": name}).scalar())
    finally:
        selected.dispose()


def _create():
    if _exists(TEST_DATABASE_NAME):
        raise RuntimeError(f"disposable database already exists={TEST_DATABASE_NAME}")
    application_engine.dispose()
    selected = _engine("postgres", "AUTOCOMMIT")
    try:
        with selected.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{TEST_DATABASE_NAME}" TEMPLATE "{DEVELOPMENT_DATABASE_NAME}"')
    finally:
        selected.dispose()


def _drop(name):
    if name != TEST_DATABASE_NAME:
        raise RuntimeError(f"unsafe disposable database target={name}")
    selected = _engine("postgres", "AUTOCOMMIT")
    try:
        with selected.connect() as connection:
            connection.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:name AND pid<>pg_backend_pid()"), {"name": name})
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}"')
    finally:
        selected.dispose()


def _development():
    if _url().database != DEVELOPMENT_DATABASE_NAME:
        raise RuntimeError(f"development database must be={DEVELOPMENT_DATABASE_NAME}")
    releases = (
        m2_manifest(ROOT).checked_components, m3_manifest(ROOT).checked_components,
        validate_frozen_m4_manifest(ROOT), m5_manifest(ROOT), m6_manifest(ROOT).checked_components,
        m7_manifest(ROOT).checked_components,
    )
    validate_existing_failure_authorities(ROOT)
    for observation in (
        ProviderObservation.TIMEOUT, ProviderObservation.PROVIDER_UNAVAILABLE,
        ProviderObservation.RETRYABLE_FAILURE, ProviderObservation.UNKNOWN,
    ):
        disposition = classify_provider_observation(observation)
        if disposition.canonical_state != "uncertain" or not disposition.retryable or disposition.settlement_allowed:
            raise RuntimeError(f"unsafe provider failure disposition={observation.value}")
    if classify_provider_observation(ProviderObservation.TERMINAL_FAILURE).canonical_state != "failed":
        raise RuntimeError("terminal provider failure classification changed")
    if not classify_provider_observation(ProviderObservation.AUTHORITATIVE_SUCCESS).settlement_allowed:
        raise RuntimeError("authoritative success classification changed")
    with application_engine.connect() as connection:
        database = connection.execute(text("SELECT current_database()" )).scalar_one()
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        if database != DEVELOPMENT_DATABASE_NAME or revision != EXPECTED_HEAD:
            raise RuntimeError(f"unexpected development authority={database}:{revision}")
        tables = set(connection.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'")).scalars())
        for table in EMPTY_TABLES:
            if table in tables and connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one():
                raise RuntimeError(f"development financial table not empty={table}")
    print(f"database={database}")
    print(f"revision={revision}")
    print("release_manifests=" + ",".join(f"m{index + 2}:{count}" for index, count in enumerate(releases)))
    print("m82_external_failure_development=PASS manifests=PASS authority_sources=PASS development_empty=PASS")


class _OutageTransport:
    def __init__(self, error):
        self.error = error
        self.calls = 0

    def post(self, *, path, headers, body):
        self.calls += 1
        raise self.error


def _expect_transport_failure(request, observation, error):
    transport = _OutageTransport(error)
    try:
        XafPayOrchestrationService.initiate(None, request, api_key="not-persisted", transport=transport)
    except type(error):
        pass
    else:
        raise RuntimeError(f"provider failure did not propagate={observation.value}")
    disposition = classify_provider_observation(observation)
    if transport.calls != 1 or disposition.canonical_state != "uncertain" or not disposition.retryable or disposition.settlement_allowed:
        raise RuntimeError(f"provider uncertainty was misclassified={observation.value}")


def _counts(session):
    names = ("provider_callback_events", "payment_settlements", "payment_settlement_transitions")
    return {name: session.execute(text(f"SELECT count(*) FROM {name}")).scalar_one() for name in names}


def _exercise(selected):
    _install_fixtures(selected)

    # Canonical event, idempotency, and outbox must roll back together, then retry once.
    event = _event_command(
        public_id=UUID("82000000-0000-0000-0000-000000000001"),
        idempotency_key="m82:event:rollback", correlation_id=UUID("82000000-0000-0000-0000-000000000099"),
        metadata={"failure_probe": "before_commit"}, actor_service="m82-verifier",
    )
    with Session(selected) as session:
        transaction = session.begin()
        TransactionalCanonicalFinancialEventEngine.emit(session, event)
        transaction.rollback()
    with selected.connect() as connection:
        for table in ("financial_events", "outbox_messages"):
            if connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one():
                raise RuntimeError(f"rolled-back event left residue={table}")
        if connection.execute(text("SELECT count(*) FROM idempotency_records WHERE idempotency_key='m82:event:rollback'")).scalar_one():
            raise RuntimeError("rolled-back event left idempotency residue")
    with Session(selected) as session, session.begin():
        first = TransactionalCanonicalFinancialEventEngine.emit(session, event)
        replay = TransactionalCanonicalFinancialEventEngine.emit(session, event)
        if replay.event.id != first.event.id or not replay.replayed:
            raise RuntimeError("event retry/replay did not converge")

    # Build one canonical attempt. Transport failures occur outside recording authority.
    with Session(selected, expire_on_commit=False) as session, session.begin():
        tenant, org, provider, operational = _seed(session)
        intent = _intent(tenant, org)
        tender = _tender(tenant, org, intent)
        attempt = _attempt(tenant, org, intent, tender, provider)
        TransactionalPaymentIntentEngine.create_intent(session, intent)
        TransactionalPaymentTenderEngine.create(session, tender)
        TransactionalPaymentAttemptEngine.create(session, attempt)
        initiation = XafPayOrchestrationService.prepare_initiation(
            session, tenant_id=tenant, organization_unit_id=org,
            payment_attempt_public_id=attempt.public_id, customer_phone="+237670000000",
            return_url="https://merchant.test/paid", cancel_url="https://merchant.test/cancelled",
            idempotency_key="m82-initiation",
        )
        _expect_transport_failure(initiation, ProviderObservation.TIMEOUT, TimeoutError("provider timeout"))
        _expect_transport_failure(initiation, ProviderObservation.PROVIDER_UNAVAILABLE, ConnectionError("provider unavailable"))
        authority = XafPayOrchestrationService.repository.attempt_authority(session, tenant_id=tenant, public_id=attempt.public_id)
        if authority["attempt_state"] != "pending":
            raise RuntimeError("transport uncertainty fabricated an attempt transition")
        response = XafPayOrchestrationService.initiate(session, initiation, api_key="not-persisted", transport=_FakeTransport())
        XafPayOrchestrationService.record_initiation(
            session, RecordXafPayInitiationCommand(tenant, org, attempt.public_id, response, BASE.replace(minute=5), intent.business_date, 1, TENANT_UUID),
        )

    # Invalid signatures are immutable rejected evidence; valid malformed bodies write nothing.
    with Session(selected) as session, session.begin():
        rejected = XafPayOrchestrationService.process_callback(
            session, _callback_command(tenant, org, provider, operational, "m82-tampered", "failed", signature_secret="wrong-secret")
        )
        if rejected.processing_state != "rejected":
            raise RuntimeError("tampered callback was accepted")
        malformed = b"{not-json"
        headers = {
            "X-Xafpay-Event-Id": "m82-malformed",
            "X-Xafpay-Signature": hmac.new(b"m45-callback-secret", malformed, hashlib.sha256).hexdigest(),
        }
        command = ProcessXafPayCallbackCommand(
            tenant, org, provider, operational, malformed, headers, "m45-callback-secret",
            BASE, intent.business_date, 1, TENANT_UUID,
        )
        try:
            XafPayOrchestrationService.process_callback(session, command)
        except XafPayIntegrationError as exc:
            if exc.code != "invalid_callback_payload":
                raise
        else:
            raise RuntimeError("malformed signed callback was accepted")

    # Inject a dependent settlement failure after callback and attempt work; savepoint must erase all of it.
    success = _callback_command(tenant, org, provider, operational, "m82-success", "succeeded")
    with Session(selected) as session, session.begin():
        before = _counts(session)
        with patch.object(TransactionalPaymentSettlementEngine, "transition", side_effect=RuntimeError("injected database failure")):
            try:
                XafPayOrchestrationService.process_callback(session, success)
            except RuntimeError as exc:
                if str(exc) != "injected database failure":
                    raise
            else:
                raise RuntimeError("injected persistence failure was suppressed")
        if _counts(session) != before:
            raise RuntimeError("failed dependent persistence left callback or settlement residue")
        authority = XafPayOrchestrationService.repository.attempt_authority(session, tenant_id=tenant, public_id=attempt.public_id)
        if authority["attempt_state"] != "requires_action":
            raise RuntimeError("failed callback changed attempt state")

    # Authoritative retry settles exactly once; replay and late failure cannot duplicate/regress it.
    with Session(selected, expire_on_commit=False) as session, session.begin():
        accepted = XafPayOrchestrationService.process_callback(session, success)
        replay = XafPayOrchestrationService.process_callback(session, success)
        if accepted.settlement_public_id is None or not replay.replayed or replay.settlement_public_id != accepted.settlement_public_id:
            raise RuntimeError("authoritative retry/replay did not converge")
        conflict = _callback_command(tenant, org, provider, operational, "m82-success", "succeeded", amount=99)
        try:
            XafPayOrchestrationService.process_callback(session, conflict)
        except XafPayIntegrationError as exc:
            if exc.code != "callback_replay_conflict":
                raise
        else:
            raise RuntimeError("conflicting callback replay was accepted")
        late = XafPayOrchestrationService.process_callback(
            session, _callback_command(tenant, org, provider, operational, "m82-late-failure", "failed")
        )
        if late.processing_state != "ignored" or late.attempt_state != "succeeded":
            raise RuntimeError("late callback regressed terminal state")
        try:
            XafPayOrchestrationService.process_callback(
                session, _callback_command(tenant + 999, org, provider, operational, "m82-cross-tenant", "succeeded")
            )
        except XafPayIntegrationError as exc:
            if exc.code != "provider_scope_mismatch":
                raise
        else:
            raise RuntimeError("cross-tenant callback was accepted")

    with selected.connect() as connection:
        counts = _counts(connection)
        if counts != {"provider_callback_events": 3, "payment_settlements": 1, "payment_settlement_transitions": 2}:
            raise RuntimeError(f"unexpected callback/settlement cardinality={counts}")
        if connection.execute(text("SELECT count(*) FROM financial_events")).scalar_one() != 1:
            raise RuntimeError("canonical event retry cardinality differs")
        if connection.execute(text("SELECT count(*) FROM outbox_messages")).scalar_one() != 1:
            raise RuntimeError("canonical event/outbox atomicity differs")
        for table in ("journal_entries", "journal_lines", "payment_allocations", "allocation_reversals"):
            if connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one():
                raise RuntimeError(f"failure rehearsal manufactured downstream authority={table}")
        if connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() != EXPECTED_HEAD:
            raise RuntimeError("M8.2 changed canonical schema head")


def _run():
    _development()
    _create()
    selected = None
    try:
        selected = _engine(TEST_DATABASE_NAME)
        _exercise(selected)
        selected.dispose(); selected = None
        _drop(TEST_DATABASE_NAME)
        _development()
    except Exception:
        if selected is not None:
            selected.dispose()
        print(f"M8.2 verification failed; retained disposable database={TEST_DATABASE_NAME}")
        raise
    print(f"m82_external_provider_infrastructure_resilience=PASS database={TEST_DATABASE_NAME} webhook_security=PASS malformed=PASS duplicate=PASS out_of_order=PASS provider_outage=PASS uncertainty=PASS replay=PASS conflict=PASS rollback=PASS atomicity=PASS tenant_scope=PASS schema_neutral=PASS migration=NONE live_calls=0 dropped=true")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "status", "create-and-verify", "drop"))
    parser.add_argument("--confirm-database-name")
    args = parser.parse_args()
    if args.command == "verify":
        _development()
    elif args.command == "status":
        print(f"database={TEST_DATABASE_NAME} exists={str(_exists(TEST_DATABASE_NAME)).lower()}")
    elif args.command == "create-and-verify":
        _run()
    else:
        if args.confirm_database_name != TEST_DATABASE_NAME:
            raise RuntimeError("exact disposable database confirmation required")
        _drop(TEST_DATABASE_NAME)
        print(f"dropped={TEST_DATABASE_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
