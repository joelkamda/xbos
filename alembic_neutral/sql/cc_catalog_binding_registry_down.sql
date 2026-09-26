DROP TRIGGER IF EXISTS trg_cc_catalog_read_binding_validate
ON public.restaurant_customer_catalog_read_bindings;

DROP FUNCTION IF EXISTS public.cc_validate_catalog_read_binding();

DROP TABLE IF EXISTS public.restaurant_customer_catalog_read_bindings;
