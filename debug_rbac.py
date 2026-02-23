# debug_rbac.py

from database import SessionLocal
from core.users.user_repository import UserRepository
from core.rbac.roles.role_packs import ROLE_PACKS
from core.rbac.permissions.permission_registry import PERMISSION_REGISTRY

db = SessionLocal()

print("\n========================")
print("🔍 ACTIVE ROLE PACK STRUCTURE")
print("========================")
print(ROLE_PACKS)

print("\n========================")
print("🔍 PERMISSION REGISTRY COUNT")
print("========================")
print(len(PERMISSION_REGISTRY.ALL), "permissions registered")

print("\n========================")
print("🔍 ROLE→PERMISSION MAPPING FROM PACK")
print("========================")

active_pack_name = list(ROLE_PACKS.keys())[0]
active_pack = ROLE_PACKS[active_pack_name]

for role_name, perms in active_pack.items():
    print(f"➡ Role: {role_name} | {len(perms)} perms")
    print("   ", perms)

print("\n========================")
print("🔍 USER TEST")
print("========================")

user = UserRepository.find_by_username(db, "cashier")
print("User:", user.username, "| role =", user.role)

role_perms = active_pack.get(user.role)
print("ROLE PERMISSIONS FROM PACK:", role_perms)

print("\n========================")
print("🔍 VALIDATION AGAINST REGISTRY")
print("========================")
invalid = [p for p in role_perms if p not in PERMISSION_REGISTRY.ALL]
print("Invalid permissions:", invalid or "None ✅")

db.close()
