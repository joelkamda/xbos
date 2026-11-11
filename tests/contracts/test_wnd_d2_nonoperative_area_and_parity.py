"""W D1/D2 source-only synthetic negative tests. No DB/network/merchant effects."""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo
import json
import os
import unittest

from restaurant.wnd_d2_area_price_candidate import (
    AreaConfiguration, VenueConfiguration, VerifiedOrderPlacement,
    WAreaError, resolve_area_price, assert_quote_current,
)
from restaurant.wnd_d2_parity_candidate import (
    CountedLine, DraftScope, MemoryDraftFixtureRepository, StockDraft,
    StockDraftAuthority, Tender, WParityError, business_window_at,
    window_for, tender_and_receivable_preview, kitchen_intent_preview,
    receipt_80mm_preview, manager_close_preview,
)
from shared_operations.so1 import SO1Authority
from shared_operations.so1.contracts import Price, ScopeType, TargetType

ROOT = Path(__file__).resolve().parents[2]
WAT = ZoneInfo("Africa/Douala")
WHEN = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)
ORDER, TARGET = UUID(int=88), UUID(int=77)


class FakePriceRepository:
    def __init__(self, prices: tuple[Price, ...]):
        self.prices = prices
        self.queries = []

    def resolve_price(self, query):
        self.queries.append(query)
        candidates = [
            p for p in self.prices if p.tenant_id == query.tenant_id
            and p.target_type == query.target_type
            and p.target_public_id == query.target_public_id
            and p.price_code == query.price_code and p.currency == query.currency
            and p.active and p.effective_from <= query.at
            and (p.effective_to is None or query.at < p.effective_to)
            and (p.scope_type == ScopeType.TENANT or
                 p.scope_type == query.scope_type and p.scope_id == query.scope_id)
        ]
        candidates.sort(
            key=lambda p: (p.scope_type == query.scope_type and p.scope_id == query.scope_id,
                           p.precedence, p.effective_from), reverse=True
        )
        if len(candidates) > 1:
            first, second = candidates[:2]
            if (first.scope_type == second.scope_type
                    and first.scope_id == second.scope_id
                    and first.precedence == second.precedence
                    and first.effective_from == second.effective_from):
                raise ValueError("SO1_AMBIGUOUS_PRICE")
        return candidates[0] if candidates else None


class AreaFixture(unittest.TestCase):
    def setUp(self):
        self.areas = (
            AreaConfiguration(910001, 5, "main", "retail", ("T1",), 1, True),
            AreaConfiguration(910001, 5, "vip", "vip_lounge", ("V1", "V2"), 2, True),
        )
        self.venue = VenueConfiguration(910001, 5, 7, self.areas,
                                        False, False, True, True, True)
        self.placement = VerifiedOrderPlacement(ORDER, 910001, 5, "vip", 2, None, "pos")
        self.repo = FakePriceRepository((
            Price(1, UUID(int=11), 910001, TargetType.ATOMIC_UNIT,
                  TARGET, "retail", Decimal("1000"), "XAF",
                  ScopeType.TENANT, None, 10, WHEN - timedelta(days=2), None, True, 1),
            Price(2, UUID(int=12), 910001, TargetType.ATOMIC_UNIT,
                  TARGET, "vip_lounge", Decimal("1300"), "XAF",
                  ScopeType.LOCATION, 5, 12, WHEN - timedelta(days=1), None, True, 2),
        ))
        self.auth = self._authority()

    def _authority(self, permit=True, scope=True):
        return SO1Authority(
            self.repo, authorize=lambda *args: permit,
            validate_scope=lambda *args: scope, public_id_factory=lambda: UUID(int=222),
        )

    def quote(self, **kwargs):
        args = dict(venue=self.venue, order_public_id=ORDER,
                    target_type=TargetType.ATOMIC_UNIT, target_public_id=TARGET,
                    effective_at=WHEN, verified_placement_lookup=lambda t, l, o:self.placement,
                    so1_price_resolver=self.auth.resolve_price)
        return resolve_area_price(**(args | kwargs))

    def expect(self, code: str, **kwargs):
        with self.assertRaises(WAreaError) as e:
            self.quote(**kwargs)
        self.assertEqual(e.exception.code, code)

    def test_01_vip_server_selected_winner_not_retail(self):
        q = self.quote()
        self.assertEqual((q.whole_xaf, q.price_code, q.area_code), (1300, "vip_lounge", "vip"))
        self.assertEqual((q.tenant_id, q.location_id, q.price_version), (910001, 5, 2))
        self.assertEqual(self.repo.queries[-1].scope_type, ScopeType.LOCATION)
        self.assertEqual(self.repo.queries[-1].price_code, "vip_lounge")

    def test_02_normal_area_same_stock_target_and_retail_price(self):
        vip = self.quote()
        self.placement = replace(self.placement, area_code="main", area_revision=1)
        main = self.quote()
        self.assertEqual(main.whole_xaf, 1000)
        self.assertEqual(main.target_public_id, vip.target_public_id)
        self.assertNotEqual(main.price_code, vip.price_code)

    def test_03_table_configuration_retained_while_off(self):
        self.assertFalse(self.venue.table_service_enabled)
        self.assertEqual(self.venue.areas[1].allowed_tables, ("V1", "V2"))
        self.assertEqual(self.quote().whole_xaf, 1300)

    def test_04_table_id_when_service_off_denied(self):
        self.placement = replace(self.placement, table_code="V1")
        self.expect("W_TABLE_SERVICE_DISABLED")

    def test_05_enabled_table_uses_safely_bound_area(self):
        self.venue = replace(self.venue, table_service_enabled=True)
        self.placement = replace(self.placement, table_code="V1")
        self.assertEqual(self.quote().table_code, "V1")

    def test_06_table_cross_area_denied(self):
        self.venue = replace(self.venue, table_service_enabled=True)
        self.placement = replace(self.placement, table_code="T1")
        self.expect("W_TABLE_NOT_IN_AREA")

    def test_07_optional_qr_off_denied(self):
        self.venue = replace(self.venue, table_service_enabled=True)
        self.placement = replace(self.placement, table_code="V1", channel="xafchat_qr")
        self.expect("W_QR_NOT_EFFECTIVE")

    def test_08_opted_in_qr_requires_table(self):
        self.venue = replace(self.venue, table_service_enabled=True, xafchat_qr_enabled=True)
        self.placement = replace(self.placement, channel="xafchat_qr")
        self.expect("W_QR_TABLE_REQUIRED")

    def test_09_opted_in_qr_returns_only_price_quote_not_checkout(self):
        self.venue = replace(self.venue, table_service_enabled=True, xafchat_qr_enabled=True)
        self.placement = replace(self.placement, channel="xafchat_qr", table_code="V1")
        self.assertEqual(self.quote().channel, "xafchat_qr")

    def test_10_wrong_tenant_resolver_denied(self):
        self.placement = replace(self.placement, tenant_id=2)
        self.expect("W_AREA_CROSS_SCOPE_BINDING")

    def test_11_wrong_branch_location_denied(self):
        self.placement = replace(self.placement, location_id=8)
        self.expect("W_AREA_CROSS_SCOPE_BINDING")

    def test_12_forged_order_identity_denied(self):
        self.placement = replace(self.placement, order_public_id=UUID(int=999))
        self.expect("W_AREA_CROSS_SCOPE_BINDING")

    def test_13_untrusted_missing_placement_denied(self):
        self.expect("W_AREA_TRUSTED_BINDING_REQUIRED", verified_placement_lookup=lambda *a:None)

    def test_14_stale_area_revision_denied(self):
        self.placement = replace(self.placement, area_revision=1)
        self.expect("W_AREA_STALE_REVISION")

    def test_15_inactive_vip_denied(self):
        self.venue = replace(self.venue, areas=(self.areas[0], replace(self.areas[1], active=False)))
        self.expect("W_AREA_UNKNOWN_OR_INACTIVE")

    def test_16_no_vip_price_must_not_fallback_to_retail(self):
        self.repo.prices = (self.repo.prices[0],)
        self.expect("W_AREA_SO1_PRICE_UNAVAILABLE")

    def test_17_cross_tenant_so1_price_poison_denied(self):
        wrong = replace(self.repo.prices[1], tenant_id=2)
        self.expect("W_AREA_SO1_WINNER_IDENTITY_MISMATCH", so1_price_resolver=lambda q:wrong)

    def test_18_cross_target_so1_price_poison_denied(self):
        wrong = replace(self.repo.prices[1], target_public_id=UUID(int=2))
        self.expect("W_AREA_SO1_WINNER_IDENTITY_MISMATCH", so1_price_resolver=lambda q:wrong)

    def test_19_wrong_scope_so1_price_denied(self):
        wrong = replace(self.repo.prices[1], scope_id=99)
        self.expect("W_AREA_SO1_WINNER_SCOPE_MISMATCH", so1_price_resolver=lambda q:wrong)

    def test_20_wrong_price_code_so1_price_denied(self):
        wrong = replace(self.repo.prices[1], price_code="retail")
        self.expect("W_AREA_SO1_WINNER_IDENTITY_MISMATCH", so1_price_resolver=lambda q:wrong)

    def test_21_stale_quote_version_rejected(self):
        first = self.quote()
        self.repo.prices = (self.repo.prices[0], replace(self.repo.prices[1], row_version=3))
        with self.assertRaises(WAreaError) as e:
            assert_quote_current(first, self.quote())
        self.assertEqual(e.exception.code, "W_AREA_STALE_OR_CHANGED_QUOTE")

    def test_22_missing_pc5_pc4_or_pack_denied(self):
        for field in ("pc5_permission_effective", "pc4_capability_effective", "restaurant_pack_active"):
            with self.subTest(field=field):
                self.venue = replace(self.venue, **{field: False})
                self.expect("W_AREA_EFFECTIVE_AUTHORITY_REQUIRED")
                self.venue = replace(self.venue, **{field: True})

    def test_23_naive_datetime_denied(self):
        self.expect("W_AREA_AWARE_TIME_REQUIRED", effective_at=datetime(2026, 11, 9))

    def test_24_duplicate_area_policy_denied(self):
        self.venue = replace(self.venue, areas=self.areas + (self.areas[1],))
        self.expect("W_AREA_CONFIG_INCONSISTENT")

    def test_25_SO1_denied_permission_is_fail_closed(self):
        self.auth = self._authority(permit=False)
        self.expect("W_AREA_SO1_PRICE_UNAVAILABLE")

    def test_26_SO1_ambiguity_is_fail_closed(self):
        self.repo.prices = self.repo.prices + (replace(self.repo.prices[1], public_id=UUID(int=123)),)
        self.expect("W_AREA_SO1_PRICE_UNAVAILABLE")

    def test_27_nonwhole_xaf_rejected(self):
        price = replace(self.repo.prices[1], amount=Decimal("1234.25"))
        self.expect("W_AREA_NON_WHOLE_XAF_PRICE", so1_price_resolver=lambda q:price)

    def test_28_expired_price_rejected_even_forged_resolver(self):
        price = replace(self.repo.prices[1], effective_to=WHEN)
        self.expect("W_AREA_SO1_WINNER_NOT_EFFECTIVE", so1_price_resolver=lambda q:price)

    def test_29_client_cheap_price_code_not_an_argument(self):
        with self.assertRaises(TypeError):
            self.quote(client_price_code="retail")

    def test_30_repeated_exact_quote_idempotent(self):
        self.assertEqual(self.quote(), self.quote())


class DisposableFileDraftPort:
    """TEST-ONLY JSON snapshot store in a temp folder, not production storage.

    Reconstructing this port reads persisted bytes. This has NO transactional
    multiworker CAS or crash-recovery guarantee; real PG17 admission deferred.
    """
    def __init__(self, directory: Path):
        self.directory = directory

    def _path(self, scope: DraftScope) -> Path:
        from hashlib import sha256
        key = "|".join((str(scope.tenant_id), str(scope.branch_id),
                        scope.business_date.isoformat(), scope.shift))
        return self.directory / (sha256(key.encode()).hexdigest() + ".json")

    def load(self, scope: DraftScope) -> StockDraft | None:
        path = self._path(scope)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        saved_scope = DraftScope(
            int(data["tenant_id"]), int(data["branch_id"]),
            date.fromisoformat(data["business_date"]), data["shift"],
        )
        if saved_scope != scope:
            raise ValueError("FIXTURE_SCOPE_TAMPER")
        lines = tuple(CountedLine(**line) for line in data["lines"])
        return StockDraft(scope, int(data["revision"]), lines,
                          data["note"], data["fingerprint"])

    def put_if_revision(self, item: StockDraft, expected_revision: int) -> bool:
        prior = self.load(item.scope)
        if (prior.revision if prior else 0) != expected_revision:
            return False
        data = {"tenant_id": item.scope.tenant_id,
                "branch_id": item.scope.branch_id,
                "business_date": item.scope.business_date.isoformat(),
                "shift": item.scope.shift, "revision": item.revision,
                "lines": [x.__dict__ for x in item.lines], "note": item.note,
                "fingerprint": item.fingerprint}
        file = self._path(item.scope)
        temp = file.with_suffix(".pending")
        temp.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
        os.replace(temp, file)
        return True


class FileReloadBoundaryFixture(unittest.TestCase):
    def test_65_save_reload_after_reopening_disposable_fixture_store(self):
        with TemporaryDirectory(prefix="xcomp_w_local_draft_") as directory:
            folder = Path(directory)
            scope = DraftScope(910001, 5, date(2026, 11, 9), "night")
            authorization = lambda t, b, perm: (t, b) == (910001, 5)
            s1 = StockDraftAuthority(
                DisposableFileDraftPort(folder),
                authorize=authorization, closed_window=lambda s:False,
            )
            first = s1.save(scope, expected_revision=0,
                            lines=(CountedLine(100, 4),), note="Saved for tomorrow")
            self.assertEqual(first.revision, 1)
            # A NEW port/service reads independently reconstructed bytes.
            s2 = StockDraftAuthority(
                DisposableFileDraftPort(folder),
                authorize=authorization, closed_window=lambda s:False,
            )
            self.assertEqual(s2.reload(scope), first)
            self.assertEqual(len(tuple(folder.glob("*.json"))), 1)

    def test_66_disposable_snapshot_wrong_scope_not_reusable(self):
        with TemporaryDirectory(prefix="xcomp_w_scope_") as directory:
            folder = Path(directory)
            port = DisposableFileDraftPort(folder)
            scope = DraftScope(910001, 5, date(2026, 11, 9), "day")
            service = StockDraftAuthority(port, authorize=lambda *a:True,
                                          closed_window=lambda s:False)
            service.save(scope, expected_revision=0, lines=(CountedLine(100, 4),))
            self.assertIsNone(service.reload(replace(scope, tenant_id=910002)))
            self.assertIsNone(service.reload(replace(scope, branch_id=6)))


class DraftParityFixture(unittest.TestCase):
    def setUp(self):
        self.store = MemoryDraftFixtureRepository()
        self.closed = set()
        self.tenant = 910001
        self.scope = DraftScope(self.tenant, 5, date(2026, 11, 9), "day")
        self.allowed = {(self.tenant, 5)}
        self.auth = self.authority()

    def authority(self):
        return StockDraftAuthority(
            self.store, authorize=lambda t, b, p: (t, b) in self.allowed,
            closed_window=lambda s: s in self.closed,
        )

    def save(self, expected_revision=0, lines=None, note="counter-1"):
        return self.auth.save(self.scope, expected_revision=expected_revision,
                              lines=lines if lines is not None else
                              (CountedLine(100, 8), CountedLine(101, 2)),
                              note=note)

    def expect(self, code, fn):
        with self.assertRaises(WParityError) as e:
            fn()
        self.assertEqual(e.exception.code, code)

    def test_31_business_day_0759_belongs_predecessor(self):
        v = business_window_at(datetime(2026, 11, 9, 7, 59, tzinfo=WAT))
        self.assertEqual((v.business_date, v.shift), (date(2026, 11, 8), "night"))

    def test_32_business_day_0800_opens_new_day(self):
        v = business_window_at(datetime(2026, 11, 9, 8, 0, tzinfo=WAT))
        self.assertEqual((v.business_date, v.shift), (date(2026, 11, 9), "day"))

    def test_33_shift_1800_new_night_until_next_0800(self):
        v = business_window_at(datetime(2026, 11, 9, 18, 0, tzinfo=WAT))
        self.assertEqual(v.shift, "night")
        self.assertEqual(v.end_utc.astimezone(WAT).hour, 8)
        self.assertEqual(v.end_utc.astimezone(WAT).date(), date(2026, 11, 10))

    def test_34_full24_exact_08_to_next_08(self):
        v = window_for(date(2026, 11, 9), "full24")
        self.assertEqual(v.end_utc - v.start_utc, timedelta(hours=24))

    def test_35_save_reloads_across_new_service_instance(self):
        a = self.save()
        self.auth = self.authority()  # newly constructed service; shared fake PORT
        self.assertEqual(self.auth.reload(self.scope), a)
        self.assertEqual(a.revision, 1)

    def test_36_changed_count_bumps_revision(self):
        self.save()
        newer = self.save(expected_revision=1, lines=(CountedLine(100, 7), CountedLine(101, 2)))
        self.assertEqual(newer.revision, 2)
        self.assertEqual(self.auth.reload(self.scope), newer)

    def test_37_same_payload_replay_no_version_bump(self):
        a = self.save()
        b = self.save(expected_revision=0)
        self.assertEqual(a, b)
        self.assertEqual(b.revision, 1)

    def test_38_order_of_line_input_does_not_change_identity(self):
        a = self.save()
        b = self.save(lines=tuple(reversed(a.lines)))
        self.assertEqual(a.fingerprint, b.fingerprint)

    def test_39_stale_changed_payload_denied(self):
        self.save()
        self.expect("W_STOCK_STALE_DRAFT", lambda:
                    self.save(expected_revision=0, lines=(CountedLine(100, 6),)))

    def test_40_closed_window_denies_save_even_on_identical_replay(self):
        self.save()
        self.closed.add(self.scope)
        self.expect("W_STOCK_WINDOW_ALREADY_CLOSED", self.save)

    def test_41_wrong_tenant_access_denied(self):
        another = replace(self.scope, tenant_id=2)
        self.expect("W_STOCK_PERMISSION_DENIED", lambda:self.auth.reload(another))

    def test_42_wrong_branch_access_denied(self):
        another = replace(self.scope, branch_id=7)
        self.expect("W_STOCK_PERMISSION_DENIED", lambda:self.auth.reload(another))

    def test_43_duplicate_unit_denied(self):
        self.expect("W_STOCK_DUPLICATE_UNIT", lambda:self.save(
            lines=(CountedLine(100, 1), CountedLine(100, 3))))

    def test_44_negative_count_denied(self):
        self.expect("W_STOCK_LINE_INVALID", lambda:self.save(lines=(CountedLine(100, -1),)))

    def test_45_no_count_lines_denied(self):
        self.expect("W_STOCK_LINES_REQUIRED", lambda:self.save(lines=()))

    def test_46_unknown_shift_denied(self):
        self.scope = replace(self.scope, shift="unknown")
        self.expect("W_SHIFT_INVALID", self.save)

    def test_47_wrong_or_missing_inventory_basis_denied(self):
        self.save()
        self.expect("W_STOCK_SYSTEM_BASIS_INCOMPLETE", lambda:self.auth.variance_preview(
            self.scope, system_quantities={100:8}, expected_revision=1))

    def test_48_variance_is_preview_no_stock_or_finance_effect(self):
        self.save()
        preview = self.auth.variance_preview(
            self.scope, system_quantities={100:9,101:2}, expected_revision=1)
        self.assertTrue(preview["has_variance"])
        self.assertEqual(preview["stock_effects"], 0)
        self.assertEqual(preview["finance_effects"], 0)
        self.assertFalse(preview["real_close_allowed"])

    def test_49_stale_preview_revision_denied(self):
        self.save()
        self.expect("W_STOCK_DRAFT_MISSING_OR_STALE", lambda:
                    self.auth.variance_preview(self.scope, system_quantities={100:8,101:2},expected_revision=0))

    def test_50_draft_fingerprint_is_scoped_to_branch(self):
        a = self.save()
        self.allowed.add((910001, 6))
        self.scope = replace(self.scope, branch_id=6)
        b = self.save()
        self.assertNotEqual(a.fingerprint, b.fingerprint)

    def test_51_business_day_is_config_not_neutral_kernel(self):
        cfg = json.loads((ROOT / "contracts/restaurant/v1/r5_wnd_logpom_profile.json").read_text())
        self.assertEqual(cfg["business_calendar"]["business_day_boundary"], "08:00:00")

    def test_52_legacy_compat_route_has_no_draft_save_api_yet(self):
        text = (ROOT / "restaurant/r6/wnd_api_compat/router.py").read_text()
        self.assertIn('@router.post("/inventory/reconciliation/close")', text)
        self.assertNotIn('@router.post("/inventory/reconciliation/draft', text)


class FinancialKitchenReceiptFixture(unittest.TestCase):
    def test_53_partial_split_is_ar_not_paid(self):
        r = tender_and_receivable_preview(
            charge_whole_xaf=1000,tenders=(Tender("cash",300),Tender("mtn",200)),
            unpaid_allowed=True)
        self.assertEqual(r["receivable_proposed_whole_xaf"], 500)
        self.assertFalse(r["paid_assertion_allowed"])

    def test_54_full_split_still_not_independent_paid_finality(self):
        r=tender_and_receivable_preview(charge_whole_xaf=1000,tenders=(Tender("cash",500),Tender("orange",500)),unpaid_allowed=False)
        self.assertEqual(r["receivable_proposed_whole_xaf"],0)
        self.assertFalse(r["provider_verified"])
        self.assertFalse(r["paid_assertion_allowed"])

    def test_55_overcapacity_denied(self):
        with self.assertRaises(WParityError) as x:
            tender_and_receivable_preview(charge_whole_xaf=1000,tenders=(Tender("cash",1001),),unpaid_allowed=True)
        self.assertEqual(x.exception.code,"W_PAYMENT_SPLIT_OVERCAPACITY")

    def test_56_unpaid_not_enabled_denied(self):
        with self.assertRaises(WParityError) as x:
            tender_and_receivable_preview(charge_whole_xaf=1000,tenders=(Tender("cash",200),),unpaid_allowed=False)
        self.assertEqual(x.exception.code,"W_PAYMENT_UNPAID_NOT_ALLOWED")

    def test_57_kitchen_food_only(self):
        self.assertEqual(kitchen_intent_preview(server_category="FOOD",server_subcategory="MAIN DISH")["fulfillment_queue"],"kitchen")
        self.assertFalse(kitchen_intent_preview(server_category="DRINKS",server_subcategory="BEER")["requires_fulfillment"])

    def test_58_kitchen_intent_never_fires_ticket(self):
        r=kitchen_intent_preview(server_category="FOOD",server_subcategory="BREAKFAST")
        self.assertEqual(r["kitchen_effects"],0)

    def test_59_receipt_80mm_requires_niu(self):
        with self.assertRaises(WParityError) as x:
            receipt_80mm_preview(legal_name="Wine & Dine",niu="",charge_whole_xaf=1000,remainder_whole_xaf=500)
        self.assertEqual(x.exception.code,"W_RECEIPT_LEGAL_ID_REQUIRED")

    def test_60_receipt_unpaid_must_not_claim_paid_or_print(self):
        r=receipt_80mm_preview(legal_name="Wine & Dine",niu="SYNTHETIC_NIU",charge_whole_xaf=1000,remainder_whole_xaf=500)
        self.assertEqual(r["paper_mm"],80)
        self.assertEqual(r["document_status"],"PROFORMA_UNVERIFIED_PAYMENT")
        self.assertEqual(r["real_printer_effects"],0)

    def test_61_manager_close_pending_draft_holds(self):
        self.assertEqual(manager_close_preview(m6_asof_verified=True,open_stock_drafts=1,unexplained_variances=0,uncertain_provider_attempts=0)["disposition"],"HOLD")

    def test_62_manager_close_unverified_finance_holds(self):
        self.assertEqual(manager_close_preview(m6_asof_verified=False,open_stock_drafts=0,unexplained_variances=0,uncertain_provider_attempts=0)["disposition"],"HOLD")

    def test_63_manager_close_clean_is_only_candidate(self):
        r=manager_close_preview(m6_asof_verified=True,open_stock_drafts=0,unexplained_variances=0,uncertain_provider_attempts=0)
        self.assertEqual(r["disposition"],"LOCAL_CANDIDATE_ONLY")
        self.assertFalse(r["actual_m6_close"])

    def test_64_manager_close_unknown_provider_holds(self):
        self.assertEqual(manager_close_preview(m6_asof_verified=True,open_stock_drafts=0,unexplained_variances=0,uncertain_provider_attempts=1)["disposition"],"HOLD")


if __name__ == "__main__":
    unittest.main(verbosity=2)
