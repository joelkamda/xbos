"""Stable public contracts for neutral documents, files, evidence, and search."""
from __future__ import annotations
from dataclasses import dataclass,field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

class DocumentStatus(StrEnum):
    ACTIVE="active"; ARCHIVED="archived"; WITHDRAWN="withdrawn"
class EvidenceStatus(StrEnum):
    ACTIVE="active"; ENDED="ended"

@dataclass(frozen=True)
class Document:
    public_id:UUID; tenant_id:int; title:str; classification_code:str; status:DocumentStatus
    current_version_number:int=0; metadata:dict[str,Any]=field(default_factory=dict); row_version:int=1

@dataclass(frozen=True)
class DocumentVersion:
    public_id:UUID; tenant_id:int; document_public_id:UUID; version_number:int; file_name:str; content_type:str
    content_length:int; content_sha256:str; storage_provider:str; storage_key:str; created_by_reference:str|None=None
    created_at:datetime|None=None

@dataclass(frozen=True)
class EvidenceLink:
    public_id:UUID; tenant_id:int; document_public_id:UUID; version_public_id:UUID; subject_authority:str
    subject_reference:str; relation_code:str; status:EvidenceStatus; ended_at:datetime|None=None
    end_reason_code:str|None=None; row_version:int=1

@dataclass(frozen=True)
class SearchHit:
    document_public_id:UUID; title:str; classification_code:str; status:DocumentStatus
    current_version_number:int; current_version_public_id:UUID|None; current_file_name:str|None; current_content_type:str|None

@dataclass(frozen=True)
class CreateDocument:
    command_key:str; tenant_id:int; title:str; classification_code:str; metadata:dict[str,Any]=field(default_factory=dict)

@dataclass(frozen=True)
class RegisterFileVersion:
    command_key:str; tenant_id:int; document_public_id:UUID; expected_document_version:int
    file_name:str; content_type:str; content_length:int; content_sha256:str; storage_provider:str; storage_key:str
    created_by_reference:str|None=None

@dataclass(frozen=True)
class LinkEvidence:
    command_key:str; tenant_id:int; document_public_id:UUID; expected_document_version:int
    subject_authority:str; subject_reference:str; relation_code:str; version_public_id:UUID|None=None

@dataclass(frozen=True)
class EndEvidenceLink:
    command_key:str; tenant_id:int; link_public_id:UUID; expected_version:int; reason_code:str; occurred_at:datetime

@dataclass(frozen=True)
class ChangeDocumentStatus:
    command_key:str; tenant_id:int; document_public_id:UUID; expected_version:int; to_status:DocumentStatus
    reason_code:str; occurred_at:datetime
