CREATE OR REPLACE FUNCTION public.xbos_validate_operational_transfer_event()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE source_account public.operational_financial_accounts%ROWTYPE;
DECLARE destination_account public.operational_financial_accounts%ROWTYPE;
DECLARE original_type VARCHAR(80);
DECLARE selected_value_at TIMESTAMPTZ;
BEGIN
    IF NEW.event_type_code='VALUE_TRANSFERRED' THEN
        IF NEW.event_version<>1 OR NEW.economic_role<>'transfer' OR NEW.amount<=0
           OR NEW.source_operational_account_id IS NULL OR NEW.target_operational_account_id IS NULL
           OR NEW.source_operational_account_id=NEW.target_operational_account_id THEN
            RAISE EXCEPTION 'operational transfer identity, role, amount, and bilateral accounts are required'
                USING ERRCODE='23514';
        END IF;
        SELECT * INTO source_account FROM public.operational_financial_accounts
        WHERE tenant_id=NEW.tenant_id AND id=NEW.source_operational_account_id FOR SHARE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'operational transfer source account is missing or cross-tenant' USING ERRCODE='23514';
        END IF;
        SELECT * INTO destination_account FROM public.operational_financial_accounts
        WHERE tenant_id=NEW.tenant_id AND id=NEW.target_operational_account_id FOR SHARE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'operational transfer destination account is missing or cross-tenant' USING ERRCODE='23514';
        END IF;
        IF source_account.organization_unit_id<>NEW.organization_unit_id
           OR destination_account.organization_unit_id<>NEW.organization_unit_id
           OR source_account.currency_code<>NEW.currency_code
           OR destination_account.currency_code<>NEW.currency_code
           OR source_account.aggregation_role<>'leaf' OR destination_account.aggregation_role<>'leaf'
           OR NOT source_account.active OR NOT destination_account.active THEN
            RAISE EXCEPTION 'operational transfer account scope, currency, or eligibility differs' USING ERRCODE='23514';
        END IF;
        IF NEW.occurred_at<source_account.opened_at OR NEW.occurred_at<destination_account.opened_at
           OR (source_account.closed_at IS NOT NULL AND NEW.occurred_at>source_account.closed_at)
           OR (destination_account.closed_at IS NOT NULL AND NEW.occurred_at>destination_account.closed_at) THEN
            RAISE EXCEPTION 'operational transfer falls outside account lifetime' USING ERRCODE='23514';
        END IF;
        IF NEW.evidence_hash IS NULL OR NOT (NEW.classification_snapshot ? 'transfer_purpose')
           OR jsonb_typeof(NEW.metadata->'transfer') IS DISTINCT FROM 'object'
           OR jsonb_typeof(NEW.metadata#>'{transfer,evidence_payload}') IS DISTINCT FROM 'object'
           OR NEW.metadata#>'{transfer,evidence_payload}'='{}'::jsonb
           OR COALESCE(NEW.metadata#>>'{transfer,provenance}','') NOT IN
              ('operator_authorized','system_authorized','external_confirmed')
           OR NOT COALESCE((NEW.metadata#>>'{transfer,request_fingerprint}') ~ '^[0-9a-f]{64}$',FALSE)
           OR NULLIF(btrim(NEW.metadata#>>'{transfer,value_at}'),'') IS NULL THEN
            RAISE EXCEPTION 'operational transfer classification, provenance, value time, and evidence are required'
                USING ERRCODE='23514';
        END IF;
        BEGIN
            selected_value_at := (NEW.metadata#>>'{transfer,value_at}')::TIMESTAMPTZ;
        EXCEPTION WHEN invalid_datetime_format THEN
            RAISE EXCEPTION 'operational transfer value_at is invalid' USING ERRCODE='23514';
        END;
        IF selected_value_at<source_account.opened_at OR selected_value_at<destination_account.opened_at
           OR (source_account.closed_at IS NOT NULL AND selected_value_at>source_account.closed_at)
           OR (destination_account.closed_at IS NOT NULL AND selected_value_at>destination_account.closed_at) THEN
            RAISE EXCEPTION 'operational transfer value_at falls outside account lifetime' USING ERRCODE='23514';
        END IF;
    ELSIF NEW.event_type_code='FINANCIAL_FACT_REVERSED' AND NEW.original_event_id IS NOT NULL THEN
        SELECT event_type_code INTO original_type FROM public.financial_events
        WHERE tenant_id=NEW.tenant_id AND id=NEW.original_event_id;
        IF original_type='VALUE_TRANSFERRED' THEN
            IF NEW.evidence_hash IS NULL OR jsonb_typeof(NEW.metadata->'transfer_reversal') IS DISTINCT FROM 'object'
               OR jsonb_typeof(NEW.metadata#>'{transfer_reversal,evidence_payload}') IS DISTINCT FROM 'object'
               OR NEW.metadata#>'{transfer_reversal,evidence_payload}'='{}'::jsonb
               OR COALESCE(NEW.metadata#>>'{transfer_reversal,provenance}','')<>'compensating_reversal'
               OR NOT COALESCE((NEW.metadata#>>'{transfer_reversal,request_fingerprint}') ~ '^[0-9a-f]{64}$',FALSE)
               OR NULLIF(btrim(NEW.metadata#>>'{transfer_reversal,value_at}'),'') IS NULL THEN
                RAISE EXCEPTION 'operational transfer reversal evidence and value time are required' USING ERRCODE='23514';
            END IF;
            BEGIN
                selected_value_at := (NEW.metadata#>>'{transfer_reversal,value_at}')::TIMESTAMPTZ;
            EXCEPTION WHEN invalid_datetime_format THEN
                RAISE EXCEPTION 'operational transfer reversal value_at is invalid' USING ERRCODE='23514';
            END;
        END IF;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER tr_financial_events_m61_transfer_validate
BEFORE INSERT ON public.financial_events
FOR EACH ROW EXECUTE FUNCTION public.xbos_validate_operational_transfer_event();

CREATE INDEX ix_m61_financial_events_source_occurred
    ON public.financial_events(tenant_id,organization_unit_id,source_operational_account_id,occurred_at,id)
    WHERE source_operational_account_id IS NOT NULL;
CREATE INDEX ix_m61_financial_events_target_occurred
    ON public.financial_events(tenant_id,organization_unit_id,target_operational_account_id,occurred_at,id)
    WHERE target_operational_account_id IS NOT NULL;

CREATE VIEW public.operational_account_reconciliation_series AS
SELECT a.tenant_id,a.organization_unit_id,a.operational_account_id,
       'balance_anchor'::TEXT AS fact_kind,a.public_id AS fact_public_id,NULL::UUID AS original_fact_public_id,
       a.anchor_at AS fact_at,a.anchor_at AS value_at,a.recorded_at,10 AS sort_rank,
       'anchor'::TEXT AS direction,a.anchor_balance AS amount,NULL::NUMERIC(24,8) AS effect_amount,
       a.anchor_balance AS balance_snapshot,a.currency_code,a.provenance,a.evidence_hash,
       a.correlation_id,NULL::UUID AS causation_id,a.source_record_id::TEXT AS source_reference,a.metadata
FROM public.operational_account_balance_anchors a
UNION ALL
SELECT o.tenant_id,o.organization_unit_id,o.operational_account_id,
       'actual_observation'::TEXT,o.public_id,NULL::UUID,o.observed_at,o.observed_at,o.recorded_at,30,
       'observation'::TEXT,o.actual_balance,NULL::NUMERIC(24,8),o.actual_balance,o.currency_code,o.provenance,
       o.evidence_hash,o.correlation_id,NULL::UUID,o.source_record_id::TEXT,o.metadata
FROM public.operational_account_balance_observations o
UNION ALL
SELECT fe.tenant_id,fe.organization_unit_id,side.operational_account_id,
       CASE WHEN fe.event_type_code='VALUE_TRANSFERRED' THEN 'transfer' ELSE 'transfer_reversal' END::TEXT,
       fe.public_id,original.public_id,fe.occurred_at,
       COALESCE(NULLIF(CASE WHEN fe.event_type_code='VALUE_TRANSFERRED'
           THEN fe.metadata#>>'{transfer,value_at}' ELSE fe.metadata#>>'{transfer_reversal,value_at}' END,'')::TIMESTAMPTZ,fe.occurred_at),
       fe.recorded_at,20,side.direction,fe.amount,side.effect_amount,NULL::NUMERIC(24,8),fe.currency_code,
       COALESCE(CASE WHEN fe.event_type_code='VALUE_TRANSFERRED' THEN fe.metadata#>>'{transfer,provenance}'
                     ELSE fe.metadata#>>'{transfer_reversal,provenance}' END,'unspecified'),
       fe.evidence_hash,fe.correlation_id,fe.causation_id,fe.source_record_id::TEXT,fe.metadata
FROM public.financial_events fe
LEFT JOIN public.financial_events original
  ON original.tenant_id=fe.tenant_id AND original.id=fe.original_event_id
CROSS JOIN LATERAL (VALUES
    (fe.source_operational_account_id,'outflow'::TEXT,-fe.amount),
    (fe.target_operational_account_id,'inflow'::TEXT,fe.amount)
) side(operational_account_id,direction,effect_amount)
WHERE fe.event_type_code='VALUE_TRANSFERRED'
   OR (fe.event_type_code='FINANCIAL_FACT_REVERSED' AND original.event_type_code='VALUE_TRANSFERRED');
