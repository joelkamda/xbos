"""Create a local-only WND frontend runtime with the XV15 async XafPay seam enabled."""
from __future__ import annotations

import os
import shutil
from pathlib import Path


source = Path(os.environ.get(
    "XV15_WND_FRONTEND_SOURCE",
    str(Path.home() / "Downloads" / "XBOS_R6_3_UAT_WORKSPACE" / "frontend"),
)).resolve()
target = Path(os.environ.get(
    "XV15_WND_FRONTEND_RUNTIME",
    str(Path(os.environ["LOCALAPPDATA"]) / "XafPay" / "XV15" / "frontend"),
)).resolve()
if not source.is_dir() or source == target:
    raise RuntimeError("XV15_FRONTEND_SOURCE_INVALID")
target.parent.mkdir(parents=True, exist_ok=True)
shutil.copytree(
    source, target, dirs_exist_ok=True,
    ignore=shutil.ignore_patterns("node_modules"),
)
gateway_checkout = Path(os.environ.get(
    "XV15_GATEWAY_CHECKOUT_SOURCE",
    str(Path.home() / "xafpay-gateway-v2" / "apps" / "checkout-web" / "src"),
)).resolve()
if not gateway_checkout.is_dir():
    raise RuntimeError("XV15_GATEWAY_CHECKOUT_SOURCE_INVALID")
shutil.copytree(gateway_checkout, target / "public" / "xafpay-checkout", dirs_exist_ok=True)

screen = target / "src" / "modules" / "sales" / "ProcessingScreen.tsx"
text = screen.read_text(encoding="utf-8")
old = '''        if (isAsync) {
          throw new Error(
            "XafPay async gateway processing is not enabled in this ProcessingScreen yet. This guard prevents premature POS settlement."
          );
        }'''
new = '''        if (isAsync) {
          if (!orderId || isManual) {
            throw new Error("XafPay requires an existing WND order obligation.");
          }
          const xafpayLine = location.state?.lines?.find(
            (line: any) => line?.method === "xafpay"
          );
          const xafpayAmount = n(xafpayLine?.amount);
          if (xafpayAmount <= 0) {
            throw new Error("XafPay allocation must be greater than zero.");
          }
          const localLines = (location.state?.lines || []).filter(
            (line: any) => line?.method !== "xafpay"
          );
          if (localLines.length > 0) {
            const localTenderedTotal = localLines.reduce(
              (sum: number, line: any) => sum + n(line?.meta?.tendered ?? line?.amount),
              0
            );
            const localResult = await apiFetch("/payments/pos/settle", {
              method: "POST",
              body: JSON.stringify({
                ...location.state,
                order_id: orderId,
                lines: localLines,
                tendered_total: localTenderedTotal,
                paid_total: localLines.reduce((sum: number, line: any) => sum + n(line?.amount), 0),
                receipt_meta: {
                  ...(location.state?.receipt_meta || {}),
                  tendered_total: localTenderedTotal,
                  external_pending_amount: xafpayAmount,
                },
                external_pending_amount: xafpayAmount,
                client_reference: `wnd-ui-order-${orderId}-local-${xafpayAmount}`,
              }),
            });
            if (n(localResult?.balance_due) < xafpayAmount) {
              throw new Error("XBOS balance no longer covers the XafPay allocation.");
            }
          }
          const selectedRail = text(
            location.state?.xafpayProvider ||
              location.state?.provider ||
              xafpayLine?.provider ||
              "mtn"
          ).toLowerCase();
          const initiated = await apiFetch("/payments/xafpay/init", {
            method: "POST",
            body: JSON.stringify({
              order_id: orderId,
              amount: xafpayAmount,
              provider: selectedRail === "orange" ? "orange" : "mtn",
              client_reference: `wnd-ui-order-${orderId}-xafpay-${xafpayAmount}`,
            }),
          });
          const initiatedState = String(initiated?.status || "").toUpperCase();
          if (!initiated?.paymentUrl || !["CHECKOUT_OPEN", "CREATED", "PROCESSING", "PENDING", "SUCCEEDED"].includes(initiatedState)) {
            throw new Error("XafPay initiation response requires canonical status recovery.");
          }
          setCheckoutUrl(initiated.paymentUrl);
          setCheckoutAttemptId(String(initiated.attempt_public_id || ""));
          setCheckoutProjection({
            attempt_state: initiatedState,
            order_id: orderId,
            sale_id: initiated.sale_id,
            payment_record_id: initiated.payment_record_id,
            provider_submitted: initiated.provider_submitted === true,
            gateway_attempt_id: initiated.gateway_attempt_id,
            amount: xafpayAmount,
            balance_due: xafpayAmount,
            confirmed_settlements: 0,
          });
          return;
        }'''
if old not in text and new not in text:
    raise RuntimeError("XV15_FRONTEND_GUARD_MARKER_MISSING")
if old in text:
    text = text.replace(old, new, 1)
import_old = 'import { useEffect, useMemo, useRef } from "react";'
if import_old in text:
    text = text.replace(import_old, 'import { useEffect, useMemo, useRef, useState } from "react";', 1)
state_old = "  const hasRun = useRef(false);"
state_new = '''  const hasRun = useRef(false);
  const [checkoutUrl, setCheckoutUrl] = useState("");
  const [checkoutAttemptId, setCheckoutAttemptId] = useState("");
  const [checkoutProjection, setCheckoutProjection] = useState<any>(null);
  const [xafpayInitiationIssue, setXafpayInitiationIssue] = useState<any>(null);'''
if state_old in text and state_new not in text:
    text = text.replace(state_old, state_new, 1)
catch_old = '''      } catch (err: any) {
        console.error("[XBOS] Processing failed:", err);

        navigate(
          `/result?status=failure&message=${encodeURIComponent(
            err?.message || "Processing failed"
          )}`,
          { replace: true }
        );
      }'''
catch_new = '''      } catch (err: any) {
        console.error("[XBOS] Processing failed:", err);

        if (isAsync && orderId) {
          try {
            const recovery = await apiFetch(`/payments/xafpay/orders/${orderId}/recovery`, { cache: "no-store" });
            if (recovery?.has_xafpay_attempt) {
              const recoveredState = String(recovery.attempt_state || "UNKNOWN").toUpperCase();
              const terminal = ["FAILED", "CANCELLED", "CANCELED", "EXPIRED"].includes(recoveredState);
              setCheckoutAttemptId(String(recovery.attempt_public_id || ""));
              setCheckoutProjection(recovery);
              setXafpayInitiationIssue({
                ...recovery,
                terminal,
                message: terminal
                  ? "XafPay payment was not completed."
                  : "XafPay status is unresolved. Check the existing attempt; do not start another payment.",
              });
              return;
            }
          } catch (recoveryError) {
            console.warn("[XBOS] XafPay canonical recovery unavailable:", recoveryError);
          }
          navigate(`/payment?orderId=${orderId}`, {
            replace: true,
            state: { initiationNotice: "XafPay initiation could not be confirmed. No payment failure was established." },
          });
          return;
        }

        navigate(
          `/result?status=failure&message=${encodeURIComponent(
            err?.message || "Processing failed"
          )}`,
          { replace: true }
        );
      }'''
if catch_old not in text and catch_new not in text:
    raise RuntimeError("XV15_XAFPAY_ASYNC_CATCH_MARKER_MISSING")
if catch_old in text:
    text = text.replace(catch_old, catch_new, 1)
render_old = '''  return (
    <div className="flex h-[calc(100vh-7.5rem)] flex-col items-center justify-center gap-6">'''
render_new = '''  async function refreshCheckoutProjection() {
    if (!checkoutAttemptId) return;
    if (statusRefreshRef.current) return statusRefreshRef.current;
    const refresh = (async () => {
      setXafpayChecking(true);
      try {
        const projection = await apiFetch(`/payments/xafpay/attempts/${checkoutAttemptId}/status`, { cache: "no-store" });
        setCheckoutProjection(projection);
        return projection;
      } finally {
        setXafpayChecking(false);
        statusRefreshRef.current = null;
      }
    })();
    statusRefreshRef.current = refresh;
    return refresh;
  }

  useEffect(() => {
    if (!checkoutAttemptId || !checkoutUrl) return;
    const onMessage = (event: MessageEvent) => {
      if (event.origin !== window.location.origin) return;
      if (event.data?.type !== "xafpay.checkout.status") return;
      refreshCheckoutProjection().catch(() => undefined);
    };
    window.addEventListener("message", onMessage);
    const timer = window.setInterval(() => refreshCheckoutProjection().catch(() => undefined), 4000);
    return () => { window.removeEventListener("message", onMessage); window.clearInterval(timer); };
  }, [checkoutAttemptId]);

  async function returnFailedAttemptToPayment() {
    if (!checkoutAttemptId) return;
    const projection = await apiFetch(`/payments/xafpay/attempts/${checkoutAttemptId}/status`, { cache: "no-store" });
    const state = String(projection?.attempt_state || "").toUpperCase();
    if (!["FAILED", "CANCELLED", "CANCELED", "EXPIRED"].includes(state)) return;
    safeClearSplitPayments();
    setCheckoutUrl("");
    navigate(`/payment?orderId=${projection.order_id}`, {
      replace: true,
      state: { paymentRecovery: projection },
    });
  }

  function leaveConfirmationPending() {
    setCheckoutUrl("");
    const paymentRecordId = String(checkoutProjection?.payment_record_id || "");
    navigate(paymentRecordId ? `/payments?paymentId=${encodeURIComponent(paymentRecordId)}` : "/payments", { replace: true });
  }

  function returnToRecoverySurface() {
    const paymentRecordId = String(
      checkoutProjection?.payment_record_id ||
      xafpayInitiationIssue?.payment_record_id ||
      ""
    );
    navigate(
      paymentRecordId
        ? `/payments?tab=records&paymentId=${encodeURIComponent(paymentRecordId)}`
        : "/payments",
      { replace: true }
    );
  }

  function returnFromPreSubmissionCheckout() {
    setCheckoutUrl("");
    navigate(`/payment?orderId=${checkoutProjection?.order_id || orderId}`, { replace: true });
  }

  if (xafpayInitiationIssue && !checkoutUrl) {
    const terminal = xafpayInitiationIssue.terminal === true;
    return (
      <div className="flex h-[calc(100vh-7.5rem)] items-center justify-center p-4">
        <div className="w-full max-w-lg rounded-2xl border bg-white p-6 shadow-xl" role="status">
          <h1 className="text-xl font-bold">{terminal ? "Payment not completed" : "Payment confirmation unresolved"}</h1>
          <p className="mt-2 text-sm text-neutral-600">{xafpayInitiationIssue.message}</p>
          <p className="mt-3 font-medium">Attempt: {String(xafpayInitiationIssue.attempt_state || "UNKNOWN")}</p>
          <div className="mt-5 flex gap-3">
            <button type="button" className="rounded-lg border px-4 py-2" disabled={xafpayChecking} onClick={() => refreshCheckoutProjection()}>{xafpayChecking ? "Checking..." : "Check status"}</button>
            <button type="button" className="rounded-lg border px-4 py-2" onClick={returnToRecoverySurface}>Return to Payments</button>
            {terminal && <button type="button" className="rounded-lg bg-emerald-700 px-4 py-2 font-bold text-white" onClick={returnFailedAttemptToPayment}>Return to payment</button>}
          </div>
        </div>
      </div>
    );
  }

  if (checkoutUrl) {
    const attemptState = String(checkoutProjection?.attempt_state || "PENDING").toUpperCase();
    const preSubmission = checkoutProjection?.provider_submitted !== true && attemptState === "CHECKOUT_OPEN";
    const succeeded = attemptState === "SUCCEEDED" && checkoutProjection?.financially_confirmed === true;
    const failed = ["FAILED", "CANCELLED", "CANCELED", "EXPIRED"].includes(attemptState);
    return (
      <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 p-3" role="dialog" aria-modal="true" aria-label="XafPay secure checkout">
        <div className="flex h-[min(860px,96vh)] w-full max-w-xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl">
          <div className="flex items-center justify-between border-b px-4 py-3">
            <div><strong>XafPay secure checkout</strong><p className="text-xs text-neutral-500">WND remains open while XafPay confirms payment.</p></div>
            <button type="button" className="rounded-lg border px-3 py-2 text-sm" onClick={() => preSubmission ? returnFromPreSubmissionCheckout() : failed ? returnFailedAttemptToPayment() : leaveConfirmationPending()}>{preSubmission ? "Return to payment" : failed ? "Return to payment" : "Leave confirmation pending"}</button>
          </div>
          <div className="border-b bg-neutral-50 px-4 py-2 text-sm" aria-live="polite">
            {preSubmission ? "Choose an eligible XafPay method and continue securely when ready. No provider request has been submitted."
              : succeeded ? `XafPay payment confirmed · ${n(checkoutProjection?.amount).toLocaleString()} XAF received`
              : failed ? `XafPay attempt ${attemptState} · no settlement created`
              : `Payment confirmation ${attemptState.toLowerCase()} · do not start another payment`}
          </div>
          <iframe title="XafPay secure checkout" src={checkoutUrl} className="min-h-0 flex-1 border-0" allow="payment" referrerPolicy="no-referrer" />
          {succeeded && <button type="button" className="m-3 rounded-xl bg-emerald-700 px-4 py-3 font-bold text-white" onClick={() => navigate(`/result?saleId=${checkoutProjection.sale_id}`, { replace: true })}>View receipt / Continue</button>}
          {failed && <button type="button" className="m-3 rounded-xl bg-emerald-700 px-4 py-3 font-bold text-white" onClick={returnFailedAttemptToPayment}>Return to payment</button>}
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-[calc(100vh-7.5rem)] flex-col items-center justify-center gap-6">'''
if render_old in text and render_new not in text:
    text = text.replace(render_old, render_new, 1)
if "setCheckoutUrl(initiated.paymentUrl)" not in text or "XafPay secure checkout" not in text:
    raise RuntimeError("XV15_CHECKOUT_MODAL_WIRING_MISSING")
screen.write_text(text, encoding="utf-8")

payments_hook = target / "src" / "modules" / "payments" / "hooks" / "usePayments.ts"
payments_hook_text = payments_hook.read_text(encoding="utf-8")
payments_hook_text = payments_hook_text.replace(
'''      setSelectedId((prev) => {
        if (prev && normalized.some((p) => p.id === prev)) return prev;
        return normalized[0]?.id ?? null;
      });''',
'''      setSelectedId((prev) => {
        const requested = new URLSearchParams(window.location.search).get("paymentId");
        if (requested && normalized.some((p) => p.id === requested)) return requested;
        if (prev && normalized.some((p) => p.id === prev)) return prev;
        return normalized[0]?.id ?? null;
      });''', 1)
if 'get("paymentId")' not in payments_hook_text:
    raise RuntimeError("XV15_PENDING_PAYMENT_RECORD_DEEP_LINK_MISSING")
payments_hook.write_text(payments_hook_text, encoding="utf-8")

confirm_hook = target / "src" / "modules" / "sales" / "payment" / "hooks" / "useConfirmPay.ts"
hook_text = confirm_hook.read_text(encoding="utf-8")
old_confirm = '''      case "xafpay":
        if (xafpayProvider === "wallet") return !!xafpayWalletId.trim();
        if (xafpayProvider === "card") return !!xafpayCardRef.trim();
        return !!xafpayPhone.trim();'''
new_confirm = '''      case "xafpay":
        // Hosted Checkout/provider UI owns payer collection. The cashier only
        // needs a valid unresolved amount; canonical confirmation settles later.
        return due > 0;'''
if old_confirm not in hook_text and new_confirm not in hook_text:
    raise RuntimeError("XV15_FRONTEND_CONFIRM_MARKER_MISSING")
if old_confirm in hook_text:
    confirm_hook.write_text(hook_text.replace(old_confirm, new_confirm, 1), encoding="utf-8")

detail_panel = target / "src" / "modules" / "payments" / "components" / "PaymentDetailPanel.tsx"
detail = detail_panel.read_text(encoding="utf-8")
detail = detail.replace(
'''  settlement_mode?: string | null;
  meta?: any;''',
'''  settlement_mode?: string | null;
  origin_channel?: string | null;
  orchestrator?: string | null;
  rail?: string | null;
  meta?: any;''', 1)
detail = detail.replace(
'''    settlement_mode: raw?.settlement_mode ?? null,
    meta: raw?.meta ?? {},''',
'''    settlement_mode: raw?.settlement_mode ?? null,
    origin_channel: raw?.origin_channel ?? null,
    orchestrator: raw?.orchestrator ?? null,
    rail: raw?.rail ?? null,
    meta: raw?.meta ?? {},''', 1)
detail = detail.replace(
'''function methodLabel(attempt: PaymentAttemptView) {
  const method = attempt.method ? attempt.method.toUpperCase() : "UNKNOWN";
  const provider = attempt.provider ? ` / ${attempt.provider}` : "";
  return `${method}${provider}`;
}''',
'''function methodLabel(attempt: PaymentAttemptView) {
  const method = attempt.method ? attempt.method.replaceAll("_", " ").toUpperCase() : "UNKNOWN";
  const rail = attempt.rail ? ` / ${attempt.rail.replaceAll("_", " ").toUpperCase()}` : "";
  return `${method}${rail}`;
}''', 1)
detail = detail.replace(
'''        <div>
          <span className="font-medium">Method:</span> {payment.method}
        </div>

        {payment.provider && (
          <div>
            <span className="font-medium">Provider:</span> {payment.provider}
          </div>
        )}''',
'''        <div><span className="font-medium">Origin/channel:</span> {(payment as any).origin_channel || "POS"}</div>
        <div><span className="font-medium">Method:</span> {payment.method}</div>
        {(payment as any).orchestrator && <div><span className="font-medium">Orchestrator:</span> {(payment as any).orchestrator}</div>}
        {(payment as any).rail && <div><span className="font-medium">Rail:</span> {(payment as any).rail}</div>}
        {payment.provider && <div><span className="font-medium">Provider:</span> {payment.provider}</div>}''', 1)
detail = detail.replace(
'''                        {attempt.settlement_mode || "manual"}''',
'''                        {attempt.origin_channel ? `Origin: ${attempt.origin_channel} · ` : ""}
                        {attempt.orchestrator ? `Orchestrator: ${attempt.orchestrator} · ` : ""}
                        {attempt.settlement_mode || "manual"}''', 1)
detail = detail.replace(
'''  const canCompleteBalance = payment.status === "PENDING" && balanceDue > 0;''',
'''  const activePendingAttempts = Number((payment as any).active_pending_attempts || 0);
  const canCompleteBalance =
    ["PARTIAL", "PAYMENT_REQUIRED"].includes(payment.status) &&
    balanceDue > 0 && activePendingAttempts === 0 && hasSaleId;''', 1)
detail = detail.replace(
'''      if (canonicalAmountToCollect <= 0) {
        console.warn(
          "[PaymentDetailPanel] No balance due after canonical lookup."
        );
        return;
      }

      const originalDescription =''',
'''      if (canonicalAmountToCollect <= 0) {
        console.warn(
          "[PaymentDetailPanel] No balance due after canonical lookup."
        );
        return;
      }

      const latest = await apiFetch(`/payments/${payment.id}`, { cache: "no-store" });
      if (Number(latest?.active_pending_attempts || 0) > 0) return;
      const orderId = Number(latest?.meta?.order_id || 0);
      const exactBalance = Number(latest?.balance_due || canonicalAmountToCollect);
      if (orderId > 0 && Number(latest?.sale_id || payment.sale_id) > 0 && exactBalance > 0) {
        navigate(`/payment?orderId=${orderId}`, {
          state: {
            orderId,
            paymentRecovery: {
              attempt_state: "FAILED",
              order_id: orderId,
              sale_id: Number(latest?.sale_id || payment.sale_id),
              commercial_total: Number(latest?.amount || payment.amount),
              total_paid: Number(latest?.total_paid || 0),
              balance_due: exactBalance,
              collectible_now: exactBalance,
            },
          },
        });
        return;
      }

      const originalDescription =''', 1)
if "Origin/channel:" not in detail or "attempt.orchestrator" not in detail:
    raise RuntimeError("XV15_PAYMENT_ATTEMPT_VISIBILITY_MARKER_MISSING")
detail_panel.write_text(detail, encoding="utf-8")

# Make status results visible outside collapsed attempt history and refresh the
# parent read model through the same canonical status helper.
detail = detail_panel.read_text(encoding="utf-8")
if 'from "../xafpayRecovery"' not in detail:
    detail = detail.replace(
        'import { apiFetch } from "../../../lib/api";',
        'import { apiFetch } from "../../../lib/api";\nimport { checkXafpayCanonicalStatus, loadXafpayRecovery, xafpayOperatorResult, xafpayResumeState } from "../xafpayRecovery";', 1)
if "onRefresh?: () => Promise<void> | void" not in detail:
    detail = detail.replace(
'''export default function PaymentDetailPanel({
  payment,
}: {
  payment: Payment | null;
}) {''',
'''export default function PaymentDetailPanel({
  payment,
  onRefresh,
}: {
  payment: Payment | null;
  onRefresh?: () => Promise<void> | void;
}) {''', 1)
detail = detail.replace(
'''  const [loadingCanonical, setLoadingCanonical] = useState(false);''',
'''  const [loadingCanonical, setLoadingCanonical] = useState(false);
  const [xafpayStatusResult, setXafpayStatusResult] = useState<string | null>(null);''', 1)
detail = detail.replace(
'''      const projection = await apiFetch(`/payments/xafpay/attempts/${unresolvedXafpayAttempt.id}/status`, { cache: "no-store" });''',
'''      setXafpayStatusResult(null);
      const projection = await checkXafpayCanonicalStatus(unresolvedXafpayAttempt.id);''', 1)
detail = detail.replace(
'''      setCanonicalBalanceDue(Number(projection?.balance_due || 0));
    } finally {''',
'''      setCanonicalBalanceDue(Number(projection?.balance_due || 0));
      setXafpayStatusResult(xafpayOperatorResult(projection));
      await onRefresh?.();
    } finally {''', 1)
detail = detail.replace(
'''      const recovery = await apiFetch(`/payments/xafpay/orders/${orderId}/recovery`, { cache: "no-store" });
      if (recovery?.unresolved !== true || String(recovery?.attempt_public_id) !== unresolvedXafpayAttempt.id) return;
      const rail = String(recovery?.rail || unresolvedXafpayAttempt.rail || "mtn").toLowerCase();
      navigate("/processing", {
        state: {
          orderId,
          paymentMode: "xafpay",
          is_async: true,
          lines: [{ method: "xafpay", amount: Number(recovery.amount), provider: rail.includes("orange") ? "orange" : "mtn" }],
        },
      });''',
'''      const recovery = await loadXafpayRecovery(orderId);
      const state = xafpayResumeState(recovery, unresolvedXafpayAttempt.id);
      if (state) navigate("/processing", { state });''', 1)
detail = detail.replace(
'''      <div className="flex flex-wrap gap-2 pt-2">
        {unresolvedXafpayAttempt && (''',
'''      <div className="flex flex-wrap gap-2 pt-2">
        {xafpayStatusResult && <div className="w-full rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm font-semibold text-amber-900" role="status" aria-live="polite">{xafpayStatusResult}</div>}
        {unresolvedXafpayAttempt && (''', 1)
detail_panel.write_text(detail, encoding="utf-8")

payments_screen = target / "src" / "modules" / "payments" / "PaymentsScreen.tsx"
payments_screen_text = payments_screen.read_text(encoding="utf-8")
payments_screen_text = payments_screen_text.replace(
    'import { useState } from "react";',
    'import { useState } from "react";\nimport { useSearchParams } from "react-router-dom";', 1)
payments_screen_text = payments_screen_text.replace(
    'export default function PaymentsScreen() {',
    'export default function PaymentsScreen() {\n  const [searchParams] = useSearchParams();', 1)
payments_screen_text = payments_screen_text.replace(
    '  const [leftMode, setLeftMode] = useState<"activity" | "records">("activity");',
    '  const [leftMode, setLeftMode] = useState<"activity" | "records">(() =>\n    searchParams.get("tab") === "records" ? "records" : "activity"\n  );', 1)
payments_screen_text = payments_screen_text.replace(
    'error={activity.error}\n                />',
    'error={activity.error}\n                  onRefresh={refreshAll}\n                />', 1)
payments_screen_text = payments_screen_text.replace(
    '<PaymentDetailPanel payment={selected} />',
    '<PaymentDetailPanel payment={selected} onRefresh={refreshAll} />', 1)
payments_screen.write_text(payments_screen_text, encoding="utf-8")

activity_types = target / "src" / "modules" / "payments" / "hooks" / "usePaymentActivity.ts"
activity_types_text = activity_types.read_text(encoding="utf-8").replace(
    '  document_type?: string | null;\n};',
    '  document_type?: string | null;\n  recovery?: { attempt_public_id: string; order_id: number; sale_id: number; payment_record_id: string; rail?: string | null; orchestrator: string } | null;\n};', 1)
activity_types.write_text(activity_types_text, encoding="utf-8")

activity_ledger = target / "src" / "modules" / "payments" / "components" / "PaymentActivityLedger.tsx"
activity_text = activity_ledger.read_text(encoding="utf-8")
activity_text = activity_text.replace(
    'import { Fragment, useState } from "react";',
    'import { Fragment, useState } from "react";\nimport { useNavigate } from "react-router-dom";\nimport { checkXafpayCanonicalStatus, loadXafpayRecovery, xafpayResumeState } from "../xafpayRecovery";', 1)
activity_text = activity_text.replace(
    'function ActivityDetail({ item }: { item: PaymentActivityItem }) {\n  return (',
'''function ActivityDetail({ item, onRefresh }: { item: PaymentActivityItem; onRefresh?: () => Promise<void> | void }) {
  const navigate = useNavigate();
  const [action, setAction] = useState<null | "resume" | "status">(null);
  const [result, setResult] = useState<string | null>(null);
  const [lastChecked, setLastChecked] = useState<string | null>(null);
  const recovery = item.recovery;
  function visibleStatus(projection: any) {
    const state = String(projection?.attempt_state || "UNKNOWN").toUpperCase();
    if (projection?.financially_confirmed === true || state === "SUCCEEDED") return "Payment confirmed";
    if (state === "FAILED") return "Payment failed";
    if (state === "EXPIRED") return "Payment session / attempt expired";
    if (["CANCELLED", "CANCELED"].includes(state)) return "Payment cancelled";
    if (state === "UNKNOWN") return "Confirmation unresolved";
    if (state === "PROCESSING") return "Still processing — no payment confirmed yet";
    return "Awaiting confirmation";
  }
  async function checkStatus(event: React.MouseEvent) {
    event.stopPropagation();
    if (!recovery || action) return;
    setAction("status"); setResult(null);
    try {
      const projection = await checkXafpayCanonicalStatus(recovery.attempt_public_id);
      setResult(visibleStatus(projection));
      setLastChecked(new Date().toLocaleTimeString());
    } finally { setAction(null); }
  }
  async function resume(event: React.MouseEvent) {
    event.stopPropagation();
    if (!recovery || action) return;
    setAction("resume");
    try {
      const current = await loadXafpayRecovery(Number(recovery.order_id));
      const state = xafpayResumeState(current, recovery.attempt_public_id);
      if (state) navigate("/processing", { state });
    } finally { setAction(null); }
  }
  return (''', 1)
activity_text = activity_text.replace(
'''      {item.detail && (
        <div className="sm:col-span-2 lg:col-span-4">
          <Detail label="Detail" value={item.detail} />
        </div>
      )}
    </div>''',
'''      {item.detail && <div className="sm:col-span-2 lg:col-span-4"><Detail label="Detail" value={item.detail} /></div>}
      {recovery && (
        <div className="flex flex-wrap items-center gap-2 sm:col-span-2 lg:col-span-4">
          <button type="button" onClick={resume} disabled={action !== null} className="rounded-lg bg-emerald-700 px-3 py-2 text-xs font-bold text-white disabled:opacity-50">{action === "resume" ? "Reopening..." : "Resume XafPay"}</button>
          <button type="button" onClick={checkStatus} disabled={action !== null} className="rounded-lg border border-emerald-700 px-3 py-2 text-xs font-bold text-emerald-800 disabled:opacity-50">{action === "status" ? "Checking..." : "Check status"}</button>
          {result && <div role="status" aria-live="polite" className="w-full rounded-lg bg-amber-50 px-3 py-2 text-xs font-bold text-amber-900">{result}{lastChecked ? <span className="ml-2 font-semibold text-amber-700">Last checked: {lastChecked}</span> : null}</div>}
        </div>
      )}
    </div>''', 1)
activity_text = activity_text.replace('  error,\n}: {', '  error,\n  onRefresh,\n}: {', 1)
activity_text = activity_text.replace('  error: string | null;\n}) {', '  error: string | null;\n  onRefresh?: () => Promise<void> | void;\n}) {', 1)
activity_text = activity_text.replace('<ActivityDetail item={item} />', '<ActivityDetail item={item} onRefresh={onRefresh} />')
activity_ledger.write_text(activity_text, encoding="utf-8")

payment_screen = target / "src" / "modules" / "sales" / "payment" / "PaymentScreen.tsx"
pay_text = payment_screen.read_text(encoding="utf-8")
pay_text = pay_text.replace(
    'import { apiFetch } from "../../../lib/api";',
    'import { apiFetch } from "../../../lib/api";\nimport { checkXafpayCanonicalStatus, loadXafpayRecovery, xafpayOperatorResult, xafpayResumeState } from "../../payments/xafpayRecovery";', 1)
pay_text = pay_text.replace(
'''  const [xafpayRecovery, setXafpayRecovery] = useState<any>(null);
  const refreshXafpayRecovery = useCallback(async () => {
    if (!orderId) return setXafpayRecovery(null);
    const value = await apiFetch(`/payments/xafpay/orders/${orderId}/recovery`, { cache: "no-store" });
    setXafpayRecovery(value);
  }, [orderId]);''',
'''  const [xafpayRecovery, setXafpayRecovery] = useState<any>(null);
  const [xafpayChecking, setXafpayChecking] = useState(false);
  const [xafpayCheckResult, setXafpayCheckResult] = useState<string | null>(null);
  const refreshXafpayRecovery = useCallback(async () => {
    if (!orderId) return setXafpayRecovery(null);
    const value = await loadXafpayRecovery(Number(orderId));
    setXafpayRecovery(value);
  }, [orderId]);
  const checkXafpayRecovery = useCallback(async () => {
    if (!xafpayRecovery?.attempt_public_id || xafpayChecking) return;
    setXafpayChecking(true); setXafpayCheckResult(null);
    try {
      const projection = await checkXafpayCanonicalStatus(String(xafpayRecovery.attempt_public_id));
      setXafpayCheckResult(xafpayOperatorResult(projection));
      await refreshXafpayRecovery();
    } finally { setXafpayChecking(false); }
  }, [xafpayRecovery?.attempt_public_id, xafpayChecking, refreshXafpayRecovery]);''', 1)
pay_text = pay_text.replace(
'''          <div className="mt-3 flex gap-2">
            <button type="button" className="rounded-lg bg-emerald-700 px-3 py-2 text-white" onClick={() => navigate("/processing", { state: { orderId, paymentMode: "xafpay", is_async: true, lines: [{ method: "xafpay", amount: Number(xafpayRecovery.amount), provider: String(xafpayRecovery.rail || "mtn").toLowerCase().startsWith("orange") ? "orange" : "mtn" }] } })}>Resume XafPay</button>
            <button type="button" className="rounded-lg border px-3 py-2" onClick={() => refreshXafpayRecovery()}>Check status</button>
          </div>''',
'''          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button type="button" className="rounded-lg bg-emerald-700 px-3 py-2 text-white" onClick={() => { const state = xafpayResumeState(xafpayRecovery, String(xafpayRecovery.attempt_public_id)); if (state) navigate("/processing", { state }); }}>Resume XafPay</button>
            <button type="button" className="rounded-lg border px-3 py-2" disabled={xafpayChecking} onClick={checkXafpayRecovery}>{xafpayChecking ? "Checking..." : "Check status"}</button>
            {xafpayCheckResult && <span role="status" aria-live="polite" className="w-full text-sm font-semibold text-amber-900">{xafpayCheckResult}</span>}
          </div>''', 1)
payment_screen.write_text(pay_text, encoding="utf-8")

# One fail-closed cancellation-request operation is reused by every unresolved
# XafPay surface. It never maps an operator click to a canonical terminal state.
detail = detail_panel.read_text(encoding="utf-8")
detail = detail.replace(
    'xafpayOperatorResult, xafpayResumeState } from "../xafpayRecovery";',
    'xafpayOperatorResult, xafpayResumeState, requestXafpayCancellation } from "../xafpayRecovery";', 1)
detail = detail.replace(
    '"fallback" | "resume" | "status">(',
    '"fallback" | "resume" | "status" | "cancel">(', 1)
detail = detail.replace(
    '  const [xafpayStatusResult, setXafpayStatusResult] = useState<string | null>(null);',
    '  const [xafpayStatusResult, setXafpayStatusResult] = useState<string | null>(null);\n  const [xafpayCancelResult, setXafpayCancelResult] = useState<string | null>(null);', 1)
detail = detail.replace(
'''  async function resumeXafpay() {''',
'''  async function cancelXafpay() {
    if (!unresolvedXafpayAttempt || busyAction) return;
    setBusyAction("cancel"); setXafpayCancelResult(null);
    try {
      const response = await requestXafpayCancellation(unresolvedXafpayAttempt.id);
      setXafpayCancelResult(String(response?.message || "Cancellation is not yet confirmed."));
      await onRefresh?.();
    } finally { setBusyAction(null); }
  }

  async function resumeXafpay() {''', 1)
detail = detail.replace(
'''            <button className="rounded-xl border border-emerald-700 px-4 py-2 font-semibold text-emerald-800 disabled:opacity-50" onClick={checkXafpayStatus} disabled={busyAction !== null} type="button">
              {busyAction === "status" ? "Checking..." : "Check status"}
            </button>''',
'''            <button className="rounded-xl border border-emerald-700 px-4 py-2 font-semibold text-emerald-800 disabled:opacity-50" onClick={checkXafpayStatus} disabled={busyAction !== null} type="button">{busyAction === "status" ? "Checking..." : "Check status"}</button>
            <button className="rounded-xl border border-red-700 px-4 py-2 font-semibold text-red-800 disabled:opacity-50" onClick={cancelXafpay} disabled={busyAction !== null} type="button">{busyAction === "cancel" ? "Cancelling..." : "Cancel XafPay payment"}</button>
            {xafpayCancelResult && <div className="w-full rounded-xl bg-red-50 px-3 py-2 text-sm font-semibold text-red-900" role="status" aria-live="polite">{xafpayCancelResult}</div>}''', 1)
detail_panel.write_text(detail, encoding="utf-8")

activity_text = activity_ledger.read_text(encoding="utf-8")
activity_text = activity_text.replace(
    'loadXafpayRecovery, xafpayResumeState } from "../xafpayRecovery";',
    'loadXafpayRecovery, xafpayResumeState, requestXafpayCancellation } from "../xafpayRecovery";', 1)
activity_text = activity_text.replace(
    'useState<null | "resume" | "status">(null)',
    'useState<null | "resume" | "status" | "cancel">(null)', 1)
activity_text = activity_text.replace(
'''  async function resume(event: React.MouseEvent) {''',
'''  async function cancelPayment(event: React.MouseEvent) {
    event.stopPropagation();
    if (!recovery || action) return;
    setAction("cancel"); setResult(null);
    try {
      const response = await requestXafpayCancellation(recovery.attempt_public_id);
      setResult(String(response?.message || "Cancellation is not yet confirmed."));
      setLastChecked(new Date().toLocaleTimeString());
    } finally { setAction(null); }
  }
  async function resume(event: React.MouseEvent) {''', 1)
activity_text = activity_text.replace(
'''          <button type="button" onClick={checkStatus} disabled={action !== null} className="rounded-lg border border-emerald-700 px-3 py-2 text-xs font-bold text-emerald-800 disabled:opacity-50">{action === "status" ? "Checking..." : "Check status"}</button>''',
'''          <button type="button" onClick={checkStatus} disabled={action !== null} className="rounded-lg border border-emerald-700 px-3 py-2 text-xs font-bold text-emerald-800 disabled:opacity-50">{action === "status" ? "Checking..." : "Check status"}</button>
          <button type="button" onClick={cancelPayment} disabled={action !== null} className="rounded-lg border border-red-700 px-3 py-2 text-xs font-bold text-red-800 disabled:opacity-50">{action === "cancel" ? "Cancelling..." : "Cancel XafPay payment"}</button>''', 1)
activity_ledger.write_text(activity_text, encoding="utf-8")

pay_text = payment_screen.read_text(encoding="utf-8")
pay_text = pay_text.replace(
    'xafpayOperatorResult, xafpayResumeState } from "../../payments/xafpayRecovery";',
    'xafpayOperatorResult, xafpayResumeState, requestXafpayCancellation } from "../../payments/xafpayRecovery";', 1)
pay_text = pay_text.replace(
    '  const [xafpayCheckResult, setXafpayCheckResult] = useState<string | null>(null);',
    '  const [xafpayCheckResult, setXafpayCheckResult] = useState<string | null>(null);\n  const [xafpayCancelling, setXafpayCancelling] = useState(false);\n  const [xafpayCancelResult, setXafpayCancelResult] = useState<string | null>(null);', 1)
pay_text = pay_text.replace(
'''  const checkXafpayRecovery = useCallback(async () => {''',
'''  const cancelXafpayRecovery = useCallback(async () => {
    if (!xafpayRecovery?.attempt_public_id || xafpayCancelling) return;
    setXafpayCancelling(true); setXafpayCancelResult(null);
    try {
      const response = await requestXafpayCancellation(String(xafpayRecovery.attempt_public_id));
      setXafpayCancelResult(String(response?.message || "Cancellation is not yet confirmed."));
      await refreshXafpayRecovery();
    } finally { setXafpayCancelling(false); }
  }, [xafpayRecovery?.attempt_public_id, xafpayCancelling, refreshXafpayRecovery]);
  const checkXafpayRecovery = useCallback(async () => {''', 1)
pay_text = pay_text.replace(
'''            <button type="button" className="rounded-lg border px-3 py-2" disabled={xafpayChecking} onClick={checkXafpayRecovery}>{xafpayChecking ? "Checking..." : "Check status"}</button>
            {xafpayCheckResult &&''',
'''            <button type="button" className="rounded-lg border px-3 py-2" disabled={xafpayChecking} onClick={checkXafpayRecovery}>{xafpayChecking ? "Checking..." : "Check status"}</button>
            <button type="button" className="rounded-lg border border-red-700 px-3 py-2 text-red-800" disabled={xafpayCancelling} onClick={cancelXafpayRecovery}>{xafpayCancelling ? "Cancelling..." : "Cancel XafPay payment"}</button>
            {xafpayCancelResult && <span role="status" aria-live="polite" className="w-full text-sm font-semibold text-red-900">{xafpayCancelResult}</span>}
            {xafpayCheckResult &&''', 1)
payment_screen.write_text(pay_text, encoding="utf-8")

processing_screen = target / "src" / "modules" / "sales" / "ProcessingScreen.tsx"
processing_text = processing_screen.read_text(encoding="utf-8")
processing_text = processing_text.replace(
    'import { apiFetch } from "../../lib/api";',
    'import { apiFetch } from "../../lib/api";\nimport { requestXafpayCancellation } from "../payments/xafpayRecovery";', 1)
processing_text = processing_text.replace(
    '  const [xafpayInitiationIssue, setXafpayInitiationIssue] = useState<any>(null);',
    '  const [xafpayInitiationIssue, setXafpayInitiationIssue] = useState<any>(null);\n  const statusRefreshRef = useRef<Promise<any> | null>(null);\n  const [xafpayCancelling, setXafpayCancelling] = useState(false);\n  const [xafpayCancelResult, setXafpayCancelResult] = useState<string | null>(null);\n  const [xafpayChecking, setXafpayChecking] = useState(false);', 1)
processing_text = processing_text.replace(
'''  function leaveConfirmationPending() {''',
'''  async function cancelXafpayPayment() {
    if (!checkoutAttemptId || xafpayCancelling) return;
    setXafpayCancelling(true); setXafpayCancelResult(null);
    try {
      const response = await requestXafpayCancellation(checkoutAttemptId);
      setXafpayCancelResult(String(response?.message || "Cancellation is not yet confirmed."));
      await refreshCheckoutProjection();
    } finally { setXafpayCancelling(false); }
  }

  function leaveConfirmationPending() {''', 1)
processing_text = processing_text.replace(
'''          <iframe title="XafPay secure checkout" src={checkoutUrl} className="min-h-0 flex-1 border-0" allow="payment" referrerPolicy="no-referrer" />''',
'''          <iframe title="XafPay secure checkout" src={checkoutUrl} className="min-h-0 flex-1 border-0" allow="payment" referrerPolicy="no-referrer" />
          {!preSubmission && !succeeded && !failed && <div className="border-t p-3"><button type="button" className="rounded-lg border border-red-700 px-3 py-2 text-sm font-semibold text-red-800" disabled={xafpayCancelling} onClick={cancelXafpayPayment}>{xafpayCancelling ? "Cancelling..." : "Cancel XafPay payment"}</button>{xafpayCancelResult && <p role="status" aria-live="polite" className="mt-2 rounded-lg bg-red-50 p-2 text-sm font-semibold text-red-900">{xafpayCancelResult}</p>}</div>}''', 1)
processing_screen.write_text(processing_text, encoding="utf-8")

# Final parity assertions run after the later R2 overlays have added the base
# pending-attempt controls to Payment Records and PaymentScreen.

payment_types = target / "src" / "modules" / "payments" / "types.ts"
types_text = payment_types.read_text(encoding="utf-8").replace(
    'export type PaymentStatus = "PENDING" | "COMPLETED" | "FAILED";',
    'export type PaymentStatus = "PENDING" | "COMPLETED" | "FAILED" | "PARTIAL" | "RECEIVABLE" | "PAYMENT_REQUIRED";',
    1,
)
types_text = types_text.replace(
'''  amount: number;
  method: string;''',
'''  amount: number;
  total_paid?: number;
  balance_due?: number;
  approved_ar?: number;
  active_pending_attempts?: number;
  method: string;''', 1)
payment_types.write_text(types_text, encoding="utf-8")

payment_normalizers = target / "src" / "modules" / "payments" / "utils" / "paymentNormalizers.ts"
normalizer_text = payment_normalizers.read_text(encoding="utf-8")
normalizer_text = normalizer_text.replace(
'''  if (["FAILED", "ERROR", "DECLINED", "CANCELLED"].includes(s)) {
    return "FAILED";
  }

  return "PENDING";''',
'''  if (["FAILED", "ERROR", "DECLINED", "CANCELLED"].includes(s)) {
    return "FAILED";
  }
  if (s === "PARTIAL") return "PARTIAL";
  if (s === "RECEIVABLE") return "RECEIVABLE";
  if (s === "PAYMENT_REQUIRED") return "PAYMENT_REQUIRED";

  return "PENDING";''', 1)
normalizer_text = normalizer_text.replace(
'''    amount: Number(p?.amount ?? p?.total_paid ?? 0),

    method:''',
'''    amount: Number(p?.amount ?? p?.total_paid ?? 0),
    total_paid: Number(p?.total_paid ?? p?.meta?.total_paid ?? 0),
    balance_due: Number(p?.balance_due ?? p?.meta?.balance_due ?? 0),
    approved_ar: Number(p?.approved_ar ?? 0),
    active_pending_attempts: Number(p?.active_pending_attempts ?? 0),

    method:''', 1)
payment_normalizers.write_text(normalizer_text, encoding="utf-8")

status_pill = target / "src" / "modules" / "payments" / "components" / "PaymentStatusPill.tsx"
pill_text = status_pill.read_text(encoding="utf-8")
pill_text = pill_text.replace(
'''  if (status === "PENDING") {
    return (
      <span className={`${base} bg-amber-50 text-amber-700 ring-amber-200`}>
        Pending
      </span>
    );
  }

  return (''',
'''  if (status === "PENDING") {
    return <span className={`${base} bg-amber-50 text-amber-700 ring-amber-200`}>Pending</span>;
  }
  if (status === "PARTIAL") {
    return <span className={`${base} bg-amber-50 text-amber-800 ring-amber-300`}>Partial / payment required</span>;
  }
  if (status === "RECEIVABLE") {
    return <span className={`${base} bg-sky-50 text-sky-700 ring-sky-200`}>Receivable</span>;
  }
  if (status === "PAYMENT_REQUIRED") {
    return <span className={`${base} bg-orange-50 text-orange-700 ring-orange-200`}>Payment required</span>;
  }

  return (''', 1)
status_pill.write_text(pill_text, encoding="utf-8")

detail = detail_panel.read_text(encoding="utf-8")
detail = detail.replace(
'''        {payment.status === "FAILED" && (
          <span className="rounded-full bg-rose-50 px-3 py-1 text-xs font-bold text-rose-700 ring-1 ring-rose-200">
            Failed
          </span>
        )}''',
'''        {payment.status === "FAILED" && <span className="rounded-full bg-rose-50 px-3 py-1 text-xs font-bold text-rose-700 ring-1 ring-rose-200">Failed</span>}
        {payment.status === "PARTIAL" && <span className="rounded-full bg-amber-50 px-3 py-1 text-xs font-bold text-amber-800 ring-1 ring-amber-300">Partial / payment required</span>}
        {payment.status === "RECEIVABLE" && <span className="rounded-full bg-sky-50 px-3 py-1 text-xs font-bold text-sky-700 ring-1 ring-sky-200">Receivable</span>}
        {payment.status === "PAYMENT_REQUIRED" && <span className="rounded-full bg-orange-50 px-3 py-1 text-xs font-bold text-orange-700 ring-1 ring-orange-200">Payment required</span>}''', 1)
detail_panel.write_text(detail, encoding="utf-8")

# R2: Split retains local Cash/MTN/Orange authority and adds exactly one
# provider-neutral XafPay allocation. Remaining is a calculated residual.
split_panel = target / "src" / "modules" / "sales" / "payment" / "components" / "SplitPanel.tsx"
split_text = split_panel.read_text(encoding="utf-8")
split_text = split_text.replace(
'''  splitOrange,
  setSplitOrange,
  splitUnpaid,''',
'''  splitOrange,
  setSplitOrange,
  splitXafPay,
  setSplitXafPay,
  splitPaidTotal,
  splitUnpaid,''', 1)
split_text = split_text.replace(
'''        <div className="rounded-xl bg-white border px-4 py-3 font-semibold">
          Unpaid: {fmtXaf(splitUnpaid)}
        </div>''',
'''        <input
          type="number"
          placeholder="XafPay"
          aria-label="XafPay allocation"
          value={splitXafPay || ""}
          onChange={(e) => setSplitXafPay(parse(e.target.value))}
          className="rounded-xl px-4 py-3 border"
        />''', 1)
split_text = split_text.replace(
'''      </div>
    </div>
  );''',
'''      </div>
      <div className="grid grid-cols-2 gap-3 rounded-xl border bg-white px-4 py-3 text-sm" aria-live="polite">
        <div><span className="text-neutral-500">Allocated:</span> <strong>{fmtXaf(splitPaidTotal)}</strong></div>
        <div><span className="text-neutral-500">Remaining:</span> <strong>{fmtXaf(splitUnpaid)}</strong></div>
      </div>
    </div>
  );''', 1)
if 'aria-label="XafPay allocation"' not in split_text or 'Remaining:' not in split_text:
    raise RuntimeError("XV15_R2_SPLIT_PANEL_MARKER_MISSING")
split_panel.write_text(split_text, encoding="utf-8")

payment_screen = target / "src" / "modules" / "sales" / "payment" / "PaymentScreen.tsx"
pay_text = payment_screen.read_text(encoding="utf-8")
pay_text = pay_text.replace(
    'import { useMemo, useState, useEffect } from "react";',
    'import { useMemo, useState, useEffect, useCallback } from "react";', 1)
pay_text = pay_text.replace(
    '  const [mode, setMode] = useState<PayMode>("cash");',
    '''  const [mode, setMode] = useState<PayMode>("cash");
  const [xafpayRecovery, setXafpayRecovery] = useState<any>(null);
  const refreshXafpayRecovery = useCallback(async () => {
    if (!orderId) return setXafpayRecovery(null);
    const value = await apiFetch(`/payments/xafpay/orders/${orderId}/recovery`, { cache: "no-store" });
    setXafpayRecovery(value);
  }, [orderId]);
  useEffect(() => { refreshXafpayRecovery().catch(() => setXafpayRecovery(null)); }, [refreshXafpayRecovery]);''', 1)
pay_text = pay_text.replace(
    '''  const disabledReason = !canReceivePayment''',
    '''  const disabledReason = xafpayRecovery?.unresolved
    ? `XafPay ${String(xafpayRecovery.attempt_state || "pending").toLowerCase()} for ${Number(xafpayRecovery.amount || 0).toLocaleString()} XAF. Resume or check status; another tender is blocked for this sale.`
    : !canReceivePayment''', 1)
pay_text = pay_text.replace(
    '''  return (
    <>
      <div className="grid gap-6 lg:grid-cols-[1.35fr_0.65fr]">''',
    '''  return (
    <>
      {paymentRecovery && !xafpayRecovery?.unresolved && (
        <div className="mb-4 rounded-2xl border border-neutral-300 bg-white p-4" role="status">
          <strong>Previous XafPay attempt {String(paymentRecovery.attempt_state || "failed").toLowerCase()}</strong>
          <div className="mt-2 grid gap-1 text-sm">
            <span>Original total: {Number(paymentRecovery.commercial_total || 0).toLocaleString()} XAF</span>
            <span>Already settled: {Number(paymentRecovery.total_paid || 0).toLocaleString()} XAF</span>
            <span>Still to collect: {Number(paymentRecovery.collectible_now || paymentRecovery.balance_due || 0).toLocaleString()} XAF</span>
          </div>
        </div>
      )}
      {xafpayRecovery?.unresolved && (
        <div className="mb-4 rounded-2xl border border-amber-300 bg-amber-50 p-4" role="status">
          <strong>XafPay confirmation {String(xafpayRecovery.attempt_state || "pending").toLowerCase()}</strong>
          <p>{Number(xafpayRecovery.amount || 0).toLocaleString()} XAF may still settle. Other orders remain available.</p>
          <div className="mt-3 flex gap-2">
            <button type="button" className="rounded-lg bg-emerald-700 px-3 py-2 text-white" onClick={() => navigate("/processing", { state: { orderId, paymentMode: "xafpay", is_async: true, lines: [{ method: "xafpay", amount: Number(xafpayRecovery.amount), provider: String(xafpayRecovery.rail || "mtn").toLowerCase().startsWith("orange") ? "orange" : "mtn" }] } })}>Resume XafPay</button>
            <button type="button" className="rounded-lg border px-3 py-2" onClick={() => refreshXafpayRecovery()}>Check status</button>
          </div>
        </div>
      )}
      <div className="grid gap-6 lg:grid-cols-[1.35fr_0.65fr]">''', 1)
pay_text = pay_text.replace(
    'canConfirm={canReceivePayment && canConfirm && items.length > 0}',
    'canConfirm={canReceivePayment && canConfirm && !xafpayRecovery?.unresolved && items.length > 0}', 1)
pay_text = pay_text.replace(
    '  const { subtotal, totalDue } = usePaymentTotals(',
    '  const { subtotal, totalDue: calculatedTotalDue } = usePaymentTotals(', 1)
pay_text = pay_text.replace(
    '''    complimentary
  );

  /* ================= LOAD ITEMS ================= */''',
    '''    complimentary
  );
  const paymentRecovery = location.state?.paymentRecovery;
  const recoveryCollectible = Number(paymentRecovery?.collectible_now);
  const totalDue = Number.isFinite(recoveryCollectible) && recoveryCollectible >= 0
    ? recoveryCollectible
    : calculatedTotalDue;

  /* ================= LOAD ITEMS ================= */''', 1)
pay_text = pay_text.replace(
'  const [splitOrange, setSplitOrange] = useState(0);',
'  const [splitOrange, setSplitOrange] = useState(0);\n  const [splitXafPay, setSplitXafPay] = useState(0);', 1)
pay_text = pay_text.replace(
'      setSplitOrange(0);',
'      setSplitOrange(0);\n      setSplitXafPay(0);', 1)
pay_text = pay_text.replace(
'  const safeSplitOrange = Number(splitOrange || 0);',
'  const safeSplitOrange = Number(splitOrange || 0);\n  const safeSplitXafPay = Number(splitXafPay || 0);', 1)
pay_text = pay_text.replace(
'  const splitTotalPaid = safeSplitCash + safeSplitMtn + safeSplitOrange;',
'  const splitTotalPaid = safeSplitCash + safeSplitMtn + safeSplitOrange + safeSplitXafPay;', 1)
pay_text = pay_text.replace(
'''    splitOrange: safeSplitOrange,

    splitPaidTotal:''',
'''    splitOrange: safeSplitOrange,
    splitXafPay: safeSplitXafPay,

    splitPaidTotal:''', 1)
pay_text = pay_text.replace(
'''              splitOrange={splitOrange}
              setSplitOrange={setSplitOrange}
              splitUnpaid={splitUnpaid}''',
'''              splitOrange={splitOrange}
              setSplitOrange={setSplitOrange}
              splitXafPay={splitXafPay}
              setSplitXafPay={setSplitXafPay}
              splitPaidTotal={splitTotalPaid}
              splitUnpaid={splitUnpaid}''', 1)
if "safeSplitXafPay" not in pay_text or "setSplitXafPay" not in pay_text:
    raise RuntimeError("XV15_R2_PAYMENT_SCREEN_SPLIT_MARKER_MISSING")
payment_screen.write_text(pay_text, encoding="utf-8")

hook_text = confirm_hook.read_text(encoding="utf-8")
hook_text = hook_text.replace(
'  splitOrange: number;\n  splitPaidTotal:',
'  splitOrange: number;\n  splitXafPay: number;\n  splitPaidTotal:', 1)
hook_text = hook_text.replace(
'    splitOrange,\n    splitPaidTotal,',
'    splitOrange,\n    splitXafPay,\n    splitPaidTotal,', 1)
hook_text = hook_text.replace(
'num(splitCashReceived) + num(splitMtn) + num(splitOrange);',
'num(splitCashReceived) + num(splitMtn) + num(splitOrange) + num(splitXafPay);', 1)
hook_text = hook_text.replace(
'        const orange = num(splitOrange);',
'        const orange = num(splitOrange);\n        const xafpay = num(splitXafPay);', 1)
hook_text = hook_text.replace(
'''        if (cash > 0) {
          lines.push({
            method: "cash",
            amount: cash,
            meta: { tendered: cash },
          });
        }
      }

      if (unpaidAmount > 0) {''',
'''        if (cash > 0) {
          lines.push({ method: "cash", amount: cash, meta: { tendered: cash } });
        }
        if (xafpay > 0) {
          lines.push({ method: "xafpay", amount: xafpay, meta: { settlement_authority: "gateway_canonical" } });
        }
      }

      if (unpaidAmount > 0) {''', 1)
hook_text = hook_text.replace(
'      const orange = num(splitOrange);',
'      const orange = num(splitOrange);\n      const xafpay = num(splitXafPay);', 1)
hook_text = hook_text.replace(
'''      if (cash > 0) {
        lines.push({
          method: "cash",
          amount: cash,
          meta: { tendered: cash },
        });
      }

      if (num(finalChangeOwed) > 0) {''',
'''      if (cash > 0) {
        lines.push({ method: "cash", amount: cash, meta: { tendered: cash } });
      }
      if (xafpay > 0) {
        lines.push({ method: "xafpay", amount: xafpay, meta: { settlement_authority: "gateway_canonical" } });
      }

      if (num(finalChangeOwed) > 0) {''', 1)
hook_text = hook_text.replace(
'num(splitCashReceived + splitMtn + splitOrange);',
'num(splitCashReceived + splitMtn + splitOrange + splitXafPay);', 1)
hook_text = hook_text.replace(
'    const isAsync = mode === "xafpay";',
'    const isAsync = mode === "xafpay" || lines.some((line) => line.method === "xafpay");', 1)
hook_text = hook_text.replace(
'    splitOrange,\n    finalChangeOwed,',
'    splitOrange,\n    splitXafPay,\n    finalChangeOwed,', 1)
hook_text = hook_text.replace(
'    splitOrange,\n    effectiveChange,',
'    splitOrange,\n    splitXafPay,\n    effectiveChange,', 1)
hook_text = hook_text.replace(
'''        const orange = num(splitOrange);
      const xafpay = num(splitXafPay);
        const xafpay = num(splitXafPay);''',
'''        const orange = num(splitOrange);
        const xafpay = num(splitXafPay);''', 1)
normal_split = hook_text.split("/* ================= SIMPLE ================= */", 1)
if len(normal_split) == 2 and "const xafpay = num(splitXafPay);" not in normal_split[1]:
    normal_split[1] = normal_split[1].replace(
        '      const orange = num(splitOrange);',
        '      const orange = num(splitOrange);\n      const xafpay = num(splitXafPay);', 1)
    hook_text = normal_split[0] + "/* ================= SIMPLE ================= */" + normal_split[1]
if 'settlement_authority: "gateway_canonical"' not in hook_text or 'line.method === "xafpay"' not in hook_text:
    raise RuntimeError("XV15_R2_SPLIT_BUILD_LINES_MARKER_MISSING")
confirm_hook.write_text(hook_text, encoding="utf-8")

# R2 freeze-hold: result query parameters are navigation hints only. For an
# order-backed sale the page must fetch XBOS financial truth before wording a
# result, and Sales Archive must consume the backend payment projection.
result_screen = target / "src" / "modules" / "sales" / "ResultScreen.tsx"
result_text = result_screen.read_text(encoding="utf-8")
if "const [financial, setFinancial]" not in result_text:
    result_text = result_text.replace(
        'import { useRef, useEffect, useMemo } from "react";',
        'import { useRef, useEffect, useMemo, useState } from "react";', 1)
    result_text = result_text.replace(
        'import { useCartStore } from "../../lib/store/cart";',
        'import { useCartStore } from "../../lib/store/cart";\nimport { apiFetch } from "../../lib/api";', 1)
    result_text = result_text.replace(
        '  const receiptRef = useRef<ReceiptPanelHandle>(null);',
        '''  const receiptRef = useRef<ReceiptPanelHandle>(null);
  const [financial, setFinancial] = useState<any>(null);
  const [financialLoading, setFinancialLoading] = useState(false);

  useEffect(() => {
    if (!hasSaleId) return;
    let active = true;
    setFinancialLoading(true);
    apiFetch(`/sales/${saleId}`, { cache: "no-store" })
      .then((value) => { if (active) setFinancial(value); })
      .catch(() => { if (active) setFinancial(null); })
      .finally(() => { if (active) setFinancialLoading(false); });
    return () => { active = false; };
  }, [hasSaleId, saleId]);''', 1)
    result_text = result_text.replace(
        '  if (status === "failure") {',
        '  if (status === "failure" && !hasSaleId) {', 1)
    result_text = result_text.replace(
        '  const primaryActionLabel = isInvoice ? "Print invoice" : "Print receipt";',
        '''  if (hasSaleId && financialLoading) {
    return <div className="flex h-[calc(100vh-7.5rem)] items-center justify-center">Checking current payment state...</div>;
  }
  const summary = financial?.payment_summary || {};
  const due = n(summary.balance_due ?? financial?.unpaid_amount);
  const paid = n(summary.total_paid ?? financial?.paid_amount);
  const approvedAr = n(summary.approved_ar);
  const paymentState = String(financial?.payment_state || "").toUpperCase();
  const resultTitle = !hasSaleId
    ? (isInvoice ? "Invoice generated" : "Payment recorded")
    : paymentState === "PAID" && due === 0
    ? "Payment successful"
    : paymentState === "PAYMENT_PENDING"
    ? "Payment confirmation pending"
    : paymentState === "RECEIVABLE"
    ? "Payment recorded"
    : paid > 0
    ? "Partial payment recorded"
    : "Sale recorded — payment still due";
  const resultDetail = paymentState === "RECEIVABLE"
    ? `${approvedAr.toLocaleString()} XAF remains on A/R`
    : due > 0
    ? `${paid.toLocaleString()} XAF paid · ${due.toLocaleString()} XAF still due`
    : "Canonical XBOS balance is fully settled.";

  const primaryActionLabel = isInvoice ? "Print invoice" : "Print receipt";''', 1)
    result_text = result_text.replace(
        '''{isInvoice ? "Invoice generated" : "Payment successful"}''',
        '''{resultTitle}''', 1)
    result_text = result_text.replace(
        '''{isInvoice
            ? "Bill created â€” payment pending"
            : "Receipt generated successfully"}''',
        '''{resultDetail}''', 1)
if "Checking current payment state" not in result_text or "payment_summary" not in result_text:
    raise RuntimeError("XV15_R2_RESULT_FINANCIAL_TRUTH_MARKER_MISSING")
result_screen.write_text(result_text, encoding="utf-8")

archive = target / "src" / "modules" / "sales" / "CompletedOrdersScreen.tsx"
archive_text = archive.read_text(encoding="utf-8")
archive_text = archive_text.replace(
    'payment_state: "PAID" | "PARTIAL" | "UNPAID" | "CANCELLED";',
    'payment_state: "PAID" | "PARTIAL" | "UNPAID" | "RECEIVABLE" | "PAYMENT_PENDING" | "CANCELLED";', 1)
archive_text = archive_text.replace(
    '''      const paymentState: Order["payment_state"] =
        cancelled ? "CANCELLED" : unpaid <= 0 ? "PAID" : paid > 0 ? "PARTIAL" : "UNPAID";''',
    '''      const projected = String(sale.payment_state || "").toUpperCase();
      const paymentState: Order["payment_state"] = cancelled
        ? "CANCELLED"
        : (["PAID", "PARTIAL", "UNPAID", "RECEIVABLE", "PAYMENT_PENDING"].includes(projected)
            ? projected
            : unpaid <= 0 ? "PAID" : paid > 0 ? "PARTIAL" : "UNPAID") as Order["payment_state"];''', 1)
if "PAYMENT_PENDING" not in archive_text or "sale.payment_state" not in archive_text:
    raise RuntimeError("XV15_R2_ARCHIVE_FINANCIAL_TRUTH_MARKER_MISSING")
archive.write_text(archive_text, encoding="utf-8")

receipt = target / "src" / "components" / "receipt" / "Receipt.tsx"
receipt_text = receipt.read_text(encoding="utf-8")
receipt_text = receipt_text.replace(
'''<Line label={methodLabel(p.method, p)} value={n(p.amount)} />''',
'''<Line
                  label={methodLabel(p.method, p)}
                  value={String(p.method || "").toLowerCase() === "cash" ? n(p.cash_given ?? p.amount) : n(p.amount)}
                />''', 1)
receipt_text = receipt_text.replace(
'''const methodLabel = (m?: string) => {
  const v = String(m ?? "").toLowerCase();''',
'''const methodLabel = (m?: string, payment?: any) => {
  const v = String(m ?? "").toLowerCase();
  if (payment?.orchestrator === "xafpay") {
    const rail = String(payment?.rail || "").replaceAll("_", " ").toUpperCase();
    return rail ? `XAFPAY / ${rail === "MTN MOMO" ? "MTN MoMo" : rail}` : "XAFPAY";
  }''', 1)
receipt_text = receipt_text.replace(
'label={`Tendered (${methodLabel(payments[0].method)})`}',
'label={`Tendered (${methodLabel(payments[0].method, payments[0])})`}', 1)
receipt_text = receipt_text.replace(
'<Line label={methodLabel(p.method)} value={n(p.amount)} />',
'<Line label={methodLabel(p.method, p)} value={n(p.amount)} />', 1)
if 'XAFPAY / ${rail === "MTN MOMO" ? "MTN MoMo" : rail}' not in receipt_text:
    raise RuntimeError("XV15_RECEIPT_XAFPAY_TENDER_MARKER_MISSING")
receipt.write_text(receipt_text, encoding="utf-8")

reconciliation = target / "src" / "modules" / "accounting" / "screens" / "ReconciliationScreen.tsx"
recon_text = reconciliation.read_text(encoding="utf-8")
recon_text = recon_text.replace(
'''function channelSubtitle(channel: string) {
  if (channel === "bank") return "Combined balance until named bank accounts are enabled";
  return "";
}''',
'''function channelSubtitle(row: any) {
  if (row.channel === "bank") return "Combined balance until named bank accounts are enabled";
  if (row.channel === "xafpay") {
    const rails = Array.isArray(row.rails)
      ? row.rails.map((rail: string) => rail.replaceAll("_", " ").toUpperCase()).join(" / ")
      : "";
    return rails ? `Mobile Money · ${rails} via XafPay` : "Confirmed external settlements via XafPay";
  }
  return "";
}''', 1)
recon_text = recon_text.replace(
'const subtitle = channelSubtitle(row.channel);',
'const subtitle = channelSubtitle(row);', 1)
if 'Mobile Money · ${rails} via XafPay' not in recon_text:
    raise RuntimeError("XV15_RECON_XAFPAY_LABEL_MARKER_MISSING")
reconciliation.write_text(recon_text, encoding="utf-8")

vite_config = target / "vite.r6-3-uat.config.ts"
vite_text = vite_config.read_text(encoding="utf-8")
proxy_marker = '''      "/kernel": {
        target: "http://127.0.0.1:8002",
        changeOrigin: true,
      },'''
proxy_replacement = proxy_marker + '''
      "/public": {
        target: "http://127.0.0.1:3000",
        changeOrigin: true,
      },
      "/l": {
        target: "http://127.0.0.1:3000",
        changeOrigin: true,
      },'''
if proxy_marker not in vite_text and proxy_replacement not in vite_text:
    raise RuntimeError("XV15_FRONTEND_PROXY_MARKER_MISSING")
if proxy_marker in vite_text and proxy_replacement not in vite_text:
    vite_config.write_text(vite_text.replace(proxy_marker, proxy_replacement, 1), encoding="utf-8")
# R2 pending recovery is server-correlated to the exact obligation and attempt.
# No Checkout bearer token is stored in browser-global storage.
recovery_helper = target / "src" / "modules" / "payments" / "xafpayRecovery.ts"
recovery_helper.write_text('''import { apiFetch } from "../../lib/api";

export async function loadXafpayRecovery(orderId: number) {
  return await apiFetch(`/payments/xafpay/orders/${orderId}/recovery`, { cache: "no-store" });
}
export async function checkXafpayCanonicalStatus(attemptId: string) {
  return await apiFetch(`/payments/xafpay/attempts/${attemptId}/status`, { cache: "no-store" });
}
export async function requestXafpayCancellation(attemptId: string) {
  return await apiFetch(`/payments/xafpay/attempts/${attemptId}/cancel-request`, { method: "POST" });
}
export function xafpayOperatorResult(projection: any) {
  const state = String(projection?.attempt_state || "UNKNOWN").toUpperCase();
  if (projection?.financially_confirmed === true || state === "SUCCEEDED") return "Paid / confirmed";
  if (state === "FAILED") return "Failed — payment was not completed";
  if (["EXPIRED", "CANCELLED", "CANCELED"].includes(state)) return "Expired / cancelled — payment was not completed";
  if (state === "UNKNOWN") return "Unknown — confirmation unresolved";
  if (state === "PROCESSING") return "Processing — provider confirmation pending";
  return "Still awaiting confirmation";
}
export function xafpayResumeState(recovery: any, expectedAttemptId: string) {
  if (recovery?.unresolved !== true || String(recovery?.attempt_public_id) !== expectedAttemptId) return null;
  const rail = String(recovery?.rail || "mtn").toLowerCase();
  return { orderId: Number(recovery.order_id), paymentMode: "xafpay", is_async: true,
    lines: [{ method: "xafpay", amount: Number(recovery.amount), provider: rail.includes("orange") ? "orange" : "mtn" }] };
}
''', encoding="utf-8")

detail = detail_panel.read_text(encoding="utf-8")
detail = detail.replace(
'''  const [busyAction, setBusyAction] = useState<null | "balance" | "fallback">(
    null
  );''',
'''  const [busyAction, setBusyAction] = useState<null | "balance" | "fallback" | "resume" | "status">(
    null
  );''', 1)
detail = detail.replace(
'''  const canSettleAnotherWay =
    payment.status === "FAILED" ||
    (payment.status === "PENDING" && balanceDue > 0);''',
'''  const canSettleAnotherWay =
    payment.status === "FAILED" ||
    (payment.status === "PENDING" && balanceDue > 0);
  const unresolvedXafpayAttempt = [...attempts].reverse().find(
    (attempt) => attempt.orchestrator === "xafpay" &&
      ["PENDING", "PROCESSING", "UNKNOWN"].includes(attempt.status)
  );

  async function checkXafpayStatus() {
    if (!unresolvedXafpayAttempt || busyAction) return;
    setBusyAction("status");
    try {
      const projection = await apiFetch(`/payments/xafpay/attempts/${unresolvedXafpayAttempt.id}/status`, { cache: "no-store" });
      setAttempts((current) => current.map((attempt) => attempt.id === unresolvedXafpayAttempt.id
        ? { ...attempt, status: String(projection?.attempt_state || attempt.status).toUpperCase() }
        : attempt));
      setCanonicalTotalPaid(Number(projection?.total_paid || 0));
      setCanonicalBalanceDue(Number(projection?.balance_due || 0));
    } finally {
      setBusyAction(null);
    }
  }

  async function resumeXafpay() {
    if (!unresolvedXafpayAttempt || busyAction) return;
    setBusyAction("resume");
    try {
      const orderId = Number(unresolvedXafpayAttempt.meta?.order_id || meta?.order_id || 0);
      if (orderId <= 0) return;
      const recovery = await apiFetch(`/payments/xafpay/orders/${orderId}/recovery`, { cache: "no-store" });
      if (recovery?.unresolved !== true || String(recovery?.attempt_public_id) !== unresolvedXafpayAttempt.id) return;
      const rail = String(recovery?.rail || unresolvedXafpayAttempt.rail || "mtn").toLowerCase();
      navigate("/processing", {
        state: {
          orderId,
          paymentMode: "xafpay",
          is_async: true,
          lines: [{ method: "xafpay", amount: Number(recovery.amount), provider: rail.includes("orange") ? "orange" : "mtn" }],
        },
      });
    } finally {
      setBusyAction(null);
    }
  }''', 1)
detail = detail.replace(
'''      <div className="flex flex-wrap gap-2 pt-2">
        {canCompleteBalance && (''',
'''      <div className="flex flex-wrap gap-2 pt-2">
        {unresolvedXafpayAttempt && (
          <>
            <button className="rounded-xl bg-emerald-700 px-4 py-2 font-semibold text-white disabled:bg-emerald-300" onClick={resumeXafpay} disabled={busyAction !== null} type="button">
              {busyAction === "resume" ? "Reopening..." : "Resume XafPay"}
            </button>
            <button className="rounded-xl border border-emerald-700 px-4 py-2 font-semibold text-emerald-800 disabled:opacity-50" onClick={checkXafpayStatus} disabled={busyAction !== null} type="button">
              {busyAction === "status" ? "Checking..." : "Check status"}
            </button>
          </>
        )}
        {canCompleteBalance && (''', 1)
if "Resume XafPay" not in detail or "checkXafpayStatus" not in detail:
    raise RuntimeError("XV15_PENDING_PAYMENT_RECORD_RECOVERY_MISSING")
detail_panel.write_text(detail, encoding="utf-8")

# Apply shared status/result behavior after the base recovery controls exist.
detail = detail_panel.read_text(encoding="utf-8")
if 'from "../xafpayRecovery"' not in detail:
    detail = detail.replace(
        'import { apiFetch } from "../../../lib/api";',
        'import { apiFetch } from "../../../lib/api";\nimport { checkXafpayCanonicalStatus, loadXafpayRecovery, xafpayOperatorResult, xafpayResumeState } from "../xafpayRecovery";', 1)
if "onRefresh?: () => Promise<void> | void" not in detail:
    detail = detail.replace(
'''export default function PaymentDetailPanel({
  payment,
}: {
  payment: Payment | null;
}) {''',
'''export default function PaymentDetailPanel({
  payment,
  onRefresh,
}: {
  payment: Payment | null;
  onRefresh?: () => Promise<void> | void;
}) {''', 1)
if "const [xafpayStatusResult" not in detail:
    detail = detail.replace(
        '  const [loadingCanonical, setLoadingCanonical] = useState(false);',
        '  const [loadingCanonical, setLoadingCanonical] = useState(false);\n  const [xafpayStatusResult, setXafpayStatusResult] = useState<string | null>(null);', 1)
detail = detail.replace(
    '      const projection = await apiFetch(`/payments/xafpay/attempts/${unresolvedXafpayAttempt.id}/status`, { cache: "no-store" });',
    '      setXafpayStatusResult(null);\n      const projection = await checkXafpayCanonicalStatus(unresolvedXafpayAttempt.id);', 1)
detail = detail.replace(
'''      setCanonicalBalanceDue(Number(projection?.balance_due || 0));
    } finally {''',
'''      setCanonicalBalanceDue(Number(projection?.balance_due || 0));
      setXafpayStatusResult(xafpayOperatorResult(projection));
      await onRefresh?.();
    } finally {''', 1)
detail = detail.replace(
'''      const recovery = await apiFetch(`/payments/xafpay/orders/${orderId}/recovery`, { cache: "no-store" });
      if (recovery?.unresolved !== true || String(recovery?.attempt_public_id) !== unresolvedXafpayAttempt.id) return;
      const rail = String(recovery?.rail || unresolvedXafpayAttempt.rail || "mtn").toLowerCase();
      navigate("/processing", {
        state: {
          orderId,
          paymentMode: "xafpay",
          is_async: true,
          lines: [{ method: "xafpay", amount: Number(recovery.amount), provider: rail.includes("orange") ? "orange" : "mtn" }],
        },
      });''',
'''      const recovery = await loadXafpayRecovery(orderId);
      const state = xafpayResumeState(recovery, unresolvedXafpayAttempt.id);
      if (state) navigate("/processing", { state });''', 1)
detail = detail.replace(
'''      <div className="flex flex-wrap gap-2 pt-2">
        {unresolvedXafpayAttempt && (''',
'''      <div className="flex flex-wrap gap-2 pt-2">
        {xafpayStatusResult && <div className="w-full rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm font-semibold text-amber-900" role="status" aria-live="polite">{xafpayStatusResult}</div>}
        {unresolvedXafpayAttempt && (''', 1)
detail_panel.write_text(detail, encoding="utf-8")

payment_screen = target / "src" / "modules" / "sales" / "payment" / "PaymentScreen.tsx"
pay_text = payment_screen.read_text(encoding="utf-8")
if 'from "../../payments/xafpayRecovery"' not in pay_text:
    pay_text = pay_text.replace(
        'import { apiFetch } from "../../../lib/api";',
        'import { apiFetch } from "../../../lib/api";\nimport { checkXafpayCanonicalStatus, loadXafpayRecovery, xafpayOperatorResult, xafpayResumeState } from "../../payments/xafpayRecovery";', 1)
pay_text = pay_text.replace(
'''  const [xafpayRecovery, setXafpayRecovery] = useState<any>(null);
  const refreshXafpayRecovery = useCallback(async () => {
    if (!orderId) return setXafpayRecovery(null);
    const value = await apiFetch(`/payments/xafpay/orders/${orderId}/recovery`, { cache: "no-store" });
    setXafpayRecovery(value);
  }, [orderId]);''',
'''  const [xafpayRecovery, setXafpayRecovery] = useState<any>(null);
  const [xafpayChecking, setXafpayChecking] = useState(false);
  const [xafpayCheckResult, setXafpayCheckResult] = useState<string | null>(null);
  const refreshXafpayRecovery = useCallback(async () => {
    if (!orderId) return setXafpayRecovery(null);
    const value = await loadXafpayRecovery(Number(orderId));
    setXafpayRecovery(value);
  }, [orderId]);
  const checkXafpayRecovery = useCallback(async () => {
    if (!xafpayRecovery?.attempt_public_id || xafpayChecking) return;
    setXafpayChecking(true); setXafpayCheckResult(null);
    try {
      const projection = await checkXafpayCanonicalStatus(String(xafpayRecovery.attempt_public_id));
      setXafpayCheckResult(xafpayOperatorResult(projection));
      await refreshXafpayRecovery();
    } finally { setXafpayChecking(false); }
  }, [xafpayRecovery?.attempt_public_id, xafpayChecking, refreshXafpayRecovery]);''', 1)
pay_text = pay_text.replace(
'''          <div className="mt-3 flex gap-2">
            <button type="button" className="rounded-lg bg-emerald-700 px-3 py-2 text-white" onClick={() => navigate("/processing", { state: { orderId, paymentMode: "xafpay", is_async: true, lines: [{ method: "xafpay", amount: Number(xafpayRecovery.amount), provider: String(xafpayRecovery.rail || "mtn").toLowerCase().startsWith("orange") ? "orange" : "mtn" }] } })}>Resume XafPay</button>
            <button type="button" className="rounded-lg border px-3 py-2" onClick={() => refreshXafpayRecovery()}>Check status</button>
          </div>''',
'''          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button type="button" className="rounded-lg bg-emerald-700 px-3 py-2 text-white" onClick={() => { const state = xafpayResumeState(xafpayRecovery, String(xafpayRecovery.attempt_public_id)); if (state) navigate("/processing", { state }); }}>Resume XafPay</button>
            <button type="button" className="rounded-lg border px-3 py-2" disabled={xafpayChecking} onClick={checkXafpayRecovery}>{xafpayChecking ? "Checking..." : "Check status"}</button>
            {xafpayCheckResult && <span role="status" aria-live="polite" className="w-full text-sm font-semibold text-amber-900">{xafpayCheckResult}</span>}
          </div>''', 1)
payment_screen.write_text(pay_text, encoding="utf-8")

# The detail and payment-screen base recovery controls are generated later than
# the activity/modal overlays, so attach their cancellation controls here.
detail = detail_panel.read_text(encoding="utf-8")
detail = detail.replace(
    'xafpayOperatorResult, xafpayResumeState } from "../xafpayRecovery";',
    'xafpayOperatorResult, xafpayResumeState, requestXafpayCancellation } from "../xafpayRecovery";', 1)
detail = detail.replace('"fallback" | "resume" | "status">(', '"fallback" | "resume" | "status" | "cancel">(', 1)
if "const [xafpayCancelResult" not in detail:
    detail = detail.replace(
        '  const [xafpayStatusResult, setXafpayStatusResult] = useState<string | null>(null);',
        '  const [xafpayStatusResult, setXafpayStatusResult] = useState<string | null>(null);\n  const [xafpayCancelResult, setXafpayCancelResult] = useState<string | null>(null);', 1)
detail = detail.replace(
'''  async function resumeXafpay() {''',
'''  async function cancelXafpay() {
    if (!unresolvedXafpayAttempt || busyAction) return;
    setBusyAction("cancel"); setXafpayCancelResult(null);
    try {
      const response = await requestXafpayCancellation(unresolvedXafpayAttempt.id);
      setXafpayCancelResult(String(response?.message || "Cancellation is not yet confirmed."));
      await onRefresh?.();
    } finally { setBusyAction(null); }
  }

  async function resumeXafpay() {''', 1)
detail = detail.replace(
'''            <button className="rounded-xl border border-emerald-700 px-4 py-2 font-semibold text-emerald-800 disabled:opacity-50" onClick={checkXafpayStatus} disabled={busyAction !== null} type="button">
              {busyAction === "status" ? "Checking..." : "Check status"}
            </button>''',
'''            <button className="rounded-xl border border-emerald-700 px-4 py-2 font-semibold text-emerald-800 disabled:opacity-50" onClick={checkXafpayStatus} disabled={busyAction !== null} type="button">{busyAction === "status" ? "Checking..." : "Check status"}</button>
            <button className="rounded-xl border border-red-700 px-4 py-2 font-semibold text-red-800 disabled:opacity-50" onClick={cancelXafpay} disabled={busyAction !== null} type="button">{busyAction === "cancel" ? "Cancelling..." : "Cancel XafPay payment"}</button>
            {xafpayCancelResult && <div className="w-full rounded-xl bg-red-50 px-3 py-2 text-sm font-semibold text-red-900" role="status" aria-live="polite">{xafpayCancelResult}</div>}''', 1)
detail_panel.write_text(detail, encoding="utf-8")

pay_text = payment_screen.read_text(encoding="utf-8")
pay_text = pay_text.replace(
    'xafpayOperatorResult, xafpayResumeState } from "../../payments/xafpayRecovery";',
    'xafpayOperatorResult, xafpayResumeState, requestXafpayCancellation } from "../../payments/xafpayRecovery";', 1)
pay_text = pay_text.replace(
    '  const [xafpayCheckResult, setXafpayCheckResult] = useState<string | null>(null);',
    '  const [xafpayCheckResult, setXafpayCheckResult] = useState<string | null>(null);\n  const [xafpayCancelling, setXafpayCancelling] = useState(false);\n  const [xafpayCancelResult, setXafpayCancelResult] = useState<string | null>(null);', 1)
pay_text = pay_text.replace(
'''  const checkXafpayRecovery = useCallback(async () => {''',
'''  const cancelXafpayRecovery = useCallback(async () => {
    if (!xafpayRecovery?.attempt_public_id || xafpayCancelling) return;
    setXafpayCancelling(true); setXafpayCancelResult(null);
    try {
      const response = await requestXafpayCancellation(String(xafpayRecovery.attempt_public_id));
      setXafpayCancelResult(String(response?.message || "Cancellation is not yet confirmed."));
      await refreshXafpayRecovery();
    } finally { setXafpayCancelling(false); }
  }, [xafpayRecovery?.attempt_public_id, xafpayCancelling, refreshXafpayRecovery]);
  const checkXafpayRecovery = useCallback(async () => {''', 1)
pay_text = pay_text.replace(
'''            <button type="button" className="rounded-lg border px-3 py-2" disabled={xafpayChecking} onClick={checkXafpayRecovery}>{xafpayChecking ? "Checking..." : "Check status"}</button>
            {xafpayCheckResult &&''',
'''            <button type="button" className="rounded-lg border px-3 py-2" disabled={xafpayChecking} onClick={checkXafpayRecovery}>{xafpayChecking ? "Checking..." : "Check status"}</button>
            <button type="button" className="rounded-lg border border-red-700 px-3 py-2 text-red-800" disabled={xafpayCancelling} onClick={cancelXafpayRecovery}>{xafpayCancelling ? "Cancelling..." : "Cancel XafPay payment"}</button>
            {xafpayCancelResult && <span role="status" aria-live="polite" className="w-full text-sm font-semibold text-red-900">{xafpayCancelResult}</span>}
            {xafpayCheckResult &&''', 1)
payment_screen.write_text(pay_text, encoding="utf-8")

# R2 auth lifecycle: serialize refresh across concurrent 401 responses and
# wait for persisted session hydration before protected requests bootstrap.
auth_api = target / "src" / "api" / "auth.ts"
auth_text = auth_api.read_text(encoding="utf-8")
if "let refreshPromise: Promise<string> | null = null" not in auth_text:
    auth_text = auth_text.replace(
        'const DEFAULT_BRANCH_CODE = "BR001";',
        '''const DEFAULT_BRANCH_CODE = "BR001";

let refreshPromise: Promise<string> | null = null;
let terminalAuthFailureHandled = false;

export function waitForAuthBootstrap(): Promise<void> {
  const persistence = (useSessionStore as any).persist;
  if (!persistence || persistence.hasHydrated()) return Promise.resolve();
  return new Promise((resolve) => {
    const unsubscribe = persistence.onFinishHydration(() => {
      unsubscribe();
      resolve();
    });
    if (persistence.hasHydrated()) {
      unsubscribe();
      resolve();
    }
  });
}

export function handleTerminalAuthFailure() {
  if (terminalAuthFailureHandled) return;
  terminalAuthFailureHandled = true;
  useSessionStore.getState().logout();
  if (typeof window !== "undefined" && window.location.pathname !== "/login") {
    window.location.replace("/login");
  }
}''', 1)
    auth_text = auth_text.replace(
        'export async function refreshAccessToken(): Promise<string> {',
        'async function performRefreshAccessToken(): Promise<string> {', 1)
    auth_text = auth_text.replace(
        '''export function logout() {
  useSessionStore.getState().logout();
}''',
    '''export function refreshAccessToken(): Promise<string> {
  if (!refreshPromise) {
    refreshPromise = performRefreshAccessToken().finally(() => {
      refreshPromise = null;
    });
  }
  return refreshPromise;
}

export function logout() {
  terminalAuthFailureHandled = true;
  useSessionStore.getState().logout();
}''', 1)
    auth_text = auth_text.replace(
        '''  useSessionStore.getState().setAuth({
    user: data.user,
    accessToken: data.access_token,
    refreshToken: data.refresh_token ?? null,
  });''',
    '''  useSessionStore.getState().setAuth({
    user: data.user,
    accessToken: data.access_token,
    refreshToken: data.refresh_token ?? null,
  });
  terminalAuthFailureHandled = false;''', 1)
auth_api.write_text(auth_text, encoding="utf-8")

api_client = target / "src" / "lib" / "api.ts"
api_text = api_client.read_text(encoding="utf-8")
api_text = api_text.replace(
    'import { getAccessToken, logout, refreshAccessToken } from "../api/auth";',
    'import { getAccessToken, handleTerminalAuthFailure, refreshAccessToken, waitForAuthBootstrap } from "../api/auth";', 1)
api_text = api_text.replace(
    '''export async function apiFetch(path: string, options: RequestInit = {}) {
  const token = getAccessToken();''',
    '''export async function apiFetch(path: string, options: RequestInit = {}) {
  await waitForAuthBootstrap();
  const token = getAccessToken();
  const isAuthLifecycleRequest = path === "/auth/login" || path === "/auth/refresh";''', 1)
api_text = api_text.replace(
    '  if (res.status === 401) {',
    '  if (res.status === 401 && !isAuthLifecycleRequest) {', 1)
api_text = api_text.replace(
    '''    try {
      const newToken = await refreshAccessToken();''',
    '''    try {
      const currentToken = getAccessToken();
      const newToken = token && currentToken && currentToken !== token
        ? currentToken
        : await refreshAccessToken();''', 1)
api_text = api_text.replace(
    '''    } catch (refreshErr) {
      logout();''',
    '''    } catch (refreshErr) {
      handleTerminalAuthFailure();''', 1)
api_client.write_text(api_text, encoding="utf-8")

# The accepted XV15 R2 frontend files are the reproducibility authority. Keep
# this overlay inside the repository so fresh runtimes match the reviewed live
# presentation/recovery behavior exactly.
authority = Path(__file__).resolve().parent / "xv15_frontend_authority"
for relative in (
    "src/app/AppShell.tsx",
    "src/lib/xafpayOutcomeWatcher.ts",
    "src/modules/sales/ProcessingScreen.tsx",
    "src/modules/payments/PaymentsScreen.tsx",
    "src/modules/payments/hooks/usePayments.ts",
    "src/modules/payments/hooks/usePaymentActivity.ts",
    "src/modules/payments/components/StandalonePaymentBuilder.tsx",
    "src/modules/payments/components/PaymentDetailPanel.tsx",
):
    source_file = authority / relative
    if not source_file.is_file():
        raise RuntimeError(f"XV15_FRONTEND_AUTHORITY_MISSING:{relative}")
    destination = target / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_file, destination)

if "let refreshPromise: Promise<string> | null = null" not in auth_text or "waitForAuthBootstrap" not in api_text or "handleTerminalAuthFailure" not in api_text or "currentToken !== token" not in api_text:
    raise RuntimeError("XV15_R2_AUTH_REFRESH_SINGLE_FLIGHT_MISSING")

if "xafpayStatusResult" not in detail or "onRefresh={refreshAll}" not in payments_screen_text or "Resume XafPay" not in activity_text or "xafpayCheckResult" not in pay_text or "Cancel XafPay payment" not in detail or "Cancel XafPay payment" not in pay_text:
    raise RuntimeError("XV15_R2_STATUS_ACTION_PARITY_MISSING")

print("XV15_R1_WND_FRONTEND_OVERLAY=PASS")
print("XV15_R1_XAFPAY_CONFIRM_ENABLED=PASS")
print("XV15_R1_XAFPAY_CHECKOUT_MODAL=PASS")
print("XV15_R1_XAFPAY_CHECKOUT_ORIGIN=127.0.0.1:5174")
print("XV15_R1_XAFPAY_SELECTION_SETTLEMENT_CALL=ABSENT")
print("XV15_PAYMENT_RECORD_ATTEMPT_VISIBILITY=PASS")
print("XV15_PAYMENT_RECORD_METHOD_RAIL_ORCHESTRATOR_CLARITY=PASS")
