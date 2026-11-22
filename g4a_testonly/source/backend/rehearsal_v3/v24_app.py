"""Opt-in V24 detached native REST + same-origin React TEST route.
Never production mounted and never writes protected WND.
"""
from pathlib import Path
import os
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from .api import app
from .finance_phaseb_api import router as original_finance_router
from .v24_native_api import r as v24_router
app.include_router(original_finance_router)
app.include_router(v24_router)
from .v24_r4_readmodels import r4 as r4_router
app.include_router(r4_router)
from .v24_sof_ar_r6 import ar as sof_ar_router
from .v24_w_shift_handoff import handoff_router
app.include_router(sof_ar_router)
app.include_router(handoff_router)

UI=Path(os.environ.get("V24_NATIVE_ROOT","/var/tmp/v24-d7-native-integration-20261122"))/"ui"
if (UI/"index.html").is_file():
    app.mount("/assets",StaticFiles(directory=str(UI/"assets")),name="v24-detached-assets")
    @app.get("/rehearsal/v24")
    def integrated_test_ui():
        return FileResponse(UI/"index.html",headers={"Cache-Control":"no-store"})

from .v24_w_receipt_custody import reprint_router
app.include_router(reprint_router)
