# core/rbac/seeds/seed_permissions.py

from core.rbac.permissions.permission_codes import PERMISSION_CODES


def seed_permissions(db, PermissionModel):
    """
    Seed all permission codes into DB (optional — if using DB storage).
    The system still works without DB persistence because JWT carries permissions.
    """
    for code, meta in PERMISSION_CODES.items():
        exists = db.query(PermissionModel).filter_by(code=code).first()
        if exists:
            continue

        perm = PermissionModel(
            code=code,
            group=meta["group"],
            description=meta["description"]
        )
        db.add(perm)

    db.commit()
    return True
