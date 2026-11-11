"""Prospective revision-guarded draft, never a committed Finance movement."""
from dataclasses import dataclass,replace
class DraftDenied(ValueError):pass
@dataclass(frozen=True)
class Draft:
    tenant_id:int
    branch_id:int
    draft_id:str
    revision:int
    status:str="DRAFT"
def advance(draft:Draft,*,tenant_id:int,branch_id:int,expected_revision:int):
    if not isinstance(draft,Draft) or not (draft.tenant_id==tenant_id and draft.branch_id==branch_id and draft.draft_id and draft.status=="DRAFT" and draft.revision>=0 and draft.revision==expected_revision):
        raise DraftDenied("DRAFT_SCOPE_OR_VERSION_DENIED")
    return replace(draft,revision=draft.revision+1)
def post_as_finance(draft:Draft):
    raise DraftDenied("DRAFT_IS_NOT_FINANCE_LEDGER")
