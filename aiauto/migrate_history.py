# migrate_history.py

"""
migrate_history.py

Разовая миграция data/history.json под префиксованные id.

Зачем
=====

До появления второго источника id вакансии был голым числом HH:
"137310637". У Хабр Карьеры id тоже числовой ("1000162215"), и
если оставить голые числа, история и дедупликация начнут путать
вакансии с разных площадок.

sources/router.py теперь возвращает id с префиксом источника:

    hh-137310637
    habr-1000162215

Старые записи в history.json без префикса после этого перестанут
совпадать с новыми ключами — бот будет считать все старые вакансии
новыми и погонит их через Qwen заново.

Скрипт дописывает префикс "hh-" ко всем существующим записям.
Перед записью делает резервную копию history.json.bak.

Запуск (один раз, до первого прогона с Хабром):

    python migrate_history.py
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import config


def main() -> None:
    path = Path(config.HISTORY_FILE)

    if not path.exists():
        print(
            f"Файл {path} не найден — мигрировать нечего."
        )
        return

    try:
        with open(path, "r", encoding="utf-8") as file:
            history = json.load(file)

    except (json.JSONDecodeError, OSError) as error:
        print(f"Не удалось прочитать историю: {error}")
        return

    if not isinstance(history, dict):
        print(
            "history.json не является JSON-объектом — "
            "миграция отменена."
        )
        return

    migrated: dict = {}

    changed = 0
    untouched = 0

    for key, value in history.items():
        raw_key = str(key)

        if raw_key.startswith(
            "hh-"
        ) or raw_key.startswith("habr-"):
            migrated[raw_key] = value
            untouched += 1
            continue

        migrated[f"hh-{raw_key}"] = value
        changed += 1

    if changed == 0:
        print(
            "Все записи уже с префиксом — "
            "миграция не нужна."
        )
        return

    backup = path.with_suffix(path.suffix + ".bak")

    shutil.copy2(path, backup)

    print(f"Резервная копия: {backup}")

    with open(path, "w", encoding="utf-8") as file:
        json.dump(
            migrated,
            file,
            ensure_ascii=False,
            indent=2,
        )

    print(
        f"Готово. Переименовано записей: {changed}, "
        f"оставлено как есть: {untouched}. "
        f"Всего в истории: {len(migrated)}."
    )


if __name__ == "__main__":
    main()
