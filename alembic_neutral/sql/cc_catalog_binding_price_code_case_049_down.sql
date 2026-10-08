ALTER TABLE public.restaurant_customer_catalog_read_bindings
    DROP CONSTRAINT ck_cc_catalog_binding_price_code;

ALTER TABLE public.restaurant_customer_catalog_read_bindings
    ADD CONSTRAINT ck_cc_catalog_binding_price_code
    CHECK(
        price_code=lower(btrim(price_code))
        AND length(price_code)>0
    );
