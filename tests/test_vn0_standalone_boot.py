"""Local-only standalone boot: no optional XafPay ecosystem configuration."""
import os
from pathlib import Path
import json
import unittest

for key in list(os.environ):
    if key.upper().startswith(("XMP", "XAFPAY", "CORE_", "WALLET_", "GATEWAY_", "XCIA_", "CUSTOMER_CHANNEL_")):
        os.environ.pop(key, None)

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://xbos_vn0_test@127.0.0.1:55439/xbos_vn0_test")
os.environ.setdefault("JWT_SECRET", "test-only-no-external-service")

from fastapi.testclient import TestClient
from main import app
from settings import settings

ROOT = Path(__file__).resolve().parents[1]

class VN0StandaloneBootTests(unittest.TestCase):
    def test_optional_services_not_required(self):
        self.assertIsNone(settings.GATEWAY_API_KEY)
        with TestClient(app) as client:
            self.assertEqual(client.get("/health").status_code, 200)
            self.assertEqual(client.get("/openapi.json").status_code, 200)

    def test_public_declarations_and_http_gap(self):
        pack = json.loads((ROOT / "contracts/packs/v1/pk0123_public_interfaces.json").read_text())
        admin = json.loads((ROOT / "contracts/platform_admin/v1/pa0123_public_interfaces.json").read_text())
        self.assertEqual(len(pack["public"]), 13)
        self.assertEqual(len(admin["public"]), 15)
        paths = list(app.openapi()["paths"])
        self.assertFalse(any("/pack" in path or "/merchant" in path for path in paths),
                         "VN0 inventory must not silently promote pack/admin Python commands to HTTP")

if __name__ == "__main__":
    unittest.main()
