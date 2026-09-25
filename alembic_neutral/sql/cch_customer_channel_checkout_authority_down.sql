DROP TRIGGER IF EXISTS trg_cc_confirmation_immutable
    ON public.restaurant_customer_order_confirmations;
DROP FUNCTION IF EXISTS public.restaurant_customer_confirmation_immutable();

DROP TABLE IF EXISTS public.restaurant_customer_order_confirmations;
DROP TABLE IF EXISTS public.restaurant_customer_delivery_policies;
