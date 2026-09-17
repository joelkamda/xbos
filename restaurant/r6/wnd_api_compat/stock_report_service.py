from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session


BUSINESS_TZ = ZoneInfo("Africa/Douala")


def _d(value: Any) -> Decimal:
    try:
        return Decimal(str(value if value is not None else 0))
    except Exception:
        return Decimal("0")


def _n(value: Any) -> float:
    return float(_d(value))


def _business_window(start_date: str, end_date: str):
    try:
        start_day = date.fromisoformat(start_date)
        end_day = date.fromisoformat(end_date)
    except ValueError as exc:
        raise ValueError("Stock report dates must use YYYY-MM-DD.") from exc

    if end_day < start_day:
        raise ValueError("Stock report end date cannot be before start date.")

    start_local = datetime.combine(
        start_day,
        time(hour=8),
        tzinfo=BUSINESS_TZ,
    )
    end_local = datetime.combine(
        end_day + timedelta(days=1),
        time(hour=8),
        tzinfo=BUSINESS_TZ,
    )

    return (
        start_local.astimezone(timezone.utc),
        end_local.astimezone(timezone.utc),
    )


def _trusted_unit_cost(group_label: str, product_name: str, unit_cost: Decimal) -> bool:
    if unit_cost <= 0:
        return False

    group = str(group_label or "").strip().lower()
    name = str(product_name or "").strip().lower()

    trusted_groups = {
        "beer",
        "wine",
        "whisky",
        "whiskey",
        "spirit",
        "spirits",
        "water",
        "soft drink",
        "soft drinks",
        "juice",
        "energy drink",
        "energy drinks",
        "champagne",
        "cocktail",
        "cocktails",
    }

    return (
        group in trusted_groups
        or ("takeaway" in name and "package" in name)
    )


class StockReportService:
    """
    Track-A WND stock-control report.

    Read-only evidence:
    - inventory movement ledger = stock control
    - sale_items / sales = independent POS product-sales control
    - physical count is joined by the frontend from the persisted
      reconciliation close for a selected day/shift

    sale_commit is a zero-delta lifecycle marker and never contributes
    another quantity deduction.

    Historical opening inventory is intentionally not reconstructed because
    the pre-stabilization cache/baseline mismatch is known to be unreliable.
    """

    @staticmethod
    def report(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        start_date: str,
        end_date: str,
    ) -> Dict[str, Any]:
        start_utc, end_utc = _business_window(start_date, end_date)

        params = {
            "tenant_id": int(tenant_id),
            "branch_id": int(branch_id),
            "start_utc": start_utc,
            "end_utc": end_utc,
        }

        products = db.execute(
            text(
                """
                WITH commerce_group AS (
                    SELECT
                        aut.atomic_unit_id,
                        (
                            array_agg(
                                n.name
                                ORDER BY
                                    COALESCE(n.sort_order, 999999),
                                    n.id
                            )
                        )[1] AS group_label
                    FROM atomic_unit_taxonomy aut
                    JOIN taxonomy_nodes n
                      ON n.id = aut.taxonomy_node_id
                    WHERE n.tenant_id = :tenant_id
                      AND UPPER(COALESCE(n.taxonomy_type, '')) = 'COMMERCE'
                      AND LOWER(COALESCE(n.semantic_level, '')) = 'subcategory'
                    GROUP BY aut.atomic_unit_id
                )
                SELECT
                    a.id AS atomic_unit_id,
                    a.name AS product_name,
                    COALESCE(cg.group_label, 'Other') AS group_label,
                    COALESCE(i.quantity_on_hand, 0) AS current_on_hand,
                    i.reorder_level,
                    COALESCE(a.unit_price, 0) AS selling_price,
                    CASE
                        WHEN a.meta IS NOT NULL
                         AND COALESCE(a.meta->>'cost_price', '') ~
                             '^[+-]?[0-9]+([.][0-9]+)?$'
                        THEN (a.meta->>'cost_price')::numeric
                        WHEN a.meta IS NOT NULL
                         AND COALESCE(a.meta->>'last_purchase_price', '') ~
                             '^[+-]?[0-9]+([.][0-9]+)?$'
                        THEN (a.meta->>'last_purchase_price')::numeric
                        ELSE 0::numeric
                    END AS unit_cost
                FROM inventory_items i
                JOIN atomic_units a
                  ON a.id = i.atomic_unit_id
                 AND a.tenant_id = i.tenant_id
                LEFT JOIN commerce_group cg
                  ON cg.atomic_unit_id = a.id
                WHERE i.tenant_id = :tenant_id
                  AND i.branch_id = :branch_id
                  AND COALESCE(a.is_active, TRUE) = TRUE
                  AND LOWER(TRIM(COALESCE(a.name, '')))
                        NOT LIKE 'delivery fee%'
                ORDER BY
                    LOWER(COALESCE(cg.group_label, 'Other')),
                    LOWER(COALESCE(a.name, '')),
                    a.id
                """
            ),
            params,
        ).mappings().all()

        movement_rows = db.execute(
            text(
                """
                SELECT
                    atomic_unit_id,
                    COALESCE(SUM(
                        CASE WHEN movement_type = 'stock_in'
                             THEN GREATEST(quantity_delta, 0)
                             ELSE 0 END
                    ), 0) AS stock_in_qty,
                    COALESCE(SUM(
                        CASE WHEN movement_type IN (
                            'sale_hold',
                            'sale_hold_adjust',
                            'sale_hold_release'
                        )
                        THEN quantity_delta ELSE 0 END
                    ), 0) AS reservation_delta,
                    COALESCE(SUM(
                        CASE WHEN movement_type = 'sale'
                             THEN quantity_delta ELSE 0 END
                    ), 0) AS direct_sale_delta,
                    COALESCE(SUM(
                        CASE WHEN movement_type = 'adjustment'
                             THEN quantity_delta ELSE 0 END
                    ), 0) AS adjustment_delta,
                    COALESCE(SUM(
                        CASE WHEN movement_type IN ('waste', 'loss', 'spoilage')
                             THEN quantity_delta ELSE 0 END
                    ), 0) AS waste_loss_delta,
                    COALESCE(SUM(
                        CASE WHEN movement_type = 'stock_count'
                             THEN quantity_delta ELSE 0 END
                    ), 0) AS stock_count_delta,
                    COALESCE(SUM(quantity_delta), 0) AS movement_net,
                    COUNT(*) FILTER (
                        WHERE movement_type = 'sale_commit'
                    ) AS commit_markers
                FROM inventory_movements
                WHERE tenant_id = :tenant_id
                  AND branch_id = :branch_id
                  AND created_at >= :start_utc
                  AND created_at < :end_utc
                GROUP BY atomic_unit_id
                """
            ),
            params,
        ).mappings().all()

        reservation_state_rows = db.execute(
            text(
                """
                WITH reservation_by_order AS (
                    SELECT
                        atomic_unit_id,
                        reference_id AS order_id,
                        COALESCE(SUM(
                            CASE
                                WHEN movement_type IN (
                                    'sale_hold',
                                    'sale_hold_adjust',
                                    'sale_hold_release'
                                )
                                THEN quantity_delta
                                ELSE 0
                            END
                        ), 0) AS reservation_delta,
                        BOOL_OR(
                            movement_type = 'sale_commit'
                        ) AS has_commit
                    FROM inventory_movements
                    WHERE tenant_id = :tenant_id
                      AND branch_id = :branch_id
                      AND created_at >= :start_utc
                      AND created_at < :end_utc
                      AND reference_type = 'order'
                    GROUP BY
                        atomic_unit_id,
                        reference_id
                )
                SELECT
                    atomic_unit_id,
                    COALESCE(SUM(
                        CASE
                            WHEN has_commit
                            THEN GREATEST(-reservation_delta, 0)
                            ELSE 0
                        END
                    ), 0) AS committed_reserved_qty,
                    COALESCE(SUM(
                        CASE
                            WHEN NOT has_commit
                            THEN GREATEST(-reservation_delta, 0)
                            ELSE 0
                        END
                    ), 0) AS active_hold_qty
                FROM reservation_by_order
                GROUP BY atomic_unit_id
                """
            ),
            params,
        ).mappings().all()

        sales_rows = db.execute(
            text(
                """
                SELECT
                    si.atomic_unit_id,
                    COALESCE(SUM(si.quantity), 0) AS sales_qty,
                    COALESCE(SUM(
                        CASE
                            WHEN COALESCE(s.unpaid_amount, 0) <= 0
                            THEN si.quantity ELSE 0
                        END
                    ), 0) AS paid_qty,
                    COALESCE(SUM(
                        CASE
                            WHEN COALESCE(s.unpaid_amount, 0) > 0
                             AND (
                                COALESCE(s.total, 0)
                                - COALESCE(s.unpaid_amount, 0)
                             ) > 0
                            THEN si.quantity ELSE 0
                        END
                    ), 0) AS partial_qty,
                    COALESCE(SUM(
                        CASE
                            WHEN COALESCE(s.unpaid_amount, 0) > 0
                             AND (
                                COALESCE(s.total, 0)
                                - COALESCE(s.unpaid_amount, 0)
                             ) <= 0
                            THEN si.quantity ELSE 0
                        END
                    ), 0) AS unpaid_qty,
                    COALESCE(SUM(si.line_total), 0) AS sales_value
                FROM sale_items si
                JOIN sales s
                  ON s.id = si.sale_id
                WHERE s.tenant_id = :tenant_id
                  AND s.branch_id = :branch_id
                  AND s.created_at >= :start_utc
                  AND s.created_at < :end_utc
                  AND LOWER(COALESCE(s.status, ''))
                        NOT IN ('cancelled', 'canceled', 'void', 'refunded')
                GROUP BY si.atomic_unit_id
                """
            ),
            params,
        ).mappings().all()

        movements = {
            int(row["atomic_unit_id"]): dict(row)
            for row in movement_rows
        }
        sales = {
            int(row["atomic_unit_id"]): dict(row)
            for row in sales_rows
        }

        reservation_states = {
            int(row["atomic_unit_id"]): dict(row)
            for row in reservation_state_rows
        }

        summary = {
            "products": 0,
            "stock_in_qty": 0.0,
            "reservation_consumption_qty": 0.0,
            "active_hold_qty": 0.0,
            "committed_reserved_qty": 0.0,
            "reservation_sales_control_delta": 0.0,
            "direct_sale_qty": 0.0,
            "adjustment_net_qty": 0.0,
            "waste_loss_qty": 0.0,
            "stock_count_net_qty": 0.0,
            "movement_net_qty": 0.0,
            "pos_sales_qty": 0.0,
            "paid_sales_qty": 0.0,
            "partial_sales_qty": 0.0,
            "unpaid_sales_qty": 0.0,
            "pos_sales_value": 0.0,
            "current_on_hand_qty": 0.0,
            "trusted_stock_value": 0.0,
            "valued_products": 0,
            "commit_markers": 0,
        }

        groups: Dict[str, List[Dict[str, Any]]] = {}
        items: List[Dict[str, Any]] = []

        for product in products:
            au_id = int(product["atomic_unit_id"])
            name = str(product["product_name"] or f"AU {au_id}")
            group = str(product["group_label"] or "Other")

            movement = movements.get(au_id, {})
            sale = sales.get(au_id, {})
            reservation_state = reservation_states.get(au_id, {})

            reservation_delta = _d(movement.get("reservation_delta"))
            direct_sale_delta = _d(movement.get("direct_sale_delta"))
            waste_delta = _d(movement.get("waste_loss_delta"))
            unit_cost = _d(product.get("unit_cost"))
            on_hand = _d(product.get("current_on_hand"))

            trusted = _trusted_unit_cost(
                group,
                name,
                unit_cost,
            )

            trusted_value = (
                on_hand * unit_cost
                if trusted and on_hand > 0
                else Decimal("0")
            )

            row = {
                "atomic_unit_id": au_id,
                "product_name": name,
                "group_label": group,
                "current_on_hand": _n(on_hand),
                "reorder_level": product.get("reorder_level"),
                "selling_price": _n(product.get("selling_price")),
                "unit_cost": _n(unit_cost) if trusted else None,
                "cost_basis": (
                    "trusted_unit_cost"
                    if trusted
                    else "not_trusted_for_track_a_valuation"
                ),
                "trusted_stock_value": _n(trusted_value),
                "stock_in_qty": _n(movement.get("stock_in_qty")),
                "reservation_consumption_qty": _n(
                    max(Decimal("0"), -reservation_delta)
                ),
                "active_hold_qty": _n(
                    reservation_state.get("active_hold_qty")
                ),
                "committed_reserved_qty": _n(
                    reservation_state.get("committed_reserved_qty")
                ),
                "reservation_delta": _n(reservation_delta),
                "direct_sale_qty": _n(
                    max(Decimal("0"), -direct_sale_delta)
                ),
                "adjustment_net_qty": _n(
                    movement.get("adjustment_delta")
                ),
                "waste_loss_qty": _n(
                    max(Decimal("0"), -waste_delta)
                ),
                "stock_count_net_qty": _n(
                    movement.get("stock_count_delta")
                ),
                "movement_net_qty": _n(
                    movement.get("movement_net")
                ),
                "commit_markers": int(
                    movement.get("commit_markers") or 0
                ),
                "pos_sales_qty": _n(sale.get("sales_qty")),
                "paid_sales_qty": _n(sale.get("paid_qty")),
                "partial_sales_qty": _n(sale.get("partial_qty")),
                "unpaid_sales_qty": _n(sale.get("unpaid_qty")),
                "pos_sales_value": _n(sale.get("sales_value")),
                "reservation_sales_control_delta": (
                    _n(reservation_state.get("committed_reserved_qty"))
                    + _n(
                        max(
                            Decimal("0"),
                            -direct_sale_delta,
                        )
                    )
                    - _n(sale.get("sales_qty"))
                ),
            }

            items.append(row)
            groups.setdefault(group, []).append(row)

            summary["products"] += 1

            for key in (
                "stock_in_qty",
                "reservation_consumption_qty",
                "active_hold_qty",
                "committed_reserved_qty",
                "reservation_sales_control_delta",
                "direct_sale_qty",
                "adjustment_net_qty",
                "waste_loss_qty",
                "stock_count_net_qty",
                "movement_net_qty",
                "pos_sales_qty",
                "paid_sales_qty",
                "partial_sales_qty",
                "unpaid_sales_qty",
                "pos_sales_value",
                "current_on_hand",
                "trusted_stock_value",
            ):
                target = (
                    "current_on_hand_qty"
                    if key == "current_on_hand"
                    else key
                )
                summary[target] += float(row[key])

            summary["commit_markers"] += row["commit_markers"]

            if trusted:
                summary["valued_products"] += 1

        grouped = [
            {
                "label": label,
                "items": sorted(
                    rows,
                    key=lambda row: (
                        str(row["product_name"]).lower(),
                        int(row["atomic_unit_id"]),
                    ),
                ),
            }
            for label, rows in sorted(
                groups.items(),
                key=lambda pair: pair[0].lower(),
            )
        ]

        return {
            "start_date": start_date,
            "end_date": end_date,
            "window": {
                "start": start_utc.isoformat(),
                "end": end_utc.isoformat(),
                "business_timezone": "Africa/Douala",
                "business_day_start": "08:00",
            },
            "tenant_id": int(tenant_id),
            "branch_id": int(branch_id),
            "summary": summary,
            "groups": grouped,
            "items": items,
            "warnings": [
                {
                    "code": "LEGACY_OPENING_NOT_RECONSTRUCTED",
                    "message": (
                        "Historical opening quantity is intentionally not "
                        "reconstructed because the legacy baseline/cache "
                        "mismatch is not trustworthy."
                    ),
                },
                {
                    "code": "SALES_IS_CONTROL_NOT_SECOND_STOCK_EFFECT",
                    "message": (
                        "POS product-sales quantity is independent control "
                        "evidence. It is never added as another stock deduction."
                    ),
                },
                {
                    "code": "VALUATION_CONSERVATIVE",
                    "message": (
                        "Value is shown only where a trusted per-unit cost "
                        "basis is available. Kitchen/expense-allocated products "
                        "remain unvalued."
                    ),
                },
            ],
        }
