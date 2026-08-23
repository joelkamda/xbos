from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

from core.domain.inventory.repository import InventoryRepository
from .inventory_service import (
    InventoryService,
    MOVEMENT_STOCK_COUNT,
    SOURCE_STOCK_COUNT,
)

DOUALA_TZ = ZoneInfo("Africa/Douala")
VALID_STOCK_RECON_SHIFTS = {"day", "night", "full24"}


def _iso(value):
    if value is None:
        return None

    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)

        value = value.astimezone(timezone.utc)

    return value.isoformat()


class StockReconciliationService:
    # Track A physical-stock count window. Not the generalized Track B model.

    @staticmethod
    def window_bounds(business_date: str, shift: str):
        try:
            day = date.fromisoformat(str(business_date))
        except Exception as exc:
            raise ValueError("business_date must be YYYY-MM-DD") from exc

        shift_key = str(shift or "").strip().lower()
        if shift_key not in VALID_STOCK_RECON_SHIFTS:
            raise ValueError("shift must be day, night, or full24")

        if shift_key == "day":
            start_local = datetime.combine(day, time(8, 0), tzinfo=DOUALA_TZ)
            end_local = datetime.combine(day, time(18, 0), tzinfo=DOUALA_TZ)
        elif shift_key == "night":
            start_local = datetime.combine(day, time(18, 0), tzinfo=DOUALA_TZ)
            end_local = datetime.combine(day + timedelta(days=1), time(8, 0), tzinfo=DOUALA_TZ)
        else:
            start_local = datetime.combine(day, time(8, 0), tzinfo=DOUALA_TZ)
            end_local = datetime.combine(day + timedelta(days=1), time(8, 0), tzinfo=DOUALA_TZ)

        return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)

    @staticmethod
    def _fingerprint(*, business_date: str, shift: str, note: str, lines: List[Dict[str, Any]]) -> str:
        canonical = {
            "business_date": str(business_date),
            "shift": str(shift).lower(),
            "note": str(note or ""),
            "lines": [
                {
                    "atomic_unit_id": int(line["atomic_unit_id"]),
                    "counted_qty": int(line["counted_qty"]),
                    "note": str(line.get("note") or ""),
                }
                for line in sorted(lines, key=lambda row: int(row["atomic_unit_id"]))
            ],
        }
        payload = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _load_window(db: Session, *, tenant_id: int, branch_id: int, business_date: str, shift: str):
        return db.execute(
            text(
                """
                SELECT *
                FROM inventory_reconciliation_windows
                WHERE tenant_id=:tenant_id
                  AND branch_id=:branch_id
                  AND business_date=:business_date
                  AND shift=:shift
                """
            ),
            {
                "tenant_id": tenant_id,
                "branch_id": branch_id,
                "business_date": business_date,
                "shift": shift,
            },
        ).mappings().first()

    @staticmethod
    def _serialize_closed_window(db: Session, row, *, replayed: bool = False) -> Dict[str, Any]:
        lines = db.execute(
            text(
                """
                SELECT l.id, l.atomic_unit_id, a.name AS product_name,
                       l.system_qty, l.counted_qty, l.variance_qty,
                       l.note, l.movement_id
                FROM inventory_reconciliation_lines l
                LEFT JOIN atomic_units a ON a.id=l.atomic_unit_id
                WHERE l.window_id=:window_id
                ORDER BY LOWER(COALESCE(a.name, '')), l.atomic_unit_id
                """
            ),
            {"window_id": int(row["id"])},
        ).mappings().all()

        return {
            "id": int(row["id"]),
            "business_date": str(row["business_date"]),
            "shift": row["shift"],
            "status": row["status"],
            "window_start": _iso(row["window_start"]),
            "window_end": _iso(row["window_end"]),
            "note": row["note"] or "",
            "fingerprint": row["fingerprint"],
            "line_count": int(row["line_count"] or 0),
            "variance_line_count": int(row["variance_line_count"] or 0),
            "total_variance_qty": int(row["total_variance_qty"] or 0),
            "closed_by_user_id": row["closed_by_user_id"],
            "closed_at": _iso(row["closed_at"]),
            "replayed": bool(replayed),
            "lines": [
                {
                    "id": int(line["id"]),
                    "atomic_unit_id": int(line["atomic_unit_id"]),
                    "product_name": line["product_name"],
                    "system_qty": int(line["system_qty"]),
                    "counted_qty": int(line["counted_qty"]),
                    "variance_qty": int(line["variance_qty"]),
                    "note": line["note"] or "",
                    "movement_id": line["movement_id"],
                }
                for line in lines
            ],
        }

    @staticmethod
    def get_window(db: Session, *, tenant_id: int, branch_id: int, business_date: str, shift: str) -> Dict[str, Any]:
        shift_key = str(shift or "").strip().lower()
        start_utc, end_utc = StockReconciliationService.window_bounds(business_date, shift_key)
        row = StockReconciliationService._load_window(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            business_date=business_date,
            shift=shift_key,
        )
        if row:
            return StockReconciliationService._serialize_closed_window(db, row)

        return {
            "id": None,
            "business_date": str(business_date),
            "shift": shift_key,
            "status": "open",
            "window_start": start_utc.isoformat(),
            "window_end": end_utc.isoformat(),
            "note": "",
            "fingerprint": None,
            "line_count": 0,
            "variance_line_count": 0,
            "total_variance_qty": 0,
            "closed_by_user_id": None,
            "closed_at": None,
            "replayed": False,
            "lines": [],
        }

    @staticmethod
    def close_window(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        business_date: str,
        shift: str,
        lines: List[Dict[str, Any]],
        note: str = "",
        closed_by_user_id: int | None = None,
    ) -> Dict[str, Any]:
        shift_key = str(shift or "").strip().lower()
        start_utc, end_utc = StockReconciliationService.window_bounds(business_date, shift_key)

        if not isinstance(lines, list) or not lines:
            raise ValueError("At least one stock count line is required")

        cleaned: List[Dict[str, Any]] = []
        seen = set()

        for incoming in lines:
            if not isinstance(incoming, dict):
                raise ValueError("Each stock count line must be an object")
            try:
                atomic_unit_id = int(incoming.get("atomic_unit_id"))
                counted_qty = int(incoming.get("counted_qty"))
            except Exception as exc:
                raise ValueError("atomic_unit_id and counted_qty must be integers") from exc

            if atomic_unit_id <= 0:
                raise ValueError("atomic_unit_id must be positive")
            if counted_qty < 0:
                raise ValueError(f"counted_qty cannot be negative for atomic_unit_id={atomic_unit_id}")
            if atomic_unit_id in seen:
                raise ValueError(f"Duplicate atomic_unit_id in stock count: {atomic_unit_id}")
            seen.add(atomic_unit_id)

            InventoryService.require_stock_tracked_profile(
                db,
                tenant_id=tenant_id,
                atomic_unit_id=atomic_unit_id,
                operation="stock_reconciliation",
            )
            cleaned.append(
                {
                    "atomic_unit_id": atomic_unit_id,
                    "counted_qty": counted_qty,
                    "note": str(incoming.get("note") or "").strip(),
                }
            )

        fingerprint = StockReconciliationService._fingerprint(
            business_date=business_date,
            shift=shift_key,
            note=note,
            lines=cleaned,
        )

        existing = StockReconciliationService._load_window(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            business_date=business_date,
            shift=shift_key,
        )
        if existing:
            if str(existing["fingerprint"]) == fingerprint:
                return StockReconciliationService._serialize_closed_window(db, existing, replayed=True)
            raise ValueError("This stock reconciliation window is already closed with different counted values")

        captured = []
        for incoming in sorted(cleaned, key=lambda row: int(row["atomic_unit_id"])):
            item = InventoryRepository.get_item(
                db,
                tenant_id=tenant_id,
                branch_id=branch_id,
                atomic_unit_id=incoming["atomic_unit_id"],
            )
            system_qty = int(item.quantity_on_hand or 0) if item else 0
            variance_qty = int(incoming["counted_qty"]) - system_qty
            captured.append({**incoming, "system_qty": system_qty, "variance_qty": variance_qty})

        variance_lines = [line for line in captured if int(line["variance_qty"]) != 0]

        window_row = db.execute(
            text(
                """
                INSERT INTO inventory_reconciliation_windows (
                    tenant_id, branch_id, business_date, shift,
                    window_start, window_end, status, note, fingerprint,
                    line_count, variance_line_count, total_variance_qty,
                    closed_by_user_id, closed_at, created_at, updated_at
                )
                VALUES (
                    :tenant_id, :branch_id, :business_date, :shift,
                    :window_start, :window_end, 'closed', :note, :fingerprint,
                    :line_count, :variance_line_count, :total_variance_qty,
                    :closed_by_user_id, NOW(), NOW(), NOW()
                )
                RETURNING *
                """
            ),
            {
                "tenant_id": tenant_id,
                "branch_id": branch_id,
                "business_date": business_date,
                "shift": shift_key,
                "window_start": start_utc,
                "window_end": end_utc,
                "note": str(note or "").strip() or None,
                "fingerprint": fingerprint,
                "line_count": len(captured),
                "variance_line_count": len(variance_lines),
                "total_variance_qty": sum(int(line["variance_qty"]) for line in captured),
                "closed_by_user_id": closed_by_user_id,
            },
        ).mappings().one()

        window_id = int(window_row["id"])

        for line in captured:
            movement_id = None
            if int(line["variance_qty"]) != 0:
                movement = InventoryService._apply_quantity_movement(
                    db,
                    tenant_id=tenant_id,
                    branch_id=branch_id,
                    atomic_unit_id=int(line["atomic_unit_id"]),
                    quantity_delta=int(line["variance_qty"]),
                    movement_type=MOVEMENT_STOCK_COUNT,
                    source=SOURCE_STOCK_COUNT,
                    reference_type="stock_reconciliation",
                    reference_id=window_id,
                    allow_negative=False,
                )
                movement_id = int(movement.id)

            db.execute(
                text(
                    """
                    INSERT INTO inventory_reconciliation_lines (
                        window_id, atomic_unit_id, system_qty, counted_qty,
                        variance_qty, note, movement_id, created_at
                    )
                    VALUES (
                        :window_id, :atomic_unit_id, :system_qty, :counted_qty,
                        :variance_qty, :note, :movement_id, NOW()
                    )
                    """
                ),
                {
                    "window_id": window_id,
                    "atomic_unit_id": int(line["atomic_unit_id"]),
                    "system_qty": int(line["system_qty"]),
                    "counted_qty": int(line["counted_qty"]),
                    "variance_qty": int(line["variance_qty"]),
                    "note": line["note"] or None,
                    "movement_id": movement_id,
                },
            )

        db.flush()
        saved = StockReconciliationService._load_window(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            business_date=business_date,
            shift=shift_key,
        )
        return StockReconciliationService._serialize_closed_window(db, saved)
