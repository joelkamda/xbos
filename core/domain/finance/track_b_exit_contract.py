"""Typed, schema-neutral Track B aggregate exit evidence."""
from __future__ import annotations

from dataclasses import dataclass


class TrackBExitError(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class TrackBExitEvidence:
    canonical_head: str
    release_components: int
    clean_replay: bool
    cross_milestone: bool
    financial_invariants: bool
    adversarial_suites: tuple[str, ...]
    development_empty: bool
    hidden_writers: tuple[str, ...]
    cutover: str
    writer_retirement: str

    def __post_init__(self) -> None:
        if not self.canonical_head or self.release_components < 12:
            raise TrackBExitError("incomplete_release_lineage", self.canonical_head)
        required = {"M8.0", "M8.1", "M8.2", "M8.3", "M8.4"}
        if set(self.adversarial_suites) != required:
            raise TrackBExitError("incomplete_adversarial_evidence", repr(self.adversarial_suites))
        if not all((self.clean_replay, self.cross_milestone, self.financial_invariants, self.development_empty)):
            raise TrackBExitError("aggregate_proof_failed", repr(self))
        if self.hidden_writers:
            raise TrackBExitError("hidden_financial_writers", repr(self.hidden_writers))
        if self.cutover != "NOT_AUTHORIZED" or self.writer_retirement != "NOT_EXECUTED":
            raise TrackBExitError("R6_boundary_exceeded", f"{self.cutover}:{self.writer_retirement}")
