from __future__ import annotations

from datetime import datetime
from calendar import monthrange
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from core.domain.accounting.models import TreasuryLog
from core.domain.sales.models import Sale, SaleItem
from core.domain.taxonomy.models import TaxonomyNode, AtomicUnit, AtomicUnitTaxonomy


# ============================================================
# MONEY / DATE HELPERS
# ============================================================

def _d(value: Any) -> Decimal:
    try:
        if value is None:
            return Decimal("0")
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def _f(value: Any) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def _month_bounds(yyyymm: str) -> Tuple[datetime, datetime]:
    """
    Convert YYYY-MM into inclusive/exclusive datetime range.

    Example:
      2026-05 -> 2026-05-01 00:00:00 to 2026-06-01 00:00:00
    """

    try:
        year_s, month_s = yyyymm.split("-")
        year = int(year_s)
        month = int(month_s)

        if month < 1 or month > 12:
            raise ValueError

    except Exception:
        raise ValueError("Invalid month format. Expected YYYY-MM.")

    last_day = monthrange(year, month)[1]

    start = datetime(year, month, 1, 0, 0, 0)

    if month == 12:
        end = datetime(year + 1, 1, 1, 0, 0, 0)
    else:
        end = datetime(year, month + 1, 1, 0, 0, 0)

    # last_day is intentionally kept available for future printable labels.
    _ = last_day

    return start, end


def _year_month_keys(year: int) -> List[str]:
    return [f"{year}-{str(i).zfill(2)}" for i in range(1, 13)]


def _py_month_keys(year: int) -> List[str]:
    return [f"{year}-{str(i).zfill(2)}" for i in range(1, 13)]


def _safe_key(value: str) -> str:
    raw = str(value or "unknown").strip().lower()

    cleaned = []
    for ch in raw:
        if ch.isalnum():
            cleaned.append(ch)
        elif ch in {" ", "-", "_", "/", "."}:
            cleaned.append("-")

    key = "".join(cleaned).strip("-")

    while "--" in key:
        key = key.replace("--", "-")

    return key or "unknown"


def _meta(log: TreasuryLog) -> Dict[str, Any]:
    return log.meta or {}


def _cost_from_meta(meta: Optional[Dict[str, Any]]) -> Decimal:
    """
    Legacy helper for cost lookup from AtomicUnit.meta.

    Monthly statements no longer auto-calculate bar/drinks COGS
    from sold quantities. COGS now comes only from explicit
    TreasuryLog COGS entries. This helper is kept for backward
    compatibility in case older/private helpers still reference it.
    """

    m = meta or {}

    for key in ("buying_price", "cost_price", "unit_cost", "purchase_price"):
        value = m.get(key)
        cost = _d(value)

        if cost > 0:
            return cost

    return Decimal("0")


# ============================================================
# STATEMENT NODE BUILDER
# ============================================================

def _node(
    *,
    key: str,
    label: str,
    amount: Decimal | float | int = Decimal("0"),
    children: Optional[List[Dict[str, Any]]] = None,
    source: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "amount": _f(amount),
        "children": children or [],
        "source": source,
        "meta": meta or {},
    }


class _TreeAccumulator:
    """
    Accumulates 2-level statement lines under a section.

    Formal report depth:
      Section -> Group -> Subcategory

    Example:
      Sales Revenue
        Bar
          Beer
        Kitchen
          Main Dish
    """

    def __init__(self, section_key: str):
        self.section_key = section_key
        self.groups: Dict[str, Dict[str, Any]] = {}

    def add(
        self,
        *,
        group_label: str,
        child_label: str,
        amount: Any,
        source: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        amt = _d(amount)

        if amt == 0:
            return

        group_label = group_label or "Unclassified"
        child_label = child_label or "Unclassified"

        group_key = _safe_key(group_label)
        child_key = _safe_key(child_label)

        if group_key not in self.groups:
            self.groups[group_key] = _node(
                key=f"{self.section_key}:{group_key}",
                label=group_label,
                amount=Decimal("0"),
                children=[],
                source=source,
            )

        group = self.groups[group_key]
        group["amount"] = _f(_d(group["amount"]) + amt)

        children = group["children"]
        existing = None

        for child in children:
            if child["key"] == f"{self.section_key}:{group_key}:{child_key}":
                existing = child
                break

        if existing:
            existing["amount"] = _f(_d(existing["amount"]) + amt)
        else:
            children.append(
                _node(
                    key=f"{self.section_key}:{group_key}:{child_key}",
                    label=child_label,
                    amount=amt,
                    children=[],
                    source=source,
                    meta=meta or {},
                )
            )

    def nodes(self) -> List[Dict[str, Any]]:
        result = list(self.groups.values())

        for group in result:
            group["children"] = sorted(
                group.get("children", []),
                key=lambda n: (str(n.get("label", "")).lower(), str(n.get("key", ""))),
            )

        return sorted(
            result,
            key=lambda n: (str(n.get("label", "")).lower(), str(n.get("key", ""))),
        )

    def total(self) -> Decimal:
        total = Decimal("0")

        for group in self.groups.values():
            total += _d(group.get("amount"))

        return total


# ============================================================
# REPORTS SERVICE
# ============================================================

class ReportsService:
    """
    Cross-domain reports service.

    This is the reporting brain for XBOS. It may read from:
    - treasury_logs
    - sales
    - sale_items
    - atomic_units
    - atomic_unit_taxonomy
    - taxonomy_nodes
    - inventory later

    V1 implemented:
    - monthly_summary()
    - monthly_statement()

    Financial truth rules:
    - Sales Revenue source of truth = SALE_REVENUE_GROSS TreasuryLog.
    - Sales grouping detail comes from SaleItem + COMMERCE taxonomy.
    - Other Income comes from OTHER_INCOME / SERVICE_REVENUE TreasuryLog.
    - COGS source of truth = explicit TreasuryLog COGS classification.
    - Inventory stock-in does not automatically create monthly statement COGS.
    - Bar/drinks COGS must be manually posted like other COGS entries.
    - Operating Expenses include EXPENSE_POSTED (excluding COGS), DISCOUNT_APPLIED, and COMPLIMENTARY_APPLIED.
    """

    # --------------------------------------------------------
    # Public: yearly summary
    # --------------------------------------------------------

    @staticmethod
    def monthly_summary(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        year: int,
    ) -> Dict[str, Any]:
        rows: List[Dict[str, Any]] = []

        ytd_income = Decimal("0")
        ytd_expense = Decimal("0")
        ytd_net = Decimal("0")

        for month_key in _py_month_keys(year):
            statement = ReportsService.monthly_statement(
                db,
                tenant_id=tenant_id,
                branch_id=branch_id,
                yyyymm=month_key,
            )

            totals = statement["totals"]

            income = _d(totals.get("sales")) + _d(totals.get("otherIncome"))
            expense = _d(totals.get("cogs")) + _d(totals.get("opex"))
            net = income - expense

            rows.append(
                {
                    "key": month_key,
                    "income": _f(income),
                    "expense": _f(expense),
                    "net": _f(net),
                    "totals": totals,
                }
            )

            ytd_income += income
            ytd_expense += expense
            ytd_net += net

        return {
            "year": year,
            "rows": rows,
            "totals": {
                "income": _f(ytd_income),
                "expense": _f(ytd_expense),
                "net": _f(ytd_net),
            },
        }

    # --------------------------------------------------------
    # Public: monthly statement
    # --------------------------------------------------------

    @staticmethod
    def monthly_statement(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        yyyymm: str,
    ) -> Dict[str, Any]:
        start, end = _month_bounds(yyyymm)

        warnings: List[Dict[str, Any]] = []

        taxonomy_nodes = ReportsService._load_taxonomy_nodes(
            db,
            tenant_id=tenant_id,
        )

        atomic_paths = ReportsService._load_atomic_unit_commerce_paths(
            db,
            tenant_id=tenant_id,
            taxonomy_nodes=taxonomy_nodes,
        )

        sales_logs = ReportsService._treasury_logs(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            start=start,
            end=end,
            event_types=["SALE_REVENUE_GROSS"],
        )

        sale_ids = ReportsService._sale_ids_from_sales_logs(sales_logs)

        sales_section, sales_detail_total = ReportsService._build_sales_revenue_section(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            sale_ids=sale_ids,
            atomic_paths=atomic_paths,
        )

        sales_total = sum((_d(log.amount) for log in sales_logs), Decimal("0"))

        if sales_total != sales_detail_total:
            warnings.append(
                {
                    "code": "SALES_TOTAL_MISMATCH",
                    "message": (
                        "SALE_REVENUE_GROSS total differs from SaleItem grouped total. "
                        "Statement uses treasury gross as the financial source of truth."
                    ),
                    "treasury_total": _f(sales_total),
                    "sale_item_total": _f(sales_detail_total),
                    "difference": _f(sales_total - sales_detail_total),
                }
            )

        if sales_total > 0 and sales_detail_total == 0:
            sales_section = [
                _node(
                    key="sales:unclassified",
                    label="Unclassified Sales",
                    amount=sales_total,
                    children=[
                        _node(
                            key="sales:unclassified:gross",
                            label="Treasury Gross Revenue",
                            amount=sales_total,
                            source="treasury_logs",
                        )
                    ],
                    source="treasury_logs",
                )
            ]

        other_income_section, other_income_total = ReportsService._build_other_income_section(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            start=start,
            end=end,
        )

        cogs_section, cogs_total, cogs_warnings = ReportsService._build_cogs_section(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            start=start,
            end=end,
            sale_ids=sale_ids,
            atomic_paths=atomic_paths,
        )

        warnings.extend(cogs_warnings)

        opex_section, opex_total = ReportsService._build_opex_section(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            start=start,
            end=end,
        )

        gross_profit = sales_total + other_income_total - cogs_total
        net_profit = gross_profit - opex_total

        return {
            "month": yyyymm,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "totals": {
                "sales": _f(sales_total),
                "otherIncome": _f(other_income_total),
                "cogs": _f(cogs_total),
                "gross": _f(gross_profit),
                "opex": _f(opex_total),
                "net": _f(net_profit),
            },
            "sections": {
                "sales": sales_section,
                "otherIncome": other_income_section,
                "cogs": cogs_section,
                "opex": opex_section,
            },
            "warnings": warnings,
            "rules": {
                "salesRevenue": "SALE_REVENUE_GROSS treasury events are the financial source of truth.",
                "otherIncome": "OTHER_INCOME and SERVICE_REVENUE treasury events.",
                "cogs": "COGS comes only from explicit TreasuryLog COGS entries. Inventory stock-in and drink sales do not automatically create COGS.",
                "opex": "EXPENSE_POSTED excluding COGS, plus DISCOUNT_APPLIED and COMPLIMENTARY_APPLIED as non-cash operating expenses.",
                "depth": "Formal statement depth is Section → Group → Subcategory. Deeper rows are reserved for drilldown.",
            },
        }

    # ========================================================
    # Treasury helpers
    # ========================================================

    @staticmethod
    def _treasury_logs(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        start: datetime,
        end: datetime,
        event_types: Optional[List[str]] = None,
    ) -> List[TreasuryLog]:
        q = (
            db.query(TreasuryLog)
            .filter(TreasuryLog.tenant_id == tenant_id)
            .filter(TreasuryLog.branch_id == branch_id)
            .filter(TreasuryLog.occurred_at >= start)
            .filter(TreasuryLog.occurred_at < end)
        )

        if event_types:
            q = q.filter(TreasuryLog.event_type.in_(event_types))

        return q.order_by(TreasuryLog.occurred_at.asc(), TreasuryLog.id.asc()).all()

    @staticmethod
    def _sale_ids_from_sales_logs(logs: List[TreasuryLog]) -> List[int]:
        ids: List[int] = []

        for log in logs:
            sale_id = None

            if log.reference_type == "sale" and log.reference_id:
                sale_id = int(log.reference_id)
            else:
                m = _meta(log)
                raw = m.get("sale_id")
                try:
                    if raw:
                        sale_id = int(raw)
                except Exception:
                    sale_id = None

            if sale_id and sale_id not in ids:
                ids.append(sale_id)

        return ids

    # ========================================================
    # Taxonomy helpers
    # ========================================================

    @staticmethod
    def _load_taxonomy_nodes(
        db: Session,
        *,
        tenant_id: int,
    ) -> Dict[int, TaxonomyNode]:
        nodes = (
            db.query(TaxonomyNode)
            .filter(TaxonomyNode.tenant_id == tenant_id)
            .filter(TaxonomyNode.is_active.is_(True))
            .all()
        )

        return {int(n.id): n for n in nodes}

    @staticmethod
    def _path_to_root(
        *,
        node_id: Optional[int],
        taxonomy_nodes: Dict[int, TaxonomyNode],
    ) -> List[TaxonomyNode]:
        if not node_id:
            return []

        path: List[TaxonomyNode] = []
        seen = set()
        current_id = int(node_id)

        while current_id and current_id not in seen:
            seen.add(current_id)

            node = taxonomy_nodes.get(current_id)
            if not node:
                break

            path.append(node)

            if not node.parent_id:
                break

            current_id = int(node.parent_id)

        path.reverse()
        return path

    @staticmethod
    def _commerce_path_info(path: List[TaxonomyNode]) -> Optional[Dict[str, Any]]:
        """
        Extract COMMERCE Inventory category/subcategory.

        Expected examples:
          Inventory -> Food -> Main Dish
          Inventory -> Drinks -> Beer
        """

        if not path:
            return None

        commerce_path = [
            n for n in path if str(n.taxonomy_type or "").upper() == "COMMERCE"
        ]

        if not commerce_path:
            return None

        domain = None
        category = None
        subcategory = None

        for node in commerce_path:
            level = str(node.semantic_level or "").lower()

            if level == "domain" and node.name == "Inventory":
                domain = node
            elif level == "category":
                category = node
            elif level == "subcategory":
                subcategory = node

        if not domain:
            return None

        if not category:
            return None

        return {
            "domain": domain.name,
            "category": category.name,
            "subcategory": subcategory.name if subcategory else category.name,
            "category_id": category.id,
            "subcategory_id": subcategory.id if subcategory else None,
            "segment": ReportsService._commerce_category_to_segment(category.name),
        }

    @staticmethod
    def _commerce_category_to_segment(category_name: str) -> str:
        name = str(category_name or "").strip().lower()

        if name == "drinks":
            return "Bar"

        if name == "food":
            return "Kitchen"

        if name == "others":
            return "Other Sales"

        return category_name or "Unclassified"

    @staticmethod
    def _load_atomic_unit_commerce_paths(
        db: Session,
        *,
        tenant_id: int,
        taxonomy_nodes: Dict[int, TaxonomyNode],
    ) -> Dict[int, Dict[str, Any]]:
        """
        Map atomic_unit_id -> COMMERCE Inventory path info.
        """

        links = (
            db.query(AtomicUnitTaxonomy)
            .join(AtomicUnit, AtomicUnit.id == AtomicUnitTaxonomy.atomic_unit_id)
            .filter(AtomicUnit.tenant_id == tenant_id)
            .all()
        )

        result: Dict[int, Dict[str, Any]] = {}

        for link in links:
            path = ReportsService._path_to_root(
                node_id=link.taxonomy_node_id,
                taxonomy_nodes=taxonomy_nodes,
            )

            info = ReportsService._commerce_path_info(path)

            if not info:
                continue

            # Prefer the deepest / subcategory path.
            existing = result.get(int(link.atomic_unit_id))

            if not existing:
                result[int(link.atomic_unit_id)] = info
                continue

            if info.get("subcategory_id") and not existing.get("subcategory_id"):
                result[int(link.atomic_unit_id)] = info

        return result

    # ========================================================
    # A. Sales Revenue
    # ========================================================

    @staticmethod
    def _build_sales_revenue_section(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        sale_ids: List[int],
        atomic_paths: Dict[int, Dict[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], Decimal]:
        if not sale_ids:
            return [], Decimal("0")

        rows = (
            db.query(SaleItem)
            .join(Sale, Sale.id == SaleItem.sale_id)
            .filter(Sale.tenant_id == tenant_id)
            .filter(Sale.branch_id == branch_id)
            .filter(Sale.id.in_(sale_ids))
            .all()
        )

        acc = _TreeAccumulator("sales")
        total = Decimal("0")

        for item in rows:
            amount = _d(item.line_total)
            total += amount

            path = atomic_paths.get(int(item.atomic_unit_id))

            if path:
                group = path.get("segment") or "Unclassified Sales"
                child = path.get("subcategory") or "Unclassified"
            else:
                group = "Unclassified Sales"
                child = "Unclassified"

            acc.add(
                group_label=group,
                child_label=child,
                amount=amount,
                source="sale_items",
                meta={
                    "atomic_unit_id": item.atomic_unit_id,
                    "sale_id": item.sale_id,
                    "name_snapshot": item.name_snapshot,
                    "quantity": item.quantity,
                },
            )

        return acc.nodes(), total

    # ========================================================
    # B. Other Income
    # ========================================================

    @staticmethod
    def _build_other_income_section(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        start: datetime,
        end: datetime,
    ) -> Tuple[List[Dict[str, Any]], Decimal]:
        logs = ReportsService._treasury_logs(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            start=start,
            end=end,
            event_types=["OTHER_INCOME", "SERVICE_REVENUE"],
        )

        acc = _TreeAccumulator("otherIncome")
        total = Decimal("0")

        for log in logs:
            amount = _d(log.amount)
            total += amount

            m = _meta(log)

            category = (
                m.get("category_name")
                or "Other Income"
            )

            subcategory = (
                m.get("subcategory_name")
                or m.get("item_name")
                or "General"
            )

            acc.add(
                group_label=category,
                child_label=subcategory,
                amount=amount,
                source="treasury_logs",
                meta={
                    "treasury_log_id": log.id,
                    "event_type": log.event_type,
                    "taxonomy_node_id": log.taxonomy_node_id,
                },
            )

        return acc.nodes(), total

    # ========================================================
    # C. COGS
    # ========================================================

    @staticmethod
    def _build_cogs_section(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        start: datetime,
        end: datetime,
        sale_ids: List[int],
        atomic_paths: Dict[int, Dict[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], Decimal, List[Dict[str, Any]]]:
        """
        Build COGS strictly from explicit accounting / treasury entries.

        V1 policy:
        - COGS must be manually posted through TreasuryLog.
        - Drinks/bar COGS is NOT auto-calculated from sold units anymore.
        - Inventory stock-in remains an inventory movement only unless a
          separate manual expense/COGS entry is posted.

        sale_ids and atomic_paths are intentionally kept in the signature so
        existing callers do not break, but they are no longer used for COGS.
        """

        _ = sale_ids
        _ = atomic_paths

        acc = _TreeAccumulator("cogs")
        warnings: List[Dict[str, Any]] = []

        manual_total = ReportsService._add_manual_cogs(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            start=start,
            end=end,
            acc=acc,
            warnings=warnings,
        )

        return acc.nodes(), manual_total, warnings

    @staticmethod
    def _is_cogs_log(log: TreasuryLog) -> bool:
        if log.event_type == "COGS_RECOGNIZED":
            return True

        if log.event_type != "EXPENSE_POSTED":
            return False

        m = _meta(log)

        category = str(m.get("category_name") or "").strip().lower()
        domain = str(m.get("domain_name") or "").strip().lower()

        if category == "cogs":
            return True

        # Fallback for older or partially-classified logs.
        subcategory = str(m.get("subcategory_name") or "").strip().lower()
        if "cogs" in subcategory:
            return True

        return domain == "expenses" and category == "cost of goods sold"

    @staticmethod
    def _manual_cogs_group(subcategory: str) -> str:
        """
        Group manual COGS into Kitchen or Bar for statement presentation.

        Bar/drinks COGS is now expected to be manually posted, so no
        double-counting warning is produced here.
        """

        s = str(subcategory or "").lower()

        if "drink" in s or "bar" in s or "shisha" in s:
            return "Bar"

        return "Kitchen"

    @staticmethod
    def _add_manual_cogs(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        start: datetime,
        end: datetime,
        acc: _TreeAccumulator,
        warnings: List[Dict[str, Any]],
    ) -> Decimal:
        logs = ReportsService._treasury_logs(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            start=start,
            end=end,
            event_types=["EXPENSE_POSTED", "COGS_RECOGNIZED"],
        )

        total = Decimal("0")

        for log in logs:
            if not ReportsService._is_cogs_log(log):
                continue

            m = _meta(log)
            amount = _d(log.amount)
            total += amount

            subcategory = (
                m.get("subcategory_name")
                or m.get("item_name")
                or "Manual COGS"
            )

            group = ReportsService._manual_cogs_group(subcategory)

            acc.add(
                group_label=group,
                child_label=subcategory,
                amount=amount,
                source="treasury_logs",
                meta={
                    "treasury_log_id": log.id,
                    "event_type": log.event_type,
                    "taxonomy_node_id": log.taxonomy_node_id,
                    "source_model": "manual_cogs",
                },
            )

        return total

    @staticmethod
    def _add_bar_calculated_cogs(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        sale_ids: List[int],
        atomic_paths: Dict[int, Dict[str, Any]],
        acc: _TreeAccumulator,
        warnings: List[Dict[str, Any]],
    ) -> Decimal:
        """
        Legacy helper.

        This method is intentionally no longer called by monthly_statement().
        It is kept temporarily to avoid breaking any old/debug code that may
        import or call private helpers during transition.
        """

        if not sale_ids:
            return Decimal("0")

        rows = (
            db.query(SaleItem, AtomicUnit)
            .join(Sale, Sale.id == SaleItem.sale_id)
            .join(AtomicUnit, AtomicUnit.id == SaleItem.atomic_unit_id)
            .filter(Sale.tenant_id == tenant_id)
            .filter(Sale.branch_id == branch_id)
            .filter(Sale.id.in_(sale_ids))
            .all()
        )

        total = Decimal("0")
        missing_cost_items = set()

        for item, unit in rows:
            path = atomic_paths.get(int(item.atomic_unit_id))

            if not path:
                continue

            category = str(path.get("category") or "").lower()
            segment = path.get("segment")

            # Bar / drinks only.
            if category != "drinks" and segment != "Bar":
                continue

            quantity = _d(item.quantity)
            unit_cost = _cost_from_meta(unit.meta)

            if unit_cost <= 0:
                missing_key = f"{unit.id}:{unit.name}"
                if missing_key not in missing_cost_items:
                    missing_cost_items.add(missing_key)
                    warnings.append(
                        {
                            "code": "MISSING_BAR_COST",
                            "message": (
                                "Bar item has no seeded cost price. COGS was calculated as 0 for this item."
                            ),
                            "atomic_unit_id": unit.id,
                            "item_name": unit.name,
                            "sale_item_name": item.name_snapshot,
                        }
                    )

            amount = quantity * unit_cost
            total += amount

            subcategory = path.get("subcategory") or "Drinks"

            acc.add(
                group_label="Bar",
                child_label=subcategory,
                amount=amount,
                source="sale_items_cost",
                meta={
                    "atomic_unit_id": unit.id,
                    "sale_id": item.sale_id,
                    "name_snapshot": item.name_snapshot,
                    "quantity": int(item.quantity or 0),
                    "unit_cost": _f(unit_cost),
                    "source_model": "bar_calculated_cogs",
                },
            )

        return total

    # ========================================================
    # E. Operating Expenses
    # ========================================================

    @staticmethod
    def _build_opex_section(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        start: datetime,
        end: datetime,
    ) -> Tuple[List[Dict[str, Any]], Decimal]:
        """
        Build all non-COGS expenses used by the monthly statement.

        Includes:
        - EXPENSE_POSTED: manually posted operating expenses.
        - DISCOUNT_APPLIED: system-generated staff/customer/promotional discounts.
        - COMPLIMENTARY_APPLIED: system-generated complimentary items/offers.

        Discounts and complimentary items are non-cash expenses. They reduce
        accounting profit but must not be treated as settlement-channel cash
        outflows in reconciliation.
        """

        logs = ReportsService._treasury_logs(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            start=start,
            end=end,
            event_types=[
                "EXPENSE_POSTED",
                "DISCOUNT_APPLIED",
                "COMPLIMENTARY_APPLIED",
            ],
        )

        acc = _TreeAccumulator("opex")
        total = Decimal("0")

        for log in logs:
            # Only manually posted COGS is excluded here because it is already
            # presented in the dedicated COGS section.
            if ReportsService._is_cogs_log(log):
                continue

            amount = abs(_d(log.amount))
            if amount == 0:
                continue

            total += amount
            m = _meta(log)

            if log.event_type == "DISCOUNT_APPLIED":
                category = (
                    m.get("category_name")
                    or ReportsService._discount_default_category(m)
                )
                subcategory = (
                    m.get("subcategory_name")
                    or m.get("display_label")
                    or m.get("discount_reason")
                    or m.get("discount_type")
                    or "Other Discount"
                )
                source = "system_discount"

            elif log.event_type == "COMPLIMENTARY_APPLIED":
                category = m.get("category_name") or "Marketing & Promotions"
                subcategory = (
                    m.get("subcategory_name")
                    or m.get("display_label")
                    or m.get("complimentary_reason")
                    or "Complimentary Items"
                )
                source = "system_complimentary"

            else:
                category = m.get("category_name") or "Operating Expenses"
                subcategory = (
                    m.get("subcategory_name")
                    or m.get("item_name")
                    or "General"
                )
                source = "treasury_logs"

            acc.add(
                group_label=category,
                child_label=subcategory,
                amount=amount,
                source=source,
                meta={
                    "treasury_log_id": log.id,
                    "event_type": log.event_type,
                    "taxonomy_node_id": log.taxonomy_node_id,
                    "non_cash": log.event_type in {
                        "DISCOUNT_APPLIED",
                        "COMPLIMENTARY_APPLIED",
                    },
                    "reference_type": log.reference_type,
                    "reference_id": log.reference_id,
                },
            )

        return acc.nodes(), total

    @staticmethod
    def _discount_default_category(meta: Dict[str, Any]) -> str:
        """
        Provide a stable report group when older discount events do not yet
        contain the richer settlement classification metadata.
        """
        raw = str(
            meta.get("display_label")
            or meta.get("discount_reason")
            or meta.get("discount_type")
            or ""
        ).strip().lower()

        if "staff" in raw:
            return "Staff Welfare"

        if any(token in raw for token in ("promo", "marketing", "loyalty", "customer")):
            return "Marketing & Promotions"

        return "Sales Allowances"