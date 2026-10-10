"""Minimal neutral domain-policy contract for VN0.

No restaurant taxonomy, tenant identity, pack implementation or side effects.
Policy selection/binding remains explicit; absence always fails safe.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class OperationalPolicy(Protocol):
    def category_family(self, category_name: str | None) -> str | None: ...
    def name_family(self, name: str) -> str | None: ...
    def subcategory_score(self, name: str, subcategory: str | None) -> int: ...
    def negative_stock(self, family: str) -> bool: ...
    def disable_when_out(self, family: str, stock_tracked: bool) -> bool: ...
    def fulfillment(self, names: set[str], category: str, subcategory: str, status: str) -> dict: ...


class NeutralOperationalPolicy:
    """No pack grants restaurant decisions or implicit negative stock."""

    @staticmethod
    def category_family(category_name: str | None) -> str | None:
        return None

    @staticmethod
    def name_family(name: str) -> str | None:
        return None

    @staticmethod
    def subcategory_score(name: str, subcategory: str | None) -> int:
        return 0

    @staticmethod
    def negative_stock(family: str) -> bool:
        return False

    @staticmethod
    def disable_when_out(family: str, stock_tracked: bool) -> bool:
        return False

    @staticmethod
    def fulfillment(names: set[str], category: str, subcategory: str, status: str) -> dict:
        return {
            "requires_fulfillment": False,
            "requires_preparation": False,
            "fulfillment_queue": None,
            "fulfillment_station": None,
            "fulfillment_status": status if status != "waiting" else None,
            "show_queue_qualifier": False,
        }


NEUTRAL_POLICY = NeutralOperationalPolicy()
