# PC7 Neutral Interaction Authority

PC7 registers the accepted IA0 neutral-interaction authority as a first-class Platform Core authority. The A1 contract foundation and A2 persistence foundation are accepted, and PC7 full Platform release registration is now materialized and frozen without adding interaction behavior.

The canonical public facade is `core.platform.interaction`. PC7 owns exactly ten public business primitives: `ExternalChannelIdentity`, `Conversation`, `ConversationParticipant`, `InteractionSession`, `InteractionMessage`, `InteractionIntent`, `InteractionHandoff`, `InteractionEvent`, `InteractionCapabilityGrant`, and `InteractionContextBinding`. `ia0_commands` is internal command-ledger persistence and is not an eleventh business primitive.

The existing persistence revision is `ia0_neutral_interaction_authority_045`, whose parent is `r63_legacy_inventory_writer_compat_044`. PC7 release registration creates no new migration and changes no schema or database state.

PC7 owns neutral interaction truth only. Party remains PC2; authentication and employee membership remain PC5; generalized workflow/task remains SO6; document/file truth remains SO7; transport/delivery remains SO8; payment economic truth remains Neutral Finance; provider execution remains XafPay Gateway; domain business truth remains its domain owner; the frontend owns no business truth. Public authority references preserve those boundaries instead of importing their private implementations.

AI is a first-class interaction participant and proposer, never a business authority. It may classify, extract, summarize, propose intent or command parameters, request domain action, generate a response proposal, observe scoped context, and request human review. It may not declare authentication or payment success, self-grant capability, write Finance/inventory/domain tables, fuzzy-create Party identity, or bypass public domain contracts.

PC7 is additive. It retires no legacy authority and therefore adds no reference-authority migration entry. Its dependency-policy node is `interaction: []`; reference contracts are not code dependencies. The frozen PC6 public-contract inventory remains PC1–PC5 only because PC7 is a post-PC6 authority.

`pc7_release_manifest.json`, the PC7 cumulative release proof, operator install/acceptance surfaces, descendant lineage propagation, and Platform release freeze are registered under PC7 full Platform release. `IA0-A3=NOT_YET_REPOSITORY_AUTHORITY`; no repository authority currently defines or authorizes A3.
