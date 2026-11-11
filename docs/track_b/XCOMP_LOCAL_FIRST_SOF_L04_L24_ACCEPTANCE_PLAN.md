# SOF L04?L24 offline acceptance requirements
L04 tenant B Finance denial; L08 offline cash posting exactly once; L09
provider-finality absent; L10 replay/no double posting; L11 dual writer fence;
L15/L16 isolated encrypted restore and device replacement; L21 seven-day
WAN outage and reconnect; L22 local delegated admin audit; L24 cloud/local
identical ledger idempotency. Every live test needs a separate PG17 sandbox
and physical WAN-offline evidence. Current tests are synthetic only.
