# core/models_import.py
"""
Ensures all SQLAlchemy models are imported so Alembic and
Base.metadata can discover the full schema.
"""

# -------------------------
# Tier-0 (Existence Layer)
# -------------------------
from core.tenants.tenant_model import Tenant, Branch
from core.users.user_model import User
from core.rbac.roles.role_model import Role

# -------------------------
# Tier-1 (Business Layer)
# -------------------------
from core.domain.catalog.models import BillableUnit
from core.domain.taxonomy.models import TaxonomyNode, BillableUnitTaxonomy
from core.domain.sales.models import Sale, SaleItem
from core.domain.payments.models import PaymentIntent, PaymentAttempt
from core.domain.inventory.models import InventoryItem, InventoryMovement
