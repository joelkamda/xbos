DROP TRIGGER IF EXISTS trg_so6_workflow_history_immutable ON public.so6_workflow_history;
DROP FUNCTION IF EXISTS public.so6_history_immutable();
DROP TABLE IF EXISTS public.so6_workflow_history;
DROP TABLE IF EXISTS public.so6_operational_approvals;
DROP TABLE IF EXISTS public.so6_workflow_tasks;
DROP TABLE IF EXISTS public.so6_workflows;
DROP TABLE IF EXISTS public.so6_workflow_commands;
