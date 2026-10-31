# main.py

from fastapi import FastAPI

from core.security.oidc_access_log_redaction import install_access_log_filter

# Configure the worker access logger before the ASGI app can receive requests.
install_access_log_filter()

from startup import create_app

# ---------------------------------------------------------
# Create the XBOS Kernel Application
# ---------------------------------------------------------

app: FastAPI = create_app()

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
