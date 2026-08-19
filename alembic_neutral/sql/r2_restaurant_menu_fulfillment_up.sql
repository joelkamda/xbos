CREATE TABLE public.r2_restaurant_commands(
 id bigserial PRIMARY KEY,
 tenant_id bigint NOT NULL REFERENCES public.tenants(id),
 command_key varchar(180) NOT NULL,
 request_fingerprint char(64) NOT NULL,
 command_type varchar(96) NOT NULL,
 result_type varchar(96),
 result_public_id uuid,
 created_at timestamptz NOT NULL DEFAULT now(),
 completed_at timestamptz,
 UNIQUE(tenant_id,command_key),
 CHECK(request_fingerprint~'^[0-9a-f]{64}$')
);

CREATE TABLE public.r2_restaurant_menu_sections(
 id bigserial PRIMARY KEY,
 public_id uuid NOT NULL DEFAULT gen_random_uuid(),
 tenant_id bigint NOT NULL,
 catalog_id bigint NOT NULL,
 section_code varchar(120) NOT NULL,
 display_name varchar(240) NOT NULL,
 sort_order integer NOT NULL DEFAULT 0,
 effective_from timestamptz NOT NULL,
 effective_to timestamptz,
 active boolean NOT NULL DEFAULT true,
 metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
 row_version integer NOT NULL DEFAULT 1,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 CONSTRAINT uq_r2_menu_section_public UNIQUE(tenant_id,public_id),
 CONSTRAINT uq_r2_menu_section_tenant_id UNIQUE(tenant_id,id),
 CONSTRAINT uq_r2_menu_section_code UNIQUE(tenant_id,catalog_id,section_code,effective_from),
 FOREIGN KEY(tenant_id,catalog_id) REFERENCES public.so1_catalogs(tenant_id,id),
 CHECK(section_code=lower(btrim(section_code)) AND length(section_code)>0),
 CHECK(length(btrim(display_name))>0),
 CHECK(effective_to IS NULL OR effective_to>effective_from),
 CHECK(jsonb_typeof(metadata)='object'), CHECK(row_version>=1)
);

CREATE TABLE public.r2_restaurant_menu_section_entries(
 id bigserial PRIMARY KEY,
 tenant_id bigint NOT NULL,
 section_id bigint NOT NULL,
 catalog_entry_public_id uuid NOT NULL REFERENCES public.so1_catalog_entries(public_id),
 sort_order integer NOT NULL DEFAULT 0,
 effective_from timestamptz NOT NULL,
 effective_to timestamptz,
 created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(tenant_id,section_id) REFERENCES public.r2_restaurant_menu_sections(tenant_id,id),
 UNIQUE(tenant_id,section_id,catalog_entry_public_id,effective_from),
 CHECK(effective_to IS NULL OR effective_to>effective_from)
);

CREATE TABLE public.r2_restaurant_modifier_groups(
 id bigserial PRIMARY KEY,
 public_id uuid NOT NULL DEFAULT gen_random_uuid(),
 tenant_id bigint NOT NULL REFERENCES public.tenants(id),
 group_code varchar(120) NOT NULL,
 display_name varchar(240) NOT NULL,
 selection_mode varchar(16) NOT NULL,
 minimum_selections integer NOT NULL DEFAULT 0,
 maximum_selections integer NOT NULL DEFAULT 1,
 effective_from timestamptz NOT NULL,
 effective_to timestamptz,
 active boolean NOT NULL DEFAULT true,
 metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
 row_version integer NOT NULL DEFAULT 1,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 CONSTRAINT uq_r2_modifier_group_public UNIQUE(tenant_id,public_id),
 CONSTRAINT uq_r2_modifier_group_tenant_id UNIQUE(tenant_id,id),
 CONSTRAINT uq_r2_modifier_group_code UNIQUE(tenant_id,group_code,effective_from),
 CHECK(group_code=lower(btrim(group_code)) AND length(group_code)>0),
 CHECK(length(btrim(display_name))>0),
 CHECK(selection_mode IN('single','multiple','quantity')),
 CHECK(minimum_selections>=0 AND maximum_selections>=1 AND maximum_selections>=minimum_selections),
 CHECK(selection_mode<>'single' OR maximum_selections=1),
 CHECK(effective_to IS NULL OR effective_to>effective_from),
 CHECK(jsonb_typeof(metadata)='object'), CHECK(row_version>=1)
);

CREATE TABLE public.r2_restaurant_modifier_options(
 id bigserial PRIMARY KEY,
 public_id uuid NOT NULL DEFAULT gen_random_uuid(),
 tenant_id bigint NOT NULL,
 modifier_group_id bigint NOT NULL,
 option_code varchar(120) NOT NULL,
 display_name varchar(240) NOT NULL,
 effect_type varchar(16) NOT NULL,
 target_type varchar(16),
 atomic_unit_id integer,
 offer_id bigint,
 price_id bigint REFERENCES public.so1_prices(id),
 default_quantity numeric(18,6) NOT NULL DEFAULT 1,
 preparation_instruction text,
 sort_order integer NOT NULL DEFAULT 0,
 active boolean NOT NULL DEFAULT true,
 metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
 created_at timestamptz NOT NULL DEFAULT now(),
 CONSTRAINT uq_r2_modifier_option_public UNIQUE(tenant_id,public_id),
 CONSTRAINT uq_r2_modifier_option_tenant_id UNIQUE(tenant_id,id),
 CONSTRAINT uq_r2_modifier_option_code UNIQUE(tenant_id,modifier_group_id,option_code),
 FOREIGN KEY(tenant_id,modifier_group_id) REFERENCES public.r2_restaurant_modifier_groups(tenant_id,id),
 FOREIGN KEY(tenant_id,atomic_unit_id) REFERENCES public.atomic_units(tenant_id,id),
 FOREIGN KEY(tenant_id,offer_id) REFERENCES public.so1_offers(tenant_id,id),
 CHECK(option_code=lower(btrim(option_code)) AND length(option_code)>0),
 CHECK(length(btrim(display_name))>0),
 CHECK(effect_type IN('add','remove','replace','instruction')),
 CHECK((target_type IS NULL AND atomic_unit_id IS NULL AND offer_id IS NULL) OR
       (target_type='atomic_unit' AND atomic_unit_id IS NOT NULL AND offer_id IS NULL) OR
       (target_type='offer' AND offer_id IS NOT NULL AND atomic_unit_id IS NULL)),
 CHECK(effect_type='instruction' OR target_type IS NOT NULL),
 CHECK(price_id IS NULL OR target_type IS NOT NULL),
 CHECK(default_quantity>0), CHECK(jsonb_typeof(metadata)='object')
);

CREATE TABLE public.r2_restaurant_menu_entry_modifier_groups(
 id bigserial PRIMARY KEY,
 tenant_id bigint NOT NULL,
 catalog_entry_public_id uuid NOT NULL REFERENCES public.so1_catalog_entries(public_id),
 modifier_group_id bigint NOT NULL,
 sequence integer NOT NULL DEFAULT 0,
 effective_from timestamptz NOT NULL,
 effective_to timestamptz,
 created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(tenant_id,modifier_group_id) REFERENCES public.r2_restaurant_modifier_groups(tenant_id,id),
 UNIQUE(tenant_id,catalog_entry_public_id,modifier_group_id,effective_from),
 CHECK(effective_to IS NULL OR effective_to>effective_from)
);

CREATE TABLE public.r2_restaurant_order_line_modifier_sets(
 id bigserial PRIMARY KEY,
 public_id uuid NOT NULL DEFAULT gen_random_uuid(),
 tenant_id bigint NOT NULL,
 order_line_id bigint NOT NULL,
 selection_version integer NOT NULL,
 created_at timestamptz NOT NULL,
 created_by_party_id bigint,
 CONSTRAINT uq_r2_modifier_set_public UNIQUE(tenant_id,public_id),
 CONSTRAINT uq_r2_modifier_set_tenant_id UNIQUE(tenant_id,id),
 UNIQUE(tenant_id,order_line_id,selection_version),
 FOREIGN KEY(tenant_id,order_line_id) REFERENCES public.r1_restaurant_order_lines(tenant_id,id),
 FOREIGN KEY(tenant_id,created_by_party_id) REFERENCES public.parties(tenant_id,id),
 CHECK(selection_version>=1)
);

CREATE TABLE public.r2_restaurant_order_line_modifier_items(
 id bigserial PRIMARY KEY,
 tenant_id bigint NOT NULL,
 modifier_set_id bigint NOT NULL,
 modifier_group_id bigint NOT NULL,
 modifier_option_id bigint NOT NULL,
 quantity numeric(18,6) NOT NULL,
 price_amount_snapshot numeric(18,6) NOT NULL DEFAULT 0,
 currency char(3),
 instruction_snapshot text,
 created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(tenant_id,modifier_set_id) REFERENCES public.r2_restaurant_order_line_modifier_sets(tenant_id,id),
 FOREIGN KEY(tenant_id,modifier_group_id) REFERENCES public.r2_restaurant_modifier_groups(tenant_id,id),
 FOREIGN KEY(tenant_id,modifier_option_id) REFERENCES public.r2_restaurant_modifier_options(tenant_id,id),
 UNIQUE(tenant_id,modifier_set_id,modifier_group_id,modifier_option_id),
 CHECK(quantity>0), CHECK(price_amount_snapshot>=0),
 CHECK(currency IS NULL OR (currency=upper(currency) AND currency~'^[A-Z]{3}$'))
);

CREATE TABLE public.r2_restaurant_station_profiles(
 id bigserial PRIMARY KEY,
 public_id uuid NOT NULL DEFAULT gen_random_uuid(),
 tenant_id bigint NOT NULL,
 resource_id bigint NOT NULL,
 station_code varchar(120) NOT NULL,
 display_name varchar(240) NOT NULL,
 station_kind varchar(24) NOT NULL,
 output_channel_code varchar(120),
 destination_reference varchar(500),
 active boolean NOT NULL DEFAULT true,
 metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
 row_version integer NOT NULL DEFAULT 1,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 CONSTRAINT uq_r2_station_public UNIQUE(tenant_id,public_id),
 CONSTRAINT uq_r2_station_tenant_id UNIQUE(tenant_id,id),
 UNIQUE(tenant_id,resource_id), UNIQUE(tenant_id,station_code),
 FOREIGN KEY(tenant_id,resource_id) REFERENCES public.so5_resources(tenant_id,id),
 CHECK(station_code=lower(btrim(station_code)) AND length(station_code)>0),
 CHECK(length(btrim(display_name))>0),
 CHECK(station_kind IN('kitchen','bar','expo','pastry','prep','beverage','pickup','other')),
 CHECK(output_channel_code IS NULL OR (output_channel_code=lower(btrim(output_channel_code)) AND length(output_channel_code)>0)),
 CHECK(jsonb_typeof(metadata)='object'), CHECK(row_version>=1)
);

CREATE TABLE public.r2_restaurant_routing_rules(
 id bigserial PRIMARY KEY,
 public_id uuid NOT NULL DEFAULT gen_random_uuid(),
 tenant_id bigint NOT NULL REFERENCES public.tenants(id),
 rule_code varchar(160) NOT NULL,
 station_profile_id bigint NOT NULL,
 target_type varchar(16),
 atomic_unit_id integer,
 offer_id bigint,
 semantic_reference varchar(240),
 service_mode_id bigint,
 source_channel_code varchar(120),
 course_code varchar(120),
 priority integer NOT NULL DEFAULT 100,
 effective_from timestamptz NOT NULL,
 effective_to timestamptz,
 active boolean NOT NULL DEFAULT true,
 metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
 created_at timestamptz NOT NULL DEFAULT now(),
 CONSTRAINT uq_r2_route_public UNIQUE(tenant_id,public_id),
 CONSTRAINT uq_r2_route_tenant_id UNIQUE(tenant_id,id),
 UNIQUE(tenant_id,rule_code,effective_from),
 FOREIGN KEY(tenant_id,station_profile_id) REFERENCES public.r2_restaurant_station_profiles(tenant_id,id),
 FOREIGN KEY(tenant_id,atomic_unit_id) REFERENCES public.atomic_units(tenant_id,id),
 FOREIGN KEY(tenant_id,offer_id) REFERENCES public.so1_offers(tenant_id,id),
 FOREIGN KEY(tenant_id,service_mode_id) REFERENCES public.r1_restaurant_service_modes(tenant_id,id),
 CHECK(rule_code=lower(btrim(rule_code)) AND length(rule_code)>0),
 CHECK((semantic_reference IS NOT NULL AND target_type IS NULL AND atomic_unit_id IS NULL AND offer_id IS NULL) OR
       (semantic_reference IS NULL AND target_type='atomic_unit' AND atomic_unit_id IS NOT NULL AND offer_id IS NULL) OR
       (semantic_reference IS NULL AND target_type='offer' AND offer_id IS NOT NULL AND atomic_unit_id IS NULL)),
 CHECK(source_channel_code IS NULL OR (source_channel_code=lower(btrim(source_channel_code)) AND length(source_channel_code)>0)),
 CHECK(course_code IS NULL OR (course_code=lower(btrim(course_code)) AND length(course_code)>0)),
 CHECK(effective_to IS NULL OR effective_to>effective_from),
 CHECK(jsonb_typeof(metadata)='object')
);

CREATE TABLE public.r2_restaurant_preparation_specs(
 id bigserial PRIMARY KEY,
 public_id uuid NOT NULL DEFAULT gen_random_uuid(),
 tenant_id bigint NOT NULL REFERENCES public.tenants(id),
 spec_code varchar(160) NOT NULL,
 spec_version integer NOT NULL,
 display_name varchar(240) NOT NULL,
 output_atomic_unit_id integer NOT NULL,
 yield_stock_units bigint NOT NULL,
 lifecycle_status varchar(16) NOT NULL DEFAULT 'active',
 effective_from timestamptz NOT NULL,
 effective_to timestamptz,
 metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
 created_at timestamptz NOT NULL DEFAULT now(),
 CONSTRAINT uq_r2_prep_spec_public UNIQUE(tenant_id,public_id),
 CONSTRAINT uq_r2_prep_spec_tenant_id UNIQUE(tenant_id,id),
 UNIQUE(tenant_id,spec_code,spec_version),
 FOREIGN KEY(tenant_id,output_atomic_unit_id) REFERENCES public.atomic_units(tenant_id,id),
 CHECK(spec_code=lower(btrim(spec_code)) AND length(spec_code)>0),
 CHECK(spec_version>=1), CHECK(length(btrim(display_name))>0), CHECK(yield_stock_units>=1),
 CHECK(lifecycle_status IN('active','retired')), CHECK(effective_to IS NULL OR effective_to>effective_from),
 CHECK(jsonb_typeof(metadata)='object')
);

CREATE TABLE public.r2_restaurant_preparation_components(
 id bigserial PRIMARY KEY,
 tenant_id bigint NOT NULL,
 preparation_spec_id bigint NOT NULL,
 component_type varchar(24) NOT NULL,
 atomic_unit_id integer,
 dependency_spec_id bigint,
 required_stock_units bigint NOT NULL,
 sequence integer NOT NULL DEFAULT 0,
 optional boolean NOT NULL DEFAULT false,
 metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
 created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(tenant_id,preparation_spec_id) REFERENCES public.r2_restaurant_preparation_specs(tenant_id,id),
 FOREIGN KEY(tenant_id,atomic_unit_id) REFERENCES public.atomic_units(tenant_id,id),
 FOREIGN KEY(tenant_id,dependency_spec_id) REFERENCES public.r2_restaurant_preparation_specs(tenant_id,id),
 CHECK((component_type='atomic_unit' AND atomic_unit_id IS NOT NULL AND dependency_spec_id IS NULL) OR
       (component_type='preparation_spec' AND dependency_spec_id IS NOT NULL AND atomic_unit_id IS NULL)),
 CHECK(dependency_spec_id IS NULL OR dependency_spec_id<>preparation_spec_id),
 CHECK(required_stock_units>=1), CHECK(jsonb_typeof(metadata)='object'),
 UNIQUE(tenant_id,preparation_spec_id,component_type,atomic_unit_id,dependency_spec_id,sequence)
);

CREATE TABLE public.r2_restaurant_preparation_tickets(
 id bigserial PRIMARY KEY,
 public_id uuid NOT NULL DEFAULT gen_random_uuid(),
 tenant_id bigint NOT NULL,
 order_id bigint NOT NULL,
 station_profile_id bigint NOT NULL,
 release_command_key varchar(180) NOT NULL,
 ticket_code varchar(180) NOT NULL,
 lifecycle_status varchar(24) NOT NULL,
 course_code varchar(120),
 priority integer NOT NULL DEFAULT 100,
 held boolean NOT NULL DEFAULT false,
 released_at timestamptz NOT NULL,
 fired_at timestamptz,
 completed_at timestamptz,
 voided_at timestamptz,
 row_version integer NOT NULL DEFAULT 1,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 CONSTRAINT uq_r2_ticket_public UNIQUE(tenant_id,public_id),
 CONSTRAINT uq_r2_ticket_tenant_id UNIQUE(tenant_id,id),
 UNIQUE(tenant_id,ticket_code),
 FOREIGN KEY(tenant_id,order_id) REFERENCES public.r1_restaurant_orders(tenant_id,id),
 FOREIGN KEY(tenant_id,station_profile_id) REFERENCES public.r2_restaurant_station_profiles(tenant_id,id),
 FOREIGN KEY(tenant_id,release_command_key) REFERENCES public.r2_restaurant_commands(tenant_id,command_key),
 CHECK(release_command_key=btrim(release_command_key) AND length(release_command_key)>0),
 CHECK(ticket_code=btrim(ticket_code) AND length(ticket_code)>0),
 CHECK(lifecycle_status IN('held','queued','in_progress','partially_ready','ready','completed','voided')),
 CHECK(course_code IS NULL OR (course_code=lower(btrim(course_code)) AND length(course_code)>0)),
 CHECK(row_version>=1)
);

CREATE TABLE public.r2_restaurant_preparation_ticket_items(
 id bigserial PRIMARY KEY,
 public_id uuid NOT NULL DEFAULT gen_random_uuid(),
 tenant_id bigint NOT NULL,
 ticket_id bigint NOT NULL,
 order_line_id bigint NOT NULL,
 modifier_set_id bigint,
 quantity numeric(18,6) NOT NULL,
 lifecycle_status varchar(24) NOT NULL,
 preparation_note text,
 modifier_snapshot jsonb NOT NULL DEFAULT '[]'::jsonb,
 row_version integer NOT NULL DEFAULT 1,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 CONSTRAINT uq_r2_ticket_item_public UNIQUE(tenant_id,public_id),
 CONSTRAINT uq_r2_ticket_item_tenant_id UNIQUE(tenant_id,id),
 FOREIGN KEY(tenant_id,ticket_id) REFERENCES public.r2_restaurant_preparation_tickets(tenant_id,id),
 FOREIGN KEY(tenant_id,order_line_id) REFERENCES public.r1_restaurant_order_lines(tenant_id,id),
 FOREIGN KEY(tenant_id,modifier_set_id) REFERENCES public.r2_restaurant_order_line_modifier_sets(tenant_id,id),
 UNIQUE(tenant_id,ticket_id,order_line_id),
 CHECK(quantity>0), CHECK(lifecycle_status IN('held','queued','in_progress','ready','completed','voided')),
 CHECK(jsonb_typeof(modifier_snapshot)='array'), CHECK(row_version>=1)
);

CREATE TABLE public.r2_restaurant_ticket_item_dependencies(
 id bigserial PRIMARY KEY,
 tenant_id bigint NOT NULL,
 ticket_item_id bigint NOT NULL,
 depends_on_ticket_item_id bigint NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(tenant_id,ticket_item_id) REFERENCES public.r2_restaurant_preparation_ticket_items(tenant_id,id),
 FOREIGN KEY(tenant_id,depends_on_ticket_item_id) REFERENCES public.r2_restaurant_preparation_ticket_items(tenant_id,id),
 UNIQUE(tenant_id,ticket_item_id,depends_on_ticket_item_id),
 CHECK(ticket_item_id<>depends_on_ticket_item_id)
);

CREATE TABLE public.r2_restaurant_ticket_history(
 sequence bigserial PRIMARY KEY,
 tenant_id bigint NOT NULL,
 ticket_id bigint NOT NULL,
 event_type varchar(64) NOT NULL,
 from_status varchar(24),
 to_status varchar(24) NOT NULL,
 reason_code varchar(160) NOT NULL,
 occurred_at timestamptz NOT NULL,
 event_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
 created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(tenant_id,ticket_id) REFERENCES public.r2_restaurant_preparation_tickets(tenant_id,id),
 CHECK(jsonb_typeof(event_payload)='object')
);

CREATE TABLE public.r2_restaurant_ticket_item_history(
 sequence bigserial PRIMARY KEY,
 tenant_id bigint NOT NULL,
 ticket_item_id bigint NOT NULL,
 event_type varchar(64) NOT NULL,
 from_status varchar(24),
 to_status varchar(24) NOT NULL,
 reason_code varchar(160) NOT NULL,
 occurred_at timestamptz NOT NULL,
 event_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
 created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(tenant_id,ticket_item_id) REFERENCES public.r2_restaurant_preparation_ticket_items(tenant_id,id),
 CHECK(jsonb_typeof(event_payload)='object')
);

CREATE TABLE public.r2_restaurant_preparation_runs(
 id bigserial PRIMARY KEY,
 public_id uuid NOT NULL DEFAULT gen_random_uuid(),
 tenant_id bigint NOT NULL,
 preparation_spec_id bigint NOT NULL,
 ticket_item_id bigint,
 lifecycle_status varchar(16) NOT NULL,
 planned_output_units bigint NOT NULL,
 actual_output_units bigint,
 waste_output_units bigint,
 started_at timestamptz NOT NULL,
 completed_at timestamptz,
 row_version integer NOT NULL DEFAULT 1,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 CONSTRAINT uq_r2_prep_run_public UNIQUE(tenant_id,public_id),
 CONSTRAINT uq_r2_prep_run_tenant_id UNIQUE(tenant_id,id),
 FOREIGN KEY(tenant_id,preparation_spec_id) REFERENCES public.r2_restaurant_preparation_specs(tenant_id,id),
 FOREIGN KEY(tenant_id,ticket_item_id) REFERENCES public.r2_restaurant_preparation_ticket_items(tenant_id,id),
 CHECK(lifecycle_status IN('in_progress','completed','voided')),
 CHECK(planned_output_units>=1), CHECK(actual_output_units IS NULL OR actual_output_units>=0),
 CHECK(waste_output_units IS NULL OR waste_output_units>=0),
 CHECK((lifecycle_status='in_progress' AND completed_at IS NULL) OR (lifecycle_status<>'in_progress' AND completed_at IS NOT NULL)),
 CHECK(row_version>=1)
);

CREATE TABLE public.r2_restaurant_preparation_run_inputs(
 id bigserial PRIMARY KEY,
 tenant_id bigint NOT NULL,
 preparation_run_id bigint NOT NULL,
 atomic_unit_id integer NOT NULL,
 planned_stock_units bigint NOT NULL,
 consumed_stock_units bigint,
 waste_stock_units bigint,
 created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(tenant_id,preparation_run_id) REFERENCES public.r2_restaurant_preparation_runs(tenant_id,id),
 FOREIGN KEY(tenant_id,atomic_unit_id) REFERENCES public.atomic_units(tenant_id,id),
 UNIQUE(tenant_id,preparation_run_id,atomic_unit_id),
 CHECK(planned_stock_units>=0), CHECK(consumed_stock_units IS NULL OR consumed_stock_units>=0), CHECK(waste_stock_units IS NULL OR waste_stock_units>=0)
);

CREATE TABLE public.r2_restaurant_preparation_run_history(
 sequence bigserial PRIMARY KEY,
 tenant_id bigint NOT NULL,
 preparation_run_id bigint NOT NULL,
 event_type varchar(64) NOT NULL,
 from_status varchar(16),
 to_status varchar(16) NOT NULL,
 reason_code varchar(160) NOT NULL,
 occurred_at timestamptz NOT NULL,
 event_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
 created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(tenant_id,preparation_run_id) REFERENCES public.r2_restaurant_preparation_runs(tenant_id,id),
 CHECK(jsonb_typeof(event_payload)='object')
);

CREATE INDEX ix_r2_menu_sections_catalog ON public.r2_restaurant_menu_sections(tenant_id,catalog_id,active,sort_order);
CREATE INDEX ix_r2_menu_entries_section ON public.r2_restaurant_menu_section_entries(tenant_id,section_id,sort_order);
CREATE INDEX ix_r2_modifier_sets_line ON public.r2_restaurant_order_line_modifier_sets(tenant_id,order_line_id,selection_version DESC);
CREATE INDEX ix_r2_routes_target ON public.r2_restaurant_routing_rules(tenant_id,target_type,atomic_unit_id,offer_id,active,priority);
CREATE INDEX ix_r2_tickets_order ON public.r2_restaurant_preparation_tickets(tenant_id,order_id,lifecycle_status);
CREATE INDEX ix_r2_tickets_release_command ON public.r2_restaurant_preparation_tickets(tenant_id,release_command_key,id);
CREATE INDEX ix_r2_ticket_items_ticket ON public.r2_restaurant_preparation_ticket_items(tenant_id,ticket_id,lifecycle_status);
CREATE INDEX ix_r2_prep_specs_output ON public.r2_restaurant_preparation_specs(tenant_id,output_atomic_unit_id,lifecycle_status,effective_from);
CREATE INDEX ix_r2_prep_runs_spec ON public.r2_restaurant_preparation_runs(tenant_id,preparation_spec_id,lifecycle_status,started_at);

CREATE OR REPLACE FUNCTION public.r2_validate_catalog_entry_tenant() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE actual_tenant bigint; entry_catalog bigint; section_catalog bigint;
BEGIN
 SELECT tenant_id,catalog_id INTO actual_tenant,entry_catalog FROM public.so1_catalog_entries WHERE public_id=NEW.catalog_entry_public_id;
 IF actual_tenant IS NULL OR actual_tenant<>NEW.tenant_id THEN RAISE EXCEPTION 'R2_CATALOG_ENTRY_TENANT_MISMATCH'; END IF;
 IF TG_TABLE_NAME='r2_restaurant_menu_section_entries' THEN
   SELECT catalog_id INTO section_catalog FROM public.r2_restaurant_menu_sections WHERE tenant_id=NEW.tenant_id AND id=NEW.section_id;
   IF section_catalog IS NULL OR section_catalog<>entry_catalog THEN RAISE EXCEPTION 'R2_MENU_ENTRY_CATALOG_MISMATCH'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER trg_r2_menu_section_entry_tenant BEFORE INSERT OR UPDATE ON public.r2_restaurant_menu_section_entries FOR EACH ROW EXECUTE FUNCTION public.r2_validate_catalog_entry_tenant();
CREATE TRIGGER trg_r2_menu_modifier_entry_tenant BEFORE INSERT OR UPDATE ON public.r2_restaurant_menu_entry_modifier_groups FOR EACH ROW EXECUTE FUNCTION public.r2_validate_catalog_entry_tenant();

CREATE OR REPLACE FUNCTION public.r2_validate_modifier_option_authorities() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE actual_tenant bigint; price_tenant bigint; price_type varchar(16); price_atomic integer; price_offer bigint;
BEGIN
 IF NEW.target_type='atomic_unit' THEN SELECT tenant_id INTO actual_tenant FROM public.atomic_units WHERE id=NEW.atomic_unit_id;
 ELSIF NEW.target_type='offer' THEN SELECT tenant_id INTO actual_tenant FROM public.so1_offers WHERE id=NEW.offer_id;
 ELSE actual_tenant:=NEW.tenant_id; END IF;
 IF actual_tenant IS NULL OR actual_tenant<>NEW.tenant_id THEN RAISE EXCEPTION 'R2_MODIFIER_TARGET_TENANT_MISMATCH'; END IF;
 IF NEW.price_id IS NOT NULL THEN
   SELECT tenant_id,target_type,atomic_unit_id,offer_id INTO price_tenant,price_type,price_atomic,price_offer FROM public.so1_prices WHERE id=NEW.price_id;
   IF price_tenant IS NULL OR price_tenant<>NEW.tenant_id THEN RAISE EXCEPTION 'R2_MODIFIER_PRICE_TENANT_MISMATCH'; END IF;
   IF price_type<>NEW.target_type OR (price_type='atomic_unit' AND price_atomic<>NEW.atomic_unit_id) OR (price_type='offer' AND price_offer<>NEW.offer_id) THEN RAISE EXCEPTION 'R2_MODIFIER_PRICE_TARGET_MISMATCH'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER trg_r2_modifier_option_authority BEFORE INSERT OR UPDATE ON public.r2_restaurant_modifier_options FOR EACH ROW EXECUTE FUNCTION public.r2_validate_modifier_option_authorities();

CREATE OR REPLACE FUNCTION public.r2_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'R2 restaurant evidence is append-only'; END $$;
CREATE TRIGGER trg_r2_modifier_sets_immutable BEFORE UPDATE OR DELETE ON public.r2_restaurant_order_line_modifier_sets FOR EACH ROW EXECUTE FUNCTION public.r2_append_only();
CREATE TRIGGER trg_r2_modifier_items_immutable BEFORE UPDATE OR DELETE ON public.r2_restaurant_order_line_modifier_items FOR EACH ROW EXECUTE FUNCTION public.r2_append_only();
CREATE TRIGGER trg_r2_ticket_history_immutable BEFORE UPDATE OR DELETE ON public.r2_restaurant_ticket_history FOR EACH ROW EXECUTE FUNCTION public.r2_append_only();
CREATE TRIGGER trg_r2_ticket_item_history_immutable BEFORE UPDATE OR DELETE ON public.r2_restaurant_ticket_item_history FOR EACH ROW EXECUTE FUNCTION public.r2_append_only();
CREATE TRIGGER trg_r2_prep_run_history_immutable BEFORE UPDATE OR DELETE ON public.r2_restaurant_preparation_run_history FOR EACH ROW EXECUTE FUNCTION public.r2_append_only();

COMMENT ON TABLE public.r2_restaurant_menu_sections IS 'Restaurant presentation sections over SO1 catalog authority; never a duplicate catalog.';
COMMENT ON TABLE public.r2_restaurant_modifier_groups IS 'Restaurant modifier selection semantics; commercial target and prices remain SO1.';
COMMENT ON TABLE public.r2_restaurant_preparation_tickets IS 'Kitchen/bar preparation intent and state; SO8 owns durable delivery jobs and devices.';
COMMENT ON TABLE public.r2_restaurant_preparation_specs IS 'Restaurant recipe/preparation semantics; SO3 owns stock movement and valuation remains outside Restaurant.';
