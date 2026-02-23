from fastapi import HTTPException, status

# ---------------------------------------------------------
# CENTRAL ERROR REGISTRY
# ---------------------------------------------------------

ERROR_MAP = {
    # --------------------
    # Auth / User
    # --------------------
    "INVALID_CREDENTIALS": {
        "message": "Invalid username or password.",
        "status_code": status.HTTP_401_UNAUTHORIZED,
    },
    "USER_DISABLED": {
        "message": "This user account is disabled.",
        "status_code": status.HTTP_403_FORBIDDEN,
    },

    # --------------------
    # Tenant / Branch
    # --------------------
    "TENANT_NOT_FOUND": {
        "message": "Tenant not found.",
        "status_code": status.HTTP_404_NOT_FOUND,
    },
    "BRANCH_NOT_FOUND": {
        "message": "Branch not found.",
        "status_code": status.HTTP_404_NOT_FOUND,
    },
    "USER_TENANT_MISMATCH": {
        "message": "User does not belong to this tenant/branch.",
        "status_code": status.HTTP_403_FORBIDDEN,
    },
    "TENANT_CONTEXT_MISSING": {
        "message": "Tenant context missing.",
        "status_code": status.HTTP_400_BAD_REQUEST,
    },
    "TENANT_MISMATCH": {
        "message": "Token tenant does not match request tenant.",
        "status_code": status.HTTP_403_FORBIDDEN,
    },
    "BRANCH_MISMATCH": {
        "message": "Token branch does not match request branch.",
        "status_code": status.HTTP_403_FORBIDDEN,
    },
    "MISSING_TENANT_HEADER": {
        "message": "X-Tenant-Code header missing.",
        "status_code": status.HTTP_400_BAD_REQUEST,
    },
    "MISSING_BRANCH_HEADER": {
        "message": "X-Branch-Code header missing.",
        "status_code": status.HTTP_400_BAD_REQUEST,
    },

    # --------------------
    # Token
    # --------------------
    "MISSING_AUTHORIZATION": {
        "message": "Authorization header missing.",
        "status_code": status.HTTP_401_UNAUTHORIZED,
    },
    "INVALID_TOKEN": {
        "message": "Invalid authentication token.",
        "status_code": status.HTTP_401_UNAUTHORIZED,
    },
    "INVALID_TOKEN_PAYLOAD": {
        "message": "Malformed authentication payload.",
        "status_code": status.HTTP_400_BAD_REQUEST,
    },

    # --------------------
    # Catalog (NEW — REQUIRED)
    # --------------------
    "CATALOG_SUMMARY_FAILED": {
        "message": "Failed to load catalog summary.",
        "status_code": status.HTTP_500_INTERNAL_SERVER_ERROR,
    },
    "CATALOG_SUBCATEGORY_LIST_FAILED": {
        "message": "Failed to load items for subcategory.",
        "status_code": status.HTTP_500_INTERNAL_SERVER_ERROR,
    },
    "CATALOG_LIST_FAILED": {
        "message": "Failed to list catalog items.",
        "status_code": status.HTTP_500_INTERNAL_SERVER_ERROR,
    },
    "CATALOG_TAXONOMY_LIST_FAILED": {
        "message": "Failed to list catalog items by taxonomy.",
        "status_code": status.HTTP_500_INTERNAL_SERVER_ERROR,
    },
    "CATALOG_SEARCH_FAILED": {
        "message": "Catalog search failed.",
        "status_code": status.HTTP_500_INTERNAL_SERVER_ERROR,
    },
}

# ---------------------------------------------------------
# API ERROR CLASS
# ---------------------------------------------------------

class APIError(HTTPException):
    """
    Standardized application error.
    Throws well-formatted FastAPI HTTPExceptions based on ERROR_MAP.
    """

    def __init__(self, code: str):
        if code not in ERROR_MAP:
            super().__init__(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown error: {code}",
            )
            return

        err = ERROR_MAP[code]
        super().__init__(
            status_code=err["status_code"],
            detail=err["message"],
        )
