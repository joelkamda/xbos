import { apiFetch } from "./api";

type WatchedPayment = { paymentId: string; lastState?: string };
const STORAGE_KEY = "xv15_xafpay_watched_payments";
const TERMINAL = new Set(["COMPLETED", "FAILED", "EXPIRED", "CANCELLED", "CANCELED"]);

function read(): WatchedPayment[] {
  try {
    const value = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
    return Array.isArray(value) ? value.filter((x) => x && typeof x.paymentId === "string") : [];
  } catch { return []; }
}
function write(value: WatchedPayment[]) { localStorage.setItem(STORAGE_KEY, JSON.stringify(value)); }

export function registerXafpayOutcomeWatch(paymentId: string) {
  if (!paymentId) return;
  const current = read();
  if (!current.some((x) => x.paymentId === paymentId)) write([...current, { paymentId }]);
}

export function readXafpayOutcomeWatches() { return read(); }
export function removeXafpayOutcomeWatch(paymentId: string) { write(read().filter((x) => x.paymentId !== paymentId)); }

export async function checkWatchedPayment(paymentId: string) {
  const result = await apiFetch(`/payments/${encodeURIComponent(paymentId)}`, { cache: "no-store" });
  const attempts = Array.isArray(result?.attempts) ? result.attempts : [];
  const xafpayAttempts = attempts.filter((attempt: any) =>
    String(attempt?.orchestrator || attempt?.provider || "").toLowerCase() === "xafpay"
  );
  const latestXafpay = xafpayAttempts[xafpayAttempts.length - 1];
  const state = String(latestXafpay?.status || result?.status || "").toUpperCase();
  if (!TERMINAL.has(state)) return { terminal: false, result };
  removeXafpayOutcomeWatch(paymentId);
  window.dispatchEvent(new CustomEvent("xv15:payment-terminal", { detail: { paymentId, state, result } }));
  return { terminal: true, state, result };
}

export const XAFPAY_WATCH_INTERVAL_MS = 10_000;
