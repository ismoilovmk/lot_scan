#!/bin/sh
# Проверки качества (ub-mode): ./quality.sh crap | dry | mutate [доп. параметры инструмента]
# Инструменты по умолчанию берут другой Python, без requests, поэтому команды тестов заданы явно.
export PYTHONUTF8=1
COV=target/coverage/python
COVERAGE="python -m coverage run --data-file=$COV/.coverage --source=filters,http_client,main,notifier,sources,storage -m pytest -q -p no:cacheprovider && python -m coverage lcov --data-file=$COV/.coverage -o $COV/lcov.info"
mkdir -p "$COV"
tool="$1"
[ $# -gt 0 ] && shift
case "$tool" in
  crap)   crapper --coverage-command "$COVERAGE" --threshold 10 "$@" ;;
  dry)    dryer --threshold 0.8 "$@" ;;
  mutate) mutator --coverage-command "$COVERAGE" --test-command "python -m pytest -q -x -p no:cacheprovider" "$@" ;;
  *)      echo "Использование: ./quality.sh crap | dry | mutate"; exit 1 ;;
esac
