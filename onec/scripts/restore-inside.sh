#!/usr/bin/env bash
# Выполняется ВНУТРИ контейнера onec (см. onec/restore.sh):
# пересоздаёт базу из XML-исходников, загружает fixtures/data.json через ReconLoader,
# заводит пользователей и проверяет права. В конце ibsrv остановлен.
set -euo pipefail

: "${ONEC_ADMIN_USER:?не задан ONEC_ADMIN_USER}"
: "${ONEC_ADMIN_PASSWORD:?не задан ONEC_ADMIN_PASSWORD}"
: "${ONEC_USER:?не задан ONEC_USER}"
: "${ONEC_PASSWORD:?не задан ONEC_PASSWORD}"

DATA=/onec/data
URL=http://localhost:8314/hs/recon-load/fixtures
LOG=/tmp/ibsrv-load.log
BODY=/tmp/load-body.json
trap 'rm -f "$BODY"' EXIT

log() { echo "[restore] $*"; }
fail() { echo "[restore] ОШИБКА: $*" >&2; exit 1; }
json_str() { local s=${1//\\/\\\\}; s=${s//\"/\\\"}; printf '"%s"' "$s"; }

# ibsrv после обработанных запросов пишет "Server stopped" по SIGINT, но процесс
# не завершается. Ждём эту строку (база закрыта) и только потом добиваем.
stop_ibsrv() {
  pkill -INT -x ibsrv || return 0
  for _ in $(seq 30); do grep -q "Server stopped" "$LOG" && break; sleep 1; done
  sleep 2
  pkill -9 -x ibsrv || true
  while pgrep -x ibsrv >/dev/null; do sleep 1; done
}

log "1/5 пересоздаю базу из onec/config (XML)"
rm -rf "${DATA:?}"/*
ibcmd infobase create --data="$DATA" --db-path="$DATA/db" --create-database \
  --import=/onec/config --apply --force

log "2/5 запускаю ibsrv в режиме загрузки (localhost внутри контейнера)"
ibsrv --data="$DATA" -c /onec/ibsrv/load.yml >"$LOG" 2>&1 &
disown
for _ in $(seq 120); do curl -s -o /dev/null http://localhost:8314/ && break; sleep 1; done
curl -s -o /dev/null http://localhost:8314/ || { cat "$LOG"; fail "ibsrv не запустился"; }

# Администратор первым: платформа требует, чтобы первый пользователь имел право Администрирование.
{
  printf '{"fixtures":'; cat /onec/fixtures/data.json
  printf ',"users":[{"name":%s,"password":%s,"role":"ПолныеПрава"},' \
    "$(json_str "$ONEC_ADMIN_USER")" "$(json_str "$ONEC_ADMIN_PASSWORD")"
  printf '{"name":%s,"password":%s,"role":"ЧтениеДанных"}]}' \
    "$(json_str "$ONEC_USER")" "$(json_str "$ONEC_PASSWORD")"
} >"$BODY"

log "3/5 загрузка фикстур (база без пользователей)"
code=$(curl -s -o /tmp/r1 -w '%{http_code}' -X POST --data-binary @"$BODY" "$URL")
[ "$code" = 200 ] || { cat /tmp/r1; fail "загрузка вернула HTTP $code"; }
log "    итог: $(cat /tmp/r1)"

log "4/5 повторная загрузка под администратором (дублей быть не должно)"
code=$(curl -s -o /tmp/r2 -w '%{http_code}' -u "$ONEC_ADMIN_USER:$ONEC_ADMIN_PASSWORD" \
  -X POST --data-binary @"$BODY" "$URL")
[ "$code" = 200 ] || { cat /tmp/r2; fail "повторная загрузка вернула HTTP $code"; }
cmp -s /tmp/r1 /tmp/r2 || fail "после повторной загрузки изменилось количество: $(cat /tmp/r2)"
log "    итог: $(cat /tmp/r2) — совпадает"

log "5/5 проверка прав"
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST --data-binary @"$BODY" "$URL")
[ "$code" = 401 ] || fail "вход без пароля должен быть закрыт (401), получено $code"
log "    без пароля: 401"
code=$(curl -s -o /dev/null -w '%{http_code}' -u "$ONEC_USER:$ONEC_PASSWORD" \
  -X POST --data-binary @"$BODY" "$URL")
[ "$code" = 403 ] || fail "запись под $ONEC_USER должна быть запрещена (403), получено $code"
log "    запись под $ONEC_USER: 403 (отказ)"

stop_ibsrv
log "готово: база восстановлена, ibsrv остановлен"
