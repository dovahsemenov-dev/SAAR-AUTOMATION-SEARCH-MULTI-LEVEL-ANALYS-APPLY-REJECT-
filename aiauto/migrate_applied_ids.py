# ============================================================
# Одноразовый скрипт-мигратор.
#
# Проблема: applied_ids.json — новый файл, он появился только
# в последнем патче. Все вакансии, на которые был подтверждённый
# отклик в ПРОШЛЫХ прогонах (4-5 прогонов назад и раньше), в нём
# не значатся, а REPROCESS_VACANCIES = True не даёт history.json
# их отсеять — поэтому они снова и снова уходят в Qwen-конвейер
# и (после уже отправленного отклика) утыкаются в
# NO_RESPONSE_BUTTON / ALREADY_RESPONDED.
#
# Решение: history.json копится ВСЕ прогоны подряд (его никто не
# затирает) и для каждой вакансии хранит её финальный apply_status
# на момент последнего прогона, где она обрабатывалась. Этого
# достаточно, чтобы восстановить applied_ids.json задним числом,
# не трогая results.csv.
#
# Запуск (один раз, из корня проекта):
#
#     python migrate_applied_ids.py
#
# Скрипт НЕ трогает браузер, HH, Qwen — только читает history.json
# и applied_ids.json на диске и дописывает второй файл. Существующие
# записи в applied_ids.json не перезаписываются и не удаляются —
# только добавляются новые.
# ============================================================

import json
import os

import config


def load_json_dict(path) -> dict:
    if not os.path.exists(path):
        return {}

    try:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (json.JSONDecodeError, OSError):
        return {}

    if not isinstance(data, dict):
        return {}

    return data


def save_json_dict(path, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)

    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


# Та же логика, что и в main.py::_is_permanently_applied_status —
# продублирована здесь намеренно, чтобы скрипт был самодостаточным
# и не тянул за собой playwright/браузерные импорты main.py.
_PERMANENTLY_APPLIED_EXACT_STATUSES = {
    "INSTANT_APPLY_CONFIRMED",
    "ALREADY_RESPONDED",
}


def is_permanently_applied_status(status: str) -> bool:
    status = str(status or "")

    if status.startswith("SUBMITTED_CONFIRMED"):
        return True

    return status in _PERMANENTLY_APPLIED_EXACT_STATUSES


def main() -> None:
    history = load_json_dict(config.HISTORY_FILE)

    print(f"Прочитано записей из history.json: {len(history)}")

    if not history:
        print(
            "history.json пуст или не найден — мигрировать "
            "нечего. Проверь путь config.HISTORY_FILE."
        )
        return

    applied_ids = load_json_dict(config.APPLIED_IDS_FILE)

    print(
        f"Уже было в applied_ids.json до миграции: "
        f"{len(applied_ids)}"
    )

    added = 0
    skipped_not_confirmed = 0
    already_present = 0

    for vacancy_id, entry in history.items():
        if not isinstance(entry, dict):
            continue

        apply_status = entry.get("apply_status", "")

        if not is_permanently_applied_status(apply_status):
            skipped_not_confirmed += 1
            continue

        if vacancy_id in applied_ids:
            already_present += 1
            continue

        applied_ids[vacancy_id] = {
            "status": apply_status,
            "title": "",
            "url": entry.get("url", ""),
        }

        added += 1

    save_json_dict(config.APPLIED_IDS_FILE, applied_ids)

    print()
    print("=" * 60)
    print("ИТОГ МИГРАЦИИ")
    print("=" * 60)
    print(f"Добавлено новых записей в applied_ids.json: {added}")
    print(
        f"Уже были в applied_ids.json (пропущены): "
        f"{already_present}"
    )
    print(
        f"В history.json, но без подтверждённого отклика "
        f"(REJECT/REVIEW/NOT_CONFIRMED и т.п.), не переносились: "
        f"{skipped_not_confirmed}"
    )
    print(f"Итого в applied_ids.json теперь: {len(applied_ids)}")
    print()
    print(
        f"Файл сохранён: {config.APPLIED_IDS_FILE}"
    )


if __name__ == "__main__":
    main()
