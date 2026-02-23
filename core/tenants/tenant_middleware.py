async def enforce_tenant(request, call_next):
    user = getattr(request.state, "user", None)

    if not user:
        return await call_next(request)

    request.state.tenant_id = user.get("tenant_id")
    request.state.branch_id = user.get("branch_id")

    return await call_next(request)
