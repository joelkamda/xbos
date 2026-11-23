"""Explicit opt-in detached V3 functional TEST app, never production mounted.

Only run after N approves a dedicated nonpersonal 910001/1 TEST PostgreSQL
destination and phaseb_finance_schema.sql. Importing rehearsal_v3.api alone
does not activate the Phase B Finance router. This wrapper has no effects on
live WND, Twilio, Gateway, printing, issuer or source release.
"""
from .api import app
from .finance_phaseb_api import router as finance_phaseb_router

app.include_router(finance_phaseb_router)
