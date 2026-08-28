/* =========================================================
FILE: src/modules/sales/ProcessingScreen.tsx

INFUSED:
- Prefer payment lines from location.state.lines
- Fallback to cart splitPayments for legacy compatibility
- Supports standalone/direct-pay/manual payment draft flow
- Supports completing an existing pending PaymentIntent
- Preserves change/tip/tendered truth
- Prevents async/XafPay from being prematurely settled through POS
- Fetches fresh order data before settlement when orderId exists
- Carries commission-safe order author fields into receipt_meta:
  served_by_name
  order_created_by_name
  order_created_by_user_id
- Passes canonical identifiers to ResultScreen:
  saleId for sale receipts
  intentId for manual/payment-intent receipts
========================================================= */

import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { v4 as uuidv4 } from "uuid";
import { useCartStore } from "../../lib/store/cart";
import { apiFetch } from "../../lib/api";
import { requestXafpayCancellation } from "../payments/xafpayRecovery";
import { registerXafpayOutcomeWatch } from "../../lib/xafpayOutcomeWatcher";

const ACTIVE_ORDER_ID_KEY = "xbos_active_order_id";

const n = (v: any) => {
  const x = Number(v);
  return Number.isFinite(x) ? x : 0;
};

const text = (v: any) => String(v ?? "").trim();

const firstText = (...values: any[]) => {
  for (const value of values) {
    const cleaned = text(value);
    if (cleaned) return cleaned;
  }

  return "";
};

const firstValue = (...values: any[]) => {
  for (const value of values) {
    if (value !== undefined && value !== null && value !== "") return value;
  }

  return null;
};

export default function ProcessingScreen() {
  const navigate = useNavigate();
  const location = useLocation();
  const hasRun = useRef(false);
  const statusRefreshRef = useRef<Promise<any> | null>(null);
  const [checkoutUrl, setCheckoutUrl] = useState("");
  const [checkoutAttemptId, setCheckoutAttemptId] = useState("");
  const [checkoutProjection, setCheckoutProjection] = useState<any>(null);
  const [xafpayInitiationIssue, setXafpayInitiationIssue] = useState<any>(null);
  const [xafpayCancelling, setXafpayCancelling] = useState(false);
  const [xafpayCancelResult, setXafpayCancelResult] = useState<string | null>(null);
  const [xafpayChecking, setXafpayChecking] = useState(false);

  const setSaleId = useCartStore((s: any) => s.setSaleId);
  const clearSplitPayments = useCartStore((s: any) => s.clearSplitPayments);
  const clearCart = useCartStore((s: any) => s.clearCart);

  const safeSetSaleId = typeof setSaleId === "function" ? setSaleId : () => {};
  const safeClearSplitPayments =
    typeof clearSplitPayments === "function" ? clearSplitPayments : () => {};
  const safeClearCart = typeof clearCart === "function" ? clearCart : () => {};

  /* ================= ROUTE / SOURCE ================= */

  const paymentSource = text(location.state?.payment_source);
  const paymentMode = text(location.state?.paymentMode);

  const isAsync =
    location.state?.is_async === true ||
    location.state?.settlement_mode === "gateway" ||
    paymentMode === "xafpay";

  const stateOrderId = Number(location.state?.orderId ?? 0);

  const queryOrderId = useMemo(() => {
    const params = new URLSearchParams(location.search);
    return Number(params.get("orderId") ?? 0);
  }, [location.search]);

  const persistedOrderId = useMemo(() => {
    try {
      return Number(sessionStorage.getItem(ACTIVE_ORDER_ID_KEY) ?? 0);
    } catch {
      return 0;
    }
  }, []);

  const orderId =
    stateOrderId > 0
      ? stateOrderId
      : queryOrderId > 0
      ? queryOrderId
      : persistedOrderId > 0
      ? persistedOrderId
      : null;

  const isStandalone =
    paymentSource === "standalone" || location.state?.manual === true;

  const isManual = isStandalone || !orderId;
  const isInvoice = location.state?.mode === "invoice";

  const builderReceiptMeta = location.state?.receipt_meta || {};
  const metaTotals = builderReceiptMeta?.totals || {};

  const existingIntentId =
    location.state?.existing_intent_id ||
    location.state?.parent_intent_id ||
    builderReceiptMeta?.existing_intent_id ||
    builderReceiptMeta?.parent_intent_id ||
    null;

  const isCompletingExistingIntent =
    Boolean(existingIntentId) || location.state?.complete_balance === true;

  const isSettlingFailedIntent =
    Boolean(existingIntentId) || location.state?.settle_failed_intent === true;

  const descriptionFromState = text(location.state?.description);
  const customerFromState = location.state?.customer ?? null;
  const referenceFromState = text(location.state?.reference);

  useEffect(() => {
    if (!orderId) return;

    try {
      sessionStorage.setItem(ACTIVE_ORDER_ID_KEY, String(orderId));
    } catch {}
  }, [orderId]);

  useEffect(() => {
    if (hasRun.current) return;
    hasRun.current = true;

    async function run() {
      try {
        /* =====================================================
           ASYNC / XAFPAY GUARD
           ===================================================== */

        if (isAsync) {
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
        }

        /* =====================================================
           FRESH ORDER LOOKUP

           Purpose:
           - Get created_by_user_id / created_by_name / served_by_name
           - This is commission-safe because it refers to the person who
             created the order, not the cashier who later settled payment.
        ===================================================== */

        let freshOrder: any = null;

        if (orderId && Number(orderId) > 0 && !isManual) {
          try {
            freshOrder = await apiFetch(`/orders/${orderId}`, {
              cache: "no-store",
            });

            console.log("XBOS settlement fresh order object:", freshOrder);
          } catch (orderError) {
            console.warn(
              "[XBOS] Could not fetch fresh order for receipt author fields:",
              orderError
            );
          }
        }

        const locationOrder =
          location.state?.order ||
          location.state?.selectedOrder ||
          location.state?.pendingOrder ||
          null;

        const servedByName = firstText(
          freshOrder?.served_by_name,
          freshOrder?.created_by_name,
          freshOrder?.order_created_by_name,

          locationOrder?.served_by_name,
          locationOrder?.created_by_name,
          locationOrder?.order_created_by_name,

          location.state?.served_by_name,
          location.state?.created_by_name,
          location.state?.order_created_by_name,

          builderReceiptMeta?.served_by_name,
          builderReceiptMeta?.created_by_name,
          builderReceiptMeta?.order_created_by_name,
          builderReceiptMeta?.waiter_name,
          builderReceiptMeta?.staff_name,
          builderReceiptMeta?.cashier_name
        );

        const orderCreatedByName = firstText(
          freshOrder?.created_by_name,
          freshOrder?.served_by_name,
          freshOrder?.order_created_by_name,

          locationOrder?.created_by_name,
          locationOrder?.served_by_name,
          locationOrder?.order_created_by_name,

          location.state?.created_by_name,
          location.state?.served_by_name,
          location.state?.order_created_by_name,

          builderReceiptMeta?.order_created_by_name,
          builderReceiptMeta?.created_by_name,
          builderReceiptMeta?.served_by_name
        );

        const orderCreatedByUserId = firstValue(
          freshOrder?.created_by_user_id,
          freshOrder?.order_created_by_user_id,

          locationOrder?.created_by_user_id,
          locationOrder?.order_created_by_user_id,

          location.state?.created_by_user_id,
          location.state?.order_created_by_user_id,

          builderReceiptMeta?.created_by_user_id,
          builderReceiptMeta?.order_created_by_user_id
        );

        console.log("XBOS receipt served_by_name:", servedByName);
        console.log("XBOS receipt order_created_by_name:", orderCreatedByName);
        console.log(
          "XBOS receipt order_created_by_user_id:",
          orderCreatedByUserId
        );

        /* =====================================================
           PAYMENT LINES
           Prefer location.state.lines.
           Fallback to cart splitPayments for legacy flows.
           ===================================================== */

        const storeState =
          typeof (useCartStore as any).getState === "function"
            ? (useCartStore as any).getState()
            : {};

        const stateLines = Array.isArray(location.state?.lines)
          ? location.state.lines
          : [];

        const storeLines = Array.isArray(storeState?.splitPayments)
          ? storeState.splitPayments
          : [];

        const rawLines = stateLines.length ? stateLines : storeLines;

        const lines = rawLines
          .map((p: any) => {
            const method = text(p?.method).toLowerCase();
            const amount = n(p?.amount);

            const meta = p?.meta && typeof p.meta === "object" ? p.meta : {};

            if (!method || amount <= 0) return null;

            return {
              method,
              amount,
              provider: p?.provider || null,
              meta: {
                ...meta,
                role: meta.role || "TENDERED",
                tendered: n(meta.tendered ?? meta.received ?? amount),
              },
            };
          })
          .filter(Boolean);

        if (!lines.length) {
          throw new Error("No valid payment lines provided");
        }

        /* =====================================================
           TOTALS

           Important:
           For Complete Balance / Settle Another Way, location.state.amount
           is the remaining amount to collect, so it must be allowed as
           gross/net fallback.
           ===================================================== */

        let tenderedTotal = 0;
        let paidAppliedTotal = 0;
        let unpaidLinesTotal = 0;

        const grossTotal = n(
          metaTotals.gross_total ??
            builderReceiptMeta.gross_total ??
            builderReceiptMeta.original_total ??
            location.state?.amount
        );

        const discountTotal = n(
          metaTotals.discount_total ??
            builderReceiptMeta.discount_total ??
            location.state?.discount
        );

        const complimentaryTotal = n(
          metaTotals.complimentary_total ??
            builderReceiptMeta.complimentary_total ??
            location.state?.complimentary
        );

        const netTotal = n(
          metaTotals.net_total ??
            builderReceiptMeta.net_total ??
            builderReceiptMeta.client_pays ??
            location.state?.amount ??
            Math.max(grossTotal - discountTotal - complimentaryTotal, 0)
        );

        for (const p of lines as any[]) {
          const method = p.method;
          const amount = n(p.amount);
          const meta = p.meta || {};
          const tag = text(meta.tag).toUpperCase();

          if (method === "unpaid") {
            unpaidLinesTotal += amount;
            continue;
          }

          const tendered = n(meta.tendered ?? meta.received ?? amount);
          tenderedTotal += tendered;

          if (tag === "CHANGE_OWED") {
            unpaidLinesTotal += amount;
          }
        }

        paidAppliedTotal = Math.min(netTotal, tenderedTotal);

        /* =====================================================
           CHANGE / TIP
        ===================================================== */

        const originalChange = n(
          location.state?.change_amount ??
            builderReceiptMeta?.change_amount ??
            Math.max(0, tenderedTotal - netTotal)
        );

        const changeGivenNow = n(
          location.state?.change_given_now ??
            builderReceiptMeta?.change_given_now ??
            originalChange
        );

        const tipAmount = n(
          location.state?.tip_amount ?? builderReceiptMeta?.tip_amount ?? 0
        );

        const changeRemaining = n(
          location.state?.change_remaining ??
            builderReceiptMeta?.change_remaining ??
            Math.max(0, originalChange - (changeGivenNow + tipAmount))
        );

        const unpaidAmount = Math.max(
          unpaidLinesTotal,
          Math.max(netTotal - paidAppliedTotal, 0)
        );

        /* =====================================================
           RECEIPT META NORMALIZATION
        ===================================================== */

        const normalizedDescription =
          text(builderReceiptMeta.description ?? descriptionFromState) ||
          "Payment";

        const normalizedCustomer =
          builderReceiptMeta.customer ?? customerFromState ?? null;

        const normalizedReference =
          text(builderReceiptMeta.reference ?? referenceFromState) || null;

        const normalizedItems =
          Array.isArray(builderReceiptMeta.items) &&
          builderReceiptMeta.items.length > 0
            ? builderReceiptMeta.items
            : [
                {
                  name: normalizedDescription,
                  quantity: 1,
                  unit_price: netTotal || paidAppliedTotal || tenderedTotal,
                  line_total: netTotal || paidAppliedTotal || tenderedTotal,
                },
              ];

        const priorReceiptMetaTotals =
          builderReceiptMeta?.totals &&
          typeof builderReceiptMeta.totals === "object"
            ? builderReceiptMeta.totals
            : {};

        const finalReceiptMeta = {
          ...builderReceiptMeta,

          description: normalizedDescription,
          customer: normalizedCustomer,
          reference: normalizedReference,
          items: normalizedItems,

          gross_total: grossTotal,
          original_total: grossTotal,
          discount_total: discountTotal,
          complimentary_total: complimentaryTotal,
          net_total: netTotal,
          client_pays: netTotal,

          totals: {
            ...priorReceiptMetaTotals,
            gross_total: grossTotal,
            discount_total: discountTotal,
            complimentary_total: complimentaryTotal,
            net_total: netTotal,
            client_pays: netTotal,
          },

          paid_total: paidAppliedTotal,
          total_paid: paidAppliedTotal,
          unpaid_total: unpaidAmount,
          balance_due: unpaidAmount,
          tendered_total: tenderedTotal,

          change_amount: originalChange,
          change_given_now: changeGivenNow,
          change_remaining: changeRemaining,
          tip_amount: tipAmount,

          notes: text(location.state?.splitNote) || undefined,

          store_credit: false,
          store_credit_amount: 0,

          manual: isManual,
          payment_source: isStandalone ? "standalone" : "order",
          settlement_mode: "manual",

          existing_intent_id: existingIntentId || undefined,
          parent_intent_id: existingIntentId || undefined,
          complete_balance: isCompletingExistingIntent || undefined,
          settle_failed_intent: isSettlingFailedIntent || undefined,

          // =================================================
          // COMMISSION-SAFE ORDER AUTHOR / STAFF ATTRIBUTION
          // =================================================
          // These fields must represent the person who created
          // the original order, not necessarily the cashier who
          // processed payment.
          served_by_name: servedByName || undefined,
          order_created_by_name: orderCreatedByName || servedByName || undefined,
          created_by_name: orderCreatedByName || servedByName || undefined,

          order_created_by_user_id: orderCreatedByUserId || undefined,
          created_by_user_id: orderCreatedByUserId || undefined,

          order_id: orderId || undefined,
        };

        console.log("XBOS final settlement lines:", lines);
        console.log("XBOS final receipt_meta:", finalReceiptMeta);

        /* =====================================================
           SETTLEMENT

           Backend rule:
           - order payment: send order_id
           - standalone/direct-pay payment: order_id null
           - balance completion: send existing_intent_id so backend can
             apply a new attempt to the existing PaymentIntent
        ===================================================== */

        const clientReferencePrefix = isCompletingExistingIntent
          ? `balance:${existingIntentId}`
          : isSettlingFailedIntent
          ? `fallback:${existingIntentId}`
          : isManual
          ? "manual"
          : "pos";

        const settlement = await apiFetch("/payments/pos/settle", {
          method: "POST",
          body: JSON.stringify({
            order_id: isManual ? null : orderId,

            existing_intent_id: existingIntentId,
            parent_intent_id: existingIntentId,
            complete_balance: isCompletingExistingIntent,
            settle_failed_intent: isSettlingFailedIntent,

            client_reference: `${clientReferencePrefix}:${uuidv4()}`,

            lines,
            tendered_total: tenderedTotal,
            change_amount: originalChange,
            change_given_now: changeGivenNow,
            change_remaining: changeRemaining,
            tip_amount: tipAmount,
            unpaid_amount: unpaidAmount,

            receipt_meta: finalReceiptMeta,
          }),
        });

        const payableId = Number(
          settlement?.sale_id ?? settlement?.payable_id ?? 0
        );

        const intentId = settlement?.intent_id
          ? String(settlement.intent_id)
          : existingIntentId
          ? String(existingIntentId)
          : "";

        const saleId =
          !isManual && payableId > 0
            ? payableId
            : settlement?.sale_id
            ? Number(settlement.sale_id)
            : null;

        if (!isManual && saleId && saleId > 0) {
          safeSetSaleId(saleId);
        }

        safeClearSplitPayments();
        safeClearCart();

        try {
          sessionStorage.removeItem(ACTIVE_ORDER_ID_KEY);
        } catch {}

        const query = [
          "status=success",
          isManual ? "manual=true" : "",
          orderId ? `orderId=${orderId}` : "",
          saleId && saleId > 0 ? `saleId=${saleId}` : "",
          intentId ? `intentId=${encodeURIComponent(intentId)}` : "",
          isManual ? "payableType=manual" : "",
        ]
          .filter(Boolean)
          .join("&");

        navigate(`/result?${query}`, {
          replace: true,
          state: {
            receipt_meta: finalReceiptMeta,

            settlement,
            manual: isManual,
            payment_source: isStandalone ? "standalone" : "order",

            existing_intent_id: existingIntentId || undefined,
            parent_intent_id: existingIntentId || undefined,
            complete_balance: isCompletingExistingIntent || undefined,
            settle_failed_intent: isSettlingFailedIntent || undefined,

            order_id: orderId || undefined,
            sale_id: saleId || undefined,
            intent_id: intentId || undefined,

            payable_type: settlement?.payable_type,
            payable_id: settlement?.payable_id,

            total_paid: paidAppliedTotal,
            tendered_total: tenderedTotal,
            change_given_now: changeGivenNow,
            change_remaining: changeRemaining,
            tip_amount: tipAmount,
            unpaid_amount: unpaidAmount,
            balance_due: unpaidAmount,

            // Keep staff attribution available to ResultScreen even
            // if it bypasses receipt_meta in some rendering path.
            served_by_name: servedByName || undefined,
            order_created_by_name:
              orderCreatedByName || servedByName || undefined,
            created_by_name: orderCreatedByName || servedByName || undefined,
            order_created_by_user_id: orderCreatedByUserId || undefined,
            created_by_user_id: orderCreatedByUserId || undefined,
          },
        });
      } catch (err: any) {
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
      }
    }

    run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function refreshCheckoutProjection() {
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

  async function cancelXafpayPayment() {
    if (!checkoutAttemptId || xafpayCancelling) return;
    setXafpayCancelling(true); setXafpayCancelResult(null);
    try {
      const response = await requestXafpayCancellation(checkoutAttemptId);
      setXafpayCancelResult(String(response?.message || "Cancellation is not yet confirmed."));
      await refreshCheckoutProjection();
    } finally { setXafpayCancelling(false); }
  }

  function returnToRecoverySurface() {
    const paymentRecordId = String(
      checkoutProjection?.payment_record_id ||
      xafpayInitiationIssue?.payment_record_id ||
      ""
    );
    if (paymentRecordId) registerXafpayOutcomeWatch(paymentRecordId);
    navigate(
      paymentRecordId
        ? `/payments?tab=records&paymentId=${encodeURIComponent(paymentRecordId)}`
        : "/payments",
      { replace: true }
    );
  }

  function leaveConfirmationPending() {
    setCheckoutUrl("");
    const paymentRecordId = String(checkoutProjection?.payment_record_id || "");
    if (paymentRecordId) registerXafpayOutcomeWatch(paymentRecordId);
    navigate(paymentRecordId ? `/payments?paymentId=${encodeURIComponent(paymentRecordId)}` : "/payments", { replace: true });
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
          {!preSubmission && !succeeded && !failed && <div className="border-t p-3"><button type="button" className="rounded-lg border border-red-700 px-3 py-2 text-sm font-semibold text-red-800" disabled={xafpayCancelling} onClick={cancelXafpayPayment}>{xafpayCancelling ? "Cancelling..." : "Cancel XafPay payment"}</button>{xafpayCancelResult && <p role="status" aria-live="polite" className="mt-2 rounded-lg bg-red-50 p-2 text-sm font-semibold text-red-900">{xafpayCancelResult}</p>}</div>}
          {succeeded && <button type="button" className="m-3 rounded-xl bg-emerald-700 px-4 py-3 font-bold text-white" onClick={() => navigate(`/result?saleId=${checkoutProjection.sale_id}`, { replace: true })}>View receipt / Continue</button>}
          {failed && <button type="button" className="m-3 rounded-xl bg-emerald-700 px-4 py-3 font-bold text-white" onClick={returnFailedAttemptToPayment}>Return to payment</button>}
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-[calc(100vh-7.5rem)] flex-col items-center justify-center gap-6">
      <div className="h-16 w-16 animate-spin rounded-full border-4 border-emerald-600 border-t-transparent" />

      <p className="text-lg font-semibold">
        {isInvoice
          ? "Generating invoice…"
          : isManual
          ? isCompletingExistingIntent
            ? "Completing balance…"
            : "Processing payment…"
          : "Processing order…"}
      </p>

      <p className="text-sm opacity-70">Please do not close this screen</p>
    </div>
  );
}
