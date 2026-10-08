DROP TRIGGER IF EXISTS trg_ia0_event_append_only ON public.ia0_interaction_events;
DROP TRIGGER IF EXISTS trg_ia0_message_append_only ON public.ia0_interaction_messages;
DROP FUNCTION IF EXISTS public.ia0_reject_append_only_mutation();

DROP TABLE IF EXISTS public.ia0_interaction_events;
DROP TABLE IF EXISTS public.ia0_interaction_context_bindings;
DROP TABLE IF EXISTS public.ia0_interaction_capability_grants;
DROP TABLE IF EXISTS public.ia0_interaction_handoffs;
DROP TABLE IF EXISTS public.ia0_interaction_intents;
DROP TABLE IF EXISTS public.ia0_interaction_messages;
DROP TABLE IF EXISTS public.ia0_interaction_sessions;
DROP TABLE IF EXISTS public.ia0_conversation_participants;
DROP TABLE IF EXISTS public.ia0_conversations;
DROP TABLE IF EXISTS public.ia0_external_channel_identities;
DROP TABLE IF EXISTS public.ia0_commands;
