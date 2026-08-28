import { useEffect, useMemo, useRef, useState } from "react";
import { apiFetch } from "../../../lib/api";
import type { Payment, PaymentKpiSummary } from "../types";
import { normalizePayments } from "../utils/paymentNormalizers";

type PaymentsRuntimeCache = { payments: Payment[] | null };
const runtime = globalThis as typeof globalThis & {
  __xv15PaymentsCache?: PaymentsRuntimeCache;
};
const paymentsRuntimeCache =
  (runtime.__xv15PaymentsCache ??= { payments: null });

export function usePayments(enabled = true) {
  const [payments, setPayments] = useState<Payment[]>(
    () => paymentsRuntimeCache.payments ?? []
  );
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const loadedRef = useRef(paymentsRuntimeCache.payments !== null);

  async function loadPayments() {
    try {
      setLoading(true);

      // IMPORTANT:
      // Keep the trailing slash.
      // Backend route is /kernel/payments/
      // Calling /payments causes a 307 redirect to /payments/,
      // and the redirected browser request may lose Authorization.
      const raw = await apiFetch("/payments/");

      const normalized = normalizePayments(raw);

      setPayments(normalized);
      loadedRef.current = true;
      paymentsRuntimeCache.payments = normalized;

      setSelectedId((prev) => {
        const requested = new URLSearchParams(window.location.search).get("paymentId");
        if (requested && normalized.some((p) => p.id === requested)) return requested;
        if (prev && normalized.some((p) => p.id === prev)) return prev;
        return normalized[0]?.id ?? null;
      });
    } catch (error) {
      console.error("Failed to load payments:", error);
      setPayments([]);
      setSelectedId(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (enabled && !loadedRef.current) loadPayments();
  }, [enabled]);

  useEffect(() => {
    const onTerminal = () => {
      paymentsRuntimeCache.payments = null;
      loadedRef.current = false;
      if (enabled) void loadPayments();
    };
    window.addEventListener("xv15:payment-terminal", onTerminal);
    return () => window.removeEventListener("xv15:payment-terminal", onTerminal);
  }, [enabled]);

  const filtered = useMemo(() => {
    if (!query.trim()) return payments;

    const q = query.toLowerCase();

    return payments.filter((p) =>
      [
        p.customer_name ?? "",
        p.sale_id ?? "",
        p.method ?? "",
        p.status ?? "",
        p.provider ?? "",
        p.phone ?? "",
        p.payable_type ?? "",
        p.payable_id ?? "",
      ]
        .join(" ")
        .toLowerCase()
        .includes(q)
    );
  }, [payments, query]);

  const selected =
    filtered.find((p) => p.id === selectedId) ??
    payments.find((p) => p.id === selectedId) ??
    null;

  const kpis: PaymentKpiSummary = useMemo(() => {
    const total = payments.length;

    const completed = payments.filter(
      (p) => p.status === "COMPLETED"
    ).length;

    const pending = payments.filter(
      (p) => p.status === "PENDING"
    ).length;

    const failed = payments.filter(
      (p) => p.status === "FAILED"
    ).length;

    return {
      total,
      completed,
      pending,
      failed,
    };
  }, [payments]);

  return {
    payments,
    filtered,
    selected,
    selectedId,
    setSelectedId,
    query,
    setQuery,
    kpis,
    loading,
    loadPayments,
  };
}
