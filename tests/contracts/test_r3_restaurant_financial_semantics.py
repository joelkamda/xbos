from __future__ import annotations
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4
import pytest
from restaurant.r1.contracts import ObligationHandoff, ObligationHandoffLine, TargetType
from restaurant.r2.contracts import ModifierSelection, ModifierSelectionSet
from restaurant.r3 import *

NOW=datetime(2026,8,19,7,0,tzinfo=timezone.utc)

def context(source,debtor=None):
    return RestaurantFinanceContext(1,10,'order',source,uuid4(),debtor or uuid4(),'XAF',NOW,date(2026,8,19),1,uuid4())

def handoff(source,line=None):
    lp=line or uuid4();target=uuid4();l=ObligationHandoffLine(lp,TargetType.ATOMIC_UNIT,target,Decimal('2'),Decimal('3000'),'XAF',Decimal('6000'))
    return ObligationHandoff(1,'order',source,'dine_in',uuid4(),'XAF',(l,),Decimal('6000'))

def test_r1_base_and_r2_modifier_snapshots_compile_without_repricing_so1():
    source=uuid4();h=handoff(source);line=h.lines[0];g=uuid4();o=uuid4();mods=ModifierSelectionSet(uuid4(),1,line.order_line_public_id,1,(ModifierSelection(g,o,Decimal('1'),Decimal('500'),'XAF'),),NOW)
    plan=RestaurantFinancialSemantics.compile_order_charge(context(source),h,modifier_sets={line.order_line_public_id:mods})
    assert plan.gross_sales_amount==Decimal('7000') and plan.charge_lines[-1].source_kind is ChargeSourceKind.MODIFIER
    assert plan.commands[0].command_type=='CanonicalFinancialEventCommand' and plan.commands[0].execution_allowed is False

def test_discount_complimentary_service_fee_tax_formula_and_delivery_fee_classification():
    source=uuid4();h=handoff(source)
    terms=(
      CommercialTerm(uuid4(),CommercialTermKind.DISCOUNT,Decimal('500'),{'discount_reason':{'code':'promo'}},'d1'),
      CommercialTerm(uuid4(),CommercialTermKind.COMPLIMENTARY,Decimal('500'),{'complimentary_reason':{'code':'recovery'},'complimentary_policy':{'code':'service_recovery'}},'c1'),
      CommercialTerm(uuid4(),CommercialTermKind.CUSTOMER_SERVICE_FEE,Decimal('1000'),{'revenue_nature':{'code':'delivery_fee'}},'fee1'),
      CommercialTerm(uuid4(),CommercialTermKind.OUTPUT_TAX,Decimal('200'),{'tax_jurisdiction':{'code':'cm'},'tax_code':{'code':'vat'}},'tax1'),
    )
    plan=RestaurantFinancialSemantics.compile_order_charge(context(source),h,terms=terms)
    assert plan.gross_sales_amount==Decimal('6000') and plan.customer_collectible_before_tip==Decimal('6200')
    terms_cmd=next(x for x in plan.commands if x.command_type=='RecognizeCommercialTermsCommand')
    assert {x['component_type'] for x in terms_cmd.payload['components']}=={'discount','complimentary','customer_service_fee','output_tax'}

def test_allowances_cannot_exceed_gross():
    source=uuid4();h=handoff(source);term=CommercialTerm(uuid4(),CommercialTermKind.DISCOUNT,Decimal('7000'),{'discount_reason':{'code':'bad'}},'x')
    with pytest.raises(R3Error) as e:RestaurantFinancialSemantics.compile_order_charge(context(source),h,terms=(term,))
    assert e.value.code=='R3_ALLOWANCE_CAPACITY_EXCEEDED'

def test_tip_and_commission_delegate_to_m53_and_do_not_create_payment_settlement():
    source=uuid4();h=handoff(source);staff=uuid4()
    tip=EarningInstruction(uuid4(),EarningKind.TIP,Decimal('500'),staff,'staff_beneficiary','tip')
    comm=EarningInstruction(uuid4(),EarningKind.COMMISSION,Decimal('300'),staff,'waiter_commission','comm','percentage',Decimal('6000'),Decimal('5'))
    plan=RestaurantFinancialSemantics.compile_order_charge(context(source),h,earnings=(tip,comm))
    assert plan.customer_due_amount==Decimal('6500')
    names={x.command_type for x in plan.commands};assert {'RecognizeTipCommand','RecognizeCommissionCommand'}.issubset(names)
    assert not any('PaymentSettlement' in x.command_type for x in plan.commands)

def test_tenant_income_tip_has_no_beneficiary_and_still_increases_customer_due():
    source=uuid4();h=handoff(source);tip=EarningInstruction(uuid4(),EarningKind.TIP,Decimal('250'),None,'tenant_income','tip')
    plan=RestaurantFinancialSemantics.compile_order_charge(context(source),h,earnings=(tip,));assert plan.customer_due_amount==Decimal('6250')

def test_obligation_handoff_requires_existing_party_identity_for_customer_due():
    source=uuid4();h=handoff(source);ctx=RestaurantFinanceContext(1,10,'order',source,uuid4(),None,'XAF',NOW,date(2026,8,19),1,uuid4())
    with pytest.raises(R3Error) as e:RestaurantFinancialSemantics.compile_order_charge(ctx,h)
    assert e.value.code=='R3_DEBTOR_PARTY_REQUIRED'

def test_pre_financial_cancel_is_operational_only_and_has_no_finance_command():
    req=CorrectionRequest(1,10,uuid4(),CorrectionKind.CANCEL,Decimal('1000'),'XAF',NOW,date(2026,8,19),1,uuid4(),False,False,False,'customer_request','C-1','a'*64)
    plan=RestaurantFinancialSemantics.correction_plan(req);assert plan.commands==() and plan.operational_disposition.startswith('restaurant_')

def test_post_financial_cancel_is_rejected_and_refund_is_append_only_finance_mapping():
    req=CorrectionRequest(1,10,uuid4(),CorrectionKind.CANCEL,Decimal('1000'),'XAF',NOW,date(2026,8,19),1,uuid4(),True,True,False,'customer_request','C-2','b'*64)
    with pytest.raises(R3Error) as e:RestaurantFinancialSemantics.correction_plan(req)
    assert e.value.code=='R3_CANCELLATION_TOO_LATE'
    refund=CorrectionRequest(1,10,req.source_public_id,CorrectionKind.REFUND,Decimal('1000'),'XAF',NOW,date(2026,8,19),1,uuid4(),True,True,True,'customer_request','R-1','c'*64,original_settlement_public_id=uuid4(),refund_settlement_public_id=uuid4())
    plan=RestaurantFinancialSemantics.correction_plan(refund);assert plan.commands[0].command_type=='RecognizeRefundCommand' and plan.original_financial_truth_immutable

def test_reversal_requires_original_financial_event_and_is_append_only():
    req=CorrectionRequest(1,10,uuid4(),CorrectionKind.REVERSE,Decimal('500'),'XAF',NOW,date(2026,8,19),1,uuid4(),True,False,False,'correction','RV-1','d'*64,original_event_public_id=uuid4())
    plan=RestaurantFinancialSemantics.correction_plan(req);assert plan.commands[0].command_type=='ReverseFinancialFactCommand' and plan.commands[0].execution_allowed is False

def test_reports_are_finance_so9_projections_not_restaurant_ledger():
    req=RestaurantReportRequest(1,10,'sales_summary',date(2026,8,1),date(2026,8,31),('mode_code','waiter_party_public_id'))
    plan=RestaurantFinancialSemantics.report_plan(req);assert plan.financial_truth_source=='Neutral Finance / SO9' and plan.restaurant_calculates_ledger_truth is False

def test_exact_replay_is_deterministic_and_changed_payload_conflicts():
    source=uuid4();h=handoff(source);ctx=context(source);a=RestaurantFinancialSemantics.compile_order_charge(ctx,h);b=RestaurantFinancialSemantics.compile_order_charge(ctx,h);assert_plan_replay(a,b)
    term=CommercialTerm(uuid4(),CommercialTermKind.DISCOUNT,Decimal('100'),{'discount_reason':{'code':'promo'}},'d')
    c=RestaurantFinancialSemantics.compile_order_charge(ctx,h,terms=(term,))
    with pytest.raises(R3Error) as e:assert_plan_replay(a,c)
    assert e.value.code=='R3_MAPPING_IDEMPOTENCY_CONFLICT'

def test_r3_has_no_schema_or_finance_writer_imports():
    root=Path(__file__).resolve().parents[2]
    assert not list((root/'alembic_neutral/versions').glob('r3_*'))
    source=(root/'restaurant/r3/service.py').read_text(encoding='utf-8').lower()
    for token in ('_repository import','_engine import','session.execute','insert into public.financial','createpaymentsettlementcommand'):
        assert token not in source

def test_r3_source_checkpoint_and_no_migration_contract():
    import json
    root=Path(__file__).resolve().parents[2];a=json.loads((root/'contracts/restaurant/v1/r3_financial_semantics_authority.json').read_text())
    assert a['source_checkpoint']=='c9ab012e8e666f2bf96b8ad50b571f608acfeebd' and a['accepted_head']=='r2_restaurant_menu_fulfillment_043' and a['migration']=='NONE'
