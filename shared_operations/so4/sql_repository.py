"""Private SQLAlchemy adapter for SO4; shares the transaction used by SO3."""
from __future__ import annotations
import json
from uuid import UUID
from sqlalchemy import text
from .contracts import *
from .service import SO4AuthorityError


class SQLSO4Repository:
    def __init__(self,db_session): self.db_session=db_session
    def _command(self,tenant,key,fingerprint,kind):
        self.db_session.execute(text("INSERT INTO so4_procurement_commands(tenant_id,command_key,request_fingerprint,command_type) VALUES(:t,:k,:f,:y) ON CONFLICT(tenant_id,command_key) DO NOTHING"),{"t":tenant,"k":key,"f":fingerprint,"y":kind})
        row=self.db_session.execute(text("SELECT * FROM so4_procurement_commands WHERE tenant_id=:t AND command_key=:k FOR UPDATE"),{"t":tenant,"k":key}).one()
        if row.request_fingerprint!=fingerprint or row.command_type!=kind: raise SO4AuthorityError("SO4_COMMAND_CONFLICT","conflict","Command key was reused with different content")
        return row
    def _complete(self,tenant,key,kind,public_id): self.db_session.execute(text("UPDATE so4_procurement_commands SET result_type=:y,result_public_id=:p,completed_at=now() WHERE tenant_id=:t AND command_key=:k"),{"t":tenant,"k":key,"y":kind,"p":str(public_id)})
    def _lines(self,tenant,order_id):
        rows=self.db_session.execute(text("""SELECT l.*,u.public_id atomic_unit_public_id,s.public_id stock_location_public_id FROM so4_purchase_order_lines l LEFT JOIN atomic_units u ON (u.tenant_id,u.id)=(l.tenant_id,l.atomic_unit_id) LEFT JOIN so3_stock_locations s ON (s.tenant_id,s.id)=(l.tenant_id,l.stock_location_id) WHERE l.tenant_id=:t AND l.purchase_order_id=:o ORDER BY l.line_number"""),{"t":tenant,"o":order_id}).all()
        return tuple(PurchaseOrderLine(UUID(str(x.public_id)),x.line_number,LineType(x.line_type),x.description,UUID(str(x.atomic_unit_public_id)) if x.atomic_unit_public_id else None,UUID(str(x.stock_location_public_id)) if x.stock_location_public_id else None,x.ordered_quantity,x.received_quantity) for x in rows)
    def request(self,tenant_id,public_id):
        row=self.db_session.execute(text("SELECT * FROM so4_purchase_requests WHERE tenant_id=:t AND public_id=:p"),{"t":tenant_id,"p":str(public_id)}).first()
        if not row:return None
        lines=self.db_session.execute(text("""SELECT l.*,u.public_id atomic_unit_public_id,s.public_id stock_location_public_id FROM so4_purchase_request_lines l LEFT JOIN atomic_units u ON (u.tenant_id,u.id)=(l.tenant_id,l.atomic_unit_id) LEFT JOIN so3_stock_locations s ON (s.tenant_id,s.id)=(l.tenant_id,l.stock_location_id) WHERE l.tenant_id=:t AND l.purchase_request_id=:r ORDER BY l.line_number"""),{"t":tenant_id,"r":row.id}).all()
        return PurchaseRequest(UUID(str(row.public_id)),tenant_id,row.request_code,ProcurementStatus(row.lifecycle_status),tuple(ProcurementLineInput(x.line_number,LineType(x.line_type),x.description,x.requested_quantity,UUID(str(x.atomic_unit_public_id)) if x.atomic_unit_public_id else None,UUID(str(x.stock_location_public_id)) if x.stock_location_public_id else None) for x in lines),row.expected_by,row.row_version)
    def order(self,tenant_id,public_id):
        row=self.db_session.execute(text("""SELECT o.*,p.public_id party_public_id,r.public_id relationship_public_id FROM so4_purchase_orders o JOIN parties p ON (p.tenant_id,p.id)=(o.tenant_id,o.supplier_party_id) JOIN so2_operational_relationships r ON (r.tenant_id,r.id)=(o.tenant_id,o.supplier_relationship_id) WHERE o.tenant_id=:t AND o.public_id=:p"""),{"t":tenant_id,"p":str(public_id)}).first()
        return PurchaseOrder(UUID(str(row.public_id)),tenant_id,row.order_code,UUID(str(row.party_public_id)),UUID(str(row.relationship_public_id)),ProcurementStatus(row.lifecycle_status),OverReceiptPolicy(row.over_receipt_policy),self._lines(tenant_id,row.id),row.expected_by,row.row_version) if row else None
    def create_request(self,command,lines,public_id,fingerprint):
        replay=self._command(command.tenant_id,command.command_key,fingerprint,"create_request")
        if replay.result_public_id:return self.request(command.tenant_id,replay.result_public_id)
        row=self.db_session.execute(text("INSERT INTO so4_purchase_requests(public_id,tenant_id,request_code,lifecycle_status,expected_by,source_reference,document_reference) VALUES(:p,:t,:c,'draft',:e,:s,:d) RETURNING id"),{"p":str(public_id),"t":command.tenant_id,"c":command.request_code,"e":command.expected_by,"s":command.source_reference,"d":command.document_reference}).one()
        for x in lines:
            unit=self.db_session.execute(text("SELECT id FROM atomic_units WHERE tenant_id=:t AND public_id=:p"),{"t":command.tenant_id,"p":str(x.atomic_unit_public_id)}).scalar() if x.atomic_unit_public_id else None
            stock=self.db_session.execute(text("SELECT id FROM so3_stock_locations WHERE tenant_id=:t AND public_id=:p"),{"t":command.tenant_id,"p":str(x.stock_location_public_id)}).scalar() if x.stock_location_public_id else None
            self.db_session.execute(text("INSERT INTO so4_purchase_request_lines(public_id,tenant_id,purchase_request_id,line_number,line_type,description,atomic_unit_id,stock_location_id,requested_quantity) VALUES(gen_random_uuid(),:t,:r,:n,:y,:d,:u,:s,:q)"),{"t":command.tenant_id,"r":row.id,"n":x.line_number,"y":x.line_type.value,"d":x.description,"u":unit,"s":stock,"q":x.quantity})
        self._complete(command.tenant_id,command.command_key,"request",public_id);return self.request(command.tenant_id,public_id)
    def create_order(self,command,party_id,relationship_id,request_id,lines,public_id,fingerprint):
        replay=self._command(command.tenant_id,command.command_key,fingerprint,"create_order")
        if replay.result_public_id:return self.order(command.tenant_id,replay.result_public_id)
        request_db_id=self.db_session.execute(text("SELECT id FROM so4_purchase_requests WHERE tenant_id=:t AND public_id=:p"),{"t":command.tenant_id,"p":str(request_id)}).scalar() if request_id else None
        row=self.db_session.execute(text("""INSERT INTO so4_purchase_orders(public_id,tenant_id,order_code,supplier_party_id,supplier_relationship_id,purchase_request_id,lifecycle_status,over_receipt_policy,expected_by,approval_public_id,source_reference,document_reference) VALUES(:p,:t,:c,:party,:rel,:req,'draft',:policy,:e,:a,:s,:d) RETURNING id"""),{"p":str(public_id),"t":command.tenant_id,"c":command.order_code,"party":party_id,"rel":relationship_id,"req":request_db_id,"policy":command.over_receipt_policy.value,"e":command.expected_by,"a":str(command.approval_public_id) if command.approval_public_id else None,"s":command.source_reference,"d":command.document_reference}).one()
        for x in lines:
            unit=self.db_session.execute(text("SELECT id FROM atomic_units WHERE tenant_id=:t AND public_id=:p"),{"t":command.tenant_id,"p":str(x.atomic_unit_public_id)}).scalar() if x.atomic_unit_public_id else None
            stock=self.db_session.execute(text("SELECT id FROM so3_stock_locations WHERE tenant_id=:t AND public_id=:p"),{"t":command.tenant_id,"p":str(x.stock_location_public_id)}).scalar() if x.stock_location_public_id else None
            self.db_session.execute(text("""INSERT INTO so4_purchase_order_lines(public_id,tenant_id,purchase_order_id,line_number,line_type,description,atomic_unit_id,stock_location_id,ordered_quantity) VALUES(gen_random_uuid(),:t,:o,:n,:y,:d,:u,:s,:q)"""),{"t":command.tenant_id,"o":row.id,"n":x.line_number,"y":x.line_type.value,"d":x.description,"u":unit,"s":stock,"q":x.quantity})
        self._complete(command.tenant_id,command.command_key,"order",public_id);return self.order(command.tenant_id,public_id)
    def transition(self,command,fingerprint,is_order):
        kind="order" if is_order else "request"; replay=self._command(command.tenant_id,command.command_key,fingerprint,"transition_"+kind)
        getter=self.order if is_order else self.request
        if replay.result_public_id:return getter(command.tenant_id,replay.result_public_id)
        table="so4_purchase_orders" if is_order else "so4_purchase_requests"
        current=self.db_session.execute(text(f"SELECT lifecycle_status FROM {table} WHERE tenant_id=:t AND public_id=:p AND row_version=:v FOR UPDATE"),{"t":command.tenant_id,"p":str(command.resource_public_id),"v":command.expected_version}).first()
        if not current:return None
        row=self.db_session.execute(text(f"UPDATE {table} SET lifecycle_status=:s,row_version=row_version+1,updated_at=now(),approval_public_id=COALESCE(:a,approval_public_id) WHERE tenant_id=:t AND public_id=:p AND row_version=:v RETURNING id,public_id"),{"s":command.to_status.value,"a":str(command.approval_public_id) if command.approval_public_id else None,"t":command.tenant_id,"p":str(command.resource_public_id),"v":command.expected_version}).first()
        if not row:return None
        self.db_session.execute(text("INSERT INTO so4_procurement_history(tenant_id,resource_type,resource_id,from_status,to_status,reason_code,occurred_at) VALUES(:t,:y,:r,:f,:s,:reason,:at)"),{"t":command.tenant_id,"y":kind,"r":row.id,"f":current.lifecycle_status,"s":command.to_status.value,"reason":command.reason_code,"at":command.occurred_at})
        self._complete(command.tenant_id,command.command_key,kind,command.resource_public_id);return getter(command.tenant_id,command.resource_public_id)
    def begin_receipt(self,command,public_id,fingerprint):
        replay=self._command(command.tenant_id,command.command_key,fingerprint,"receive_order")
        if replay.result_public_id:return self.receipt(command.tenant_id,replay.result_public_id),()
        order=self.db_session.execute(text("SELECT * FROM so4_purchase_orders WHERE tenant_id=:t AND public_id=:p FOR UPDATE"),{"t":command.tenant_id,"p":str(command.purchase_order_public_id)}).first()
        if not order or order.lifecycle_status not in ('ordered','partially_received'): raise SO4AuthorityError("SO4_ORDER_NOT_RECEIVABLE","invalid_state_transition","Only ordered or partially received orders may be received")
        seen=set();plan=[]
        for x in command.lines:
            if x.order_line_public_id in seen:raise SO4AuthorityError("SO4_DUPLICATE_RECEIPT_LINE","validation_failure","Receipt line occurs more than once")
            seen.add(x.order_line_public_id)
            line=self.db_session.execute(text("""SELECT l.*,u.public_id atomic_unit_public_id,loc.public_id location_public_id FROM so4_purchase_order_lines l LEFT JOIN atomic_units u ON (u.tenant_id,u.id)=(l.tenant_id,l.atomic_unit_id) LEFT JOIN so3_stock_locations s ON (s.tenant_id,s.id)=(l.tenant_id,l.stock_location_id) LEFT JOIN locations loc ON (loc.tenant_id,loc.id)=(s.tenant_id,s.location_id) WHERE l.tenant_id=:t AND l.purchase_order_id=:o AND l.public_id=:p FOR UPDATE OF l"""),{"t":command.tenant_id,"o":order.id,"p":str(x.order_line_public_id)}).first()
            if not line:raise SO4AuthorityError("SO4_ORDER_LINE_NOT_FOUND","scope_mismatch","Order line not found in this tenant/order")
            plan.append({"order_line_public_id":UUID(str(line.public_id)),"quantity":x.quantity,"outstanding":line.ordered_quantity-line.received_quantity,"policy":order.over_receipt_policy,"line_type":line.line_type,"atomic_unit_public_id":UUID(str(line.atomic_unit_public_id)) if line.atomic_unit_public_id else None,"location_public_id":UUID(str(line.location_public_id)) if line.location_public_id else None})
        self.db_session.execute(text("INSERT INTO so4_operational_receipts(public_id,tenant_id,purchase_order_id,receipt_code,occurred_at,source_reference,document_reference) VALUES(:p,:t,:o,:c,:at,:s,:d)"),{"p":str(public_id),"t":command.tenant_id,"o":order.id,"c":command.receipt_code,"at":command.occurred_at,"s":command.source_reference,"d":command.document_reference})
        return None,tuple(plan)
    def complete_receipt(self,command,receipt_public_id,movements):
        receipt=self.db_session.execute(text("SELECT * FROM so4_operational_receipts WHERE tenant_id=:t AND public_id=:p FOR UPDATE"),{"t":command.tenant_id,"p":str(receipt_public_id)}).one(); movement_map=dict(movements)
        for x in command.lines:
            line=self.db_session.execute(text("SELECT * FROM so4_purchase_order_lines WHERE tenant_id=:t AND public_id=:p FOR UPDATE"),{"t":command.tenant_id,"p":str(x.order_line_public_id)}).one()
            self.db_session.execute(text("UPDATE so4_purchase_order_lines SET received_quantity=received_quantity+:q WHERE id=:id"),{"q":x.quantity,"id":line.id})
            self.db_session.execute(text("INSERT INTO so4_operational_receipt_lines(tenant_id,receipt_id,purchase_order_line_id,quantity,stock_movement_public_id) VALUES(:t,:r,:l,:q,:m)"),{"t":command.tenant_id,"r":receipt.id,"l":line.id,"q":x.quantity,"m":str(movement_map[x.order_line_public_id]) if x.order_line_public_id in movement_map else None})
        remaining=self.db_session.execute(text("SELECT count(*) FROM so4_purchase_order_lines WHERE purchase_order_id=:o AND received_quantity<ordered_quantity"),{"o":receipt.purchase_order_id}).scalar_one()
        status='received' if remaining==0 else 'partially_received'
        self.db_session.execute(text("UPDATE so4_purchase_orders SET lifecycle_status=:s,row_version=row_version+1,updated_at=now() WHERE id=:id"),{"s":status,"id":receipt.purchase_order_id})
        self._complete(command.tenant_id,command.command_key,"receipt",receipt_public_id);return self.receipt(command.tenant_id,receipt_public_id)
    def receipt(self,tenant_id,public_id):
        row=self.db_session.execute(text("SELECT r.*,o.public_id order_public_id FROM so4_operational_receipts r JOIN so4_purchase_orders o ON o.id=r.purchase_order_id WHERE r.tenant_id=:t AND r.public_id=:p"),{"t":tenant_id,"p":str(public_id)}).first()
        if not row:return None
        lines=self.db_session.execute(text("SELECT l.quantity,l.stock_movement_public_id,ol.public_id order_line_public_id FROM so4_operational_receipt_lines l JOIN so4_purchase_order_lines ol ON ol.id=l.purchase_order_line_id WHERE l.receipt_id=:r ORDER BY l.id"),{"r":row.id}).all()
        return ProcurementReceipt(UUID(str(row.public_id)),tenant_id,UUID(str(row.order_public_id)),row.receipt_code,row.occurred_at,tuple(ReceiptLineInput(UUID(str(x.order_line_public_id)),x.quantity) for x in lines),tuple(UUID(str(x.stock_movement_public_id)) for x in lines if x.stock_movement_public_id))
    def history(self,tenant_id,resource_public_id):
        return tuple(self.db_session.execute(text("SELECT h.* FROM so4_procurement_history h LEFT JOIN so4_purchase_orders o ON h.resource_type='order' AND o.id=h.resource_id LEFT JOIN so4_purchase_requests r ON h.resource_type='request' AND r.id=h.resource_id WHERE h.tenant_id=:t AND COALESCE(o.public_id,r.public_id)=:p ORDER BY h.sequence"),{"t":tenant_id,"p":str(resource_public_id)}).mappings())
