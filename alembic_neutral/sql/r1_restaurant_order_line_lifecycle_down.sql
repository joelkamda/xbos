DO $$ BEGIN
 IF EXISTS (
  SELECT 1 FROM public.r1_restaurant_order_lines
  WHERE lifecycle_status='removed'
 ) THEN
  RAISE EXCEPTION
   'r1_restaurant_order_line_lifecycle_046 downgrade refused: removed order-line history exists'
   USING ERRCODE='23514';
 END IF;
END $$;

ALTER TABLE public.r1_restaurant_order_lines
 DROP CONSTRAINT IF EXISTS ck_r1_order_line_lifecycle_status;

ALTER TABLE public.r1_restaurant_order_lines
 DROP COLUMN IF EXISTS lifecycle_status;
