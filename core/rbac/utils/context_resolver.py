def get_tenant(request):
    return getattr(request.state, "tenant", None)
