#!/usr/bin/env bash
# Повний цикл тестування. Запуск: bash qa/run_all.sh
#
# Провалом вважається лише позначка ✗ або рядок ПРОВАЛЕНО. Трейсбеки в
# логах не рахуються: частина наборів навмисно імітує збої Telegram і бази,
# і виняток там — очікуваний результат, а не поломка.
set -u
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD:$PWD/qa"
PY="${PY:-python3}"
fail=0

run() {
  printf '  %-13s ' "$1"
  rm -f /tmp/qa_*.db 2>/dev/null
  out=$($PY "$2" 2>&1)
  summary=$(echo "$out" | grep -E '^[A-ZА-Я]+: [0-9]+/[0-9]+|Всього провалено|усі контракти' | tail -1)
  if echo "$out" | grep -qE '✗|ПРОВАЛЕНО'; then
    echo "ПРОВАЛ — ${summary:-див. деталі}"
    echo "$out" | grep -E '✗' | head -5 | sed 's/^/      /'
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

echo
echo "Контракти й дані"
run contracts tests_contracts.py
run repo tests_repo.py
echo
echo "Рівні тестування"
run smoke qa/qa_smoke.py
run negative qa/qa_negative.py
run security qa/qa_security.py
run database qa/qa_db.py
run faq qa/qa_faq.py
run faq-flow qa/qa_faq_flow.py
run faq-public qa/qa_faq_public.py
run env qa/qa_env.py
run docs qa/qa_docs.py
run legal qa/qa_legal.py
run scheduler qa/qa_scheduler.py
run public qa/qa_public_chat.py
run logging qa/qa_logging.py
run logs-api qa/qa_logs_api.py
run backups-api qa/qa_backups_api.py
run dialect qa/qa_dialect.py
run e2e qa/qa_e2e.py
run performance qa/qa_perf.py

echo
[ $fail -eq 0 ] && echo "Усі набори пройдено" || echo "Є провали — див. вище"
exit $fail
