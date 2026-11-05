# main.py

from fastapi import FastAPI

from core.security.oidc_access_log_redaction import install_access_log_filter

# Configure the worker access logger before the ASGI app can receive requests.
install_access_log_filter()

import os

from restaurant.customer_channel.swes_r48_protected_launcher import (
    load_verified_gateway_custody_admission,
)
from startup import create_app

# ---------------------------------------------------------
# Create the XBOS Kernel Application
# ---------------------------------------------------------
# Ordinary startup still has NO protected admission. Only the explicit TEST
# gate plus independently PCR-signed key-custody grant can admit this receiver.
# Missing/invalid operative proof aborts startup, never silently degrades.

app: FastAPI = create_app(
    gateway_custody_admission=load_verified_gateway_custody_admission(
        environ=os.environ
    )
)

# ---------------------------------------------------------
# Basic health check endpoint
# ---------------------------------------------------------

@app.get("/health")
def health():
    return {
        "status": "ok",
        "kernel": "online",
        "version": "1.0.0"
    }

# ---------------------------------------------------------
# Allow running with: python main.py
# ---------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8001,
        reload=True
    )
