# R4 — Restaurant Pack Registration

R4 turns the accepted R0-R3 Restaurant capability into an immutable **PK industry pack** without moving any underlying authority into Restaurant.

## Identity

- Pack: `industry.restaurant`
- Version: `1.0.0`
- Kind: `industry`
- Owner: `restaurant`
- Database migration: **NONE**
- Canonical schema head remains `r2_restaurant_menu_fulfillment_043`.

## What is registered

R4 registers the global Restaurant pack version through `PackAuthority.register` and certifies it through `PK456Authority.certify`. Restaurant itself never writes PK tables. The persisted development proof is limited to the global pack version and its immutable certification; tenant installation and activation are reserved for R5.

The manifest composes required authorities for Party, semantics, operating context, security, catalog, inventory, resources, and Neutral Finance. Communications/documents/reporting/scheduling remain optional composition capabilities.

## Semantic contribution

R4 declares the pack-owned `restaurant` namespace and open taxonomy systems for service mode, fulfillment station, course, and charge nature. These are contributions **through PC3/SC41**. R4 does not insert semantic rows directly and does not close the Restaurant model to WND vocabulary.

## Configuration and permissions

Restaurant configuration keys are declared for PC4. R4 deliberately supplies no universal operational values: table use, reservations, course firing, output delivery, tips, commissions, and enabled service modes are template/tenant decisions. Permission codes are references for PC5; R4 does not grant permissions.

## Experience composition

XA receives presentation-only workspace/navigation candidates. No frontend route, composition engine, or UI implementation is added. Tables are explicitly optional.

## Finance and shared authority

R3 remains a mapping layer into Neutral Finance. R4 adds only a Finance conformance reference. SO1, SO3, SO5, SO8, SO9 and SO10 remain their existing authorities.

## WND

WND remains a production specimen, not the Restaurant standard. R4 performs no WND tenant installation and no production cutover. R5 is responsible for proving template/tenant composition; R6 is the later cutover milestone.
