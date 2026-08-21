"""Сборка GitHub Pages: site/*.html → docs/*.html (index, cases).

Единственный источник правды — site/. Скрипт копирует страницы в
docs/ (каталог, который деплоит .github/workflows/pages.yml),
добавляет generated-заголовок и проверяет инварианты:

- нет служебных маркеров дизайн-референсов в CSS-комментариях;
- нет относительных ссылок на .md (на Pages они отдаются как plain text —
  все ссылки на доки должны вести на github.com blob-URL ветки master).

Запуск из корня репозитория:  python site/build_pages.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGES = ["index.html", "cases.html"]

HEADER = "<!-- GENERATED from site/index.html by site/build_pages.py — do not edit -->\n"

#: Служебные id из черновиков дизайна не должны попадать в продакшн-разметку.
_FORBIDDEN = re.compile(r"musepool|from [a-zA-Z0-9]{6,}\)")

#: Относительные ссылки на markdown — признак неотредактированного исходника.
_RELATIVE_MD = re.compile(r'href="(?!https?://|#|mailto:)[^"]*\.md"')


def main() -> int:
    rc = 0
    for name in PAGES:
        src = ROOT / "site" / name
        dst = ROOT / "docs" / name
        if not src.exists():
            print(f"ERROR: нет исходника {src}", file=sys.stderr)
            rc = 1
            continue
        html = src.read_text(encoding="utf-8")
        problems: list[str] = []
        for match in _FORBIDDEN.finditer(html):
            line = html.count("\n", 0, match.start()) + 1
            problems.append(f"служебный маркер на строке {line}: {match.group(0)!r}")
        for match in _RELATIVE_MD.finditer(html):
            line = html.count("\n", 0, match.start()) + 1
            problems.append(f"относительная ссылка на .md на строке {line}: {match.group(0)!r}")
        if problems:
            for p in problems:
                print(f"ERROR [{name}]: {p}", file=sys.stderr)
            rc = 1
            continue
        dst.write_text(HEADER + html, encoding="utf-8")
        print(f"OK: {dst.relative_to(ROOT)} ({len(html)} chars)")
    return rc


if __name__ == "__main__":
    sys.exit(main())
