#!/usr/bin/env bash
# Воспроизводимое восстановление демобазы 1С с нуля:
#   1) пересоздать базу из XML (onec/config) и загрузить fixtures/data.json — ReconLoader
#      опубликован только на это время и только на localhost внутри контейнера;
#   2) запустить рабочий ibsrv, где опубликован ТОЛЬКО ReconAPI;
#   3) проверить снаружи: reader читает, загрузчик не опубликован (404).
# Запуск из корня репозитория: ./onec/restore.sh   (нужны .env и onec-dist/)
set -euo pipefail
cd "$(dirname "$0")/.."

[ -f .env ] || { echo "Нет .env: cp .env.example .env и заполните ONEC_*" >&2; exit 1; }
set -a; . ./.env; set +a
: "${ONEC_PASSWORD:?заполните ONEC_PASSWORD в .env}"
: "${ONEC_ADMIN_PASSWORD:?заполните ONEC_ADMIN_PASSWORD в .env}"

DC="docker compose --profile onec"
BASE="http://localhost:${ONEC_PORT:-8314}"

echo "[restore] сборка образа (если ещё не собран)"
$DC build onec

echo "[restore] остановка рабочего ibsrv"
$DC stop onec >/dev/null 2>&1 || true

echo "[restore] фаза восстановления (ReconLoader опубликован только внутри контейнера)"
$DC run --rm --no-deps onec /onec/scripts/restore-inside.sh

echo "[restore] рабочая фаза: ibsrv только с ReconAPI"
$DC up -d --wait onec

fail() { echo "[restore] ОШИБКА: $*" >&2; exit 1; }
for c in accounts charges payments; do
  code=$(curl -s -o /dev/null -w '%{http_code}' -u "$ONEC_USER:$ONEC_PASSWORD" "$BASE/hs/recon/$c")
  [ "$code" = 200 ] || fail "GET /hs/recon/$c под $ONEC_USER вернул $code"
done
echo "[restore] GET accounts/charges/payments под $ONEC_USER: 200"
code=$(curl -s -o /dev/null -w '%{http_code}' -u "$ONEC_ADMIN_USER:$ONEC_ADMIN_PASSWORD" \
  -X POST -d '{}' "$BASE/hs/recon-load/fixtures")
[ "$code" = 404 ] || fail "ReconLoader не должен быть опубликован (ожидали 404, получили $code)"
echo "[restore] ReconLoader в рабочем режиме: 404 (не опубликован)"
echo "[restore] готово: $BASE/hs/recon"
