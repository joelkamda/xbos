from fastapi import FastAPI
from restaurant.customer_channel.swes_r48_ia0_receiver import install_cc_receiver


def test_missing_trusted_attestor_keeps_route_absent():
    app = FastAPI()
    assert install_cc_receiver(app, independently_verified_attestor=None) is False
    assert not any(route.path.endswith("/ia0-events") for route in app.routes)


def test_trusted_attestor_installs_once_only():
    app = FastAPI()
    assert install_cc_receiver(app, independently_verified_attestor=lambda *_: False)
    assert sum(route.path.endswith("/ia0-events") for route in app.routes) == 1
