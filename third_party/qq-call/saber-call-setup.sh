#!/usr/bin/env bash
# 本脚本只配置容器内部；缺失授权文件时保持普通 NapCat 启动。
if [[ ! -f /run/saber-call/disabled && -r /run/saber-call/allowed-uin && -r /run/saber-call/access-token ]]; then
  mkdir -p /app/napcat/plugins
  bash /opt/saber/bridge/scripts/install.sh --qq-dir /opt/QQ --napcat-dir /app/napcat --install-dir /tmp/saber-call
  python3 /opt/saber/patch-napcat.py || { echo "[qq-call] 补丁校验失败，电话桥未启用"; return 1; }
  chown -R napcat:napcat /tmp/saber-call /app/napcat/plugins /app/napcat/config
  export MAIBOT_QQ_CALL_RESTART_AV_HOST=0
  export SABER_QQ_CALL_ALLOWED_UIN="$(cat /run/saber-call/allowed-uin)"
  export SABER_QQ_CALL_ARM_FILE=/run/saber-call/armed
  export SABER_QQ_CALL_READY_FILE=/tmp/saber-call/runtime/worker-ready
  export SABER_QQ_CALL_BRIDGE_TOKEN_FILE=/tmp/saber-call/runtime/control.token
  export SABER_QQ_CALL_PANEL_TOKEN_FILE=/run/saber-call/access-token
  export PULSE_SERVER=unix:/tmp/saber-call/runtime/pulse/native
  export PYTHONPATH=/opt/saber/site-packages
  gosu napcat /tmp/saber-call/scripts/audio-control.sh start
  gosu napcat /tmp/saber-call/scripts/run-av-host.sh >/dev/null 2>&1 &
  gosu napcat python3 /opt/saber/qq_call_worker.py >>/tmp/saber-call/logs/worker.log 2>&1 &
else
  echo '[qq-call] 未提供来电授权文件，通话功能未启用'
fi
