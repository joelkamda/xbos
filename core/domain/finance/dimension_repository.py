"""Effective-dated, fail-closed resolution of posting dimensions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from sqlalchemy import text

from .dimension_contract import PostingDimensionContext
from .event_contract import FinancialEventValidationError
from .event_repository import FinancialEventRecord


@dataclass(frozen=True)
class DimensionPolicy:
    dimension_type_id: int
    dimension_code: str
    requirement: str
    default_dimension_value_id: int | None
    default_value_code: str | None
    default_display_name: str | None
    profile_specific: bool
    role_specific: bool

    @property
    def specificity(self) -> int:
        return (2 if self.profile_specific else 0) + (1 if self.role_specific else 0)


class FinancialDimensionRepository:
    @classmethod
    def resolve_line_snapshot(
        cls,
        session,
        event: FinancialEventRecord,
        *,
        profile_code: str,
        account_role: str,
        context: PostingDimensionContext,
    ) -> dict[str, dict[str, object]]:
        selected_values = context.for_account_role(account_role)
        policies = cls._effective_policies(
            session,
            event,
            profile_code=profile_code,
            account_role=account_role,
        )
        policy_by_dimension = cls._select_precedence(policies)

        not_allowed = sorted(set(selected_values) - set(policy_by_dimension))
        if not_allowed:
            raise FinancialEventValidationError(
                "dimension_not_allowed",
                "posting dimensions have no effective policy for this line: "
                + ", ".join(not_allowed),
            )

        snapshot: dict[str, dict[str, object]] = {}
        for dimension_code in sorted(policy_by_dimension):
            policy = policy_by_dimension[dimension_code]
            supplied = selected_values.get(dimension_code)
            if policy.requirement == "forbidden":
                if supplied is not None:
                    raise FinancialEventValidationError(
                        "dimension_forbidden",
                        f"dimension {dimension_code} is forbidden for account role {account_role}",
                    )
                continue

            selection_source = "posting_context"
            if supplied is None and policy.default_dimension_value_id is not None:
                supplied = policy.default_value_code
                selection_source = "policy_default"
            if supplied is None:
                if policy.requirement == "required":
                    raise FinancialEventValidationError(
                        "dimension_required",
                        f"dimension {dimension_code} is required for account role {account_role}",
                    )
                continue

            value = cls._resolve_value(
                session,
                event,
                dimension_type_id=policy.dimension_type_id,
                value_code=supplied,
            )
            if (
                selection_source == "policy_default"
                and int(value["id"]) != policy.default_dimension_value_id
            ):
                raise FinancialEventValidationError(
                    "dimension_default_mismatch",
                    f"dimension {dimension_code} default no longer resolves deterministically",
                )
            snapshot[dimension_code] = {
                "dimension_type_id": policy.dimension_type_id,
                "dimension_value_id": int(value["id"]),
                "value_code": value["value_code"],
                "display_name": value["display_name"],
                "selection_source": selection_source,
            }
        return snapshot

    @staticmethod
    def _effective_policies(
        session,
        event: FinancialEventRecord,
        *,
        profile_code: str,
        account_role: str,
    ) -> tuple[DimensionPolicy, ...]:
        rows = session.execute(
            text(
                """
                SELECT policy.dimension_type_id,
                       dimension.dimension_code,
                       policy.requirement,
                       policy.default_dimension_value_id,
                       default_value.value_code AS default_value_code,
                       default_value.display_name AS default_display_name,
                       policy.posting_profile_code,
                       policy.account_role
                FROM public.posting_dimension_policies policy
                JOIN public.financial_dimension_types dimension
                  ON dimension.tenant_id = policy.tenant_id
                 AND dimension.id = policy.dimension_type_id
                LEFT JOIN public.financial_dimension_values default_value
                  ON default_value.tenant_id = policy.tenant_id
                 AND default_value.dimension_type_id = policy.dimension_type_id
                 AND default_value.id = policy.default_dimension_value_id
                WHERE policy.tenant_id = :tenant_id
                  AND policy.legal_entity_unit_id = :organization_unit_id
                  AND policy.posting_profile_code IN ('*', :profile_code)
                  AND policy.account_role IN ('*', :account_role)
                  AND policy.active
                  AND dimension.active
                  AND policy.effective_from <= :business_date
                  AND (policy.effective_to IS NULL OR policy.effective_to >= :business_date)
                  AND dimension.effective_from <= :business_date
                  AND (dimension.effective_to IS NULL OR dimension.effective_to >= :business_date)
                ORDER BY policy.dimension_type_id, policy.id
                FOR SHARE OF policy, dimension
                """
            ),
            {
                "tenant_id": event.tenant_id,
                "organization_unit_id": event.organization_unit_id,
                "profile_code": profile_code,
                "account_role": account_role,
                "business_date": event.business_date,
            },
        ).mappings().all()
        return tuple(
            DimensionPolicy(
                dimension_type_id=int(row["dimension_type_id"]),
                dimension_code=row["dimension_code"],
                requirement=row["requirement"],
                default_dimension_value_id=(
                    int(row["default_dimension_value_id"])
                    if row["default_dimension_value_id"] is not None
                    else None
                ),
                default_value_code=row["default_value_code"],
                default_display_name=row["default_display_name"],
                profile_specific=row["posting_profile_code"] != "*",
                role_specific=row["account_role"] != "*",
            )
            for row in rows
        )

    @staticmethod
    def _select_precedence(
        policies: tuple[DimensionPolicy, ...]
    ) -> Mapping[str, DimensionPolicy]:
        grouped: dict[str, list[DimensionPolicy]] = {}
        for policy in policies:
            grouped.setdefault(policy.dimension_code, []).append(policy)
        selected: dict[str, DimensionPolicy] = {}
        for code, candidates in grouped.items():
            best = max(item.specificity for item in candidates)
            winners = [item for item in candidates if item.specificity == best]
            if len(winners) != 1:
                raise FinancialEventValidationError(
                    "dimension_policy_ambiguous",
                    f"multiple equally specific policies resolve dimension {code}",
                )
            selected[code] = winners[0]
        return selected

    @staticmethod
    def _resolve_value(
        session,
        event: FinancialEventRecord,
        *,
        dimension_type_id: int,
        value_code: str,
    ):
        rows = session.execute(
            text(
                """
                SELECT id, value_code, display_name
                FROM public.financial_dimension_values
                WHERE tenant_id = :tenant_id
                  AND dimension_type_id = :dimension_type_id
                  AND value_code = :value_code
                  AND active
                  AND effective_from <= :business_date
                  AND (effective_to IS NULL OR effective_to >= :business_date)
                ORDER BY effective_from DESC, id DESC
                LIMIT 2
                FOR SHARE
                """
            ),
            {
                "tenant_id": event.tenant_id,
                "dimension_type_id": dimension_type_id,
                "value_code": value_code,
                "business_date": event.business_date,
            },
        ).mappings().all()
        if not rows:
            raise FinancialEventValidationError(
                "dimension_value_missing",
                f"dimension value {value_code} is not active for the business date",
            )
        if len(rows) != 1:
            raise FinancialEventValidationError(
                "dimension_value_ambiguous",
                f"dimension value {value_code} resolves more than once",
            )
        return rows[0]
