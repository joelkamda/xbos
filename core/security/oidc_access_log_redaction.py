"""Remove query strings from access log paths before output."""
from __future__ import annotations

import logging


class QueryRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            record.args = (*args[:2], args[2].split("?", 1)[0], *args[3:])
        return True


def install_access_log_filter() -> None:
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, QueryRedactionFilter) for item in logger.filters):
        logger.addFilter(QueryRedactionFilter())
