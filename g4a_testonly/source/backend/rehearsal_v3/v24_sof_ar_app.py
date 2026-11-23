"""SOF R6 opt-in isolated native TEST app. No protected source or hosted routing."""
from .v24_app import app
from .v24_sof_ar_r6 import ar
app.include_router(ar)
