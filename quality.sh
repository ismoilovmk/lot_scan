#!/bin/sh
# Проверки качества (ub-mode): ./quality.sh crap | dry | mutate [доп. параметры инструмента]
# Инструменты по умолчанию берут другой Python, без requests, поэтому команды тестов заданы явно.
export PYTHONUTF8=1
COV=target/coverage/python
COVERAGE="python -m coverage run --data-file=$COV/.coverage --source=filters,health,http_client,main,notifier,sources,storage -m pytest -q -p no:cacheprovider && python -m coverage lcov --data-file=$COV/.coverage -o $COV/lcov.info"
mkdir -p "$COV"
tool="$1"
[ $# -gt 0 ] && shift
case "$tool" in
  crap)   crapper --coverage-command "$COVERAGE" --threshold 10 "$@" ;;
  dry)    dryer --threshold 0.8 "$@" ;;
  # mutator запускает мутантов через символические ссылки, а Windows их не даёт (WinError 1314).
  # Поэтому mutator только находит места мутаций, а прогоняет их tests/tools/mutation_run.py.
  # --scan сам покрытие не обновляет, а по нему решает, какие строки покрыты — считаем заново.
  mutate) sh -c "$COVERAGE" > /dev/null 2>&1 || { echo "Тесты не проходят"; exit 2; }
          mutator --use-existing-coverage --scan "$@" > target/mutation-sites.txt 2>&1 \
            && python tests/tools/mutation_run.py target/mutation-sites.txt ;;
  *)      echo "Использование: ./quality.sh crap | dry | mutate"; exit 1 ;;
esac
