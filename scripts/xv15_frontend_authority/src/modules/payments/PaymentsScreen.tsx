import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import { usePayments } from "./hooks/usePayments";
import { usePaymentActivity } from "./hooks/usePaymentActivity";
import { useSessionStore } from "../../lib/store/session";

import PaymentKpis from "./components/PaymentKpis";
import PaymentList from "./components/PaymentList";
import PaymentActivityLedger from "./components/PaymentActivityLedger";
import StandalonePaymentBuilder from "./components/StandalonePaymentBuilder";
import PaymentDetailPanel from "./components/PaymentDetailPanel";

function hasAnyPermission(
  userPermissions: string[] = [],
  required: string[] = [],
  role?: string | null,
) {
  if (required.length === 0) return true;
  if (String(role || "").toLowerCase() === "admin") return true;
  const set = new Set(userPermissions);
  if (set.has("*")) return true;
  return required.some((permission) => set.has(permission));
}

function AccessNotice({
  title,
  message,
}: {
  title: string;
  message: string;
}) {
  return (
    <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-amber-900">
      <div className="text-sm font-black">{title}</div>
      <div className="mt-0.5 text-xs font-medium">{message}</div>
    </div>
  );
}

export default function PaymentsScreen() {
  const [searchParams] = useSearchParams();
  const authUser = useSessionStore((s) => s.authUser);
  const session = useSessionStore((s) => s.session);
  const userPermissions = authUser?.permissions ?? session?.permissions ?? [];

  const canViewPayments = hasAnyPermission(userPermissions, ["payments.view"], authUser?.role ?? session?.role);
  const canReceivePayments = hasAnyPermission(userPermissions, [
    "payments.receive",
  ], authUser?.role ?? session?.role);
  const canSendPayments = hasAnyPermission(userPermissions, ["payments.send"], authUser?.role ?? session?.role);
  const canOperatePayments = canReceivePayments || canSendPayments;

  const [leftMode, setLeftMode] = useState<"activity" | "records">(() =>
    searchParams.get("tab") === "records" ? "records" : "activity"
  );
  const [compactMode, setCompactMode] = useState<"activity" | "operate">("activity");

  const activityActive = canViewPayments && leftMode === "activity";
  const recordsActive = canViewPayments && leftMode === "records";
  const operationActive = compactMode === "operate";

  const activity = usePaymentActivity(activityActive);

  const {
    filtered,
    selected,
    selectedId,
    setSelectedId,
    query,
    setQuery,
    kpis,
    loading: paymentsLoading,
    loadPayments,
  } = usePayments(recordsActive);

  async function refreshAll() {
    if (!canViewPayments) return;
    if (activityActive) await activity.loadActivity();
    if (recordsActive) await loadPayments();
  }

  const refreshing = activity.loading || paymentsLoading;

  return (
    <div className="flex h-full min-h-0 flex-col gap-2 overflow-hidden">
      <div className="wnd-module-strip flex shrink-0 flex-wrap items-center gap-1.5 p-1.5">
        <div className="flex shrink-0 items-center gap-2 px-2 py-1">
          <span className="wnd-module-label text-base font-black tracking-tight">
            Payments
          </span>
          <span className="wnd-module-meta rounded-full px-2 py-0.5 text-[9px] font-extrabold uppercase tracking-wide">
            Money desk
          </span>
        </div>

        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">
          <button
            type="button"
            onClick={() => {
              setLeftMode("activity");
              setCompactMode("activity");
            }}
            className={`wnd-subnav-item px-2.5 py-1.5 text-xs ${
              leftMode === "activity" ? "wnd-subnav-item-active" : ""
            }`}
          >
            Money Activity
          </button>
          <button
            type="button"
            onClick={() => {
              setLeftMode("records");
              setCompactMode("activity");
            }}
            className={`wnd-subnav-item px-2.5 py-1.5 text-xs ${
              leftMode === "records" ? "wnd-subnav-item-active" : ""
            }`}
          >
            Payment Records
          </button>
          {canOperatePayments && (
            <button
              type="button"
              onClick={() => setCompactMode("operate")}
              className={`wnd-subnav-item px-2.5 py-1.5 text-xs ${
                compactMode === "operate" ? "wnd-subnav-item-active" : ""
              }`}
            >
              Operate
            </button>
          )}
        </div>

        <button
          onClick={refreshAll}
          disabled={refreshing || !canViewPayments}
          className={`wnd-soft-button ml-auto px-3 py-1.5 text-xs ${
            refreshing || !canViewPayments ? "cursor-not-allowed opacity-50" : ""
          }`}
          type="button"
        >
          {refreshing ? "Refreshing..." : "Refresh"}
        </button>
      </div>

      {!canViewPayments && (
        <AccessNotice
          title="Limited payment access"
          message="Your role does not have permission to view payment activity."
        />
      )}

      <div className="grid min-h-0 flex-1 gap-2 overflow-hidden lg:grid-cols-[minmax(0,1.45fr)_minmax(300px,0.9fr)]">
        <div
          className={`min-h-0 flex-col gap-2 overflow-hidden ${
            compactMode === "activity" ? "flex" : "hidden lg:flex"
          }`}
        >
          {canViewPayments ? (
            leftMode === "activity" ? (
              <div className="min-h-0 flex-1 overflow-hidden">
                <PaymentActivityLedger
                  items={activity.filtered}
                  summary={activity.summary}
                  windowInfo={activity.windowInfo}
                  query={activity.query}
                  onQueryChange={activity.setQuery}
                  loading={activity.loading}
                  error={activity.error}
                  onRefresh={refreshAll}
                />
              </div>
            ) : (
              <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-hidden">
                <div className="shrink-0">
                  <PaymentKpis {...kpis} />
                </div>
                <div className="min-h-0 flex-1 overflow-hidden">
                  <PaymentList
                    payments={filtered}
                    selectedId={selectedId}
                    query={query}
                    onQueryChange={setQuery}
                    onSelect={setSelectedId}
                    loading={paymentsLoading}
                  />
                </div>
              </div>
            )
          ) : (
            <div className="flex h-full items-center justify-center rounded-2xl bg-white text-sm font-semibold text-neutral-500 ring-1 ring-neutral-200">
              Payment activity is restricted for your current role.
            </div>
          )}
        </div>

        <div
          className={`min-h-0 overflow-y-auto pr-0 lg:pr-1 ${
            operationActive || recordsActive ? "block" : "hidden"
          }`}
        >
          <div className="flex min-h-full flex-col gap-2 pb-2">
            {operationActive &&
              (canOperatePayments ? (
                <StandalonePaymentBuilder onPosted={refreshAll} />
              ) : (
                <AccessNotice
                  title="Money operations disabled"
                  message="Your role cannot receive, pay, or transfer money from Payments."
                />
              ))}

            {leftMode === "records" && canViewPayments && (
              <PaymentDetailPanel payment={selected} onRefresh={refreshAll} />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
