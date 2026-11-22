#!/bin/bash
set -euo pipefail
umask 077
ROOT=/var/tmp/g4a-v24-r7-canonical-source-20261122
PG=/var/tmp/g3-pg17-20261119/pkgroot/usr/lib/postgresql/17/bin
LIB=/var/tmp/g3-pg17-20261119/pkgroot/usr/lib/x86_64-linux-gnu
VENV=/var/tmp/g3-b2-v3-20261119/venv/bin/python
BROWSER=/var/tmp/g3-r3-browser-20261119/venv/bin/python
HERE="$(cd "$(dirname "$0")/source" && pwd)"
test -d "$HERE/backend/rehearsal_v3" || { echo FRESH_TEST_SOURCE_MISSING;exit 10; }
test ! -e "$ROOT/data/PG_VERSION" || { echo FAIL_CLOSED_ALREADY_PROVISIONED_NO_RESTART;exit 11; }
mkdir -p "$ROOT/src" "$ROOT/integration" "$ROOT/private" "$ROOT/sock" "$ROOT/log"
cp -r "$HERE/backend/rehearsal_v3" "$HERE/backend/restaurant" "$ROOT/src/"
cp -r "$HERE/backend/pack_platform" "$ROOT/src/"
cp "$HERE/backend"/v24_*.py "$ROOT/src/"
cp "$HERE/backend/v24_init_r7.sql" "$ROOT/integration/"
cp "$HERE/integration/"*.py "$ROOT/integration/"
if [ -d "$HERE/frontend/dist" ];then cp -r "$HERE/frontend/dist" "$ROOT/ui";fi
# Old synthetic runner compatibility file unused in R7: omitted in G4-A.
export ROOT PG LIB VENV BROWSER
echo V24_SOURCE_STAGED=YES
unshare --mount --net --pid --ipc --uts --fork --mount-proc -- env ROOT="$ROOT" PG="$PG" LIB="$LIB" VENV="$VENV" BROWSER="$BROWSER" bash -euo pipefail -c '
export LD_LIBRARY_PATH="$LIB"
export V24_NATIVE_ROOT="$ROOT"
mount --make-rprivate /
mount -t tmpfs -o mode=0555,nosuid,nodev,noexec tmpfs /mnt
unset WSL_INTEROP WSLENV WSL_DISTRO_NAME DISPLAY
if [ -e /init ];then mount --bind /dev/null /init;fi
ip link set lo up
test -z "$(ip route show default)" || { echo V24_NETWORK_EGRESS_HOLD;exit 31; }
test ! -e /mnt/c/Windows/System32/cmd.exe || { echo V24_WINDOWS_BRIDGE_HOLD;exit 32; }
mkdir -p "$ROOT/data" "$ROOT/sock" "$ROOT/log"
chmod 0755 "$ROOT"
chown -R postgres:postgres "$ROOT/data" "$ROOT/sock" "$ROOT/log"
chmod 700 "$ROOT/private"
export V24_SESSION_HMAC_HEX="$(head -c 32 /dev/urandom | xxd -p -c 64)"
export V24_CURSOR_SECRET_HEX="$(head -c 32 /dev/urandom | xxd -p -c 64)"
started=0
api_pid=""
ui_pid=""
cleanup(){
  set +e
  [ -z "$ui_pid" ] || { kill "$ui_pid" >/dev/null 2>&1 || true;wait "$ui_pid" >/dev/null 2>&1 || true; }
  [ -z "$api_pid" ] || { kill "$api_pid" >/dev/null 2>&1 || true;wait "$api_pid" >/dev/null 2>&1 || true; }
  if [ "$started" = 1 ];then
     runuser -u postgres -- "$PG/pg_ctl" -D "$ROOT/data" -m fast stop >/dev/null 2>&1 || true
  fi
  echo V24_TEST_PG17_STOPPED_CLEANLY
}
trap cleanup EXIT
chmod 0755 "$ROOT/integration"
chmod 0644 "$ROOT/integration/v24_init_r7.sql"
runuser -u postgres -- "$PG/initdb" -D "$ROOT/data" -A trust --encoding=UTF8 --no-locale > "$ROOT/log/initdb.private" 2>&1 || { echo V24_INITDB_HOLD;exit 40; }
runuser -u postgres -- "$PG/pg_ctl" -D "$ROOT/data" -o "-c port=55449 -c listen_addresses=127.0.0.1 -c unix_socket_directories=$ROOT/sock" -l "$ROOT/log/pg.private" -w start > "$ROOT/log/pg_start.private" 2>&1 || { echo V24_PG_START_HOLD;exit 41; }
started=1
runuser -u postgres -- "$PG/createdb" -h "$ROOT/sock" -p 55449 v24_native_d7_test
runuser -u postgres -- "$PG/psql" -X -q -v ON_ERROR_STOP=1 -h "$ROOT/sock" -p 55449 -d v24_native_d7_test -f "$ROOT/integration/v24_init_r7.sql" > "$ROOT/log/schema.private" 2>&1 || { echo V24_SCHEMA_HOLD;exit 42; }
PYTHONPATH="$ROOT/src" "$VENV" "$ROOT/integration/seed_synthetic.py" > "$ROOT/log/seed.private" 2>&1 || { echo V24_FIXTURE_HOLD;exit 43; }
PYTHONPATH="$ROOT/src" "$VENV" "$ROOT/integration/pa_seed_test_grant.py" > "$ROOT/log/r7_pa_seed.private" 2>&1 || { echo R7_TEST_GRANT_SEED_HOLD;exit 55; }
grep -q "PA_SYNTHETIC_TEST_GRANT_SEEDED_NOT_PC5=PASS" "$ROOT/log/r7_pa_seed.private"
echo V24_NATIVE_PG17_FRESH_NO_EGRESS=PASS
PYTHONPATH="$ROOT/src" "$VENV" -m uvicorn rehearsal_v3.v24_app:app --host 127.0.0.1 --port 8791 --log-level warning --no-access-log > "$ROOT/log/api.private" 2>&1 &
api_pid=$!
for i in $(seq 1 100);do
 if curl -fsS --noproxy "*" http://127.0.0.1:8791/api/v3/health > "$ROOT/log/health.private";then break;fi
 kill -0 "$api_pid" >/dev/null 2>&1 || { echo V24_API_CRASH_HOLD;exit 44; }
 sleep 0.1
done
grep -q v24_native_d7_test "$ROOT/log/health.private" || { echo V24_API_HEALTH_HOLD;exit 45; }
echo V24_NATIVE_FASTAPI_PG17=PASS
if [ -f "$ROOT/ui/index.html" ];then
  "$VENV" -m http.server 8792 --bind 127.0.0.1 --directory "$ROOT/ui" > "$ROOT/log/ui.private" 2>&1 &
  ui_pid=$!
fi
PYTHONPATH="$ROOT/src" "$VENV" "$ROOT/integration/r4_native_api_acceptance.py" > "$ROOT/log/r3_api.private" 2>&1 || { echo V24_HTTP_JOURNEY_HOLD;tail -n 45 "$ROOT/log/http_journey.private" | sed -E "s/(token|password|secret)[=:][^ ,]+/REDACTED/g";exit 46; }
grep -q "^R4_NATIVE_FINANCE_INVENTORY_PG_PASS=" "$ROOT/log/r3_api.private" || { echo V24_HTTP_RECEIPT_HOLD;exit 47; }
grep "^R4_NATIVE_FINANCE_INVENTORY_PG_PASS=" "$ROOT/log/r3_api.private"
PYTHONPATH="$ROOT/src" "$VENV" "$ROOT/integration/r5_statement_api_acceptance.py" > "$ROOT/log/r5_api.private" 2>&1 || { echo R5_OPERATOR_STATEMENT_API_HOLD; tail -n 25 "$ROOT/log/r5_api.private";exit 50; }
grep "^R5_STATEMENT_RECON_PG17_PASS=" "$ROOT/log/r5_api.private"
PYTHONPATH="$ROOT/src" "$VENV" "$ROOT/integration/r6_integrated_sof_ar_acceptance.py" > "$ROOT/log/r6_sof.private" 2>&1 || { echo R6_SOF_AR_NATIVE_HOLD;tail -n 35 "$ROOT/log/r6_sof.private";exit 52; }
grep "^R6_INTEGRATED_SOF_AR_PG17_PASS=" "$ROOT/log/r6_sof.private"
PYTHONPATH="$ROOT/src" "$VENV" "$ROOT/integration/r6_native_w_n_acceptance.py" > "$ROOT/log/r6_w_n.private" 2>&1 || { echo R6_W_N_NATIVE_HOLD;tail -n 35 "$ROOT/log/r6_w_n.private";exit 53; }
grep "^R6_NATIVE_W_N_REALPG17_PASS=" "$ROOT/log/r6_w_n.private"
PYTHONPATH="$ROOT/src" "$VENV" "$ROOT/integration/r6_cogs_source_classification_acceptance.py" > "$ROOT/log/r7_cogs.private" 2>&1 || { echo R7_SALE_ONLY_COGS_HOLD;tail -n 24 "$ROOT/log/r7_cogs.private";exit 56; }
grep "^R6_COGS_SALE_VS_STOCK_COUNT_REAL_PG_PASS=" "$ROOT/log/r7_cogs.private"
PYTHONPATH="$ROOT/src" "$VENV" "$ROOT/integration/r7_unified_native_acceptance.py" > "$ROOT/log/r7_native.private" 2>&1 || { echo R7_NATIVE_COMBINED_PUBLISH_CUSTODY_HOLD;tail -n 32 "$ROOT/log/r7_native.private";exit 57; }
grep "^R7_UNIFIED_N_PK_PA_W_PG17_PASS=" "$ROOT/log/r7_native.private"

if [ -f "$ROOT/ui/index.html" ];then
  env LD_LIBRARY_PATH="/var/tmp/g3-r3-browser-20261119/private-runtime-libs/usr/lib/x86_64-linux-gnu:$LIB" PLAYWRIGHT_BROWSERS_PATH="/var/tmp/g3-r3-browser-20261119/browsers" PYTHONPATH="$ROOT/src" "$BROWSER" "$ROOT/integration/r7_unified_chromium_acceptance.py" > "$ROOT/log/r7_browser.private" 2>&1 || { echo R7_CHROMIUM_UNIFIED_HOLD;tail -n 35 "$ROOT/log/r7_browser.private";exit 58; }
  grep "^R7_UNIFIED_CHROMIUM_API_PG17_PASS=" "$ROOT/log/r7_browser.private"
fi
test -z "$(ip route show default)" || { echo V24_EGRESS_BREACH;exit 49; }
echo G4A_CANONICAL_R7_NO_EGRESS_NATIVE_SOURCE_TEST=PASS
'
