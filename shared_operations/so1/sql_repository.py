"""Private SQL persistence adapter for SO1."""

from __future__ import annotations

import json
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from .contracts import (
    AtomicUnit, Catalog, ComponentRule, CreateAtomicUnit, CreateCatalog, CreateOffer,
    DefinePrice, Offer, OfferComponent, Price, PublishCatalogEntry, ResolvePrice,
    ScopeType, TargetType, UpdateAtomicUnit, UpdateOffer,
)


class SQLSO1Repository:
    def __init__(self, session: Session): self._session = session

    @staticmethod
    def _unit(row) -> AtomicUnit:
        return AtomicUnit(row.id, row.public_id, row.tenant_id, row.sku, row.name, row.unit_type, row.is_active, row.meta or {}, row.row_version)

    @staticmethod
    def _catalog(row) -> Catalog:
        return Catalog(row.id, row.public_id, row.tenant_id, row.code, row.name, ScopeType(row.scope_type), row.scope_id, row.active, row.effective_from, row.effective_to, row.row_version)

    @staticmethod
    def _price(row) -> Price:
        return Price(row.id, row.public_id, row.tenant_id, TargetType(row.target_type), row.target_public_id, row.price_code, row.amount, row.currency, ScopeType(row.scope_type), row.scope_id, row.precedence, row.effective_from, row.effective_to, row.active, row.row_version)

    def create_atomic_unit(self, command: CreateAtomicUnit, public_id: UUID) -> AtomicUnit:
        row = self._session.execute(text("""INSERT INTO atomic_units(public_id,tenant_id,name,sku,unit_type,is_active,meta,row_version)
            VALUES(:public_id,:tenant_id,:name,:code,:kind,true,CAST(:metadata AS jsonb),1)
            RETURNING id,public_id,tenant_id,sku,name,unit_type,is_active,meta,row_version"""),
            {"public_id":public_id,"tenant_id":command.tenant_id,"name":command.name.strip(),"code":command.code.strip(),"kind":command.unit_kind,"metadata":json.dumps(command.metadata or {})}).one()
        return self._unit(row)

    def atomic_unit(self, tenant_id: int, public_id: UUID) -> AtomicUnit | None:
        row = self._session.execute(text("SELECT id,public_id,tenant_id,sku,name,unit_type,is_active,meta,row_version FROM atomic_units WHERE tenant_id=:tenant AND public_id=:public_id"),{"tenant":tenant_id,"public_id":public_id}).one_or_none()
        return self._unit(row) if row else None

    def update_atomic_unit(self, command: UpdateAtomicUnit) -> AtomicUnit | None:
        row = self._session.execute(text("""UPDATE atomic_units SET name=COALESCE(:name,name),unit_type=COALESCE(:kind,unit_type),
            meta=COALESCE(CAST(:metadata AS jsonb),meta),updated_at=now(),row_version=row_version+1
            WHERE tenant_id=:tenant AND public_id=:public_id AND row_version=:version
            RETURNING id,public_id,tenant_id,sku,name,unit_type,is_active,meta,row_version"""),
            {"tenant":command.tenant_id,"public_id":command.public_id,"version":command.expected_version,"name":command.name.strip() if command.name else None,"kind":command.unit_kind,"metadata":json.dumps(command.metadata) if command.metadata is not None else None}).one_or_none()
        return self._unit(row) if row else None

    def deactivate_atomic_unit(self, tenant_id: int, public_id: UUID, expected_version: int) -> AtomicUnit | None:
        row=self._session.execute(text("""UPDATE atomic_units SET is_active=false,updated_at=now(),row_version=row_version+1
            WHERE tenant_id=:tenant AND public_id=:public_id AND row_version=:version
            RETURNING id,public_id,tenant_id,sku,name,unit_type,is_active,meta,row_version"""),{"tenant":tenant_id,"public_id":public_id,"version":expected_version}).one_or_none()
        return self._unit(row) if row else None

    def link_taxonomy(self, tenant_id: int, atomic_unit_public_id: UUID, taxonomy_node_id: int) -> None:
        result=self._session.execute(text("""INSERT INTO atomic_unit_taxonomy(atomic_unit_id,taxonomy_node_id)
            SELECT u.id,n.id FROM atomic_units u JOIN taxonomy_nodes n ON n.id=:node AND n.tenant_id=u.tenant_id
            WHERE u.tenant_id=:tenant AND u.public_id=:unit ON CONFLICT DO NOTHING RETURNING atomic_unit_id"""),{"tenant":tenant_id,"unit":atomic_unit_public_id,"node":taxonomy_node_id}).scalar_one_or_none()
        if result is None:
            exists=self._session.execute(text("""SELECT 1 FROM atomic_unit_taxonomy x JOIN atomic_units u ON u.id=x.atomic_unit_id
                WHERE u.tenant_id=:tenant AND u.public_id=:unit AND x.taxonomy_node_id=:node"""),{"tenant":tenant_id,"unit":atomic_unit_public_id,"node":taxonomy_node_id}).scalar_one_or_none()
            if exists is None: raise ValueError("SO1_CROSS_TENANT_TAXONOMY_REFERENCE")

    def create_catalog(self, command: CreateCatalog, public_id: UUID) -> Catalog:
        row=self._session.execute(text("""INSERT INTO so1_catalogs(public_id,tenant_id,code,name,scope_type,scope_id,effective_from,effective_to)
            VALUES(:public_id,:tenant,:code,:name,:scope,:scope_id,:start,:end)
            RETURNING id,public_id,tenant_id,code,name,scope_type,scope_id,active,effective_from,effective_to,row_version"""),
            {"public_id":public_id,"tenant":command.tenant_id,"code":command.code.strip(),"name":command.name.strip(),"scope":command.scope_type,"scope_id":command.scope_id,"start":command.effective_from,"end":command.effective_to}).one()
        return self._catalog(row)

    def catalog(self, tenant_id: int, public_id: UUID) -> Catalog | None:
        row=self._session.execute(text("SELECT id,public_id,tenant_id,code,name,scope_type,scope_id,active,effective_from,effective_to,row_version FROM so1_catalogs WHERE tenant_id=:tenant AND public_id=:public_id"),{"tenant":tenant_id,"public_id":public_id}).one_or_none()
        return self._catalog(row) if row else None

    def publish_entry(self, command: PublishCatalogEntry, public_id: UUID) -> UUID:
        target_column="atomic_unit_id" if command.target_type is TargetType.ATOMIC_UNIT else "offer_id"
        target_table="atomic_units" if command.target_type is TargetType.ATOMIC_UNIT else "so1_offers"
        row=self._session.execute(text(f"""INSERT INTO so1_catalog_entries(public_id,tenant_id,catalog_id,target_type,{target_column},sort_order,semantic_reference,effective_from,effective_to)
            SELECT :entry,c.tenant_id,c.id,:target_type,t.id,:sort,:semantic,COALESCE(:start,c.effective_from),:end
            FROM so1_catalogs c JOIN {target_table} t ON t.tenant_id=c.tenant_id AND t.public_id=:target
            WHERE c.tenant_id=:tenant AND c.public_id=:catalog RETURNING public_id"""),
            {"entry":public_id,"target_type":command.target_type,"sort":command.sort_order,"semantic":command.semantic_reference,"start":command.effective_from,"end":command.effective_to,"target":command.target_public_id,"tenant":command.tenant_id,"catalog":command.catalog_public_id}).scalar_one_or_none()
        if row is None: raise ValueError("SO1_CROSS_TENANT_CATALOG_REFERENCE")
        return row

    def create_offer(self, command: CreateOffer, public_id: UUID) -> Offer:
        row=self._session.execute(text("INSERT INTO so1_offers(public_id,tenant_id,code,name) VALUES(:public_id,:tenant,:code,:name) RETURNING id"),{"public_id":public_id,"tenant":command.tenant_id,"code":command.code.strip(),"name":command.name.strip()}).one()
        for item in command.components:
            inserted=self._session.execute(text("""INSERT INTO so1_offer_components(tenant_id,offer_id,atomic_unit_id,quantity,component_rule,sequence)
                SELECT :tenant,:offer,u.id,:quantity,:rule,:sequence FROM atomic_units u
                WHERE u.tenant_id=:tenant AND u.public_id=:unit RETURNING id"""),{"tenant":command.tenant_id,"offer":row.id,"unit":item.atomic_unit_public_id,"quantity":item.quantity,"rule":item.rule,"sequence":item.sequence}).scalar_one_or_none()
            if inserted is None: raise ValueError("SO1_CROSS_TENANT_OFFER_COMPONENT")
        return self.offer(command.tenant_id, public_id)  # type: ignore[return-value]

    def offer(self, tenant_id: int, public_id: UUID) -> Offer | None:
        row=self._session.execute(text("SELECT id,public_id,tenant_id,code,name,active,row_version FROM so1_offers WHERE tenant_id=:tenant AND public_id=:public_id"),{"tenant":tenant_id,"public_id":public_id}).one_or_none()
        if row is None:return None
        items=self._session.execute(text("""SELECT u.public_id,c.quantity,c.component_rule,c.sequence FROM so1_offer_components c
            JOIN atomic_units u ON (u.tenant_id,u.id)=(c.tenant_id,c.atomic_unit_id) WHERE c.tenant_id=:tenant AND c.offer_id=:offer ORDER BY c.sequence,u.public_id"""),{"tenant":tenant_id,"offer":row.id}).all()
        return Offer(row.id,row.public_id,row.tenant_id,row.code,row.name,row.active,tuple(OfferComponent(i.public_id,i.quantity,ComponentRule(i.component_rule),i.sequence) for i in items),row.row_version)

    def update_offer(self, command: UpdateOffer) -> Offer | None:
        offer_id=self._session.execute(text("""UPDATE so1_offers SET name=:name,updated_at=now(),row_version=row_version+1
            WHERE tenant_id=:tenant AND public_id=:public_id AND row_version=:version RETURNING id"""),{"name":command.name.strip(),"tenant":command.tenant_id,"public_id":command.public_id,"version":command.expected_version}).scalar_one_or_none()
        if offer_id is None:return None
        self._session.execute(text("DELETE FROM so1_offer_components WHERE tenant_id=:tenant AND offer_id=:offer"),{"tenant":command.tenant_id,"offer":offer_id})
        for item in command.components:
            inserted=self._session.execute(text("""INSERT INTO so1_offer_components(tenant_id,offer_id,atomic_unit_id,quantity,component_rule,sequence)
                SELECT :tenant,:offer,u.id,:quantity,:rule,:sequence FROM atomic_units u WHERE u.tenant_id=:tenant AND u.public_id=:unit RETURNING id"""),{"tenant":command.tenant_id,"offer":offer_id,"unit":item.atomic_unit_public_id,"quantity":item.quantity,"rule":item.rule,"sequence":item.sequence}).scalar_one_or_none()
            if inserted is None:raise ValueError("SO1_CROSS_TENANT_OFFER_COMPONENT")
        return self.offer(command.tenant_id,command.public_id)

    def deactivate_offer(self, tenant_id: int, public_id: UUID, expected_version: int) -> Offer | None:
        changed=self._session.execute(text("UPDATE so1_offers SET active=false,updated_at=now(),row_version=row_version+1 WHERE tenant_id=:tenant AND public_id=:public_id AND row_version=:version RETURNING id"),{"tenant":tenant_id,"public_id":public_id,"version":expected_version}).scalar_one_or_none()
        return self.offer(tenant_id,public_id) if changed else None

    def define_price(self, command: DefinePrice, public_id: UUID) -> Price:
        target_table="atomic_units" if command.target_type is TargetType.ATOMIC_UNIT else "so1_offers"
        target_column="atomic_unit_id" if command.target_type is TargetType.ATOMIC_UNIT else "offer_id"
        row=self._session.execute(text(f"""INSERT INTO so1_prices(public_id,tenant_id,target_type,{target_column},price_code,amount,currency,scope_type,scope_id,precedence,effective_from,effective_to)
            SELECT :public_id,:tenant,:target_type,t.id,:code,:amount,:currency,:scope,:scope_id,:precedence,:start,:end
            FROM {target_table} t WHERE t.tenant_id=:tenant AND t.public_id=:target
            RETURNING id,public_id,tenant_id,target_type,:target AS target_public_id,price_code,amount,currency,scope_type,scope_id,precedence,effective_from,effective_to,active,row_version"""),
            {"public_id":public_id,"tenant":command.tenant_id,"target_type":command.target_type,"target":command.target_public_id,"code":command.price_code,"amount":command.amount,"currency":command.currency,"scope":command.scope_type,"scope_id":command.scope_id,"precedence":command.precedence,"start":command.effective_from,"end":command.effective_to}).one_or_none()
        if row is None:raise ValueError("SO1_CROSS_TENANT_PRICE_TARGET")
        return self._price(row)

    def price(self, tenant_id: int, public_id: UUID) -> Price | None:
        row=self._session.execute(text("""SELECT p.*,COALESCE(u.public_id,o.public_id) target_public_id FROM so1_prices p
            LEFT JOIN atomic_units u ON (u.tenant_id,u.id)=(p.tenant_id,p.atomic_unit_id)
            LEFT JOIN so1_offers o ON (o.tenant_id,o.id)=(p.tenant_id,p.offer_id)
            WHERE p.tenant_id=:tenant AND p.public_id=:public_id"""),{"tenant":tenant_id,"public_id":public_id}).one_or_none()
        return self._price(row) if row else None

    def deactivate_price(self, tenant_id: int, public_id: UUID, expected_version: int) -> Price | None:
        changed=self._session.execute(text("UPDATE so1_prices SET active=false,updated_at=now(),row_version=row_version+1 WHERE tenant_id=:tenant AND public_id=:public_id AND row_version=:version RETURNING id"),{"tenant":tenant_id,"public_id":public_id,"version":expected_version}).scalar_one_or_none()
        return self.price(tenant_id,public_id) if changed else None

    def resolve_price(self, query: ResolvePrice) -> Price | None:
        target_column="atomic_unit_id" if query.target_type is TargetType.ATOMIC_UNIT else "offer_id"
        target_table="atomic_units" if query.target_type is TargetType.ATOMIC_UNIT else "so1_offers"
        rows=self._session.execute(text(f"""SELECT p.*,t.public_id target_public_id,
            CASE WHEN p.scope_type=:scope AND p.scope_id IS NOT DISTINCT FROM :scope_id THEN 1 ELSE 0 END scope_rank
            FROM so1_prices p JOIN {target_table} t ON (t.tenant_id,t.id)=(p.tenant_id,p.{target_column})
            WHERE p.tenant_id=:tenant AND t.public_id=:target AND p.target_type=:target_type AND p.price_code=:code
              AND p.currency=:currency AND p.active AND p.effective_from<=:at AND (p.effective_to IS NULL OR p.effective_to>:at)
              AND (p.scope_type='tenant' OR (p.scope_type=:scope AND p.scope_id IS NOT DISTINCT FROM :scope_id))
            ORDER BY scope_rank DESC,p.precedence DESC,p.effective_from DESC,p.public_id ASC LIMIT 2"""),
            {"tenant":query.tenant_id,"target":query.target_public_id,"target_type":query.target_type,"code":query.price_code,"currency":query.currency,"at":query.at,"scope":query.scope_type,"scope_id":query.scope_id}).all()
        if not rows:return None
        if len(rows)>1 and (rows[0].scope_rank,rows[0].precedence,rows[0].effective_from)==(rows[1].scope_rank,rows[1].precedence,rows[1].effective_from):
            raise ValueError("SO1_AMBIGUOUS_PRICE")
        return self._price(rows[0])
