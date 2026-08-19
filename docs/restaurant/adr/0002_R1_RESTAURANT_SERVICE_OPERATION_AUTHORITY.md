# ADR 0002 — R1 Restaurant Service Operation Authority

Decision: introduce a Restaurant-pack runtime authority for service sessions, operational orders and tabs while consuming, rather than duplicating, frozen PC/SO/Finance authorities.

Key rules: service modes are configurable; table identity remains SO5; reservations remain SO10; order lines reference SO1 and retain commercial snapshots; staff references PC2/PC5; tabs express operational grouping and split intent only; R1 performs no stock mutation; Finance handoff is declarative and creates no financial truth.
