"""Pure cancellation, void, and reversal disposition semantics."""

from __future__ import annotations

from dataclasses import dataclass

from .correction_contract import ClassifyLifecycleDispositionCommand


@dataclass(frozen=True)
class LifecycleDisposition:
    action: str
    creates_financial_event: bool
    preserves_original: bool
    explanation: str


class LifecycleDispositionService:
    @staticmethod
    def classify(command: ClassifyLifecycleDispositionCommand):
        if command.requested_action == "cancel": return LifecycleDisposition("cancel", False, True, "unrecognized intent is cancelled without financial mutation")
        if command.requested_action == "void": return LifecycleDisposition("void", False, True, "non-final attempt or document is voided without erasing financial truth")
        return LifecycleDisposition("reverse", True, True, "posted financial truth remains and receives a linked inverse")
