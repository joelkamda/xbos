import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { useEffect, useMemo, useState } from "react";
import { useSessionStore } from "../lib/store/session";
import { checkWatchedPayment, readXafpayOutcomeWatches, XAFPAY_WATCH_INTERVAL_MS } from "../lib/xafpayOutcomeWatcher";
import {
  NavIcon,
  primaryNavigation,
  quickNavigation,
  type NavigationItem,
} from "./navigation";

const WND_TENANT_NAME = "Wine & Dine";
const WND_BRANCH_NAME = "Main Branch";
const WND_LOGO_SRC = "/logos/wnd_logo_gold.png";

function roleLabel(role?: string | null) {
  if (!role) return "Unknown";

  return role
    .split("_")
    .map((x) => x.charAt(0).toUpperCase() + x.slice(1))
    .join(" ");
}

function hasAnyPermission(
  userPermissions: string[] = [],
  required: string[] = []
) {
  if (required.length === 0) return true;

  const set = new Set(userPermissions);
  if (set.has("*")) return true;

  return required.some((permission) => set.has(permission));
}

function mergePermissions(
  authPermissions: string[] = [],
  sessionPermissions: string[] = []
) {
  return Array.from(
    new Set([
      ...(Array.isArray(authPermissions) ? authPermissions : []),
      ...(Array.isArray(sessionPermissions) ? sessionPermissions : []),
    ])
  );
}

function cleanLabel(value?: string | number | null) {
  return String(value ?? "").trim();
}

function looksLikeCode(value?: string | null) {
  const v = cleanLabel(value);
  if (!v) return false;

  return /^[A-Z]{2,}[A-Z0-9_-]*\d+$/i.test(v);
}

function humanContextPart({
  name,
  code,
  fallback,
}: {
  name?: string | null;
  code?: string | null;
  fallback: string;
}) {
  const cleanName = cleanLabel(name);
  const cleanCode = cleanLabel(code);

  if (cleanName && cleanName !== cleanCode && !looksLikeCode(cleanName)) {
    return cleanName;
  }

  // WND Track A display bridge: never surface internal codes as the normal UI label.
  return fallback;
}

function isActivePath(pathname: string, item: NavigationItem) {
  if (item.path === "/") return pathname === "/";

  if (item.key === "sales") {
    return pathname === "/sales" || pathname.startsWith("/sales/");
  }

  return pathname === item.path || pathname.startsWith(item.path + "/");
}

function isQuickActive(pathname: string, item: NavigationItem) {
  if (item.key === "money-activity") return pathname === "/payments";
  return pathname === item.path || pathname.startsWith(item.path + "/");
}

function filterByPermissions(items: NavigationItem[], permissions: string[]) {
  return items.filter((item) =>
    hasAnyPermission(permissions, item.permissionsAny ?? [])
  );
}

function quickRailLabel(item: NavigationItem) {
  if (item.key === "reconciliation") return "Recon";
  if (item.key === "money-activity") return "Activity";
  return item.label;
}

function formatBusinessDate() {
  return new Intl.DateTimeFormat("en-GB", {
    weekday: "short",
    day: "2-digit",
    month: "short",
    year: "numeric",
    timeZone: "Africa/Douala",
  }).format(new Date());
}

export default function AppShell() {
  const navigate = useNavigate();
  const location = useLocation();

  const session = useSessionStore((s) => s.session);
  const authUser = useSessionStore((s) => s.authUser);
  const logout = useSessionStore((s) => s.logout);

  const [time, setTime] = useState("");
  const [businessDate, setBusinessDate] = useState(formatBusinessDate());
  const [profileOpen, setProfileOpen] = useState(false);
  const [mobileMoreOpen, setMobileMoreOpen] = useState(false);
  const [outcomeNotice, setOutcomeNotice] = useState<{ paymentId: string; state: string; amount?: number } | null>(null);

  useEffect(() => {
    const inFlight = new Set<string>();
    const tick = async () => {
      for (const watch of readXafpayOutcomeWatches()) {
        if (inFlight.has(watch.paymentId)) continue;
        inFlight.add(watch.paymentId);
        try {
          const outcome = await checkWatchedPayment(watch.paymentId);
          if (outcome.terminal) {
            setOutcomeNotice({ paymentId: watch.paymentId, state: outcome.state!, amount: Number(outcome.result?.total_paid || outcome.result?.amount || 0) });
          }
        } catch { /* retain the watch for a later local truth read */ }
        finally { inFlight.delete(watch.paymentId); }
      }
    };
    void tick();
    const timer = window.setInterval(() => void tick(), XAFPAY_WATCH_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    const tick = () => {
      const now = new Date();
      setTime(
        now.toLocaleTimeString("en-GB", {
          hour: "2-digit",
          minute: "2-digit",
          hour12: false,
          timeZone: "Africa/Douala",
        })
      );
      setBusinessDate(formatBusinessDate());
    };

    tick();
    const interval = window.setInterval(tick, 30_000);
    return () => window.clearInterval(interval);
  }, []);

  useEffect(() => {
    setProfileOpen(false);
    setMobileMoreOpen(false);
  }, [location.pathname]);

  const handleLogout = () => {
    logout();
    navigate("/login", { replace: true });
  };

  const userRole = authUser?.role ?? session?.role ?? "unknown";
  const username = authUser?.username ?? session?.username ?? "User";

  const userPermissions = mergePermissions(
    authUser?.permissions ?? [],
    session?.permissions ?? []
  );

  const visiblePrimary = useMemo(
    () => filterByPermissions(primaryNavigation, userPermissions),
    [userPermissions]
  );

  const visibleQuick = useMemo(
    () => filterByPermissions(quickNavigation, userPermissions),
    [userPermissions]
  );

  const canAdmin = hasAnyPermission(userPermissions, [
    "system.settings.view",
    "system.settings.edit",
    "rbac.role.view",
    "rbac.role.edit",
  ]);

  const tenantDisplay = humanContextPart({
    name: session?.tenant_name,
    code: session?.tenant_code ?? authUser?.tenant_code ?? null,
    fallback: WND_TENANT_NAME,
  });

  const branchDisplay = humanContextPart({
    name: session?.branch_name,
    code: session?.branch_code ?? authUser?.branch_code ?? null,
    fallback: WND_BRANCH_NAME,
  });

  const mobileMain = visiblePrimary.filter((item) =>
    ["home", "sales", "stock", "payments"].includes(item.key)
  );

  const mobileMorePrimary = visiblePrimary.filter(
    (item) => !["home", "sales", "stock", "payments"].includes(item.key)
  );

  const isHome = location.pathname === "/";

  return (
    <div className="flex h-dvh overflow-hidden bg-[var(--wnd-bg)] text-[15px] text-[var(--wnd-text)]">
      {/* Tenant brand + high-frequency operational rail. On desktop this owns the full left edge. */}
      <aside className="wnd-brand-rail relative z-50 hidden w-[72px] shrink-0 flex-col md:flex lg:w-[156px] xl:w-[196px]">
        <button
          type="button"
          onClick={() => navigate("/")}
          className="wnd-brand-block flex shrink-0 flex-col items-center px-2 pb-3 pt-3 lg:px-3 lg:pb-3 lg:pt-3 xl:px-4 xl:pb-4 xl:pt-4"
          title={`${tenantDisplay} home`}
        >
          <span className="wnd-brand-medallion flex h-12 w-12 items-center justify-center overflow-hidden rounded-full lg:h-[84px] lg:w-[84px] xl:h-[116px] xl:w-[116px]">
            <img
              src={WND_LOGO_SRC}
              alt="Wine & Dine"
              className="h-full w-full scale-[1.22] object-cover"
            />
          </span>
          <span className="mt-2 hidden text-center lg:block xl:mt-3">
            <span className="block text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--wnd-gold-light)]">
              Wine & Dine
            </span>
            <span className="mt-1 block text-[10px] text-[var(--wnd-rail-muted)]">
              Douala
            </span>
          </span>
        </button>

        <div className="wnd-brand-divider mx-3 hidden lg:block" />

        <div className="px-2 pb-1 pt-2 lg:px-3 xl:px-4 xl:pb-2 xl:pt-3">
          <div className="hidden text-[10px] font-semibold uppercase tracking-[0.17em] text-[var(--wnd-gold-light)] lg:block">
            Quick access
          </div>
        </div>

        <nav className="wnd-quick-list flex min-h-0 flex-1 flex-col gap-1 overflow-hidden px-2 pb-2 lg:px-2.5 xl:px-3 xl:pb-3" aria-label="Quick access">
          {visibleQuick.map((item) => {
            const active = isQuickActive(location.pathname, item);
            return (
              <button
                type="button"
                key={item.key}
                onClick={() => navigate(item.path)}
                className={`wnd-quick-nav ${active ? "wnd-quick-nav-active" : ""}`}
                title={item.label}
              >
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl">
                  <NavIcon name={item.icon} className="h-[18px] w-[18px]" />
                </span>
                <span className="hidden min-w-0 truncate text-sm font-medium lg:block">
                  {quickRailLabel(item)}
                </span>
              </button>
            );
          })}
        </nav>

        <div className="wnd-powered-block shrink-0 px-3 pb-3 pt-2 lg:px-4 lg:pb-3 xl:px-5 xl:pb-4 xl:pt-3">
          <div className="hidden lg:block">
            <div className="text-[9px] font-semibold uppercase tracking-[0.18em] text-[var(--wnd-rail-muted)]">
              Powered by
            </div>
            <div className="mt-1 text-xl font-semibold tracking-[-0.035em] text-[var(--wnd-gold-light)]">
              XBOS
            </div>
          </div>
          <div className="flex justify-center lg:hidden">
            <span className="text-[10px] font-semibold tracking-tight text-[var(--wnd-gold-light)]">X</span>
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="wnd-app-header relative z-40 shrink-0 border-b border-[var(--wnd-border)] backdrop-blur">
          {/* Human business context. No duplicate tenant logo on desktop. */}
          <div className="flex min-h-[72px] items-center gap-3 px-4 sm:px-5 lg:min-h-[78px] lg:px-7">
            <button
              type="button"
              onClick={() => navigate("/")}
              className="wnd-mobile-brand-medallion flex h-11 w-11 shrink-0 items-center justify-center overflow-hidden rounded-full md:hidden"
              title="Home"
            >
              <img src={WND_LOGO_SRC} alt="Wine & Dine" className="h-full w-full scale-[1.22] object-cover" />
            </button>

            <button
              type="button"
              onClick={() => navigate("/")}
              className="group min-w-0 text-left"
              title="Home"
            >
              <div className="wnd-tenant-name truncate text-[20px] font-semibold tracking-[-0.025em] sm:text-[22px] lg:text-[25px]">
                {tenantDisplay}
              </div>
              <div className="mt-0.5 truncate text-xs text-[var(--wnd-gold-deep)]">
                Douala · Live operations
              </div>
            </button>

            <div className="hidden h-10 w-px bg-[var(--wnd-gold-border)] sm:block" />

            <button
              type="button"
              onClick={() => navigate("/select-context")}
              className="wnd-soft-button wnd-branch-button hidden min-w-0 items-center gap-2 sm:flex"
              title="Change business context"
            >
              <NavIcon name="context" className="h-4 w-4 text-[var(--wnd-gold-deep)]" />
              <span className="max-w-[210px] truncate">{branchDisplay}</span>
              <NavIcon name="chevron" className="h-3.5 w-3.5 rotate-90 opacity-60" />
            </button>

            <div className="ml-auto flex items-center gap-2 sm:gap-3">
              <div className="hidden border-l border-[var(--wnd-gold-border)] pl-4 text-right lg:block">
                <div className="text-base font-semibold text-neutral-900">{time}</div>
                <div className="mt-0.5 text-[11px] text-neutral-500">{businessDate}</div>
              </div>

              <div className="relative">
                <button
                  type="button"
                  onClick={() => setProfileOpen((value) => !value)}
                  className="wnd-profile-button"
                  aria-expanded={profileOpen}
                  title="Profile and system options"
                >
                  <span className="hidden text-left sm:block">
                    <span className="block max-w-32 truncate text-sm font-semibold text-neutral-900">{username}</span>
                    <span className="block max-w-32 truncate text-[11px] text-neutral-500">{roleLabel(userRole)}</span>
                  </span>
                  <span className="wnd-profile-icon flex h-10 w-10 items-center justify-center rounded-2xl">
                    <NavIcon name="user" className="h-[18px] w-[18px]" />
                  </span>
                </button>

                {profileOpen && (
                  <div className="absolute right-0 top-[calc(100%+10px)] z-50 w-[calc(100vw-24px)] max-w-[340px] overflow-hidden rounded-2xl border border-neutral-200 bg-white shadow-xl">
                    <div className="border-b border-neutral-200 p-4">
                      <div className="text-base font-semibold text-neutral-950">{username}</div>
                      <div className="mt-1 text-sm text-neutral-500">{roleLabel(userRole)}</div>
                    </div>
                    <div className="space-y-1 p-2">
                      <button type="button" onClick={() => navigate("/select-context")} className="wnd-menu-row">
                        <NavIcon name="context" className="h-4 w-4" />
                        <span className="min-w-0 flex-1 text-left">
                          <span className="block text-sm font-medium">Context</span>
                          <span className="block truncate text-xs text-neutral-500">{tenantDisplay} · {branchDisplay}</span>
                        </span>
                      </button>
                      {canAdmin && (
                        <button type="button" onClick={() => navigate("/admin/users")} className="wnd-menu-row">
                          <NavIcon name="settings" className="h-4 w-4" />
                          <span className="text-sm font-medium">Admin</span>
                        </button>
                      )}
                      <div className="my-1 border-t border-neutral-200" />
                      <div className="rounded-xl px-3 py-2.5 text-xs text-neutral-500">
                        <div className="font-medium text-neutral-700">System information</div>
                        <div className="mt-1 font-mono text-[11px] leading-5">
                          {session?.tenant_code ?? authUser?.tenant_code ?? "—"} ·{" "}
                          {session?.branch_code ?? authUser?.branch_code ?? "—"}
                        </div>
                      </div>
                      <button type="button" onClick={handleLogout} className="wnd-menu-row text-red-700 hover:bg-red-50">
                        <NavIcon name="logout" className="h-4 w-4" />
                        <span className="text-sm font-medium">Sign out</span>
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Primary domains align with the workspace because the tenant rail is outside this header. */}
          <div className="wnd-primary-strip hidden px-4 sm:px-5 md:block lg:px-7">
            <nav className="wnd-primary-nav-surface wnd-no-scrollbar my-1.5 flex min-h-[50px] items-center gap-1 overflow-x-auto p-1" aria-label="Primary modules">
              {visiblePrimary.map((item) => {
                const active = isActivePath(location.pathname, item);
                return (
                  <button
                    type="button"
                    key={item.key}
                    onClick={() => navigate(item.path)}
                    className={`wnd-primary-nav ${active ? "wnd-primary-nav-active" : ""}`}
                  >
                    <NavIcon name={item.icon} className="h-[18px] w-[18px]" />
                    <span className="hidden whitespace-nowrap lg:inline">{item.label}</span>
                  </button>
                );
              })}
            </nav>
          </div>
        </header>

        {outcomeNotice && (
          <div className="mx-3 mt-2 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm font-semibold text-emerald-900 sm:mx-5 lg:mx-7" role="status" aria-live="polite">
            <button type="button" className="mr-2 underline" onClick={() => { const id = outcomeNotice.paymentId; setOutcomeNotice(null); navigate(`/payments?tab=records&paymentId=${encodeURIComponent(id)}`); }}>XafPay payment {outcomeNotice.state === "COMPLETED" ? "confirmed" : "failed"} — view payment</button>
            <button type="button" aria-label="Dismiss notification" onClick={() => setOutcomeNotice(null)}>×</button>
          </div>
        )}

        <main
          className={`min-w-0 flex-1 ${isHome ? "overflow-hidden" : "overflow-y-auto"} px-3 py-3 pb-[78px] sm:px-5 sm:py-4 md:pb-5 lg:px-7 lg:py-4 xl:py-5`}
        >
          <Outlet />
        </main>
      </div>

      {/* Mobile bottom navigation */}
      <nav className="fixed inset-x-0 bottom-0 z-50 border-t border-neutral-200 bg-white/95 px-2 pb-[max(6px,env(safe-area-inset-bottom))] pt-1.5 backdrop-blur md:hidden" aria-label="Mobile navigation">
        <div className="grid gap-1" style={{ gridTemplateColumns: `repeat(${Math.max(1, mobileMain.length + 1)}, minmax(0, 1fr))` }}>
          {mobileMain.map((item) => {
            const active = isActivePath(location.pathname, item);
            return (
              <button type="button" key={item.key} onClick={() => navigate(item.path)} className={`wnd-mobile-nav ${active ? "wnd-mobile-nav-active" : ""}`}>
                <NavIcon name={item.icon} className="h-[19px] w-[19px]" />
                <span>{item.label}</span>
              </button>
            );
          })}
          <button type="button" onClick={() => setMobileMoreOpen((value) => !value)} className={`wnd-mobile-nav ${mobileMoreOpen ? "wnd-mobile-nav-active" : ""}`} aria-expanded={mobileMoreOpen}>
            <NavIcon name="more" className="h-[19px] w-[19px]" />
            <span>More</span>
          </button>
        </div>
      </nav>

      {mobileMoreOpen && (
        <>
          <button type="button" aria-label="Close more menu" onClick={() => setMobileMoreOpen(false)} className="fixed inset-0 z-40 bg-black/10 md:hidden" />
          <div className="fixed inset-x-3 bottom-[76px] z-50 max-h-[70dvh] overflow-y-auto rounded-2xl border border-neutral-200 bg-white p-2 shadow-xl md:hidden">
            <div className="px-2 pb-2 pt-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-neutral-400">Quick access</div>
            <div className="grid grid-cols-2 gap-1">
              {visibleQuick.slice(0, 6).map((item) => (
                <button type="button" key={item.key} onClick={() => navigate(item.path)} className="wnd-mobile-sheet-item">
                  <NavIcon name={item.icon} className="h-[18px] w-[18px]" />
                  <span className="truncate">{item.label}</span>
                </button>
              ))}
            </div>
            {mobileMorePrimary.length > 0 && (
              <>
                <div className="mx-2 my-2 border-t border-neutral-200" />
                <div className="px-2 pb-2 pt-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-neutral-400">More modules</div>
                <div className="grid grid-cols-2 gap-1">
                  {mobileMorePrimary.map((item) => (
                    <button type="button" key={item.key} onClick={() => navigate(item.path)} className="wnd-mobile-sheet-item">
                      <NavIcon name={item.icon} className="h-[18px] w-[18px]" />
                      <span className="truncate">{item.label}</span>
                    </button>
                  ))}
                </div>
              </>
            )}
            <div className="mx-2 my-2 border-t border-neutral-200" />
            <div className="grid grid-cols-2 gap-1">
              <button type="button" onClick={() => navigate("/select-context")} className="wnd-mobile-sheet-item">
                <NavIcon name="context" className="h-[18px] w-[18px]" />
                <span>Context</span>
              </button>
              {canAdmin && (
                <button type="button" onClick={() => navigate("/admin/users")} className="wnd-mobile-sheet-item">
                  <NavIcon name="settings" className="h-[18px] w-[18px]" />
                  <span>Admin</span>
                </button>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
