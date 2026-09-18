# ADR 0011 — PC7 neutral interaction authority registration

Status: PC7 full Platform release registered and approved freeze materialized.

PC7 adopts the already accepted IA0 A1 contract and A2 persistence foundations as the Platform Core `NEUTRAL_INTERACTION_AUTHORITY`. The canonical module is `interaction`, exposed through `core.platform.interaction`. This decision adds platform registration only; it does not redesign `contracts.py`, `sql_repository.py`, `__init__.py`, or interaction behavior.

PC7 owns ten canonical business primitives: ExternalChannelIdentity, Conversation, ConversationParticipant, InteractionSession, InteractionMessage, InteractionIntent, InteractionHandoff, InteractionEvent, InteractionCapabilityGrant, and InteractionContextBinding. The `ia0_commands` table is an internal command ledger, not a public business primitive. The accepted schema revision remains `ia0_neutral_interaction_authority_045` with parent `r63_legacy_inventory_writer_compat_044`; no new PC7 release-registration migration is created.

Authority remains external for Party (PC2), authentication and employee membership (PC5), workflow/task (SO6), document/file (SO7), transport/delivery (SO8), financial truth (Neutral Finance), provider execution (XafPay Gateway), and domain business truth (the domain owner). Frontend state is never business truth. Interaction references to those authorities do not transfer ownership.

AI may participate, observe bounded context, classify, summarize and propose actions, but it cannot authenticate, authorize itself, declare payment success, or write domain, inventory or Finance truth. This preserves the A1 proposer/non-authority law.

PC7 is additive and has no legacy authority retirement, so the PC0 reference-authority migration register is unchanged. The dependency policy registers `interaction: []` only; no conceptual dependency is encoded as a code dependency. The historical PC6 public-contract inventory remains unchanged and continues to enumerate PC1–PC5 only.

PC7 full Platform release now includes the release manifest, cumulative release proof, operator acceptance surfaces, and exact descendant fingerprint propagation. A3 remains `NOT_YET_REPOSITORY_AUTHORITY` and is not authorized by this decision.
