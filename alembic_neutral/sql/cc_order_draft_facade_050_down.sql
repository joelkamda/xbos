DROP TRIGGER IF EXISTS trg_cc_order_draft_line_validate ON public.restaurant_customer_order_draft_lines;
DROP FUNCTION IF EXISTS public.cc_validate_order_draft_line();

DROP TRIGGER IF EXISTS trg_cc_order_draft_validate ON public.restaurant_customer_order_drafts;
DROP FUNCTION IF EXISTS public.cc_validate_order_draft_binding();

DROP TABLE IF EXISTS public.restaurant_customer_order_command_results;
DROP TABLE IF EXISTS public.restaurant_customer_order_draft_lines;
DROP TABLE IF EXISTS public.restaurant_customer_order_drafts;
