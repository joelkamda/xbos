# ============================================================
# FILE: core/domain/inventory/taxonomy_profile.py
#
# PURPOSE:
# Resolve inventory behavior for an AtomicUnit using:
# - AtomicUnit.meta explicit overrides
# - COMMERCE taxonomy mappings
# - Safe WND-specific heuristics for ambiguous mappings
#
# WHY:
# Inventory should not blindly treat every atomic unit the same.
# Bar/drinks, kitchen/food, others, and services have different
# stock, COGS, negative-stock, and POS disable behavior.
# ============================================================

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session
from sqlalchemy import select

from core.domain.taxonomy.models import (
    AtomicUnit,
    AtomicUnitTaxonomy,
    TaxonomyNode,
)


# ============================================================
# CONSTANTS
# ============================================================

COMMERCE = "COMMERCE"
INVENTORY_DOMAIN_NAME = "Inventory"

FAMILY_BAR = "bar"
FAMILY_KITCHEN = "kitchen"
FAMILY_OTHER = "other"
FAMILY_NON_INVENTORY = "non_inventory"

COST_MODE_UNIT_COST = "unit_cost"
COST_MODE_EXPENSE_ALLOCATED = "expense_allocated"
COST_MODE_NONE = "none"


# ============================================================
# DATACLASS
# ============================================================

@dataclass
class InventoryTaxonomyProfile:
    atomic_unit_id: int
    atomic_unit_name: str

    stock_tracked: bool
    inventory_family: str

    commerce_domain: Optional[str] = None
    commerce_category: Optional[str] = None
    commerce_subcategory: Optional[str] = None

    commerce_domain_id: Optional[int] = None
    commerce_category_id: Optional[int] = None
    commerce_subcategory_id: Optional[int] = None

    cost_mode: str = COST_MODE_NONE
    allow_negative_stock: bool = False
    disable_when_out: bool = False

    source: str = "taxonomy"
    mapping_warnings: List[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        if data.get("mapping_warnings") is None:
            data["mapping_warnings"] = []
        return data


# ============================================================
# SMALL HELPERS
# ============================================================

def _norm(value: Any) -> str:
    return str(value or "").strip()


def _lower(value: Any) -> str:
    return _norm(value).lower()


def _meta(unit: Optional[AtomicUnit]) -> Dict[str, Any]:
    if not unit or not unit.meta:
        return {}

    if isinstance(unit.meta, dict):
        return unit.meta

    return {}


def _is_truthy(value: Any, default: bool = False) -> bool:
    if value is None:
        return default

    if isinstance(value, bool):
        return value

    if isinstance(value, (int, float)):
        return value != 0

    text = _lower(value)

    if text in {"true", "1", "yes", "y", "on"}:
        return True

    if text in {"false", "0", "no", "n", "off"}:
        return False

    return default


def _first_text(meta: Dict[str, Any], keys: Tuple[str, ...]) -> Optional[str]:
    for key in keys:
        value = _norm(meta.get(key))
        if value:
            return value
    return None


def _family_from_text(value: Any) -> Optional[str]:
    text = _lower(value)

    if text in {"bar", "drink", "drinks", "beverage", "beverages"}:
        return FAMILY_BAR

    if text in {"kitchen", "food", "meal", "meals"}:
        return FAMILY_KITCHEN

    if text in {"other", "others", "retail", "merchandise"}:
        return FAMILY_OTHER

    if text in {"service", "services", "subscription", "subscriptions", "digital", "non_inventory"}:
        return FAMILY_NON_INVENTORY

    return None


def _category_family(category_name: Optional[str]) -> Optional[str]:
    text = _lower(category_name)

    if text == "drinks":
        return FAMILY_BAR

    if text == "food":
        return FAMILY_KITCHEN

    if text == "others":
        return FAMILY_OTHER

    return None


# ============================================================
# WND-SAFE NAME HEURISTICS
# ============================================================

FOOD_KEYWORDS = {
    "beans",
    "eru",
    "ndole",
    "achu",
    "koki",
    "cornchaff",
    "chicken",
    "goat",
    "pork",
    "fish",
    "snail",
    "snails",
    "eggs",
    "salade",
    "salad",
    "breakfast",
    "okro",
    "egussi",
    "egusi",
    "kati",
    "gambas",
    "poulet",
    "complement",
    "plantain",
    "rice",
    "fufu",
    "gari",
    "towel",  # WND menu spelling / item naming context
}

DRINK_KEYWORDS = {
    "beer",
    "guinness",
    "export",
    "castel",
    "castle",
    "mutzig",
    "heineken",
    "kadji",
    "skoll",
    "dopple",
    "booster",
    "malta",
    "smooth",
    "origin",
    "ice",
    "red bull",
    "fanta",
    "coca",
    "coke",
    "sprite",
    "top",
    "jus",
    "juice",
    "whiskey",
    "whisky",
    "vodka",
    "jack daniels",
    "monkey shoulder",
    "champagne",
    "ruinart",
}

WINE_KEYWORDS = {
    "wine",
    "domaine",
    "chenet",
    "calvet",
    "sauvignon",
    "merlot",
    "cabernet",
    "sandara",
    "ballart",
    "oliver",
    "eschenauer",
    "chateau",
    "château",
    "bordeaux",
    "rose",
    "rosé",
}


def _name_suggests_family(name: str) -> Optional[str]:
    text = _lower(name)

    # Food gets priority to avoid "White Beans" being confused with white wine.
    if any(k in text for k in FOOD_KEYWORDS):
        return FAMILY_KITCHEN

    if any(k in text for k in DRINK_KEYWORDS):
        return FAMILY_BAR

    return None


def _subcategory_score(name: str, subcategory_name: Optional[str]) -> int:
    """
    Helps choose between multiple COMMERCE subcategory mappings.

    Example:
    - White Beans mapped to Main Dish + Wine
      => food heuristic wins category first.
    - RED BULL mapped to Beer + Wine
      => both are Drinks, but Wine is penalized because Red Bull is not wine.
    """

    text = _lower(name)
    sub = _lower(subcategory_name)

    if not sub:
        return 0

    score = 0

    if sub == "main dish":
        if any(k in text for k in FOOD_KEYWORDS):
            score += 20

    if sub == "breakfast":
        if any(k in text for k in {"egg", "eggs", "breakfast", "salade", "salad"}):
            score += 20

    if sub == "complement":
        if any(k in text for k in {"complement", "plantain", "rice", "fufu", "gari"}):
            score += 20

    if sub == "beer":
        if any(k in text for k in {
            "beer",
            "guinness",
            "export",
            "castel",
            "castle",
            "mutzig",
            "heineken",
            "kadji",
            "skoll",
            "dopple",
            "booster",
            "malta",
            "smooth",
            "origin",
            "ice",
        }):
            score += 20

        # Not perfect, but safer than Wine for common bar soft/energy drinks
        # if the product was wrongly mapped to Beer + Wine.
        if "red bull" in text:
            score += 8

    if sub == "soft drinks":
        if any(k in text for k in {"red bull", "fanta", "coke", "coca", "sprite", "top"}):
            score += 25

    if sub == "wine":
        if any(k in text for k in WINE_KEYWORDS):
            score += 20
        else:
            score -= 10

    if sub == "whiskey":
        if any(k in text for k in {"whiskey", "whisky", "jack daniels", "monkey shoulder"}):
            score += 20

    if sub == "champagne":
        if any(k in text for k in {"champagne", "ruinart"}):
            score += 20

    if sub == "juice":
        if any(k in text for k in {"juice", "jus"}):
            score += 20

    return score


# ============================================================
# TAXONOMY LOADING
# ============================================================

def _load_atomic_unit(
    db: Session,
    *,
    tenant_id: int,
    atomic_unit_id: int,
) -> Optional[AtomicUnit]:
    stmt = (
        select(AtomicUnit)
        .where(AtomicUnit.tenant_id == tenant_id)
        .where(AtomicUnit.id == atomic_unit_id)
    )

    return db.execute(stmt).scalar_one_or_none()


def _load_commerce_nodes(
    db: Session,
    *,
    tenant_id: int,
) -> Dict[int, TaxonomyNode]:
    stmt = (
        select(TaxonomyNode)
        .where(TaxonomyNode.tenant_id == tenant_id)
        .where(TaxonomyNode.taxonomy_type == COMMERCE)
        .where(TaxonomyNode.is_active.is_(True))
    )

    return {node.id: node for node in db.execute(stmt).scalars().all()}


def _load_unit_commerce_mapping_nodes(
    db: Session,
    *,
    tenant_id: int,
    atomic_unit_id: int,
) -> List[TaxonomyNode]:
    stmt = (
        select(TaxonomyNode)
        .join(
            AtomicUnitTaxonomy,
            AtomicUnitTaxonomy.taxonomy_node_id == TaxonomyNode.id,
        )
        .where(AtomicUnitTaxonomy.atomic_unit_id == atomic_unit_id)
        .where(TaxonomyNode.tenant_id == tenant_id)
        .where(TaxonomyNode.taxonomy_type == COMMERCE)
        .where(TaxonomyNode.is_active.is_(True))
        .order_by(TaxonomyNode.sort_order.asc(), TaxonomyNode.id.asc())
    )

    return list(db.execute(stmt).scalars().all())


def _inventory_candidates(
    *,
    unit_name: str,
    mapping_nodes: List[TaxonomyNode],
    all_commerce_nodes: Dict[int, TaxonomyNode],
) -> List[Dict[str, Any]]:
    """
    Return only candidates under:
      COMMERCE → Inventory

    Supports atomic units mapped to:
    - subcategory
    - category
    - domain

    Output candidate has:
    - domain/category/subcategory ids and names
    """

    candidates: List[Dict[str, Any]] = []

    for node in mapping_nodes:
        semantic = _lower(node.semantic_level)

        domain: Optional[TaxonomyNode] = None
        category: Optional[TaxonomyNode] = None
        subcategory: Optional[TaxonomyNode] = None

        if semantic == "subcategory":
            subcategory = node
            category = all_commerce_nodes.get(node.parent_id)
            if category:
                domain = all_commerce_nodes.get(category.parent_id)

        elif semantic == "category":
            category = node
            domain = all_commerce_nodes.get(node.parent_id)

        elif semantic == "domain":
            domain = node

        if not domain or _lower(domain.name) != _lower(INVENTORY_DOMAIN_NAME):
            continue

        candidates.append(
            {
                "domain_id": domain.id,
                "domain_name": domain.name,
                "category_id": category.id if category else None,
                "category_name": category.name if category else None,
                "subcategory_id": subcategory.id if subcategory else None,
                "subcategory_name": subcategory.name if subcategory else None,
                "source_node_id": node.id,
                "source_node_name": node.name,
                "source_semantic_level": node.semantic_level,
                "family": _category_family(category.name if category else None),
                "subcategory_score": _subcategory_score(
                    unit_name,
                    subcategory.name if subcategory else None,
                ),
            }
        )

    return candidates


def _choose_candidate(
    *,
    unit: AtomicUnit,
    candidates: List[Dict[str, Any]],
    meta: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    warnings: List[str] = []

    if not candidates:
        return None, warnings

    if len(candidates) == 1:
        return candidates[0], warnings

    warnings.append(
        "MULTIPLE_COMMERCE_INVENTORY_MAPPINGS: "
        + ", ".join(
            f"{c.get('category_name') or '?'}"
            + (
                f" / {c.get('subcategory_name')}"
                if c.get("subcategory_name")
                else ""
            )
            for c in candidates
        )
    )

    explicit_family = _family_from_text(
        _first_text(
            meta,
            (
                "inventory_family",
                "segment",
                "category",
                "category_name",
                "commerce_category",
            ),
        )
    )

    name_family = _name_suggests_family(unit.name)

    desired_family = explicit_family or name_family

    if desired_family:
        family_matches = [
            c for c in candidates if c.get("family") == desired_family
        ]

        if family_matches:
            family_matches.sort(
                key=lambda c: (
                    c.get("subcategory_score", 0),
                    -int(c.get("source_node_id") or 0),
                ),
                reverse=True,
            )
            return family_matches[0], warnings

    # No family signal. Prefer candidates with strongest subcategory score.
    ranked = sorted(
        candidates,
        key=lambda c: (
            c.get("subcategory_score", 0),
            # Stable fallback: category before subcategory-less domain.
            1 if c.get("subcategory_id") else 0,
            -int(c.get("source_node_id") or 0),
        ),
        reverse=True,
    )

    return ranked[0], warnings


# ============================================================
# PUBLIC RESOLVER
# ============================================================

def resolve_inventory_profile(
    db: Session,
    *,
    tenant_id: int,
    atomic_unit_id: int,
) -> Dict[str, Any]:
    """
    Resolve inventory behavior for an atomic unit.

    Resolution order:
    1. Load AtomicUnit
    2. Load COMMERCE taxonomy mappings
    3. Keep only mappings under COMMERCE → Inventory
    4. Resolve best inventory candidate
    5. Apply explicit meta overrides
    6. Return stable inventory profile dict
    """

    unit = _load_atomic_unit(
        db,
        tenant_id=tenant_id,
        atomic_unit_id=atomic_unit_id,
    )

    if not unit:
        return InventoryTaxonomyProfile(
            atomic_unit_id=atomic_unit_id,
            atomic_unit_name="",
            stock_tracked=False,
            inventory_family=FAMILY_NON_INVENTORY,
            cost_mode=COST_MODE_NONE,
            allow_negative_stock=False,
            disable_when_out=False,
            source="missing_atomic_unit",
            mapping_warnings=["ATOMIC_UNIT_NOT_FOUND"],
        ).to_dict()

    meta = _meta(unit)

    all_commerce_nodes = _load_commerce_nodes(
        db,
        tenant_id=tenant_id,
    )

    mapping_nodes = _load_unit_commerce_mapping_nodes(
        db,
        tenant_id=tenant_id,
        atomic_unit_id=atomic_unit_id,
    )

    candidates = _inventory_candidates(
        unit_name=unit.name,
        mapping_nodes=mapping_nodes,
        all_commerce_nodes=all_commerce_nodes,
    )

    candidate, warnings = _choose_candidate(
        unit=unit,
        candidates=candidates,
        meta=meta,
    )

    # --------------------------------------------------------
    # Explicit meta overrides
    # --------------------------------------------------------

    explicit_track_stock = None

    if "track_stock" in meta:
        explicit_track_stock = _is_truthy(meta.get("track_stock"), default=True)

    elif "is_stock_tracked" in meta:
        explicit_track_stock = _is_truthy(
            meta.get("is_stock_tracked"),
            default=True,
        )

    explicit_family = _family_from_text(
        _first_text(
            meta,
            (
                "inventory_family",
                "segment",
                "category",
                "category_name",
                "commerce_category",
            ),
        )
    )

    explicit_cost_mode = _first_text(meta, ("cost_mode", "inventory_cost_mode"))

    explicit_disable_when_out = (
        _is_truthy(meta.get("disable_when_out"), default=False)
        if "disable_when_out" in meta
        else None
    )

    explicit_allow_negative = (
        _is_truthy(meta.get("allow_negative_stock"), default=False)
        if "allow_negative_stock" in meta
        else None
    )

    # --------------------------------------------------------
    # Family resolution
    # --------------------------------------------------------

    candidate_family = candidate.get("family") if candidate else None
    name_family = _name_suggests_family(unit.name)

    inventory_family = (
        explicit_family
        or candidate_family
        or name_family
        or FAMILY_NON_INVENTORY
    )

    if inventory_family not in {
        FAMILY_BAR,
        FAMILY_KITCHEN,
        FAMILY_OTHER,
        FAMILY_NON_INVENTORY,
    }:
        inventory_family = FAMILY_NON_INVENTORY

    # --------------------------------------------------------
    # Stock tracking
    # --------------------------------------------------------

    if explicit_track_stock is not None:
        stock_tracked = bool(explicit_track_stock)
        source = "meta"
    else:
        # Any item under COMMERCE → Inventory is stock-aware by default.
        # Services/subscriptions/digital goods outside Inventory become false.
        stock_tracked = candidate is not None
        source = "taxonomy" if candidate else "taxonomy_non_inventory"

    # --------------------------------------------------------
    # Cost mode
    # --------------------------------------------------------

    if explicit_cost_mode:
        cost_mode = _lower(explicit_cost_mode)

    elif not stock_tracked or inventory_family == FAMILY_NON_INVENTORY:
        cost_mode = COST_MODE_NONE

    elif inventory_family == FAMILY_KITCHEN:
        cost_mode = COST_MODE_EXPENSE_ALLOCATED

    else:
        cost_mode = COST_MODE_UNIT_COST

    if cost_mode not in {
        COST_MODE_UNIT_COST,
        COST_MODE_EXPENSE_ALLOCATED,
        COST_MODE_NONE,
    }:
        cost_mode = COST_MODE_NONE

    # --------------------------------------------------------
    # Negative stock policy
    # --------------------------------------------------------

    if explicit_allow_negative is not None:
        allow_negative_stock = explicit_allow_negative

    elif inventory_family == FAMILY_KITCHEN:
        # Temporary WND V1 rule:
        # Kitchen recipe/ingredient depletion is not fully mapped yet.
        allow_negative_stock = True

    else:
        allow_negative_stock = False

    # --------------------------------------------------------
    # POS disable policy
    # --------------------------------------------------------

    if explicit_disable_when_out is not None:
        disable_when_out = explicit_disable_when_out

    elif not stock_tracked:
        disable_when_out = False

    elif inventory_family in {FAMILY_BAR, FAMILY_OTHER}:
        disable_when_out = True

    elif inventory_family == FAMILY_KITCHEN:
        # Kitchen can remain sellable during V1 soft-negative phase.
        disable_when_out = False

    else:
        disable_when_out = False

    profile = InventoryTaxonomyProfile(
        atomic_unit_id=unit.id,
        atomic_unit_name=unit.name,

        stock_tracked=stock_tracked,
        inventory_family=inventory_family,

        commerce_domain=candidate.get("domain_name") if candidate else None,
        commerce_category=candidate.get("category_name") if candidate else None,
        commerce_subcategory=candidate.get("subcategory_name") if candidate else None,

        commerce_domain_id=candidate.get("domain_id") if candidate else None,
        commerce_category_id=candidate.get("category_id") if candidate else None,
        commerce_subcategory_id=candidate.get("subcategory_id") if candidate else None,

        cost_mode=cost_mode,
        allow_negative_stock=allow_negative_stock,
        disable_when_out=disable_when_out,

        source=source,
        mapping_warnings=warnings,
    )

    return profile.to_dict()


def resolve_inventory_profiles_for_units(
    db: Session,
    *,
    tenant_id: int,
    atomic_unit_ids: List[int],
) -> Dict[int, Dict[str, Any]]:
    """
    Convenience batch helper.

    Note:
    This simple version calls the single resolver repeatedly.
    Good enough for V1. If needed later, optimize into one bulk query.
    """

    result: Dict[int, Dict[str, Any]] = {}

    for atomic_unit_id in atomic_unit_ids:
        result[int(atomic_unit_id)] = resolve_inventory_profile(
            db,
            tenant_id=tenant_id,
            atomic_unit_id=int(atomic_unit_id),
        )

    return result