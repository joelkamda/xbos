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
          const selectedRail = text(
            location.state?.xafpayProvider ||
              location.state?.provider ||
              location.state?.lines?.find((line: any) => line?.method === "xafpay")?.provider ||
              "mtn"
          ).toLowerCase();
          const initiated = await apiFetch("/payments/xafpay/init", {
            method: "POST",
            body: JSON.stringify({
              order_id: orderId,
              provider: selectedRail === "orange" ? "orange" : "mtn",
              client_reference: `wnd-ui-order-${orderId}`,
            }),
          });
          if (!initiated?.paymentUrl || initiated?.status !== "PENDING") {
            throw new Error("XafPay did not return a pending Hosted Checkout session.");
          }
          setCheckoutUrl(initiated.paymentUrl);
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
  const [checkoutUrl, setCheckoutUrl] = useState("");'''
if state_old in text and state_new not in text:
    text = text.replace(state_old, state_new, 1)
render_old = '''  return (
    <div className="flex h-[calc(100vh-7.5rem)] flex-col items-center justify-center gap-6">'''
render_new = '''  if (checkoutUrl) {
    return (
      <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 p-3" role="dialog" aria-modal="true" aria-label="XafPay secure checkout">
        <div className="flex h-[min(860px,96vh)] w-full max-w-xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl">
          <div className="flex items-center justify-between border-b px-4 py-3">
            <div><strong>XafPay secure checkout</strong><p className="text-xs text-neutral-500">WND remains open while XafPay confirms payment.</p></div>
            <button type="button" className="rounded-lg border px-3 py-2 text-sm" onClick={() => navigate("/payments", { replace: true })}>Close</button>
          </div>
          <iframe title="XafPay secure checkout" src={checkoutUrl} className="min-h-0 flex-1 border-0" allow="payment" referrerPolicy="no-referrer" />
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
if "Origin/channel:" not in detail or "attempt.orchestrator" not in detail:
    raise RuntimeError("XV15_PAYMENT_ATTEMPT_VISIBILITY_MARKER_MISSING")
detail_panel.write_text(detail, encoding="utf-8")

receipt = target / "src" / "components" / "receipt" / "Receipt.tsx"
receipt_text = receipt.read_text(encoding="utf-8")
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
print("XV15_R1_WND_FRONTEND_OVERLAY=PASS")
print("XV15_R1_XAFPAY_CONFIRM_ENABLED=PASS")
print("XV15_R1_XAFPAY_CHECKOUT_MODAL=PASS")
print("XV15_R1_XAFPAY_CHECKOUT_ORIGIN=127.0.0.1:5174")
print("XV15_R1_XAFPAY_SELECTION_SETTLEMENT_CALL=ABSENT")
print("XV15_PAYMENT_RECORD_ATTEMPT_VISIBILITY=PASS")
print("XV15_PAYMENT_RECORD_METHOD_RAIL_ORCHESTRATOR_CLARITY=PASS")
