"""Private SQLAlchemy persistence adapter for SO3."""

from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import text

from .contracts import CountStatus, InventoryPosition, MovementType, ReservationStatus, StockCount, StockLocation, StockMovement, StockReservation
from .service import SO3AuthorityError


class SQLSO3Repository:
    def __init__(self, db_session):
        self.db_session = db_session

    def _command(self, tenant_id: int, key: str, fingerprint: str, command_type: str):
        self.db_session.execute(text("""INSERT INTO so3_inventory_commands(tenant_id,command_key,request_fingerprint,command_type)
            VALUES(:tenant,:key,:fingerprint,:type) ON CONFLICT(tenant_id,command_key) DO NOTHING"""),
            {"tenant":tenant_id,"key":key,"fingerprint":fingerprint,"type":command_type})
        row=self.db_session.execute(text("""SELECT request_fingerprint,command_type,result_type,result_public_id
            FROM so3_inventory_commands WHERE tenant_id=:tenant AND command_key=:key FOR UPDATE"""),{"tenant":tenant_id,"key":key}).one()
        if row.request_fingerprint != fingerprint or row.command_type != command_type:
            raise SO3AuthorityError("SO3_COMMAND_CONFLICT","conflict","The command key was already used with different content")
        return row

    def _complete(self, tenant_id: int, key: str, result_type: str, public_id: UUID):
        self.db_session.execute(text("""UPDATE so3_inventory_commands SET result_type=:type,result_public_id=:public_id,completed_at=now()
            WHERE tenant_id=:tenant AND command_key=:key"""),{"tenant":tenant_id,"key":key,"type":result_type,"public_id":str(public_id)})

    @staticmethod
    def _position(row) -> InventoryPosition:
        return InventoryPosition(row.id,UUID(str(row.public_id)),row.tenant_id,UUID(str(row.atomic_unit_public_id)),UUID(str(row.stock_location_public_id)),int(row.quantity_on_hand),int(row.reserved_quantity),int(row.quantity_on_hand-row.reserved_quantity),row.reorder_level,row.row_version)

    @staticmethod
    def _movement(row) -> StockMovement:
        metadata=row.metadata if isinstance(row.metadata,dict) else json.loads(row.metadata or "{}")
        return StockMovement(row.id,UUID(str(row.public_id)),row.tenant_id,UUID(str(row.atomic_unit_public_id)),UUID(str(row.stock_location_public_id)),MovementType(row.movement_type),int(row.quantity_delta),int(row.quantity_after),row.reason_code,row.source,row.source_reference,row.occurred_at,UUID(str(row.correction_of_public_id)) if row.correction_of_public_id else None,UUID(str(row.related_public_id)) if row.related_public_id else None,metadata)

    @staticmethod
    def _reservation(row) -> StockReservation:
        return StockReservation(row.id,UUID(str(row.public_id)),row.tenant_id,UUID(str(row.atomic_unit_public_id)),UUID(str(row.stock_location_public_id)),row.quantity,ReservationStatus(row.lifecycle_status),row.source_type,row.source_reference,row.expires_at,row.row_version)

    @staticmethod
    def _count(row) -> StockCount:
        return StockCount(row.id,UUID(str(row.public_id)),row.tenant_id,UUID(str(row.atomic_unit_public_id)),UUID(str(row.stock_location_public_id)),row.expected_quantity,row.counted_quantity,row.variance,CountStatus(row.lifecycle_status),row.reason_code,row.occurred_at,UUID(str(row.adjustment_movement_public_id)) if row.adjustment_movement_public_id else None,row.row_version)

    def _position_row(self, tenant_id: int, atomic_unit_id: int, location_id: int, *, lock: bool=False, create: bool=False):
        stock=self.db_session.execute(text("""SELECT id,public_id,legacy_branch_id FROM so3_stock_locations
            WHERE tenant_id=:tenant AND location_id=:location AND active=true"""+(" FOR UPDATE" if lock else "")),{"tenant":tenant_id,"location":location_id}).first()
        if stock is None:
            raise SO3AuthorityError("SO3_STOCK_LOCATION_NOT_FOUND","scope_mismatch","No active SO3 stock location maps to the PC1 location")
        if create:
            self.db_session.execute(text("""INSERT INTO inventory_items(public_id,tenant_id,branch_id,atomic_unit_id,stock_location_id,quantity_on_hand,reserved_quantity,row_version)
                VALUES(gen_random_uuid(),:tenant,:branch,:unit,:stock,0,0,1)
                ON CONFLICT(tenant_id,stock_location_id,atomic_unit_id) DO NOTHING"""),{"tenant":tenant_id,"branch":stock.legacy_branch_id,"unit":atomic_unit_id,"stock":stock.id})
        suffix=" FOR UPDATE" if lock else ""
        return self.db_session.execute(text("""SELECT i.*,u.public_id AS atomic_unit_public_id,s.public_id AS stock_location_public_id
            FROM inventory_items i JOIN atomic_units u ON (u.tenant_id,u.id)=(i.tenant_id,i.atomic_unit_id)
            JOIN so3_stock_locations s ON (s.tenant_id,s.id)=(i.tenant_id,i.stock_location_id)
            WHERE i.tenant_id=:tenant AND i.atomic_unit_id=:unit AND i.stock_location_id=:stock"""+suffix),{"tenant":tenant_id,"unit":atomic_unit_id,"stock":stock.id}).first()

    def _movement_row(self, tenant_id: int, public_id: UUID):
        return self.db_session.execute(text("""SELECT m.*,u.public_id AS atomic_unit_public_id,s.public_id AS stock_location_public_id,
            c.public_id AS correction_of_public_id FROM inventory_movements m
            JOIN atomic_units u ON (u.tenant_id,u.id)=(m.tenant_id,m.atomic_unit_id)
            JOIN so3_stock_locations s ON (s.tenant_id,s.id)=(m.tenant_id,m.stock_location_id)
            LEFT JOIN inventory_movements c ON c.id=m.correction_of_id
            WHERE m.tenant_id=:tenant AND m.public_id=:public_id"""),{"tenant":tenant_id,"public_id":str(public_id)}).first()

    def register_location(self, command, location_id: int, public_id: UUID, fingerprint: str) -> StockLocation:
        replay=self._command(command.tenant_id,command.command_key,fingerprint,"register_location")
        if replay.result_public_id:
            row=self.db_session.execute(text("""SELECT s.*,l.public_id AS location_public_id FROM so3_stock_locations s JOIN locations l ON (l.tenant_id,l.id)=(s.tenant_id,s.location_id) WHERE s.tenant_id=:tenant AND s.public_id=:public_id"""),{"tenant":command.tenant_id,"public_id":str(replay.result_public_id)}).one()
        else:
            row=self.db_session.execute(text("""INSERT INTO so3_stock_locations(public_id,tenant_id,location_id,code,name)
                VALUES(:public_id,:tenant,:location,:code,:name) ON CONFLICT(tenant_id,location_id) DO UPDATE SET code=EXCLUDED.code,name=EXCLUDED.name,updated_at=now(),row_version=so3_stock_locations.row_version+1
                RETURNING *"""),{"public_id":str(public_id),"tenant":command.tenant_id,"location":location_id,"code":command.code,"name":command.name}).one()
            self._complete(command.tenant_id,command.command_key,"stock_location",UUID(str(row.public_id)))
            row=self.db_session.execute(text("""SELECT s.*,l.public_id AS location_public_id FROM so3_stock_locations s JOIN locations l ON (l.tenant_id,l.id)=(s.tenant_id,s.location_id) WHERE s.tenant_id=:tenant AND s.id=:id"""),{"tenant":command.tenant_id,"id":row.id}).one()
        return StockLocation(row.id,UUID(str(row.public_id)),row.tenant_id,UUID(str(row.location_public_id)),row.code,row.name,row.active,row.legacy_branch_id)

    def position(self, tenant_id: int, atomic_unit_id: int, stock_location_id: int) -> InventoryPosition | None:
        row=self._position_row(tenant_id,atomic_unit_id,stock_location_id)
        return self._position(row) if row else None

    def list_positions(self, tenant_id: int, stock_location_id: int | None=None) -> tuple[InventoryPosition,...]:
        rows=self.db_session.execute(text("""SELECT i.*,u.public_id AS atomic_unit_public_id,s.public_id AS stock_location_public_id
            FROM inventory_items i JOIN atomic_units u ON (u.tenant_id,u.id)=(i.tenant_id,i.atomic_unit_id)
            JOIN so3_stock_locations s ON (s.tenant_id,s.id)=(i.tenant_id,i.stock_location_id)
            WHERE i.tenant_id=:tenant AND (:location IS NULL OR s.location_id=:location) ORDER BY s.code,u.public_id"""),{"tenant":tenant_id,"location":stock_location_id}).all()
        return tuple(self._position(row) for row in rows)

    def apply_movement(self, command, atomic_unit_id: int, stock_location_id: int, movement_type: MovementType, quantity_delta: int, fingerprint: str, allow_negative: bool, public_id: UUID, correction_of_id: int | None=None, related_public_id: UUID | None=None):
        replay=self._command(command.tenant_id,command.command_key,fingerprint,movement_type.value)
        if replay.result_public_id:
            movement=self._movement(self._movement_row(command.tenant_id,UUID(str(replay.result_public_id))))
            location=self.db_session.execute(text("SELECT location_id FROM so3_stock_locations WHERE tenant_id=:tenant AND public_id=:public_id"),{"tenant":command.tenant_id,"public_id":str(movement.stock_location_public_id)}).scalar_one()
            return self.position(command.tenant_id,atomic_unit_id,location),movement
        row=self._position_row(command.tenant_id,atomic_unit_id,stock_location_id,lock=True,create=True)
        new_quantity=int(row.quantity_on_hand)+quantity_delta
        if not allow_negative and new_quantity < int(row.reserved_quantity):
            raise SO3AuthorityError("SO3_INSUFFICIENT_AVAILABLE_STOCK","conflict","The movement would violate the configured negative-stock policy")
        self.db_session.execute(text("""UPDATE inventory_items SET quantity_on_hand=:quantity,row_version=row_version+1,updated_at=now() WHERE tenant_id=:tenant AND id=:id"""),{"quantity":new_quantity,"tenant":command.tenant_id,"id":row.id})
        movement=self.db_session.execute(text("""INSERT INTO inventory_movements(public_id,tenant_id,branch_id,inventory_item_id,atomic_unit_id,stock_location_id,quantity_delta,movement_type,source,source_reference,reference_type,created_at,occurred_at,reason_code,request_fingerprint,correction_of_id,related_public_id,quantity_after,metadata)
            VALUES(:public_id,:tenant,:branch,:item,:unit,:stock,:delta,:type,:source,:source_reference,:reference_type,:at,:at,:reason,:fingerprint,:correction,:related,:after,CAST(:metadata AS jsonb)) RETURNING public_id"""),{
            "public_id":str(public_id),"tenant":command.tenant_id,"branch":row.branch_id,"item":row.id,"unit":atomic_unit_id,"stock":row.stock_location_id,"delta":quantity_delta,"type":movement_type.value,
            "source":getattr(command,"source_type","inventory"),"source_reference":getattr(command,"source_reference",None),"reference_type":getattr(command,"source_type",None),"at":command.occurred_at,
            "reason":command.reason_code,"fingerprint":fingerprint,"correction":correction_of_id,"related":str(related_public_id) if related_public_id else None,"after":new_quantity,"metadata":json.dumps(getattr(command,"metadata",{}),sort_keys=True,separators=(",",":"))}).one()
        self._complete(command.tenant_id,command.command_key,"movement",UUID(str(movement.public_id)))
        result_row=self._position_row(command.tenant_id,atomic_unit_id,stock_location_id)
        return self._position(result_row),self._movement(self._movement_row(command.tenant_id,UUID(str(movement.public_id))))

    def transfer(self, command, atomic_unit_id: int, source_location_id: int, destination_location_id: int, fingerprint: str, allow_negative: bool, transfer_public_id: UUID, outbound_public_id: UUID, inbound_public_id: UUID):
        replay=self._command(command.tenant_id,command.command_key,fingerprint,"transfer")
        if replay.result_public_id:
            rows=self.db_session.execute(text("SELECT public_id FROM inventory_movements WHERE tenant_id=:tenant AND related_public_id=:related ORDER BY movement_type DESC"),{"tenant":command.tenant_id,"related":str(replay.result_public_id)}).scalars().all()
            movements=tuple(self._movement(self._movement_row(command.tenant_id,UUID(str(value)))) for value in rows)
            return movements[0],movements[1]
        ordered=sorted(((source_location_id,"source"),(destination_location_id,"destination")))
        locked={name:self._position_row(command.tenant_id,atomic_unit_id,location,lock=True,create=True) for location,name in ordered}
        source=locked["source"];destination=locked["destination"]
        source_after=int(source.quantity_on_hand)-command.quantity
        if not allow_negative and source_after<int(source.reserved_quantity):
            raise SO3AuthorityError("SO3_INSUFFICIENT_AVAILABLE_STOCK","conflict","The transfer would violate the configured negative-stock policy")
        destination_after=int(destination.quantity_on_hand)+command.quantity
        self.db_session.execute(text("UPDATE inventory_items SET quantity_on_hand=:quantity,row_version=row_version+1,updated_at=now() WHERE id=:id"),{"quantity":source_after,"id":source.id})
        self.db_session.execute(text("UPDATE inventory_items SET quantity_on_hand=:quantity,row_version=row_version+1,updated_at=now() WHERE id=:id"),{"quantity":destination_after,"id":destination.id})
        self.db_session.execute(text("""INSERT INTO so3_stock_transfers(public_id,tenant_id,atomic_unit_id,source_stock_location_id,destination_stock_location_id,quantity,lifecycle_status,source_type,source_reference,reason_code,occurred_at)
            VALUES(:public_id,:tenant,:unit,:source,:destination,:quantity,'completed',:source_type,:source_reference,:reason,:at)"""),{"public_id":str(transfer_public_id),"tenant":command.tenant_id,"unit":atomic_unit_id,"source":source.stock_location_id,"destination":destination.stock_location_id,"quantity":command.quantity,"source_type":command.source_type,"source_reference":command.source_reference,"reason":command.reason_code,"at":command.occurred_at})
        values=((source,outbound_public_id,MovementType.TRANSFER_OUT,-command.quantity,source_after),(destination,inbound_public_id,MovementType.TRANSFER_IN,command.quantity,destination_after))
        for row,public_id,movement_type,delta,after in values:
            self.db_session.execute(text("""INSERT INTO inventory_movements(public_id,tenant_id,branch_id,inventory_item_id,atomic_unit_id,stock_location_id,quantity_delta,movement_type,source,source_reference,reference_type,created_at,occurred_at,reason_code,request_fingerprint,related_public_id,quantity_after,metadata)
                VALUES(:public_id,:tenant,:branch,:item,:unit,:stock,:delta,:type,:source,:source_reference,'transfer',:at,:at,:reason,:fingerprint,:related,:after,CAST(:metadata AS jsonb))"""),{"public_id":str(public_id),"tenant":command.tenant_id,"branch":row.branch_id,"item":row.id,"unit":atomic_unit_id,"stock":row.stock_location_id,"delta":delta,"type":movement_type.value,"source":command.source_type,"source_reference":command.source_reference,"at":command.occurred_at,"reason":command.reason_code,"fingerprint":fingerprint,"related":str(transfer_public_id),"after":after,"metadata":json.dumps(command.metadata,sort_keys=True,separators=(",",":"))})
        self._complete(command.tenant_id,command.command_key,"transfer",transfer_public_id)
        return self._movement(self._movement_row(command.tenant_id,outbound_public_id)),self._movement(self._movement_row(command.tenant_id,inbound_public_id))

    def reserve(self, command, atomic_unit_id: int, stock_location_id: int, fingerprint: str, public_id: UUID) -> StockReservation:
        replay=self._command(command.tenant_id,command.command_key,fingerprint,"reserve")
        if replay.result_public_id:
            return self.reservation(command.tenant_id,UUID(str(replay.result_public_id)))
        position=self._position_row(command.tenant_id,atomic_unit_id,stock_location_id,lock=True,create=True)
        if int(position.quantity_on_hand)-int(position.reserved_quantity)<command.quantity:
            raise SO3AuthorityError("SO3_INSUFFICIENT_AVAILABLE_STOCK","conflict","Insufficient available stock for reservation")
        self.db_session.execute(text("UPDATE inventory_items SET reserved_quantity=reserved_quantity+:quantity,row_version=row_version+1,updated_at=now() WHERE id=:id"),{"quantity":command.quantity,"id":position.id})
        self.db_session.execute(text("""INSERT INTO so3_stock_reservations(public_id,tenant_id,inventory_item_id,atomic_unit_id,stock_location_id,quantity,lifecycle_status,source_type,source_reference,expires_at,created_at)
            VALUES(:public_id,:tenant,:item,:unit,:stock,:quantity,'active',:source,:reference,:expires,:at)"""),{"public_id":str(public_id),"tenant":command.tenant_id,"item":position.id,"unit":atomic_unit_id,"stock":position.stock_location_id,"quantity":command.quantity,"source":command.source_type,"reference":command.source_reference,"expires":command.expires_at,"at":command.occurred_at})
        self._complete(command.tenant_id,command.command_key,"reservation",public_id)
        return self.reservation(command.tenant_id,public_id)

    def reservation(self, tenant_id: int, public_id: UUID) -> StockReservation | None:
        row=self.db_session.execute(text("""SELECT r.*,u.public_id AS atomic_unit_public_id,s.public_id AS stock_location_public_id FROM so3_stock_reservations r
            JOIN atomic_units u ON (u.tenant_id,u.id)=(r.tenant_id,r.atomic_unit_id) JOIN so3_stock_locations s ON (s.tenant_id,s.id)=(r.tenant_id,r.stock_location_id)
            WHERE r.tenant_id=:tenant AND r.public_id=:public_id"""),{"tenant":tenant_id,"public_id":str(public_id)}).first()
        return self._reservation(row) if row else None

    def change_reservation(self, command, fingerprint: str, target: ReservationStatus, movement_public_id: UUID | None=None) -> StockReservation | None:
        replay=self._command(command.tenant_id,command.command_key,fingerprint,"reservation_"+target.value)
        if replay.result_public_id:return self.reservation(command.tenant_id,UUID(str(replay.result_public_id)))
        reservation=self.db_session.execute(text("SELECT * FROM so3_stock_reservations WHERE tenant_id=:tenant AND public_id=:public_id FOR UPDATE"),{"tenant":command.tenant_id,"public_id":str(command.reservation_public_id)}).first()
        if reservation is None or reservation.lifecycle_status!="active" or reservation.row_version!=command.expected_version:return None
        position=self.db_session.execute(text("SELECT * FROM inventory_items WHERE tenant_id=:tenant AND id=:id FOR UPDATE"),{"tenant":command.tenant_id,"id":reservation.inventory_item_id}).one()
        new_on_hand=int(position.quantity_on_hand)-(reservation.quantity if target is ReservationStatus.CONSUMED else 0)
        if new_on_hand<0:raise SO3AuthorityError("SO3_INSUFFICIENT_AVAILABLE_STOCK","conflict","Reserved stock is no longer available")
        self.db_session.execute(text("UPDATE inventory_items SET quantity_on_hand=:on_hand,reserved_quantity=reserved_quantity-:quantity,row_version=row_version+1,updated_at=now() WHERE id=:id"),{"on_hand":new_on_hand,"quantity":reservation.quantity,"id":position.id})
        changed=self.db_session.execute(text("""UPDATE so3_stock_reservations SET lifecycle_status=:status,row_version=row_version+1,updated_at=now(),released_at=CASE WHEN :status='released' THEN :at ELSE released_at END,consumed_at=CASE WHEN :status='consumed' THEN :at ELSE consumed_at END WHERE id=:id AND row_version=:version RETURNING public_id"""),{"status":target.value,"at":command.occurred_at,"id":reservation.id,"version":command.expected_version}).first()
        movement_type=MovementType.RESERVATION_CONSUME if target is ReservationStatus.CONSUMED else MovementType.RESERVATION_RELEASE
        self.db_session.execute(text("""INSERT INTO inventory_movements(public_id,tenant_id,branch_id,inventory_item_id,atomic_unit_id,stock_location_id,quantity_delta,movement_type,source,source_reference,reference_type,created_at,occurred_at,reason_code,request_fingerprint,related_public_id,quantity_after,metadata)
            VALUES(:public_id,:tenant,:branch,:item,:unit,:stock,:delta,:type,'inventory',:reference,'reservation',:at,:at,:reason,:fingerprint,:related,:after,'{}'::jsonb)"""),{"public_id":str(movement_public_id),"tenant":command.tenant_id,"branch":position.branch_id,"item":position.id,"unit":reservation.atomic_unit_id,"stock":reservation.stock_location_id,"delta":-reservation.quantity if target is ReservationStatus.CONSUMED else 0,"type":movement_type.value,"reference":str(reservation.public_id),"at":command.occurred_at,"reason":command.reason_code,"fingerprint":fingerprint,"related":str(reservation.public_id),"after":new_on_hand})
        self._complete(command.tenant_id,command.command_key,"reservation",UUID(str(changed.public_id)))
        return self.reservation(command.tenant_id,UUID(str(changed.public_id)))

    def initiate_count(self, command, atomic_unit_id: int, stock_location_id: int, fingerprint: str, public_id: UUID) -> StockCount:
        replay=self._command(command.tenant_id,command.command_key,fingerprint,"initiate_count")
        if replay.result_public_id:return self.count(command.tenant_id,UUID(str(replay.result_public_id)))
        position=self._position_row(command.tenant_id,atomic_unit_id,stock_location_id,lock=True,create=True)
        self.db_session.execute(text("""INSERT INTO so3_stock_counts(public_id,tenant_id,inventory_item_id,atomic_unit_id,stock_location_id,expected_quantity,counted_quantity,variance,lifecycle_status,reason_code,occurred_at)
            VALUES(:public_id,:tenant,:item,:unit,:stock,:expected,:counted,:variance,'open',:reason,:at)"""),{"public_id":str(public_id),"tenant":command.tenant_id,"item":position.id,"unit":atomic_unit_id,"stock":position.stock_location_id,"expected":position.quantity_on_hand,"counted":command.counted_quantity,"variance":command.counted_quantity-position.quantity_on_hand,"reason":command.reason_code,"at":command.occurred_at})
        self._complete(command.tenant_id,command.command_key,"count",public_id)
        return self.count(command.tenant_id,public_id)

    def count(self, tenant_id: int, public_id: UUID) -> StockCount | None:
        row=self.db_session.execute(text("""SELECT c.*,u.public_id AS atomic_unit_public_id,s.public_id AS stock_location_public_id,m.public_id AS adjustment_movement_public_id FROM so3_stock_counts c
            JOIN atomic_units u ON (u.tenant_id,u.id)=(c.tenant_id,c.atomic_unit_id) JOIN so3_stock_locations s ON (s.tenant_id,s.id)=(c.tenant_id,c.stock_location_id)
            LEFT JOIN inventory_movements m ON m.id=c.adjustment_movement_id WHERE c.tenant_id=:tenant AND c.public_id=:public_id"""),{"tenant":tenant_id,"public_id":str(public_id)}).first()
        return self._count(row) if row else None

    def accept_count(self, command, fingerprint: str, movement_public_id: UUID) -> StockCount | None:
        replay=self._command(command.tenant_id,command.command_key,fingerprint,"accept_count")
        if replay.result_public_id:return self.count(command.tenant_id,UUID(str(replay.result_public_id)))
        count=self.db_session.execute(text("SELECT * FROM so3_stock_counts WHERE tenant_id=:tenant AND public_id=:public_id FOR UPDATE"),{"tenant":command.tenant_id,"public_id":str(command.count_public_id)}).first()
        if count is None or count.lifecycle_status!="open" or count.row_version!=command.expected_version:return None
        position=self.db_session.execute(text("SELECT * FROM inventory_items WHERE tenant_id=:tenant AND id=:id FOR UPDATE"),{"tenant":command.tenant_id,"id":count.inventory_item_id}).one()
        if position.quantity_on_hand!=count.expected_quantity:raise SO3AuthorityError("SO3_COUNT_POSITION_CHANGED","stale_version","Stock changed after the count; recount before acceptance",retryable=True)
        movement_id=None
        if count.variance:
            movement_id=self.db_session.execute(text("""INSERT INTO inventory_movements(public_id,tenant_id,branch_id,inventory_item_id,atomic_unit_id,stock_location_id,quantity_delta,movement_type,source,source_reference,reference_type,created_at,occurred_at,reason_code,request_fingerprint,related_public_id,quantity_after,metadata)
                VALUES(:public_id,:tenant,:branch,:item,:unit,:stock,:delta,'count_correction','stock_count',:reference,'stock_count',:at,:at,:reason,:fingerprint,:related,:after,'{}'::jsonb) RETURNING id"""),{"public_id":str(movement_public_id),"tenant":command.tenant_id,"branch":position.branch_id,"item":position.id,"unit":count.atomic_unit_id,"stock":count.stock_location_id,"delta":count.variance,"reference":str(count.public_id),"at":command.occurred_at,"reason":count.reason_code,"fingerprint":fingerprint,"related":str(count.public_id),"after":count.counted_quantity}).scalar_one()
            self.db_session.execute(text("UPDATE inventory_items SET quantity_on_hand=:quantity,row_version=row_version+1,updated_at=now() WHERE id=:id"),{"quantity":count.counted_quantity,"id":position.id})
        changed=self.db_session.execute(text("UPDATE so3_stock_counts SET lifecycle_status='accepted',adjustment_movement_id=:movement,row_version=row_version+1,accepted_at=:at,updated_at=now() WHERE id=:id RETURNING public_id"),{"movement":movement_id,"at":command.occurred_at,"id":count.id}).one()
        self._complete(command.tenant_id,command.command_key,"count",UUID(str(changed.public_id)))
        return self.count(command.tenant_id,UUID(str(changed.public_id)))

    def movement(self, tenant_id: int, public_id: UUID) -> StockMovement | None:
        row=self._movement_row(tenant_id,public_id)
        return self._movement(row) if row else None

    def correct(self, command, fingerprint: str, public_id: UUID) -> StockMovement:
        replay=self._command(command.tenant_id,command.command_key,fingerprint,"correct")
        if replay.result_public_id:return self.movement(command.tenant_id,UUID(str(replay.result_public_id)))
        original=self.db_session.execute(text("SELECT * FROM inventory_movements WHERE tenant_id=:tenant AND public_id=:public_id FOR UPDATE"),{"tenant":command.tenant_id,"public_id":str(command.movement_public_id)}).first()
        if original is None:raise SO3AuthorityError("SO3_MOVEMENT_NOT_FOUND","not_found","The movement was not found")
        exists=self.db_session.execute(text("SELECT 1 FROM inventory_movements WHERE correction_of_id=:id"),{"id":original.id}).first()
        if exists:raise SO3AuthorityError("SO3_MOVEMENT_ALREADY_CORRECTED","conflict","The movement already has a correction")
        position=self.db_session.execute(text("SELECT * FROM inventory_items WHERE tenant_id=:tenant AND id=:id FOR UPDATE"),{"tenant":command.tenant_id,"id":original.inventory_item_id}).one()
        after=int(position.quantity_on_hand)-int(original.quantity_delta)
        self.db_session.execute(text("UPDATE inventory_items SET quantity_on_hand=:quantity,row_version=row_version+1,updated_at=now() WHERE id=:id"),{"quantity":after,"id":position.id})
        self.db_session.execute(text("""INSERT INTO inventory_movements(public_id,tenant_id,branch_id,inventory_item_id,atomic_unit_id,stock_location_id,quantity_delta,movement_type,source,source_reference,reference_type,created_at,occurred_at,reason_code,request_fingerprint,correction_of_id,quantity_after,metadata)
            VALUES(:public_id,:tenant,:branch,:item,:unit,:stock,:delta,'correction','inventory',:reference,'movement_correction',:at,:at,:reason,:fingerprint,:original,:after,'{}'::jsonb)"""),{"public_id":str(public_id),"tenant":command.tenant_id,"branch":position.branch_id,"item":position.id,"unit":original.atomic_unit_id,"stock":original.stock_location_id,"delta":-original.quantity_delta,"reference":str(original.public_id),"at":command.occurred_at,"reason":command.reason_code,"fingerprint":fingerprint,"original":original.id,"after":after})
        self._complete(command.tenant_id,command.command_key,"movement",public_id)
        return self.movement(command.tenant_id,public_id)

    def movements(self, tenant_id: int, atomic_unit_id: int | None=None, stock_location_id: int | None=None) -> tuple[StockMovement,...]:
        rows=self.db_session.execute(text("""SELECT m.public_id FROM inventory_movements m JOIN so3_stock_locations s ON (s.tenant_id,s.id)=(m.tenant_id,m.stock_location_id)
            WHERE m.tenant_id=:tenant AND (:unit IS NULL OR m.atomic_unit_id=:unit) AND (:location IS NULL OR s.location_id=:location) ORDER BY m.occurred_at,m.id"""),{"tenant":tenant_id,"unit":atomic_unit_id,"location":stock_location_id}).scalars().all()
        return tuple(self.movement(tenant_id,UUID(str(value))) for value in rows)
