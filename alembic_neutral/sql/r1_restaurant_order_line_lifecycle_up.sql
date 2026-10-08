ALTER TABLE public.r1_restaurant_order_lines
 ADD COLUMN IF NOT EXISTS lifecycle_status text;

UPDATE public.r1_restaurant_order_lines
 SET lifecycle_status='active'
 WHERE lifecycle_status IS NULL;

ALTER TABLE public.r1_restaurant_order_lines
 ALTER COLUMN lifecycle_status SET DEFAULT 'active',
 ALTER COLUMN lifecycle_status SET NOT NULL;

DO $$ BEGIN
 IF NOT EXISTS (
  SELECT 1 FROM pg_constraint
  WHERE conname='ck_r1_order_line_lifecycle_status'
    AND conrelid='public.r1_restaurant_order_lines'::regclass
 ) THEN
  ALTER TABLE public.r1_restaurant_order_lines
   ADD CONSTRAINT ck_r1_order_line_lifecycle_status
   CHECK(lifecycle_status IN('active','removed'));
 END IF;
END $$;
