"""Прогон мутаций без символических ссылок (на Windows mutator падает с WinError 1314).

Места мутаций находит сам mutator (--scan); этот скрипт применяет каждую в копии
проекта и запускает тесты. Проект при этом не трогается.

  python tests/tools/mutation_run.py <файл с выводом mutator --scan> [число потоков]
Код выхода: 0 — все мутанты убиты, 2 — тесты не проходят без мутаций, 3 — есть выжившие.
"""
from __future__ import annotations

import ast
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tokenize
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKIP = shutil.ignore_patterns(".git", "target", ".metrics", "__pycache__", ".pytest_cache",
                              ".env", "lots.db", "bot.log", ".coverage")
SITE = re.compile(r"^\s+(?P<file>\S+\.py):(?P<line>\d+) (?P<what>.+?)\s+\[(?P<form>[^\]]+)\]\s*$")
TEST = [sys.executable, "-B", "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider"]


def parse_sites(text: str) -> list[dict]:
    """Строки вида '  main.py:42 or -> and  [defn/run_once]' -> список мест."""
    sites, seen = [], Counter()
    for line in text.splitlines():
        match = SITE.match(line)
        if not match:
            continue
        what = match["what"]
        covered = not what.endswith(" uncovered")   # так mutator помечает строки без покрытия
        what = what.removesuffix(" uncovered")
        old, new = ("not", "") if what == "delete not" else what.split(" -> ")
        key = (match["file"], int(match["line"]), old)
        sites.append({"file": match["file"], "line": int(match["line"]), "old": old, "new": new,
                      "nth": seen[key], "form": match["form"], "what": what, "covered": covered})
        seen[key] += 1
    return sites


def hit_lines(lcov: Path) -> dict[str, set[int]]:
    """Из отчёта LCOV: файл -> номера строк, которые выполнялись в тестах."""
    hits: dict[str, set[int]] = {}
    current: set[int] = set()
    for line in lcov.read_text(encoding="utf-8").splitlines():
        if line.startswith("SF:"):
            path = Path(line[3:])
            name = path.resolve().relative_to(ROOT).as_posix() if path.is_absolute() else path.as_posix()
            current = hits.setdefault(name, set())
        elif line.startswith("DA:"):
            number, count = line[3:].split(",")[:2]
            if int(count) > 0:
                current.add(int(number))
    return hits


def statement_is_hit(source: str, line: int, hits: set[int]) -> bool:
    """coverage отмечает только первую строку многострочной инструкции, а mutator смотрит
    на саму строку. Место покрыто, если выполнялась инструкция, внутри которой оно стоит."""
    inside = [node for node in ast.walk(ast.parse(source))
              if isinstance(node, ast.stmt) and node.lineno <= line <= node.end_lineno]
    innermost = max(inside, key=lambda node: node.lineno)
    return innermost.lineno in hits


def mutate(source: str, line: int, old: str, new: str, nth: int) -> str | None:
    """Заменяет nth-й токен old в строке line. None — если такого токена нет."""
    hits = [tok for tok in tokenize.generate_tokens(io.StringIO(source).readline)
            if tok.start[0] == line and tok.string == old
            and tok.type in (tokenize.NAME, tokenize.OP, tokenize.NUMBER)]
    if nth >= len(hits):
        return None
    tok = hits[nth]
    lines = source.splitlines(keepends=True)
    text = lines[line - 1]
    lines[line - 1] = text[:tok.start[1]] + new + text[tok.end[1]:]
    return "".join(lines)


def tests_pass(workdir: Path) -> bool:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1"}
    try:
        return subprocess.run(TEST, cwd=workdir, env=env, capture_output=True, timeout=120).returncode == 0
    except subprocess.TimeoutExpired:
        return False  # зависший мутант считается убитым


def run_worker(workdir: Path, sites: list[dict], hits: dict[str, set[int]]) -> list[tuple[dict, str]]:
    results = []
    for site in sites:
        path = workdir / site["file"]
        original = path.read_text(encoding="utf-8")
        if not site["covered"] and not statement_is_hit(original, site["line"], hits.get(site["file"], set())):
            results.append((site, "не покрыта"))
            continue
        mutated = mutate(original, site["line"], site["old"], site["new"], site["nth"])
        if mutated is None:
            results.append((site, "не применена"))
            continue
        path.write_text(mutated, encoding="utf-8", newline="")
        try:
            results.append((site, "выжила" if tests_pass(workdir) else "убита"))
        finally:
            path.write_text(original, encoding="utf-8", newline="")
    return results


def main() -> int:
    sites = parse_sites(Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace"))
    hits = hit_lines(ROOT / "target" / "coverage" / "python" / "lcov.info")
    workers = max(1, min(int(sys.argv[2]) if len(sys.argv) > 2 else os.cpu_count() or 1, len(sites) or 1))
    with tempfile.TemporaryDirectory(prefix="rm-mutants-") as tmp:
        dirs = [Path(tmp) / f"w{i}" for i in range(workers)]
        for directory in dirs:
            shutil.copytree(ROOT, directory, ignore=SKIP)
        if not tests_pass(dirs[0]):
            print("Тесты не проходят и без мутаций — сначала почините их.")
            return 2
        with ThreadPoolExecutor(workers) as pool:
            batches = pool.map(run_worker, dirs, [sites[i::workers] for i in range(workers)], [hits] * workers)
            results = [item for batch in batches for item in batch]
    results.sort(key=lambda r: (r[0]["file"], r[0]["line"]))
    counts = Counter(status for _, status in results)
    for site, status in results:
        if status != "убита":
            print(f"{status.upper()}: {site['file']}:{site['line']} {site['what']}  [{site['form']}]")
    print(f"Мутаций: {len(results)}, убито: {counts['убита']}, выжило: {counts['выжила']}, "
          f"не покрыто: {counts['не покрыта']}, не применено: {counts['не применена']}")
    return 0 if counts["убита"] == len(results) else 3


if __name__ == "__main__":
    sys.exit(main())
