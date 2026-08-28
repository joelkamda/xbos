import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import type { Payment } from "../types";
import { money } from "../utils/money";
import { apiFetch } from "../../../lib/api";
import { checkXafpayCanonicalStatus, loadXafpayRecovery, xafpayOperatorResult, xafpayResumeState, requestXafpayCancellation } from "../xafpayRecovery";
import { makeClientId } from "../../../utils/clientId";
import ReceiptPanel, {
  ReceiptPanelHandle,
} from "../../../components/receipt/ReceiptPanel";

type PaymentAttemptView = {
  id: string;
  method: string;
  provider?: string | null;
  amount: number;
  status: string;
  created_at?: string | null;
  settlement_mode?: string | null;
  origin_channel?: string | null;
  orchestrator?: string | null;
  rail?: string | null;
  ordinal?: number | null;
  meta?: any;
};

const n = (value: any) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
};

function getPaymentMeta(payment: Payment | null) {
  if (!payment?.meta || typeof payment.meta !== "object") return {};
  return payment.meta;
}

function getExplicitBalanceDue(payment: Payment | null) {
  if (!payment) return 0;

  const meta = getPaymentMeta(payment);
  const totals = meta?.totals || {};

  return n(
    meta.balance_due ??
      totals.balance_due ??
      meta.unpaid_total ??
      totals.unpaid_total
  );
}

function getTotalPaid(payment: Payment | null) {
  if (!payment) return 0;

  const meta = getPaymentMeta(payment);
  const totals = meta?.totals || {};

  return n(
    meta.total_paid ??
      meta.paid_total ??
      totals.total_paid ??
      totals.paid_total ??
      meta.applied ??
      totals.applied
  );
}

function getBalanceDue(payment: Payment | null) {
  if (!payment) return 0;

  if (payment.status === "COMPLETED") return 0;

  const explicitBalance = getExplicitBalanceDue(payment);
  if (explicitBalance > 0) return explicitBalance;

  const amount = n(payment.amount);
  const totalPaid = getTotalPaid(payment);

  if (totalPaid > 0) {
    return Math.max(amount - totalPaid, 0);
  }

  if (payment.status === "PENDING") return amount;

  return 0;
}

function getDisplayType(payment: Payment) {
  if (payment.payable_type) return payment.payable_type;

  const meta = getPaymentMeta(payment);
  if (meta?.purpose) return meta.purpose;
  if (meta?.receipt_meta?.purpose) return meta.receipt_meta.purpose;

  return "direct_pay";
}

function buildCustomerFromPayment(payment: Payment) {
  const meta = getPaymentMeta(payment);

  const metaCustomer = meta?.customer || meta?.receipt_meta?.customer;
  if (metaCustomer) return metaCustomer;

  if (!payment.customer_name && !payment.phone) return null;

  return {
    ...(payment.customer_name ? { name: payment.customer_name } : {}),
    ...(payment.phone ? { phone: payment.phone } : {}),
  };
}

async function fetchCanonicalPaymentReceipt(payment: Payment) {
  if (payment.sale_id && Number(payment.sale_id) > 0) {
    return await apiFetch(`/payments/receipts/${payment.sale_id}`);
  }

  return await apiFetch(`/payments/receipts/manual/${payment.id}`);
}

async function fetchPaymentDetails(payment: Payment) {
  return await apiFetch(`/payments/${payment.id}`);
}

function unwrapReceiptPayload(payload: any) {
  if (!payload) return {};
  if (payload.receipt) return payload.receipt;
  if (payload.receipt_meta) return { ...payload, ...payload.receipt_meta };
  return payload;
}

function readBalanceFromReceipt(payload: any) {
  const receipt = unwrapReceiptPayload(payload);
  const totals = receipt?.totals || {};

  const balanceDue = n(
    receipt.balance_due ??
      totals.balance_due ??
      receipt.unpaid_total ??
      totals.unpaid_total
  );

  const totalPaid = n(
    receipt.total_paid ??
      receipt.paid_total ??
      receipt.applied ??
      totals.total_paid ??
      totals.paid_total ??
      totals.applied
  );

  const total = n(
    receipt.total ??
      receipt.client_total ??
      receipt.client_pays ??
      receipt.net_total ??
      receipt.amount ??
      totals.net_total ??
      totals.client_pays ??
      totals.gross_total
  );

  if (balanceDue > 0) return balanceDue;
  if (total > 0 && totalPaid > 0) return Math.max(total - totalPaid, 0);

  return 0;
}

function readTotalPaidFromReceipt(payload: any) {
  const receipt = unwrapReceiptPayload(payload);
  const totals = receipt?.totals || {};

  return n(
    receipt.total_paid ??
      receipt.paid_total ??
      receipt.applied ??
      totals.total_paid ??
      totals.paid_total ??
      totals.applied
  );
}

function normalizeAttempt(raw: any): PaymentAttemptView {
  return {
    id: String(raw?.id ?? raw?.attempt_id ?? makeClientId("attempt")),
    method: String(raw?.method ?? raw?.channel ?? "unknown"),
    provider: raw?.provider ?? null,
    amount: n(raw?.amount),
    status: String(raw?.status ?? "UNKNOWN").toUpperCase(),
    created_at: raw?.created_at ?? null,
    settlement_mode: raw?.settlement_mode ?? null,
    origin_channel: raw?.origin_channel ?? null,
    orchestrator: raw?.orchestrator ?? null,
    rail: raw?.rail ?? null,
    ordinal: Number.isFinite(Number(raw?.ordinal ?? raw?.sequence_number))
      ? Number(raw?.ordinal ?? raw?.sequence_number)
      : null,
    meta: raw?.meta ?? {},
  };
}

function chronologicalAttemptNumbers(attempts: PaymentAttemptView[]) {
  const ordered = attempts
    .map((attempt, index) => ({ attempt, index }))
    .sort((a, b) => {
      if (a.attempt.ordinal != null && b.attempt.ordinal != null) {
        return a.attempt.ordinal - b.attempt.ordinal || a.index - b.index;
      }
      const aTime = a.attempt.created_at ? Date.parse(a.attempt.created_at) : NaN;
      const bTime = b.attempt.created_at ? Date.parse(b.attempt.created_at) : NaN;
      if (Number.isFinite(aTime) && Number.isFinite(bTime) && aTime !== bTime) {
        return aTime - bTime;
      }
      if (Number.isFinite(aTime) !== Number.isFinite(bTime)) return Number.isFinite(aTime) ? -1 : 1;
      return a.index - b.index;
    });
  return new Map(ordered.map(({ attempt }, index) => [attempt.id, index + 1]));
}

function statusPillClass(status: string) {
  const s = String(status || "").toUpperCase();

  if (s === "COMPLETED" || s === "SUCCEEDED" || s === "SUCCESS") {
    return "bg-emerald-50 text-emerald-700 ring-emerald-200";
  }

  if (s === "FAILED" || s === "FAILURE") {
    return "bg-rose-50 text-rose-700 ring-rose-200";
  }

  return "bg-amber-50 text-amber-700 ring-amber-200";
}

function methodLabel(attempt: PaymentAttemptView) {
  const method = attempt.method ? attempt.method.replaceAll("_", " ").toUpperCase() : "UNKNOWN";
  const rail = attempt.rail ? ` / ${attempt.rail.replaceAll("_", " ").toUpperCase()}` : "";
  return `${method}${rail}`;
}

export default function PaymentDetailPanel({
  payment,
  onRefresh,
}: {
  payment: Payment | null;
  onRefresh?: () => Promise<void> | void;
}) {
  const navigate = useNavigate();

  const [showReceiptId, setShowReceiptId] = useState<string | null>(null);
  const [showAttempts, setShowAttempts] = useState(false);

  const [attempts, setAttempts] = useState<PaymentAttemptView[]>([]);
  const [loadingAttempts, setLoadingAttempts] = useState(false);
  const [attemptsError, setAttemptsError] = useState<string | null>(null);
  const attemptNumbers = useMemo(() => chronologicalAttemptNumbers(attempts), [attempts]);

  const [busyAction, setBusyAction] = useState<null | "balance" | "fallback" | "resume" | "status" | "cancel">(
    null
  );

  const [canonicalBalanceDue, setCanonicalBalanceDue] = useState<number | null>(
    null
  );
  const [canonicalTotalPaid, setCanonicalTotalPaid] = useState<number | null>(
    null
  );
  const [loadingCanonical, setLoadingCanonical] = useState(false);
  const [xafpayStatusResult, setXafpayStatusResult] = useState<string | null>(null);
  const [xafpayCancelResult, setXafpayCancelResult] = useState<string | null>(null);

  const receiptRef = useRef<ReceiptPanelHandle>(null);

  useEffect(() => {
    let mounted = true;

    async function loadCanonicalSummary() {
      setCanonicalBalanceDue(null);
      setCanonicalTotalPaid(null);

      if (!payment) return;
      if (payment.status === "COMPLETED") return;

      try {
        setLoadingCanonical(true);

        const payload = await fetchCanonicalPaymentReceipt(payment);

        if (!mounted) return;

        const backendBalance = readBalanceFromReceipt(payload);
        const backendPaid = readTotalPaidFromReceipt(payload);

        setCanonicalBalanceDue(backendBalance);
        setCanonicalTotalPaid(backendPaid);
      } catch (error) {
        console.warn(
          "[PaymentDetailPanel] Could not load canonical payment summary.",
          error
        );
      } finally {
        if (mounted) setLoadingCanonical(false);
      }
    }

    loadCanonicalSummary();

    return () => {
      mounted = false;
    };
  }, [payment?.id, payment?.status]);

  useEffect(() => {
    let mounted = true;

    async function loadAttempts() {
      setAttempts([]);
      setAttemptsError(null);

      if (!payment) return;

      try {
        setLoadingAttempts(true);

        const details = await fetchPaymentDetails(payment);

        if (!mounted) return;

        const rawAttempts = Array.isArray(details?.attempts)
          ? details.attempts
          : Array.isArray(details?.payment_attempts)
          ? details.payment_attempts
          : Array.isArray(details?.meta?.attempts)
          ? details.meta.attempts
          : [];

        setAttempts(rawAttempts.map(normalizeAttempt));

        if (details?.total_paid !== undefined) {
          setCanonicalTotalPaid(n(details.total_paid));
        }

        if (details?.balance_due !== undefined) {
          setCanonicalBalanceDue(n(details.balance_due));
        }
      } catch (error) {
        console.warn("[PaymentDetailPanel] Could not load attempts.", error);

        if (mounted) {
          setAttemptsError("Attempts unavailable");
        }
      } finally {
        if (mounted) setLoadingAttempts(false);
      }
    }

    loadAttempts();

    return () => {
      mounted = false;
    };
  }, [payment?.id]);

  if (!payment) {
    return (
      <div className="rounded-2xl bg-white p-4 text-sm text-neutral-500 shadow">
        Select a payment to view details.
      </div>
    );
  }

  const hasSaleId = Boolean(payment.sale_id && Number(payment.sale_id) > 0);

  const meta = getPaymentMeta(payment);
  const listTotalPaid = getTotalPaid(payment);
  const listBalanceDue = getBalanceDue(payment);

  const totalPaid =
    canonicalTotalPaid !== null && canonicalTotalPaid > 0
      ? canonicalTotalPaid
      : listTotalPaid;

  const balanceDue =
    payment.status === "COMPLETED"
      ? 0
      : canonicalBalanceDue !== null
      ? canonicalBalanceDue
      : listBalanceDue;

  const activePendingAttempts = Number((payment as any).active_pending_attempts || 0);
  const canCompleteBalance =
    ["PARTIAL", "PAYMENT_REQUIRED"].includes(payment.status) &&
    balanceDue > 0 && activePendingAttempts === 0 && hasSaleId;
  const canSettleAnotherWay =
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
      setXafpayStatusResult(null);
      const projection = await checkXafpayCanonicalStatus(unresolvedXafpayAttempt.id);
      setAttempts((current) => current.map((attempt) => attempt.id === unresolvedXafpayAttempt.id
        ? { ...attempt, status: String(projection?.attempt_state || attempt.status).toUpperCase() }
        : attempt));
      setCanonicalTotalPaid(Number(projection?.total_paid || 0));
      setCanonicalBalanceDue(Number(projection?.balance_due || 0));
      setXafpayStatusResult(xafpayOperatorResult(projection));
      await onRefresh?.();
    } finally {
      setBusyAction(null);
    }
  }

  async function cancelXafpay() {
    if (!unresolvedXafpayAttempt || busyAction) return;
    setBusyAction("cancel"); setXafpayCancelResult(null);
    try {
      const response = await requestXafpayCancellation(unresolvedXafpayAttempt.id);
      setXafpayCancelResult(String(response?.message || "Cancellation is not yet confirmed."));
      await onRefresh?.();
    } finally { setBusyAction(null); }
  }

  async function resumeXafpay() {
    if (!unresolvedXafpayAttempt || busyAction) return;
    setBusyAction("resume");
    try {
      const orderId = Number(unresolvedXafpayAttempt.meta?.order_id || meta?.order_id || 0);
      if (orderId <= 0) return;
      const recovery = await loadXafpayRecovery(orderId);
      const state = xafpayResumeState(recovery, unresolvedXafpayAttempt.id);
      if (state) navigate("/processing", { state });
    } finally {
      setBusyAction(null);
    }
  }

  function toggleReceipt() {
    setShowReceiptId((prev) => (prev === payment.id ? null : payment.id));
  }

  function toggleAttempts() {
    setShowAttempts((prev) => !prev);
  }

  async function resolveCanonicalBalance() {
    try {
      const receiptPayload = await fetchCanonicalPaymentReceipt(payment);
      const backendBalance = readBalanceFromReceipt(receiptPayload);

      if (backendBalance > 0) {
        setCanonicalBalanceDue(backendBalance);
        setCanonicalTotalPaid(readTotalPaidFromReceipt(receiptPayload));
        return backendBalance;
      }

      const backendPaid = readTotalPaidFromReceipt(receiptPayload);
      const originalAmount = n(payment.amount);

      if (originalAmount > 0 && backendPaid > 0) {
        const computed = Math.max(originalAmount - backendPaid, 0);
        setCanonicalBalanceDue(computed);
        setCanonicalTotalPaid(backendPaid);
        return computed;
      }
    } catch (error) {
      console.warn(
        "[PaymentDetailPanel] Could not fetch canonical balance. Falling back to display balance.",
        error
      );
    }

    return balanceDue;
  }

  async function completeBalance() {
    if (!canCompleteBalance || busyAction) return;

    setBusyAction("balance");

    try {
      const canonicalAmountToCollect = await resolveCanonicalBalance();

      if (canonicalAmountToCollect <= 0) {
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

      const originalDescription =
        meta?.description ||
        meta?.receipt_meta?.description ||
        meta?.receipt_meta?.items?.[0]?.name ||
        "Balance Payment";

      const customer = buildCustomerFromPayment(payment);

      const reference =
        meta?.reference ||
        meta?.receipt_meta?.reference ||
        payment.payable_id ||
        payment.id;

      navigate("/payment", {
        state: {
          manual: true,
          payment_source: "standalone",
          direct_pay: true,

          existing_intent_id: payment.id,
          parent_intent_id: payment.id,
          complete_balance: true,

          amount: canonicalAmountToCollect,
          description: `Balance Payment - ${originalDescription}`,
          customer,
          reference,

          receipt_meta: {
            manual: true,
            payment_source: "standalone",
            direct_pay: true,
            complete_balance: true,

            existing_intent_id: payment.id,
            parent_intent_id: payment.id,
            original_payment_id: payment.id,

            purpose:
              meta?.purpose || meta?.receipt_meta?.purpose || "direct_income",
            description: `Balance Payment - ${originalDescription}`,
            customer,
            reference: String(reference || payment.id),

            items: [
              {
                name: `Balance Payment - ${originalDescription}`,
                quantity: 1,
                unit_price: canonicalAmountToCollect,
                line_total: canonicalAmountToCollect,
                role: "balance",
              },
            ],

            gross_total: canonicalAmountToCollect,
            original_total: canonicalAmountToCollect,
            discount_total: 0,
            complimentary_total: 0,
            net_total: canonicalAmountToCollect,
            client_pays: canonicalAmountToCollect,

            totals: {
              gross_total: canonicalAmountToCollect,
              discount_total: 0,
              complimentary_total: 0,
              net_total: canonicalAmountToCollect,
              client_pays: canonicalAmountToCollect,
            },
          },
        },
      });
    } finally {
      setBusyAction(null);
    }
  }

  async function settleAnotherWay() {
    if (busyAction) return;

    setBusyAction("fallback");

    try {
      let amountToSettle = balanceDue > 0 ? balanceDue : n(payment.amount);

      if (payment.status === "PENDING") {
        const canonicalBalance = await resolveCanonicalBalance();
        if (canonicalBalance > 0) {
          amountToSettle = canonicalBalance;
        }
      }

      if (amountToSettle <= 0) return;

      const originalDescription =
        meta?.description ||
        meta?.receipt_meta?.description ||
        meta?.receipt_meta?.items?.[0]?.name ||
        "Fallback Payment";

      const customer = buildCustomerFromPayment(payment);

      const reference =
        meta?.reference ||
        meta?.receipt_meta?.reference ||
        payment.payable_id ||
        payment.id;

      navigate("/payment", {
        state: {
          manual: true,
          payment_source: "standalone",
          direct_pay: true,

          existing_intent_id: payment.id,
          parent_intent_id: payment.id,
          settle_failed_intent: payment.status === "FAILED",
          complete_balance: payment.status === "PENDING",

          amount: amountToSettle,
          description: `Fallback Payment - ${originalDescription}`,
          customer,
          reference,

          receipt_meta: {
            manual: true,
            payment_source: "standalone",
            direct_pay: true,

            existing_intent_id: payment.id,
            parent_intent_id: payment.id,
            original_payment_id: payment.id,

            settle_failed_intent: payment.status === "FAILED",
            complete_balance: payment.status === "PENDING",

            purpose:
              meta?.purpose || meta?.receipt_meta?.purpose || "direct_income",
            description: `Fallback Payment - ${originalDescription}`,
            customer,
            reference: String(reference || payment.id),

            items: [
              {
                name: `Fallback Payment - ${originalDescription}`,
                quantity: 1,
                unit_price: amountToSettle,
                line_total: amountToSettle,
                role: "fallback",
              },
            ],

            gross_total: amountToSettle,
            original_total: amountToSettle,
            discount_total: 0,
            complimentary_total: 0,
            net_total: amountToSettle,
            client_pays: amountToSettle,

            totals: {
              gross_total: amountToSettle,
              discount_total: 0,
              complimentary_total: 0,
              net_total: amountToSettle,
              client_pays: amountToSettle,
            },
          },
        },
      });
    } finally {
      setBusyAction(null);
    }
  }

  return (
    <div className="space-y-3 rounded-2xl bg-white p-4 shadow">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-xl font-bold">{money(payment.amount)}</div>

          {loadingCanonical && payment.status !== "COMPLETED" && (
            <div className="mt-1 text-xs font-semibold text-neutral-500">
              Checking balance...
            </div>
          )}

          {!loadingCanonical && balanceDue > 0 && (
            <div className="mt-1 text-sm font-semibold text-amber-700">
              Balance due: {money(balanceDue)}
            </div>
          )}

          {payment.status === "COMPLETED" && (
            <div className="mt-1 text-sm font-semibold text-emerald-700">
              Fully settled
            </div>
          )}
        </div>

        {payment.status === "PENDING" && (
          <span className="rounded-full bg-amber-50 px-3 py-1 text-xs font-bold text-amber-700 ring-1 ring-amber-200">
            Pending
          </span>
        )}

        {payment.status === "COMPLETED" && (
          <span className="rounded-full bg-emerald-50 px-3 py-1 text-xs font-bold text-emerald-700 ring-1 ring-emerald-200">
            Completed
          </span>
        )}

        {payment.status === "FAILED" && <span className="rounded-full bg-rose-50 px-3 py-1 text-xs font-bold text-rose-700 ring-1 ring-rose-200">Failed</span>}
        {payment.status === "PARTIAL" && <span className="rounded-full bg-amber-50 px-3 py-1 text-xs font-bold text-amber-800 ring-1 ring-amber-300">Partial / payment required</span>}
        {payment.status === "RECEIVABLE" && <span className="rounded-full bg-sky-50 px-3 py-1 text-xs font-bold text-sky-700 ring-1 ring-sky-200">Receivable</span>}
        {payment.status === "PAYMENT_REQUIRED" && <span className="rounded-full bg-orange-50 px-3 py-1 text-xs font-bold text-orange-700 ring-1 ring-orange-200">Payment required</span>}
      </div>

      <div className="grid grid-cols-1 gap-1 text-sm">
        <div>
          <span className="font-medium">Status:</span> {payment.status}
        </div>

        {payment.customer_name && (
          <div>
            <span className="font-medium">Customer:</span>{" "}
            {payment.customer_name}
          </div>
        )}

        {payment.phone && (
          <div>
            <span className="font-medium">Phone:</span> {payment.phone}
          </div>
        )}

        <div><span className="font-medium">Origin/channel:</span> {(payment as any).origin_channel || "POS"}</div>
        <div><span className="font-medium">Method:</span> {payment.method}</div>
        {(payment as any).orchestrator && <div><span className="font-medium">Orchestrator:</span> {(payment as any).orchestrator}</div>}
        {(payment as any).rail && <div><span className="font-medium">Rail:</span> {(payment as any).rail}</div>}
        {payment.provider && <div><span className="font-medium">Provider:</span> {payment.provider}</div>}

        {payment.sale_id && (
          <div>
            <span className="font-medium">Sale:</span> {payment.sale_id}
          </div>
        )}

        {!payment.sale_id && (
          <div>
            <span className="font-medium">Type:</span>{" "}
            {getDisplayType(payment)}
          </div>
        )}

        {totalPaid > 0 && (
          <div>
            <span className="font-medium">Paid so far:</span>{" "}
            {money(totalPaid)}
          </div>
        )}

        {balanceDue > 0 && (
          <div>
            <span className="font-medium">Remaining:</span>{" "}
            {money(balanceDue)}
          </div>
        )}

        <div>
          <span className="font-medium">Created:</span>{" "}
          {new Date(payment.created_at).toLocaleString()}
        </div>
      </div>

      <div className="flex flex-wrap gap-2 pt-2">
        {xafpayStatusResult && <div className="w-full rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm font-semibold text-amber-900" role="status" aria-live="polite">{xafpayStatusResult}</div>}
        {unresolvedXafpayAttempt && (
          <>
            <button className="rounded-xl bg-emerald-700 px-4 py-2 font-semibold text-white disabled:bg-emerald-300" onClick={resumeXafpay} disabled={busyAction !== null} type="button">
              {busyAction === "resume" ? "Reopening..." : "Resume XafPay"}
            </button>
            <button className="rounded-xl border border-emerald-700 px-4 py-2 font-semibold text-emerald-800 disabled:opacity-50" onClick={checkXafpayStatus} disabled={busyAction !== null} type="button">{busyAction === "status" ? "Checking..." : "Check status"}</button>
            <button className="rounded-xl border border-red-700 px-4 py-2 font-semibold text-red-800 disabled:opacity-50" onClick={cancelXafpay} disabled={busyAction !== null} type="button">{busyAction === "cancel" ? "Cancelling..." : "Cancel XafPay payment"}</button>
            {xafpayCancelResult && <div className="w-full rounded-xl bg-red-50 px-3 py-2 text-sm font-semibold text-red-900" role="status" aria-live="polite">{xafpayCancelResult}</div>}
          </>
        )}
        {canCompleteBalance && (
          <button
            className="rounded-xl bg-amber-600 px-4 py-2 font-semibold text-white hover:bg-amber-700 disabled:cursor-not-allowed disabled:bg-amber-300"
            onClick={completeBalance}
            disabled={busyAction !== null || loadingCanonical}
            type="button"
          >
            {busyAction === "balance" ? "Checking..." : "Complete Balance"}
          </button>
        )}

        {canSettleAnotherWay && payment.status === "FAILED" && (
          <button
            className="rounded-xl bg-amber-600 px-4 py-2 font-semibold text-white hover:bg-amber-700 disabled:cursor-not-allowed disabled:bg-amber-300"
            onClick={settleAnotherWay}
            disabled={busyAction !== null}
            type="button"
          >
            {busyAction === "fallback" ? "Checking..." : "Settle Another Way"}
          </button>
        )}

        <button
          className="rounded-xl bg-emerald-700 px-4 py-2 text-white hover:bg-emerald-800"
          onClick={toggleReceipt}
          type="button"
        >
          {showReceiptId === payment.id ? "Hide Receipt" : "View Receipt"}
        </button>

        {showReceiptId === payment.id && (
          <button
            onClick={() => receiptRef.current?.print()}
            className="rounded-xl bg-black px-4 py-2 text-white"
            type="button"
          >
            Print
          </button>
        )}

        <button
          className="rounded-xl bg-neutral-100 px-4 py-2 font-semibold text-neutral-800 hover:bg-neutral-200"
          onClick={toggleAttempts}
          type="button"
        >
          {showAttempts ? "Hide Attempts" : "View Attempts"}
        </button>
      </div>

      {showReceiptId === payment.id && (
        <div className="rounded-xl border border-neutral-200 bg-neutral-50 p-3">
          <ReceiptPanel
            ref={receiptRef}
            saleId={hasSaleId ? Number(payment.sale_id) : undefined}
            intentId={hasSaleId ? undefined : payment.id}
          />
        </div>
      )}

      {showAttempts && (
        <div className="rounded-2xl border border-neutral-200 bg-neutral-50 p-3">
          <div className="mb-3 flex items-center justify-between gap-2">
            <div>
              <div className="text-sm font-extrabold text-neutral-950">
                Payment Attempts
              </div>
              <div className="text-xs text-neutral-500">
                Internal tender and settlement history for this payment.
              </div>
            </div>

            {loadingAttempts && (
              <span className="text-xs font-semibold text-neutral-500">
                Loading...
              </span>
            )}
          </div>

          {attemptsError && (
            <div className="rounded-xl bg-rose-50 p-3 text-sm font-semibold text-rose-700 ring-1 ring-rose-100">
              {attemptsError}
            </div>
          )}

          {!attemptsError && !loadingAttempts && attempts.length === 0 && (
            <div className="rounded-xl bg-white p-3 text-sm text-neutral-500 ring-1 ring-neutral-200">
              No attempts found for this payment yet.
            </div>
          )}

          {!attemptsError && attempts.length > 0 && (
            <div className="space-y-2">
              {attempts.map((attempt) => (
                <div
                  key={attempt.id}
                  className="rounded-xl bg-white p-3 ring-1 ring-neutral-200"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-sm font-bold text-neutral-950">
                        #{attemptNumbers.get(attempt.id) ?? "?"} {methodLabel(attempt)}
                      </div>

                      <div className="mt-1 text-xs text-neutral-500">
                        {attempt.origin_channel ? `Origin: ${attempt.origin_channel} · ` : ""}
                        {attempt.orchestrator ? `Orchestrator: ${attempt.orchestrator} · ` : ""}
                        {attempt.settlement_mode || "manual"}
                        {attempt.created_at
                          ? ` • ${new Date(
                              attempt.created_at
                            ).toLocaleString()}`
                          : ""}
                      </div>
                    </div>

                    <div className="text-right">
                      <div className="text-sm font-extrabold text-neutral-950">
                        {money(attempt.amount)}
                      </div>

                      <span
                        className={`mt-1 inline-flex rounded-full px-2.5 py-1 text-[11px] font-bold ring-1 ${statusPillClass(
                          attempt.status
                        )}`}
                      >
                        {attempt.status}
                      </span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
