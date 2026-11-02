"""R48 normal startup remains unexposed; trusted composer is explicit."""
from startup import create_app

PATH = "/internal/swes/track-a/test-only/ia0-events"


def test_normal_app_has_no_ia0_ingest_receiver():
    app = create_app()
    assert not any(route.path == PATH for route in app.routes)


def test_explicit_attestor_only_mounts_receiver():
    app = create_app(r48_receipt_attestor=lambda *_: False)
    assert sum(route.path == PATH for route in app.routes) == 1
