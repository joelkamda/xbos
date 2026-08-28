import { useEffect, useMemo, useState } from "react";

import { apiFetch } from "../../../lib/api";
import { useSessionStore } from "../../../lib/store/session";
import { money } from "../utils/money";
import {
  fetchIncomeTaxonomy,
  fetchExpenseTaxonomyTree,
  createManualIncome,
  createExpense,
  createCashMovement,
  type SettlementChannel,
} from "../../../api/accounting";
import OperationDocumentCard, {
  type OperationDocument,
} from "./OperationDocumentCard";

type Operation = "receive" | "pay" | "transfer";
type ReceiveMode = "income" | "ar";

type TaxonomyNode = {
  id: number;
  name?: string;
  label?: string;
  subcategories?: TaxonomyNode[];
};

type TaxonomyTree = {
  categories?: TaxonomyNode[];
};

type Receivable = {
  id: number;
  sale_id?: string | number | null;
  customer_name?: string | null;
  customer_phone?: string | null;
  original_amount?: number | string | null;
  paid_amount?: number | string | null;
  balance_due?: number | string | null;
  status?: string | null;
  reference?: string | null;
};

const CHANNELS = [
  { value: "cash", label: "Cash" },
  { value: "mtn", label: "MTN MoMo" },
  { value: "orange", label: "Orange Money" },
  { value: "xafpay", label: "XafPay" },
  { value: "bank", label: "Bank" },
] as const;

const inputClass =
  "w-full rounded-xl border border-neutral-200 bg-white px-3 py-2.5 text-sm text-neutral-900 outline-none transition focus:border-emerald-400 focus:ring-2 focus:ring-emerald-100 disabled:cursor-not-allowed disabled:bg-neutral-100";

const labelClass =
  "mb-1 block text-[10px] font-black uppercase tracking-[0.08em] text-neutral-500";

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

function nodeName(node?: TaxonomyNode | null) {
  return node?.name || node?.label || (node ? `#${node.id}` : "");
}

function numberValue(value: string | number | null | undefined) {
  const parsed = Number(value ?? 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

function makeClientReference(prefix: string) {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

function FieldLabel({ children }: { children: React.ReactNode }) {
  return <label className={labelClass}>{children}</label>;
}

function EffectRow({
  label,
  value,
  emphasis = false,
}: {
  label: string;
  value: string;
  emphasis?: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-4 py-1 text-xs">
      <span className="text-neutral-500">{label}</span>
      <span
        className={
          emphasis
            ? "font-black text-neutral-950"
            : "font-bold text-neutral-800"
        }
      >
        {value}
      </span>
    </div>
  );
}

export default function StandalonePaymentBuilder({
  onPosted,
}: {
  onPosted?: () => void | Promise<void>;
}) {
  const authUser = useSessionStore((s) => s.authUser);
  const session = useSessionStore((s) => s.session);
  const userPermissions = authUser?.permissions ?? session?.permissions ?? [];

  const role = authUser?.role ?? session?.role;
  const canReceive = hasAnyPermission(userPermissions, ["payments.receive"], role);
  const canSend = hasAnyPermission(userPermissions, ["payments.send"], role);

  const [operation, setOperation] = useState<Operation>(
    canReceive ? "receive" : canSend ? "pay" : "receive"
  );
  const [receiveMode, setReceiveMode] = useState<ReceiveMode>("income");

  const [incomeTaxonomy, setIncomeTaxonomy] = useState<TaxonomyTree | null>(null);
  const [expenseTaxonomy, setExpenseTaxonomy] =
    useState<TaxonomyTree | null>(null);
  const [loadingReferenceData, setLoadingReferenceData] = useState(false);
  const [referenceError, setReferenceError] = useState<string | null>(null);

  const [arQuery, setArQuery] = useState("");
  const [receivables, setReceivables] = useState<Receivable[]>([]);
  const [receivableId, setReceivableId] = useState<number | null>(null);
  const [arSearching, setArSearching] = useState(false);

  const [amount, setAmount] = useState("");
  const [channel, setChannel] = useState("cash");

  const [incomeCategoryId, setIncomeCategoryId] = useState<number | null>(null);
  const [incomeSubcategoryId, setIncomeSubcategoryId] =
    useState<number | null>(null);
  const [incomeItem, setIncomeItem] = useState("");
  const [sourceName, setSourceName] = useState("");

  const [expenseCategoryId, setExpenseCategoryId] =
    useState<number | null>(null);
  const [expenseSubcategoryId, setExpenseSubcategoryId] =
    useState<number | null>(null);
  const [expenseItem, setExpenseItem] = useState("");
  const [vendor, setVendor] = useState("");
  const [receiptRef, setReceiptRef] = useState("");

  const [sourceChannel, setSourceChannel] = useState("cash");
  const [targetChannel, setTargetChannel] = useState("mtn");

  const [reference, setReference] = useState("");
  const [note, setNote] = useState("");

  const [posting, setPosting] = useState(false);
  const [postError, setPostError] = useState<string | null>(null);
  const [documentData, setDocumentData] =
    useState<OperationDocument | null>(null);

  async function loadReferenceData() {
    setLoadingReferenceData(true);
    setReferenceError(null);

    try {
      const jobs: Promise<void>[] = [];

      if (canReceive) {
        jobs.push(
      fetchIncomeTaxonomy().then((data) => {
        setIncomeTaxonomy(data as TaxonomyTree);
          })
        );
      }

      if (canSend) {
        jobs.push(
      fetchExpenseTaxonomyTree().then((data) => {
        setExpenseTaxonomy(data as TaxonomyTree);
          })
        );
      }

      await Promise.all(jobs);
    } catch (error: any) {
      setReferenceError(
        error?.message || "Could not load Payments reference data."
      );
    } finally {
      setLoadingReferenceData(false);
    }
  }

  async function searchReceivables(query = arQuery) {
    if (!canReceive) return;

    try {
      setArSearching(true);
      setReferenceError(null);

      const data = await apiFetch(
        `/payments/standalone/receivables/search?q=${encodeURIComponent(
          query.trim()
        )}&limit=25`
      );
      setReceivables(Array.isArray(data?.items) ? data.items : []);
    } catch (error: any) {
      setReceivables([]);
      setReferenceError(
        error?.message || "Could not search outstanding receivables."
      );
    } finally {
      setArSearching(false);
    }
  }

  useEffect(() => {
    loadReferenceData();
  }, [canReceive, canSend]);

  useEffect(() => {
    if (!canReceive && canSend && operation === "receive") {
      setOperation("pay");
    }
    if (!canSend && operation !== "receive") {
      setOperation("receive");
    }
  }, [canReceive, canSend, operation]);

  useEffect(() => {
    if (!canReceive || operation !== "receive" || receiveMode !== "ar") return;

    const timer = window.setTimeout(() => {
      searchReceivables(arQuery);
    }, 250);

    return () => window.clearTimeout(timer);
  }, [arQuery, canReceive, operation, receiveMode]);

  const incomeCategories = incomeTaxonomy?.categories ?? [];
  const expenseCategories = expenseTaxonomy?.categories ?? [];

  useEffect(() => {
    if (!incomeCategories.length) return;

    const validCategory = incomeCategories.some(
      (category) => category.id === incomeCategoryId
    );
    const nextCategory = validCategory
      ? incomeCategories.find((category) => category.id === incomeCategoryId)!
      : incomeCategories[0];

    if (nextCategory.id !== incomeCategoryId) {
      setIncomeCategoryId(nextCategory.id);
    }

    const subs = nextCategory.subcategories ?? [];
    if (
      subs.length &&
      !subs.some((subcategory) => subcategory.id === incomeSubcategoryId)
    ) {
      setIncomeSubcategoryId(subs[0].id);
    }
  }, [incomeCategories, incomeCategoryId, incomeSubcategoryId]);

  useEffect(() => {
    if (!expenseCategories.length) return;

    const validCategory = expenseCategories.some(
      (category) => category.id === expenseCategoryId
    );
    const nextCategory = validCategory
      ? expenseCategories.find((category) => category.id === expenseCategoryId)!
      : expenseCategories[0];

    if (nextCategory.id !== expenseCategoryId) {
      setExpenseCategoryId(nextCategory.id);
    }

    const subs = nextCategory.subcategories ?? [];
    if (
      subs.length &&
      !subs.some((subcategory) => subcategory.id === expenseSubcategoryId)
    ) {
      setExpenseSubcategoryId(subs[0].id);
    }
  }, [expenseCategories, expenseCategoryId, expenseSubcategoryId]);

  useEffect(() => {
    if (!receivables.length) {
      setReceivableId(null);
      return;
    }

    if (!receivables.some((item) => item.id === receivableId)) {
      setReceivableId(receivables[0].id);
    }
  }, [receivables, receivableId]);

  const selectedIncomeCategory = incomeCategories.find(
    (category) => category.id === incomeCategoryId
  );
  const incomeSubcategories = selectedIncomeCategory?.subcategories ?? [];
  const selectedIncomeSubcategory = incomeSubcategories.find(
    (subcategory) => subcategory.id === incomeSubcategoryId
  );

  const selectedExpenseCategory = expenseCategories.find(
    (category) => category.id === expenseCategoryId
  );
  const expenseSubcategories = selectedExpenseCategory?.subcategories ?? [];
  const selectedExpenseSubcategory = expenseSubcategories.find(
    (subcategory) => subcategory.id === expenseSubcategoryId
  );

  const selectedReceivable = receivables.find(
    (item) => item.id === receivableId
  );

  const numericAmount = numberValue(amount);
  const channelLabel =
    CHANNELS.find((item) => item.value === channel)?.label || channel;
  const sourceChannelLabel =
    CHANNELS.find((item) => item.value === sourceChannel)?.label ||
    sourceChannel;
  const targetChannelLabel =
    CHANNELS.find((item) => item.value === targetChannel)?.label ||
    targetChannel;

  const validationMessage = useMemo(() => {
    if (numericAmount <= 0) return "Enter an amount greater than zero.";

    if (operation === "receive" && receiveMode === "income") {
      if (!canReceive) return "Your role cannot receive money.";
      if (!incomeCategoryId || !incomeSubcategoryId) {
        return "Select an income category and subcategory.";
      }
      return null;
    }

    if (operation === "receive" && receiveMode === "ar") {
      if (!canReceive) return "Your role cannot receive money.";
      if (!receivableId) return "Find and select an unpaid bill.";
      if (
        selectedReceivable &&
        numericAmount > numberValue(selectedReceivable.balance_due)
      ) {
        return "Amount cannot exceed the selected A/R balance.";
      }
      return null;
    }

    if (operation === "pay") {
      if (!canSend) return "Your role cannot pay money.";
      if (!expenseCategoryId || !expenseSubcategoryId) {
        return "Select an expense category and subcategory.";
      }
      return null;
    }

    if (operation === "transfer") {
      if (!canSend) return "Your role cannot transfer money.";
      if (sourceChannel === targetChannel) {
        return "Source and destination must be different.";
      }
      return null;
    }

    return null;
  }, [
    numericAmount,
    operation,
    receiveMode,
    canReceive,
    canSend,
    incomeCategoryId,
    incomeSubcategoryId,
    receivableId,
    selectedReceivable,
    expenseCategoryId,
    expenseSubcategoryId,
    sourceChannel,
    targetChannel,
  ]);

  function resetEntry() {
    setAmount("");
    setReference("");
    setNote("");
    setIncomeItem("");
    setSourceName("");
    setExpenseItem("");
    setVendor("");
    setReceiptRef("");
    setPostError(null);
  }

  function makeDocument(
    title: string,
    trace: string,
    rows: Array<{ label: string; value: string }>,
    occurredAt?: string | null
  ): OperationDocument {
    return {
      title,
      trace,
      amount: numericAmount,
      currency: "XAF",
      occurredAt: occurredAt || new Date().toISOString(),
      rows,
    };
  }

  async function submit() {
    if (posting || validationMessage) return;

    setPosting(true);
    setPostError(null);
    setDocumentData(null);

    try {
      if (operation === "receive" && receiveMode === "income") {
        const clientReference = makeClientReference("payments-income");
        const response = await createManualIncome({
            amount: numericAmount,
            currency: "XAF",
            channel: channel as SettlementChannel,
            category_taxonomy_id: incomeCategoryId!,
            subcategory_taxonomy_id: incomeSubcategoryId!,
            item_mode: "free_text",
            atomic_unit_id: null,
            item_name:
              incomeItem.trim() ||
              nodeName(selectedIncomeSubcategory) ||
              "Standalone income",
            source_name: sourceName.trim() || null,
            reference: reference.trim() || null,
            note: note.trim() || null,
            client_reference: clientReference,
        });

        setDocumentData(
          makeDocument(
            "Income Receipt",
            clientReference,
            [
              { label: "Received into", value: channelLabel },
              {
                label: "Classification",
                value: `${nodeName(selectedIncomeCategory)} → ${nodeName(
                  selectedIncomeSubcategory
                )}`,
              },
              {
                label: "Item / description",
                value:
                  incomeItem.trim() ||
                  nodeName(selectedIncomeSubcategory) ||
                  "Income",
              },
              { label: "Source / customer", value: sourceName.trim() },
              { label: "Reference", value: reference.trim() },
              { label: "Note", value: note.trim() },
              { label: "Sale created", value: "No" },
            ],
            response.event?.occurred_at
          )
        );
      } else if (operation === "receive" && receiveMode === "ar") {
        if (!selectedReceivable) {
          throw new Error("Find and select an unpaid bill.");
        }

        const clientReference = makeClientReference("payments-ar");
        await apiFetch(`/accounting/accounts/ar/${receivableId}/repay`, {
          method: "POST",
          body: JSON.stringify({
            amount: numericAmount,
            payment_method: channel,
            reference: reference.trim() || null,
            note: note.trim() || null,
            client_reference: clientReference,
          }),
        });

        setDocumentData(
          makeDocument("A/R Payment Receipt", clientReference, [
            {
              label: "Bill / sale",
              value: selectedReceivable.sale_id
                ? `Sale #${selectedReceivable.sale_id}`
                : "—",
            },
            {
              label: "Customer",
              value: selectedReceivable.customer_name || "—",
            },
            { label: "A/R account", value: `A/R #${selectedReceivable.id}` },
            { label: "Received into", value: channelLabel },
            { label: "Reference", value: reference.trim() },
            { label: "Note", value: note.trim() },
            { label: "New income", value: "0 XAF" },
          ])
        );

        await searchReceivables(arQuery);
      } else if (operation === "pay") {
        const clientReference = makeClientReference("payments-expense");
        const response = await createExpense({
            amount: numericAmount,
            currency: "XAF",
            channel,
            category_taxonomy_id: expenseCategoryId,
            subcategory_taxonomy_id: expenseSubcategoryId,
            item_mode: "free_text",
            atomic_unit_id: null,
            item_name:
              expenseItem.trim() ||
              nodeName(selectedExpenseSubcategory) ||
              "Standalone expense",
            vendor: vendor.trim() || null,
            receipt_ref: receiptRef.trim() || null,
            reference: reference.trim() || null,
            note: note.trim() || null,
            client_reference: clientReference,
        });

        setDocumentData(
          makeDocument(
            "Payment Voucher",
            clientReference,
            [
              { label: "Paid from", value: channelLabel },
              {
                label: "Classification",
                value: `${nodeName(selectedExpenseCategory)} → ${nodeName(
                  selectedExpenseSubcategory
                )}`,
              },
              {
                label: "Expense item",
                value:
                  expenseItem.trim() ||
                  nodeName(selectedExpenseSubcategory) ||
                  "Expense",
              },
              { label: "Vendor", value: vendor.trim() },
              { label: "Receipt / voucher ref", value: receiptRef.trim() },
              { label: "Reference", value: reference.trim() },
              { label: "Note", value: note.trim() },
            ],
            response?.event?.occurred_at
          )
        );
      } else if (operation === "transfer") {
        const clientReference = makeClientReference("payments-transfer");
        const response = await createCashMovement({
            amount: numericAmount,
            currency: "XAF",
            source_channel: sourceChannel,
            target_channel: targetChannel,
            reason: note.trim() || null,
            reference: reference.trim() || null,
            client_reference: clientReference,
        });

        setDocumentData(
          makeDocument(
            "Transfer Slip",
            clientReference,
            [
              { label: "From", value: sourceChannelLabel },
              { label: "To", value: targetChannelLabel },
              { label: "Reference", value: reference.trim() },
              { label: "Reason", value: note.trim() },
              { label: "P&L effect", value: "0 XAF" },
            ],
            response?.event?.occurred_at
          )
        );
      }

      resetEntry();
      await onPosted?.();
    } catch (error: any) {
      setPostError(error?.message || "The money operation could not be posted.");
    } finally {
      setPosting(false);
    }
  }

  const operationButton = (
    key: Operation,
    label: string,
    symbol: string,
    disabled: boolean
  ) => {
    const active = operation === key;
    return (
      <button
        key={key}
        type="button"
        disabled={disabled}
        onClick={() => {
          setOperation(key);
          setPostError(null);
          setDocumentData(null);
        }}
        className={`flex-1 rounded-xl px-2.5 py-1.5 text-left transition ring-1 ${
          active
            ? "bg-emerald-700 text-white ring-emerald-700 shadow-sm"
            : disabled
            ? "cursor-not-allowed bg-neutral-100 text-neutral-400 ring-neutral-200"
            : "bg-white text-neutral-800 ring-neutral-200 hover:bg-neutral-50"
        }`}
      >
        <div className="text-sm font-black">{symbol}</div>
        <div className="text-xs font-black">{label}</div>
      </button>
    );
  };

  return (
    <div className="rounded-2xl bg-white p-3 shadow-sm ring-1 ring-neutral-200">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-sm font-black text-neutral-950">Money Desk</div>
          <div className="mt-0.5 text-[11px] font-semibold leading-4 text-neutral-500">
            Receive, pay or transfer money with the accounting effect shown
            before posting.
          </div>
        </div>

        <button
          type="button"
          onClick={() => {
            loadReferenceData();
            if (operation === "receive" && receiveMode === "ar") {
              searchReceivables(arQuery);
            }
          }}
          disabled={loadingReferenceData}
          className="shrink-0 rounded-xl bg-neutral-100 px-3 py-2 text-xs font-bold text-neutral-700 hover:bg-neutral-200 disabled:cursor-not-allowed disabled:text-neutral-400"
        >
          {loadingReferenceData ? "Loading..." : "Reload"}
        </button>
      </div>

      <div className="mt-3 flex gap-1.5">
        {operationButton("receive", "Receive", "+", !canReceive)}
        {operationButton("pay", "Pay", "−", !canSend)}
        {operationButton("transfer", "Transfer", "⇄", !canSend)}
      </div>

      {referenceError && (
        <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-semibold text-amber-800">
          {referenceError}
        </div>
      )}

      {operation === "receive" && (
        <div className="mt-3 flex rounded-xl bg-neutral-100 p-1">
          {(["income", "ar"] as ReceiveMode[]).map((mode) => (
            <button
              key={mode}
              type="button"
              onClick={() => {
                setReceiveMode(mode);
                setPostError(null);
                setDocumentData(null);
              }}
              className={`flex-1 rounded-lg px-3 py-1.5 text-xs font-black transition ${
                receiveMode === mode
                  ? "bg-white text-emerald-800 shadow-sm"
                  : "text-neutral-500 hover:text-neutral-800"
              }`}
            >
              {mode === "income" ? "Income" : "Accounts Receivable"}
            </button>
          ))}
        </div>
      )}

      <div className="mt-3">
        <FieldLabel>Amount</FieldLabel>
        <div className="relative">
          <input
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
            inputMode="decimal"
            placeholder="0"
            className="w-full rounded-xl border border-neutral-200 bg-neutral-50 px-3 py-2.5 pr-14 text-xl font-black tracking-tight text-neutral-950 outline-none transition focus:border-emerald-400 focus:ring-2 focus:ring-emerald-100"
          />
          <span className="absolute right-4 top-1/2 -translate-y-1/2 text-xs font-black text-neutral-400">
            XAF
          </span>
        </div>
      </div>

      {operation === "receive" && receiveMode === "income" && (
        <div className="mt-3 space-y-2">
          <div className="grid gap-2 sm:grid-cols-2">
            <div>
              <FieldLabel>Receive into</FieldLabel>
              <select
                value={channel}
                onChange={(event) => setChannel(event.target.value)}
                className={inputClass}
              >
                {CHANNELS.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <FieldLabel>Income category</FieldLabel>
              <select
                value={incomeCategoryId ?? ""}
                onChange={(event) => {
                  const nextId = Number(event.target.value);
                  setIncomeCategoryId(nextId);
                  const category = incomeCategories.find(
                    (item) => item.id === nextId
                  );
                  setIncomeSubcategoryId(
                    category?.subcategories?.[0]?.id ?? null
                  );
                }}
                className={inputClass}
              >
                {incomeCategories.map((category) => (
                  <option key={category.id} value={category.id}>
                    {nodeName(category)}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="grid gap-2 sm:grid-cols-2">
            <div>
              <FieldLabel>Subcategory</FieldLabel>
              <select
                value={incomeSubcategoryId ?? ""}
                onChange={(event) =>
                  setIncomeSubcategoryId(Number(event.target.value))
                }
                className={inputClass}
              >
                {incomeSubcategories.map((subcategory) => (
                  <option key={subcategory.id} value={subcategory.id}>
                    {nodeName(subcategory)}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <FieldLabel>Item / description</FieldLabel>
              <input
                value={incomeItem}
                onChange={(event) => setIncomeItem(event.target.value)}
                placeholder={nodeName(selectedIncomeSubcategory) || "Income item"}
                className={inputClass}
              />
            </div>
          </div>

          <div>
            <FieldLabel>Source / customer</FieldLabel>
            <input
              value={sourceName}
              onChange={(event) => setSourceName(event.target.value)}
              placeholder="Optional"
              className={inputClass}
            />
          </div>

          <div className="rounded-xl bg-blue-50 px-3 py-2 text-[11px] font-semibold leading-4 text-blue-800 ring-1 ring-blue-100">
            Manual income classification. No sale is created by this operation.
          </div>
        </div>
      )}

      {operation === "receive" && receiveMode === "ar" && (
        <div className="mt-3 space-y-2">
          <div>
            <FieldLabel>Find unpaid bill</FieldLabel>
            <div className="relative">
              <input
                value={arQuery}
                onChange={(event) => setArQuery(event.target.value)}
                placeholder="Bill #, customer, phone, reference, A/R #"
                className={inputClass}
              />
              {arSearching && (
                <span className="absolute right-3 top-1/2 -translate-y-1/2 text-[10px] font-black text-neutral-400">
                  SEARCHING
                </span>
              )}
            </div>
          </div>

          <div>
            <FieldLabel>Outstanding receivable</FieldLabel>
            <select
              value={receivableId ?? ""}
              onChange={(event) => setReceivableId(Number(event.target.value))}
              className={inputClass}
              disabled={!receivables.length}
            >
              {!receivables.length && (
                <option value="">No matching open receivable</option>
              )}
              {receivables.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.sale_id ? `Sale #${item.sale_id}` : `A/R #${item.id}`}
                  {item.customer_name ? ` · ${item.customer_name}` : ""}
                  {` · ${money(numberValue(item.balance_due))} due`}
                </option>
              ))}
            </select>
          </div>

          {selectedReceivable && (
            <div className="rounded-2xl bg-neutral-50 p-3 ring-1 ring-neutral-100">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <div className="text-sm font-black text-neutral-950">
                    {selectedReceivable.sale_id
                      ? `Sale #${selectedReceivable.sale_id}`
                      : `A/R #${selectedReceivable.id}`}
                    {selectedReceivable.customer_name
                      ? ` · ${selectedReceivable.customer_name}`
                      : ""}
                  </div>
                  <div className="mt-1 text-[10px] font-black uppercase tracking-wide text-neutral-400">
                    A/R #{selectedReceivable.id} ·{" "}
                    {String(selectedReceivable.status || "open")}
                  </div>
                </div>

                <button
                  type="button"
                  onClick={() =>
                    setAmount(String(numberValue(selectedReceivable.balance_due)))
                  }
                  className="rounded-xl bg-emerald-700 px-3 py-2 text-xs font-black text-white hover:bg-emerald-800"
                >
                  Pay full {money(numberValue(selectedReceivable.balance_due))}
                </button>
              </div>

              <div className="mt-2 grid gap-2 text-xs sm:grid-cols-3">
                <div>
                  <div className="font-bold text-neutral-400">Original</div>
                  <div className="mt-0.5 font-black text-neutral-800">
                    {money(numberValue(selectedReceivable.original_amount))}
                  </div>
                </div>
                <div>
                  <div className="font-bold text-neutral-400">Paid</div>
                  <div className="mt-0.5 font-black text-neutral-800">
                    {money(numberValue(selectedReceivable.paid_amount))}
                  </div>
                </div>
                <div>
                  <div className="font-bold text-neutral-400">Balance due</div>
                  <div className="mt-0.5 font-black text-amber-700">
                    {money(numberValue(selectedReceivable.balance_due))}
                  </div>
                </div>
              </div>
            </div>
          )}

          <div>
            <FieldLabel>Receive into</FieldLabel>
            <select
              value={channel}
              onChange={(event) => setChannel(event.target.value)}
              className={inputClass}
            >
              {CHANNELS.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </div>
        </div>
      )}

      {operation === "pay" && (
        <div className="mt-3 space-y-2">
          <div className="grid gap-2 sm:grid-cols-2">
            <div>
              <FieldLabel>Pay from</FieldLabel>
              <select
                value={channel}
                onChange={(event) => setChannel(event.target.value)}
                className={inputClass}
              >
                {CHANNELS.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <FieldLabel>Expense category</FieldLabel>
              <select
                value={expenseCategoryId ?? ""}
                onChange={(event) => {
                  const nextId = Number(event.target.value);
                  setExpenseCategoryId(nextId);
                  const category = expenseCategories.find(
                    (item) => item.id === nextId
                  );
                  setExpenseSubcategoryId(
                    category?.subcategories?.[0]?.id ?? null
                  );
                }}
                className={inputClass}
              >
                {expenseCategories.map((category) => (
                  <option key={category.id} value={category.id}>
                    {nodeName(category)}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="grid gap-2 sm:grid-cols-2">
            <div>
              <FieldLabel>Subcategory</FieldLabel>
              <select
                value={expenseSubcategoryId ?? ""}
                onChange={(event) =>
                  setExpenseSubcategoryId(Number(event.target.value))
                }
                className={inputClass}
              >
                {expenseSubcategories.map((subcategory) => (
                  <option key={subcategory.id} value={subcategory.id}>
                    {nodeName(subcategory)}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <FieldLabel>Expense item</FieldLabel>
              <input
                value={expenseItem}
                onChange={(event) => setExpenseItem(event.target.value)}
                placeholder={
                  nodeName(selectedExpenseSubcategory) || "Expense description"
                }
                className={inputClass}
              />
            </div>
          </div>

          <div className="grid gap-2 sm:grid-cols-2">
            <div>
              <FieldLabel>Vendor</FieldLabel>
              <input
                value={vendor}
                onChange={(event) => setVendor(event.target.value)}
                placeholder="Optional"
                className={inputClass}
              />
            </div>
            <div>
              <FieldLabel>Receipt / voucher reference</FieldLabel>
              <input
                value={receiptRef}
                onChange={(event) => setReceiptRef(event.target.value)}
                placeholder="Optional"
                className={inputClass}
              />
            </div>
          </div>
        </div>
      )}

      {operation === "transfer" && (
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          <div>
            <FieldLabel>From</FieldLabel>
            <select
              value={sourceChannel}
              onChange={(event) => setSourceChannel(event.target.value)}
              className={inputClass}
            >
              {CHANNELS.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <FieldLabel>To</FieldLabel>
            <select
              value={targetChannel}
              onChange={(event) => setTargetChannel(event.target.value)}
              className={inputClass}
            >
              {CHANNELS.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </div>
        </div>
      )}

      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        <div>
          <FieldLabel>Reference</FieldLabel>
          <input
            value={reference}
            onChange={(event) => setReference(event.target.value)}
            placeholder="Optional reference"
            className={inputClass}
          />
        </div>
        <div>
          <FieldLabel>{operation === "transfer" ? "Reason" : "Note"}</FieldLabel>
          <input
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder="Optional"
            className={inputClass}
          />
        </div>
      </div>

      {documentData && (
        <div className="mt-3">
          <OperationDocumentCard documentData={documentData} />
        </div>
      )}

      {postError && (
        <div className="mt-3 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-xs font-semibold text-red-700">
          {postError}
        </div>
      )}

      <div className="sticky bottom-0 z-20 mt-3 rounded-2xl border border-emerald-100 bg-white/95 p-3 shadow-[0_-10px_30px_rgba(0,0,0,0.06)] backdrop-blur">
        <div className="text-[10px] font-black uppercase tracking-[0.08em] text-emerald-800">
          Accounting effect
        </div>

        <div className="mt-1 divide-y divide-emerald-100 rounded-xl bg-emerald-50/70 px-3 py-1">
          {operation === "receive" && receiveMode === "income" && (
            <>
              <EffectRow
                label={channelLabel}
                value={`+ ${money(numericAmount)}`}
                emphasis
              />
              <EffectRow
                label={nodeName(selectedIncomeSubcategory) || "Revenue"}
                value={`+ ${money(numericAmount)}`}
              />
              <EffectRow label="Sale created" value="No" />
            </>
          )}

          {operation === "receive" && receiveMode === "ar" && (
            <>
              <EffectRow
                label={channelLabel}
                value={`+ ${money(numericAmount)}`}
                emphasis
              />
              <EffectRow
                label="Accounts Receivable"
                value={`− ${money(numericAmount)}`}
              />
              <EffectRow label="New income" value="0 XAF" />
            </>
          )}

          {operation === "pay" && (
            <>
              <EffectRow
                label={channelLabel}
                value={`− ${money(numericAmount)}`}
                emphasis
              />
              <EffectRow
                label={nodeName(selectedExpenseSubcategory) || "Expense"}
                value={`+ ${money(numericAmount)}`}
              />
              <EffectRow label="Sale created" value="No" />
            </>
          )}

          {operation === "transfer" && (
            <>
              <EffectRow
                label={sourceChannelLabel}
                value={`− ${money(numericAmount)}`}
                emphasis
              />
              <EffectRow
                label={targetChannelLabel}
                value={`+ ${money(numericAmount)}`}
              />
              <EffectRow label="P&L effect" value="0 XAF" />
            </>
          )}
        </div>

        {validationMessage && numericAmount > 0 && (
          <div className="mt-2 text-[11px] font-bold text-amber-700">
            {validationMessage}
          </div>
        )}

        <button
          type="button"
          onClick={submit}
          disabled={posting || Boolean(validationMessage)}
          className={`mt-2 w-full rounded-xl py-3 text-sm font-black text-white transition ${
            posting || validationMessage
              ? "cursor-not-allowed bg-neutral-300"
              : "bg-emerald-700 hover:bg-emerald-800"
          }`}
        >
          {posting
            ? "Posting..."
            : operation === "receive"
            ? receiveMode === "income"
              ? "Receive Income"
              : selectedReceivable &&
                numericAmount === numberValue(selectedReceivable.balance_due)
              ? "Settle Bill in Full"
              : "Receive A/R Payment"
            : operation === "pay"
            ? "Pay Expense"
            : "Post Transfer"}
        </button>
      </div>
    </div>
  );
}
