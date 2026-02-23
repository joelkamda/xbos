# app.py

from startup import create_app

# -----------------------------------------------------
# XBOS Kernel entrypoint
# Allows: uvicorn app:app --reload
# -----------------------------------------------------

app = create_app()
