import { useEffect, useMemo, useRef, useState } from "react";
import { apiFetch } from "../../../lib/api";

export type PaymentActivityItem = {
  id: string;
  source: "treasury_event" | "payment_intent" | string;
  source_id: number;
  activity_type: string;
  event_type: string;
  status: string;
  flow: "in" | "out" | "transfer" | "attention" | string;
  amount: number;
  currency: string;
  channel: string;
  reference?: string | null;
  detail?: string | null;
  occurred_at?: string | null;
  document_type?: string | null;
  recovery?: { attempt_public_id: string; order_id: number; sale_id: number; payment_record_id: string; rail?: string | null; orchestrator: string } | null;
};

export type PaymentActivitySummary = {
  received: number;
  paid_out: number;
  transferred: number;
  attention: number;
};

export type PaymentActivityWindow = {
  label: string;
  timezone: string;
  start: string;
  end: string;
};

const EMPTY_SUMMARY: PaymentActivitySummary = {
  received: 0,
  paid_out: 0,
  transferred: 0,
  attention: 0,
};

type ActivityRuntimeCache = {
  items: PaymentActivityItem[];
  summary: PaymentActivitySummary;
  windowInfo: PaymentActivityWindow | null;
};
const activityRuntime = globalThis as typeof globalThis & {
  __xv15ActivityCache?: ActivityRuntimeCache | null;
};
const activityCache = activityRuntime.__xv15ActivityCache;

export function usePaymentActivity(enabled = true) {
  const [items, setItems] = useState<PaymentActivityItem[]>(() => activityCache?.items ?? []);
  const [summary, setSummary] =
    useState<PaymentActivitySummary>(() => activityCache?.summary ?? EMPTY_SUMMARY);
  const [windowInfo, setWindowInfo] =
    useState<PaymentActivityWindow | null>(() => activityCache?.windowInfo ?? null);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const loadedRef = useRef(activityRuntime.__xv15ActivityCache !== undefined);
  const inFlightRef = useRef(false);

  async function loadActivity() {
    if (!enabled || inFlightRef.current) return;
    inFlightRef.current = true;

    try {
      setLoading(true);
      setError(null);

      const data = await apiFetch("/payments/activity?limit=100");
      loadedRef.current = true;
      activityRuntime.__xv15ActivityCache = {
        items: Array.isArray(data?.items) ? data.items : [],
        summary: {
          received: Number(data?.summary?.received ?? 0),
          paid_out: Number(data?.summary?.paid_out ?? 0),
          transferred: Number(data?.summary?.transferred ?? 0),
          attention: Number(data?.summary?.attention ?? 0),
        },
        windowInfo: data?.window ?? null,
      };
      setItems(activityRuntime.__xv15ActivityCache.items);
      setSummary(activityRuntime.__xv15ActivityCache.summary);
      setWindowInfo(activityRuntime.__xv15ActivityCache.windowInfo);
    } catch (err: any) {
      console.error("Failed to load Payments activity:", err);
      setError(err?.message || "Could not load money activity.");
      setItems([]);
      setSummary(EMPTY_SUMMARY);
      setWindowInfo(null);
    } finally {
      inFlightRef.current = false;
      setLoading(false);
    }
  }

  useEffect(() => {
    if (enabled && !loadedRef.current) loadActivity();
  }, [enabled]);

  useEffect(() => {
    const onTerminal = () => {
      if (activityRuntime.__xv15ActivityCache) activityRuntime.__xv15ActivityCache.items = [];
      loadedRef.current = false;
      if (enabled) void loadActivity();
    };
    window.addEventListener("xv15:payment-terminal", onTerminal);
    return () => window.removeEventListener("xv15:payment-terminal", onTerminal);
  }, [enabled]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;

    return items.filter((item) =>
      [
        item.activity_type,
        item.event_type,
        item.status,
        item.channel,
        item.reference,
        item.detail,
        item.amount,
        item.source_id,
      ]
        .join(" ")
        .toLowerCase()
        .includes(q)
    );
  }, [items, query]);

  return {
    items,
    filtered,
    summary,
    windowInfo,
    query,
    setQuery,
    loading,
    error,
    loadActivity,
  };
}
