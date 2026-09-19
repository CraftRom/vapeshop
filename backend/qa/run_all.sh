#!/usr/bin/env bash
# Повний цикл тестування. Запуск: bash qa/run_all.sh
#
# Провалом вважається позначка ✗, рядок ПРОВАЛЕНО або ненульовий код виходу.
# Трейсбеки в логах самі по собі не рахуються: частина наборів навмисно
# імітує збої Telegram і бази, і виняток там — очікуваний результат. А от
# набір, що впав і вийшов з кодом 1, раніше показувався «ok», якщо встиг
# упасти до першої позначки ✗.
set -u
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD:$PWD/qa"
PY="${PY:-python3}"

# Без aiosqlite кожен Python-набір падає на імпорті, і зведення показує
# десятки однакових провалів замість однієї причини.
if ! $PY -c "import aiosqlite" 2>/dev/null; then
  echo "Не встановлено залежності QA: pip install -r requirements-qa.txt"
  exit 2
fi
fail=0

run() {
  printf '  %-13s ' "$1"
  rm -f /tmp/qa_*.db 2>/dev/null
  out=$($PY "$2" 2>&1)
  code=$?
  summary=$(echo "$out" | grep -E '^[A-ZА-Я ]+: [0-9]+/[0-9]+|Всього провалено|усі контракти' | tail -1)
  # Код виходу враховується, як і в run_node. Без цього набір, що падав
  # із traceback до першої перевірки, показувався «ok».
  if [[ $code -ne 0 ]] || echo "$out" | grep -qE '✗|ПРОВАЛЕНО'; then
    echo "ПРОВАЛ (код $code) — ${summary:-див. деталі}"
    echo "$out" | grep -E '✗' | head -5 | sed 's/^/      /'
    echo "$out" | grep -qE '✗' || echo "$out" | tail -4 | sed 's/^/      /'
    fail=1
  else
    echo "${summary:-ok}"
  fi
}

echo "Комплектність"
printf '  %-13s ' "wiring"
if out=$($PY qa/audit_wiring.py 2>&1) && ! echo "$out" | grep -q "✗"; then
  echo "усі рівні звʼязані"
else
  echo "ПРОВАЛ"; echo "$out" | grep "✗" | head -5 | sed 's/^/      /'; fail=1
fi

# Тести вітрини на Node. Їх не було в цьому переліку взагалі: три набори
# лежали в miniapp/tests і не запускались ніколи, хоч саме вони стережуть
# стан «Збереженого» й видимість полів введення.
# $1 — назва в зведенні, $2 — шлях до набору, $3 — каталог застосунку
# (за замовчуванням вітрина). Каталог параметром, а не другою копією
# цього ж блоку: копія для панелі вже існувала окремо, і будь-яка правка
# тут довелося б робити двічі.
run_node() {
  printf '  %-13s ' "$1"
  if ! command -v node >/dev/null 2>&1; then
    echo "пропущено — немає node"
    return
  fi
  # Код виходу враховується разом із позначками. Раніше дивились лише на
  # ✗/ПРОВАЛЕНО у виводі: набір, що друкував «FAIL» і виходив з кодом 1,
  # показувався зеленим — так client-logging падав непоміченим.
  out=$(cd "../${3:-miniapp}" && node "$2" 2>&1)
  code=$?
  if [[ $code -ne 0 ]] || echo "$out" | grep -qE '✗|ПРОВАЛЕНО|FAIL'; then
    echo "ПРОВАЛ (код $code)"
    # Без позначок у виводі (падіння до першої перевірки) показуємо хвіст.
    echo "$out" | grep -E '✗|FAIL' | head -5 | sed 's/^/      /'
    echo "$out" | grep -qE '✗|FAIL' || echo "$out" | tail -3 | sed 's/^/      /'
    fail=1
  else
    echo "$(echo "$out" | tail -1)"
  fi
}

echo
echo "Вітрина"
run_node cart-response tests/cart-response.mjs
run_node catalog-order tests/catalog-order.mjs
run_node wishlist-state tests/wishlist-state.mjs
run_node wishlist-wiring tests/wishlist-wiring.mjs
run_node checkout tests/checkout-validation.mjs
run_node input-visibility tests/input-visibility.mjs
run_node field-paint tests/field-paint.mjs
run_node phone tests/phone.mjs
run_node client-logging tests/client-logging.mjs
run_node legacy-bridge tests/legacy-bridge.mjs
run_node bridge-runtime tests/legacy-bridge-runtime.mjs
# Набори полів і дизайну. field-guard і text-input стерегли поля, але не
# входили в зведення, як і колишній ui-refresh (він друкував OK/FAIL, а
# зведення бачить лише ✓/✗). Дизайн-набір замінює ui-refresh.
run_node field-guard tests/field-guard.mjs
run_node text-input tests/text-input.mjs
run_node design tests/storefront-design.mjs
run_node crm-status-ui tests/crm-status-source.mjs dashboard
run_node filters tests/filters.mjs dashboard
run_node new-markers tests/new-order-message-markers.mjs dashboard
run_node catalog-ux tests/catalog-ux.mjs dashboard
run_node support-ux tests/support-ux.mjs dashboard
run_node notifications tests/notifications.mjs dashboard
# Ці три набори існували, але в зведення не входили. Два з них уже падали
# (закріплена версія 1.32.1), і цього ніхто не бачив.
run_node payment-ux tests/order-payment-ux.mjs dashboard
run_node volume tests/notification-volume.mjs dashboard
run_node performance tests/performance.mjs dashboard

echo
echo "Контракти й дані"
run contracts tests_contracts.py
run repo tests_repo.py
# Наскрізні сценарії бота. Існували, але в зведення не входили — і
# tests_bot падав непоміченим, відколи маршрут статусів отримав обовʼязкове
# «Прийнято». Саме він проганяє кнопки статусу в чаті.
run bot tests_bot.py
run smoke-api tests_smoke.py
run api tests_api.py
echo
echo "Рівні тестування"
run smoke qa/qa_smoke.py
run negative qa/qa_negative.py
run security qa/qa_security.py
run revoke qa/qa_revoke.py
run headers qa/qa_headers.py
run transport-sec qa/qa_transport_security.py
run security-log qa/qa_security_log.py
run database qa/qa_db.py
run faq qa/qa_faq.py
run faq-flow qa/qa_faq_flow.py
run support qa/qa_support.py
run panel-notify qa/qa_panel_notifications.py
run faq-public qa/qa_faq_public.py
run env qa/qa_env.py
run docs qa/qa_docs.py
run legal qa/qa_legal.py
run scheduler qa/qa_scheduler.py
run public qa/qa_public_chat.py
run logging qa/qa_logging.py
run storefront-log qa/qa_storefront_logging.py
run logs-api qa/qa_logs_api.py
run backups-api qa/qa_backups_api.py
run status-flow qa/qa_status_flow.py
run auto-accept qa/qa_auto_accept.py
run recon qa/qa_recon.py
run alerts qa/qa_alerts.py
run edges qa/qa_edges.py
run dialect qa/qa_dialect.py
run orders_delete qa/qa_orders_delete.py
run settings_save qa/qa_settings_save.py
run novaposhta qa/qa_novaposhta.py
run product-io qa/qa_product_io.py
run e2e qa/qa_e2e.py
run salesdrive qa/qa_salesdrive.py
run sd-dicts qa/qa_salesdrive_dictionaries.py
run sd-no-backfill qa/qa_salesdrive_no_backfill.py
run sd-read-side qa/qa_salesdrive_read_side.py
run crm-status qa/qa_crm_status_authority.py
run salesdrive-source qa/qa_salesdrive_source_guard.py
run wishlists qa/qa_wishlists.py
run performance qa/qa_perf.py

echo
[ $fail -eq 0 ] && echo "Усі набори пройдено" || echo "Є провали — див. вище"
exit $fail
