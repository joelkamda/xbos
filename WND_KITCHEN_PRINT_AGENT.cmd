@echo off
setlocal
if not defined XBOS_KITCHEN_DB set "XBOS_KITCHEN_DB=xbos"
if not defined XBOS_KITCHEN_STATE_FILE set "XBOS_KITCHEN_STATE_FILE=kitchen_print_state_xbos.json"
if not defined XBOS_KITCHEN_LOG_FILE set "XBOS_KITCHEN_LOG_FILE=kitchen_print_agent_xbos.log"
cd /d "%~dp0"
python "scripts\wnd_kitchen_print_agent.py" --database "%XBOS_KITCHEN_DB%" --watch
endlocal
