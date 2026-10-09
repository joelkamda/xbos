"""XBOS-owned public browser-session.v1 response contracts."""
from typing import Literal
from pydantic import BaseModel, Field


class BrowserSessionAccess(BaseModel):
    access_token: str = Field(min_length=1)
    token_type: Literal["bearer"] = "bearer"
    expires_in: Literal[900] = 900


class BrowserSessionLogout(BaseModel):
    status: Literal["logged_out"] = "logged_out"
