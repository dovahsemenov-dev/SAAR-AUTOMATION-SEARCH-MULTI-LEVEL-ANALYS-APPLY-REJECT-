# main.py

import csv
import json
import os
import random
import time
import config
from hh.browser import (
    start_browser,
    stop_browser,
    check_blocked,
    wait_for_unblock,
    BlockedPageError,
)

# ============================================================
# РОУТЕР ИСТОЧНИКОВ
# ============================================================
#
# Раньше здесь было три прямых импорта из hh.*:
#
#     from hh.search  import collect_vacancies
#     from hh.vacancy import open_vacancy
#     from hh.apply   import respond_to_vacancy, check_already_responded
#
# Теперь те же четыре функции приходят из router.py. Он смотрит
# на домен URL и отдаёт вызов нужному адаптеру:
#
#     hh.ru / *.hh.ru  -> hh/*     (существующий код, не тронут)
#     career.habr.com  -> habr/*
#
# Сигнатуры функций совпадают с прежними один в один, поэтому
# ниже по файлу ничего менять не пришлось.
# ============================================================

from router import (
    collect_vacancies,
    open_vacancy,
    respond_to_vacancy,
    check_already_responded,
)
from ai.ollama_client import check_ready
from ai.classifier import classify_vacancy
from ai.requirements_analyzer import (
    analyze_requirements,
)
from ai.evaluator import evaluate_vacancy
from ai.fact_selector import select_facts
from ai.cover_letter import (
    generate_cover_letter,
)
from ai.letter_validator import (
    validate_letter,
)
from filters.rules import (
    quick_reject,
    check_geography,
    check_experience,
    check_extended_target_constraints,
)
from filters.decision_guard import (
    apply_decision_guard,
    apply_post_evaluator_guard,
)


def load_text(path) -> str:
    with open(path, "r", encoding="utf-8") as file:
        return file.read().strip()


def load_json(path) -> dict:
    with open(path, "r", encoding="utf-8") as file:
        data = json.load(file)
        if not isinstance(data, dict):
            raise RuntimeError(f"{path} должен содержать JSON-объект.")
        return data


def load_history(path) -> dict:
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


def save_history(path, history: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)

    with open(path, "w", encoding="utf-8") as file:
        json.dump(history, file, ensure_ascii=False, indent=2)


# ============================================================
# Постоянный список окончательно отвеченных вакансий
# (см. config.APPLIED_IDS_FILE)
# ============================================================
#
# В отличие от history.json, этот файл не предназначен для очистки:
# history можно чистить, чтобы пере-оценить ранее отклонённые
# вакансии после смены PROFILE/PREFERENCES, а повторно откликаться
# на вакансию, на которую отклик уже подтверждён, не нужно никогда —
# независимо от REPROCESS_VACANCIES и от состояния history.json.

def load_applied_ids(path) -> dict:
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


def save_applied_ids(path, applied_ids: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)

    with open(path, "w", encoding="utf-8") as file:
        json.dump(applied_ids, file, ensure_ascii=False, indent=2)


# Статусы, которые hh/apply.py и habr/apply.py возвращают, когда
# доставка отклика реально подтверждена (сетью, reload-проверкой,
# либо HH/Хабр сразу показали "уже откликнулись"). Неподтверждённые
# варианты (*_NOT_CONFIRMED, голый "SUBMITTED" из
# hh/complex_application.py) сюда намеренно НЕ входят — это
# кандидаты на повторную попытку в следующем прогоне, а не на
# постоянное исключение из очереди.
_PERMANENTLY_APPLIED_EXACT_STATUSES = {
    "INSTANT_APPLY_CONFIRMED",
    "ALREADY_RESPONDED",
}


def _is_permanently_applied_status(status: str) -> bool:
    status = str(status or "")

    if status.startswith("SUBMITTED_CONFIRMED"):
        return True

    return status in _PERMANENTLY_APPLIED_EXACT_STATUSES


def record_applied_id(
    path,
    applied_ids: dict,
    vacancy_id: str,
    apply_status: str,
    vacancy: dict | None,
) -> None:
    """
    Сохраняет вакансию в постоянный список отвеченных сразу же, как
    только apply_status подтверждён — а не только в конце прогона.
    При обрыве посреди списка (капча, критическая ошибка, ручная
    остановка) уже подтверждённые отклики не потеряются и не
    повторятся на следующем прогоне.
    """
    if not _is_permanently_applied_status(apply_status):
        return

    applied_ids[vacancy_id] = {
        "status": apply_status,
        "title": (vacancy or {}).get("title", ""),
        "url": (vacancy or {}).get("url", ""),
    }

    save_applied_ids(path, applied_ids)


def append_result_csv(path, row: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    file_exists = os.path.exists(path)

    fieldnames = [
        "id",
        "title",
        "company",
        "salary",
        "experience",
        "work_format",
        "location",
        "geography_status",
        "seniority",
        "experience_required",
        "experience_importance",
        "decision",
        "score",
        "letter_status",
        "apply_status",
        "url",
        "summary",
    ]

    with open(path, "a", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)

        if not file_exists:
            writer.writeheader()

        writer.writerow(row)


def save_cover_letter(
    vacancy_id: str,
    vacancy: dict,
    selected_facts: list[dict],
    letter: str,
    validation: dict,
    apply_status: str,
) -> str:
    config.COVER_LETTERS_DIR.mkdir(parents=True, exist_ok=True)

    path = config.COVER_LETTERS_DIR / f"{vacancy_id}.txt"

    lines = [
        f"ВАКАНСИЯ: {vacancy.get('title', '')}",
        f"КОМПАНИЯ: {vacancy.get('company', '')}",
        f"URL: {vacancy.get('url', '')}",
        "",
        "ИСПОЛЬЗОВАННЫЕ ПОДТВЕРЖДЁННЫЕ ФАКТЫ:",
    ]

    if selected_facts:
        for item in selected_facts:
            lines.append("- " + str(item.get("fact", "")))
    else:
        lines.append("- факты не выбраны")

    lines.extend(
        [
            "",
            "СОПРОВОДИТЕЛЬНОЕ:",
            letter or "[ПИСЬМО НЕ СОЗДАНО]",
            "",
            "VALIDATION: " + str(validation.get("status", "REQUIRES_USER")),
        ]
    )

    problems = validation.get("problems", [])

    if problems:
        lines.append("ПРОБЛЕМЫ:")

        for problem in problems:
            lines.append(f"- {problem}")

    lines.extend(["", f"ОТПРАВКА: {apply_status}"])

    path.write_text("\n".join(lines), encoding="utf-8")

    return str(path)


def save_debug_dump(
    vacancy_id: str,
    vacancy: dict,
    geography: dict,
    classification: dict | None,
    requirements: dict | None,
    evaluation: dict | None,
    reject_reason: str | None,
    selected_facts: list[dict] | None,
    letter: str | None,
    validation: dict | None,
    apply_result: dict | None,
) -> str:
    config.DEBUG_DUMP_DIR.mkdir(parents=True, exist_ok=True)

    path = config.DEBUG_DUMP_DIR / f"{vacancy_id}.txt"

    work_format = vacancy.get("work_format") or {}

    lines = [
        "=" * 70,
        "ИСХОДНЫЕ ДАННЫЕ ВАКАНСИИ ИЗ DOM HH",
        "=" * 70,
        f"НАЗВАНИЕ: {vacancy.get('title', '')}",
        f"КОМПАНИЯ: {vacancy.get('company', '')}",
        f"ЗАРПЛАТА: {vacancy.get('salary', '')}",
        f"ОПЫТ: {vacancy.get('experience', '')}",
        f"ЗАНЯТОСТЬ: {vacancy.get('employment', '')}",
        f"ГРАФИК: {vacancy.get('schedule', '')}",
        f"РАБОЧИЕ ЧАСЫ: {vacancy.get('working_hours', '')}",
        f"ФОРМАТ РАБОТЫ: {work_format.get('raw', '')}",
        f"REMOTE: {work_format.get('remote')}",
        f"OFFICE: {work_format.get('office')}",
        f"HYBRID: {work_format.get('hybrid')}",
        f"UNKNOWN FORMAT: {work_format.get('unknown')}",
        f"МЕСТОПОЛОЖЕНИЕ: {vacancy.get('location', '')}",
        "КЛЮЧЕВЫЕ НАВЫКИ: " + ", ".join(vacancy.get("skills", [])),
        f"URL: {vacancy.get('url', '')}",
        "",
        "ПОЛНОЕ ОПИСАНИЕ:",
        "-" * 70,
        vacancy.get("description", "") or "[ОПИСАНИЕ ПУСТОЕ]",
        "-" * 70,
        "",
        "=" * 70,
        "ПРОГРАММНЫЕ ПРОВЕРКИ",
        "=" * 70,
        f"GEOGRAPHY STATUS: {geography.get('status', '')}",
        f"GEOGRAPHY REASON: {geography.get('reason', '')}",
    ]

    if reject_reason:
        lines.extend(["", f"БЫСТРЫЙ ОТКАЗ: {reject_reason}"])

    if classification is not None:
        lines.extend(
            [
                "",
                "КЛАССИФИКАЦИЯ:",
                f"is_it_role = {classification.get('is_it_role')}",
                f"role_summary = {classification.get('role_summary', '')}",
                f"reason = {classification.get('reason', '')}",
                f"guard_applied = {classification.get('guard_applied')}",
            ]
        )

    if requirements is not None:
        lines.extend(
            [
                "",
                "=" * 70,
                "STRUCTURED REQUIREMENTS",
                "=" * 70,
                json.dumps(requirements, ensure_ascii=False, indent=2),
            ]
        )

    if evaluation is not None:
        lines.extend(
            [
                "",
                "EVALUATOR:",
                f"decision = {evaluation.get('decision', '')}",
                f"score = {evaluation.get('score', '')}",
                "reasons:",
            ]
        )

        for reason in evaluation.get("reasons", []):
            lines.append(f" • {reason}")

        missing = evaluation.get("missing", [])

        if missing:
            lines.append("missing:")

            for item in missing:
                lines.append(f" • {item}")

        lines.append("summary = " + str(evaluation.get("summary", "")))

    if selected_facts is not None:
        lines.extend(
            [
                "",
                "ВЫБРАННЫЕ ФАКТЫ ДЛЯ ПИСЬМА:",
            ]
        )

        if selected_facts:
            for item in selected_facts:
                lines.append(
                    " • "
                    + str(item.get("fact", ""))
                    + " ("
                    + str(item.get("relevance", ""))
                    + ")"
                )
        else:
            lines.append(" (факты не выбраны)")

    if letter is not None:
        lines.extend(
            [
                "",
                "СГЕНЕРИРОВАННОЕ ПИСЬМО:",
                "-" * 70,
                letter or "[ПИСЬМО НЕ СОЗДАНО]",
                "-" * 70,
            ]
        )

    if validation is not None:
        lines.extend(
            [
                "",
                f"VALIDATION: {validation.get('status', '')}",
            ]
        )

        for problem in validation.get("problems", []):
            lines.append(f" • {problem}")

    if apply_result is not None:
        lines.extend(
            [
                "",
                "=" * 70,
                "HH.APPLY",
                "=" * 70,
                f"status = {apply_result.get('status', '')}",
                f"reason = {apply_result.get('reason', '')}",
            ]
        )

        if apply_result.get("resume_warning"):
            lines.append(
                f"resume_warning = {apply_result['resume_warning']}"
            )

    path.write_text("\n".join(lines), encoding="utf-8")

    return str(path)


def main():
    print("=" * 70)
    print("HH LOCAL JOB AGENT — Playwright + Qwen, без HH API")
    print("=" * 70)

    if config.DEBUG_MODE:
        print("\n[DEBUG_MODE = True] Сохраняются диагностические дампы:")
        print(config.DEBUG_DUMP_DIR)

    print("\nПроверяю Ollama и модель...")

    if not check_ready(
        config.OLLAMA_URL,
        config.OLLAMA_MODEL,
    ):
        print("Ollama или модель недоступны.")
        return

    print("Ollama и модель готовы.")

    try:
        profile = load_text(config.PROFILE_FILE)
        preferences = load_text(config.PREFERENCES_FILE)
        profile_facts = load_json(config.PROFILE_FACTS_FILE)

    except Exception as error:
        print("Ошибка загрузки профиля:")
        print(error)
        return

    print("PROFILE / PREFERENCES / PROFILE_FACTS загружены.")

    history = load_history(config.HISTORY_FILE)

    print(f"В истории уже есть: {len(history)} вакансий")

    applied_ids = load_applied_ids(config.APPLIED_IDS_FILE)

    print(
        f"Окончательно отвеченных вакансий (не будут открываться "
        f"повторно, см. {config.APPLIED_IDS_FILE.name}): "
        f"{len(applied_ids)}"
    )

    print("\nЗапускаю Chrome...")

    playwright, context, page = start_browser(
        config.CHROME_PROFILE_DIR,
        config.HEADLESS,
    )

    try:
        if not wait_for_unblock(
            page,
            stage="перед началом сбора вакансий",
            max_wait_sec=config.CAPTCHA_MAX_WAIT_SEC,
            poll_interval_sec=config.CAPTCHA_POLL_INTERVAL_SEC,
            vision_enabled=config.CAPTCHA_VISION_ENABLED,
            vision_ollama_url=config.OLLAMA_URL,
            vision_model=config.CAPTCHA_VISION_MODEL,
            vision_region={
                "x": config.CAPTCHA_SCREENSHOT_X,
                "y": config.CAPTCHA_SCREENSHOT_Y,
                "width": config.CAPTCHA_SCREENSHOT_WIDTH,
                "height": config.CAPTCHA_SCREENSHOT_HEIGHT,
            },
        ):
            print("HH требует проверку/капчу. Останавливаюсь.")
            return

        print(
            f"\nСобираю ссылки по списку поисковых URL "
            f"({len(config.SEARCH_URLS)} шт.)..."
        )

        vacancies_short = []
        seen_ids = set()

        for url_index, search_url in enumerate(
            config.SEARCH_URLS,
            start=1,
        ):
            print(
                f"\n[{url_index}/{len(config.SEARCH_URLS)}] "
                f"{search_url}"
            )

            found = collect_vacancies(
                page,
                search_url,
                config.MAX_VACANCIES_PER_URL,
            )

            new_count = 0

            for item in found:
                if item["id"] in seen_ids:
                    continue

                seen_ids.add(item["id"])
                vacancies_short.append(item)
                new_count += 1

            print(
                f"Найдено: {len(found)}, "
                f"новых (без дублей): {new_count}"
            )

        # Всё, что ниже, выполняется ОДИН раз, уже после того как
        # собраны и объединены вакансии со всех SEARCH_URLS.
        print(
            f"\nВсего уникальных вакансий по всем URL: "
            f"{len(vacancies_short)}"
        )

        if not vacancies_short:
            print("Вакансий не найдено. Проверь SEARCH_URLS.")
            return

        # Искусственной обрезки количества ПРОСМАТРИВАЕМЫХ вакансий
        # нет — просмотр сам по себе не тот параметр, на который
        # стоит давить (см. договорённость: лимит должен быть на
        # ОТКЛИКАХ, а не на просмотрах). Единственный реальный лимит
        # за прогон — config.MAX_APPLIES_PER_RUN, по количеству
        # решений APPLY, применяется ниже в основном цикле.

        stats = {
            "APPLY": 0,
            "REVIEW": 0,
            "REJECT": 0,
            "SKIPPED": 0,
            "ERROR": 0,
            "LETTER_PASS": 0,
            "LETTER_REQUIRES_USER": 0,
            # ФИКС (см. hh/apply.py, докстринг, ФИКС №3): сколько
            # вакансий были отсечены как "уже откликались" СРАЗУ
            # после открытия страницы, до Qwen-конвейера — отдельно
            # от обычного REJECT, чтобы в ИТОГЕ было видно, сколько
            # LLM-вызовов и времени реально сэкономлено этой
            # проверкой за прогон.
            "ALREADY_RESPONDED_EARLY": 0,
            # ФИКС (см. hh/apply.py, докстринг, ФИКС №5): отдельно
            # считаем случаи, когда отклик был отправлен, но его
            # реальная доставка НЕ подтвердилась (ни по сети, ни по
            # перезагрузке страницы) — раньше такие случаи молча
            # тонули внутри общего "INSTANT_APPLY" и выглядели как
            # успех, хотя по факту это ровно те самые "отклики, что
            # не доходят".
            "APPLY_CONFIRMED": 0,
            "APPLY_NOT_CONFIRMED": 0,
            # Сколько вакансий отсечены по applied_ids.json — то есть
            # даже без открытия страницы, потому что на них уже точно
            # был подтверждён отклик в одном из прошлых прогонов.
            "SKIPPED_PERMANENTLY_APPLIED": 0,
        }

        processed_count = 0

        for index, short_vacancy in enumerate(
            vacancies_short,
            start=1,
        ):
            vacancy_id = short_vacancy["id"]

            print("\n" + "-" * 70)
            print(
                f"[{index}/{len(vacancies_short)}] "
                f"{short_vacancy['title']}"
            )

            # ФИКС (applied_ids.json): проверяем ПЕРВОЙ, до паузы и
            # до открытия страницы — независимо от REPROCESS_VACANCIES
            # и от history.json. Если отклик на эту вакансию уже точно
            # подтверждён в прошлом прогоне, вакансия даже не
            # открывается браузером, не говоря уже про Qwen.
            if vacancy_id in applied_ids:
                print(
                    "Пропущено (отклик уже окончательно подтверждён "
                    "ранее, см. applied_ids.json)."
                )
                stats["SKIPPED_PERMANENTLY_APPLIED"] += 1
                continue

            if (
                not config.REPROCESS_VACANCIES
                and vacancy_id in history
            ):
                print("Пропущено (есть в истории).")
                stats["SKIPPED"] += 1
                continue

            # ФИКС (пауза): раньше пауза отрабатывала по позиции в
            # общем списке (index > 1), то есть ждали даже перед
            # вакансиями, которые тут же пропускались проверками выше.
            # Теперь пауза считается только для вакансий, которые
            # реально доходят до обработки (processed_count).
            processed_count += 1

            if processed_count > 1:
                delay = random.uniform(
                    config.MIN_DELAY_SEC,
                    config.MAX_DELAY_SEC,
                )

                print(
                    f"Пауза: {delay:.1f} сек."
                )

                time.sleep(delay)

            vacancy = None
            geography = {
                "status": "UNKNOWN",
                "reason": "",
            }

            reject_reason = None
            classification = None
            requirements = None
            evaluation = None
            selected_facts = None
            letter = None
            validation = None
            apply_result = None
            apply_status = "NOT_ATTEMPTED"
            decision = None

            try:
                if check_blocked(page):
                    if not wait_for_unblock(
                        page,
                        stage="перед открытием вакансии",
                        max_wait_sec=config.CAPTCHA_MAX_WAIT_SEC,
                        poll_interval_sec=config.CAPTCHA_POLL_INTERVAL_SEC,
                        vision_enabled=config.CAPTCHA_VISION_ENABLED,
                        vision_ollama_url=config.OLLAMA_URL,
                        vision_model=config.CAPTCHA_VISION_MODEL,
                        vision_region={
                            "x": config.CAPTCHA_SCREENSHOT_X,
                            "y": config.CAPTCHA_SCREENSHOT_Y,
                            "width": config.CAPTCHA_SCREENSHOT_WIDTH,
                            "height": config.CAPTCHA_SCREENSHOT_HEIGHT,
                        },
                    ):
                        break

                vacancy = open_vacancy(
                    page,
                    short_vacancy["url"],
                )

                # Защита от ситуации, когда HH показывает CAPTCHA уже
                # после открытия страницы вакансии. Не передаём такую
                # страницу в Qwen — но и не роняем весь прогон сразу:
                # сначала пауза-и-восстановление, break/raise только
                # если блокировка не снята за отведённое время.
                if check_blocked(page):
                    if not wait_for_unblock(
                        page,
                        stage="после open_vacancy",
                        max_wait_sec=config.CAPTCHA_MAX_WAIT_SEC,
                        poll_interval_sec=config.CAPTCHA_POLL_INTERVAL_SEC,
                        vision_enabled=config.CAPTCHA_VISION_ENABLED,
                        vision_ollama_url=config.OLLAMA_URL,
                        vision_model=config.CAPTCHA_VISION_MODEL,
                        vision_region={
                            "x": config.CAPTCHA_SCREENSHOT_X,
                            "y": config.CAPTCHA_SCREENSHOT_Y,
                            "width": config.CAPTCHA_SCREENSHOT_WIDTH,
                            "height": config.CAPTCHA_SCREENSHOT_HEIGHT,
                        },
                    ):
                        raise BlockedPageError(
                            "HH CAPTCHA/блокировка обнаружена "
                            "после open_vacancy, ожидание истекло."
                        )

                already_responded_check = (
                    check_already_responded(page)
                )

                if already_responded_check[
                    "already_responded"
                ]:

                    # ФИКС №3 (см. hh/apply.py, докстринг модуля):
                    # HH уже показывает эту вакансию как
                    # "отклик отправлен" прямо при открытии
                    # страницы — отсекаем здесь, ДО quick_reject/
                    # geography/experience и ДО любых вызовов Qwen,
                    # вместо того чтобы узнавать об этом только
                    # после полного прогона конвейера и клика по
                    # "Откликнуться" (respond_to_vacancy).

                    work_format = (
                        vacancy.get("work_format") or {}
                    )

                    print(f"Компания: {vacancy['company']}")
                    print(f"Зарплата: {vacancy['salary']}")
                    print(
                        f"Местоположение: "
                        f"{vacancy['location']}"
                    )

                    print(
                        "\n[EARLY CHECK] Уже откликались на эту "
                        "вакансию ранее — обнаружено сразу при "
                        "открытии страницы, до запуска "
                        "Qwen-конвейера."
                    )
                    print(
                        f" • "
                        f"{already_responded_check['reason']}"
                    )

                    decision, score, summary = (
                        "REJECT",
                        0,
                        already_responded_check["reason"],
                    )
                    reasons, missing = [summary], []
                    apply_status = "ALREADY_RESPONDED"

                    stats["ALREADY_RESPONDED_EARLY"] += 1

                    record_applied_id(
                        config.APPLIED_IDS_FILE,
                        applied_ids,
                        vacancy_id,
                        apply_status,
                        vacancy,
                    )

                    # geography остаётся дефолтным ("UNKNOWN") —
                    # инициализирован до try, здесь намеренно не
                    # проверяется, ниже (save_debug_dump,
                    # append_result_csv) это отражает то, что
                    # проверка не выполнялась.

                else:
                    work_format = vacancy.get("work_format") or {}

                    print(f"Компания: {vacancy['company']}")
                    print(f"Зарплата: {vacancy['salary']}")
                    print(
                        f"Формат работы: "
                        f"{work_format.get('raw', '')}"
                    )
                    print(
                        f"Местоположение: "
                        f"{vacancy['location']}"
                    )
                    print(
                        f"OFFICE / HYBRID / REMOTE: "
                        f"{work_format.get('office')} / "
                        f"{work_format.get('hybrid')} / "
                        f"{work_format.get('remote')}"
                    )

                    reject_reason = quick_reject(
                        vacancy,
                        config.STOP_WORDS_IN_TITLE,
                    )

                    # Performance / SEO(+Technical SEO) / Data-BI
                    # имеют отдельные пользовательские ограничения:
                    # только REMOTE, только NO EXPERIENCE, без прямых
                    # продаж/звонков/постоянного клиентского ведения.
                    # Для старых профессий функция вернёт NOT_TARGET
                    # и ничего в прежнем pipeline не изменит.
                    extended_target = check_extended_target_constraints(
                        vacancy
                    )

                    if extended_target["status"] != "NOT_TARGET":
                        print(
                            "EXTENDED TARGET CHECK: "
                            f"{extended_target['status']} | "
                            f"role={extended_target.get('role')}"
                        )
                        print(
                            "EXTENDED TARGET REASON: "
                            f"{extended_target['reason']}"
                        )

                    if (
                        not reject_reason
                        and extended_target["status"] == "REJECT"
                    ):
                        reject_reason = extended_target["reason"]

                    geography = check_geography(vacancy)

                    print(
                        f"GEOGRAPHY CHECK: "
                        f"{geography['status']}"
                    )
                    print(
                        f"GEOGRAPHY REASON: "
                        f"{geography['reason']}"
                    )

                    experience_check = check_experience(
                        vacancy,
                        config.MAX_EXPERIENCE_YEARS_MIN,
                    )

                    print(
                        f"EXPERIENCE CHECK: "
                        f"{experience_check['status']}"
                    )
                    print(
                        f"EXPERIENCE REASON: "
                        f"{experience_check['reason']}"
                    )

                    if reject_reason:
                        decision, score, summary = (
                            "REJECT",
                            0,
                            reject_reason,
                        )
                        reasons, missing = [reject_reason], []

                    elif geography["status"] == "REJECT":
                        decision, score = "REJECT", 5
                        summary = (
                            "Отклонено программной проверкой "
                            f"географии: {geography['reason']}"
                        )
                        reasons, missing = [summary], []

                    elif experience_check["status"] == "REJECT":
                        decision, score, summary = (
                            "REJECT",
                            5,
                            experience_check["reason"],
                        )
                        reasons, missing = [summary], []

                    else:
                        print(
                            "Qwen классифицирует профессию "
                            "(без PROFILE)..."
                        )

                        classification = classify_vacancy(
                            config.OLLAMA_URL,
                            config.OLLAMA_MODEL,
                            vacancy,
                        )

                        print(
                            f"Классификация: "
                            f"is_it_role="
                            f"{classification['is_it_role']} | "
                            f"{classification['role_summary']}"
                        )

                        if not classification["is_it_role"]:
                            decision, score = "REJECT", 5
                            summary = (
                                "Отклонено на этапе "
                                "классификации профессии: "
                                f"{classification['role_summary']}"
                            )
                            reasons, missing = [summary], []

                        else:
                            print(
                                "Qwen структурирует "
                                "требования вакансии..."
                            )

                            requirements = analyze_requirements(
                                config.OLLAMA_URL,
                                config.OLLAMA_MODEL,
                                vacancy,
                            )

                            print("Требования:")
                            print(
                                f" • seniority: "
                                f"{requirements['seniority']}"
                            )

                            exp = requirements["experience"]

                            print(
                                f" • опыт: "
                                f"{exp['years_min']} | "
                                f"{exp['importance']}"
                            )

                            education = requirements["education"]

                            print(
                                f" • образование: "
                                f"{education['requirement']} | "
                                f"{education['importance']}"
                            )

                            print(
                                f" • flexibility: "
                                f"{requirements['flexibility']}"
                            )

                            if requirements["hard_blockers"]:
                                print(" • hard blockers:")

                                for blocker in requirements[
                                    "hard_blockers"
                                ]:
                                    print(f" - {blocker}")

                            guard_result = apply_decision_guard(
                                requirements,
                                vacancy_title=vacancy.get("title", ""),
                            )

                            if guard_result is not None:
                                print(
                                    "\n[decision_guard] "
                                    "Явное детерминированное решение — "
                                    "Qwen (evaluator) НЕ вызывается."
                                )

                                evaluation = guard_result

                                decision = evaluation["decision"]
                                score = evaluation["score"]
                                summary = evaluation.get(
                                    "summary",
                                    "",
                                )

                                reasons = evaluation.get(
                                    "reasons",
                                    [],
                                )

                                missing = evaluation.get(
                                    "missing",
                                    [],
                                )

                            else:
                                print(
                                    "Qwen анализирует "
                                    "соответствие профилю..."
                                )

                                evaluation = evaluate_vacancy(
                                    config.OLLAMA_URL,
                                    config.OLLAMA_MODEL,
                                    vacancy,
                                    profile,
                                    preferences,
                                    profile_facts,
                                    requirements,
                                )

                                # ==========================================
                                # Программный слой ПОСЛЕ evaluator
                                # (decision_guard):
                                #
                                # 1) чистит из reasons/missing галлюцинации
                                #    про географию/формат работы, которые
                                #    evaluator'у прямо запрещено использовать
                                #    (эти параметры уже проверены
                                #    детерминированно выше);
                                #
                                # 2) переопределяет REVIEW -> APPLY,
                                #    т.к. это автокликер, а не анализатор:
                                #    REVIEW пользователь не читает, а жёсткие
                                #    случаи уже отсечены как REJECT
                                #    в apply_decision_guard() до вызова evaluator.
                                #
                                # Применяется только к решению самого evaluator —
                                # ветка guard_result (REJECT по hard-правилам)
                                # её не проходит и остаётся как есть.
                                # ==========================================

                                evaluation = apply_post_evaluator_guard(
                                    evaluation,
                                    requirements,
                                    vacancy_title=vacancy.get("title", ""),
                                )

                                decision = evaluation["decision"]
                                score = evaluation["score"]
                                summary = evaluation.get(
                                    "summary",
                                    "",
                                )

                                reasons = evaluation.get(
                                    "reasons",
                                    [],
                                )

                                missing = evaluation.get(
                                    "missing",
                                    [],
                                )

                            # REVIEW не является рабочим конечным состоянием.
                            # Неизвестная/неразобранная вилка HH сама по себе
                            # НЕ блокирует APPLY: обязательность опыта уже
                            # проверяется по STRUCTURED REQUIREMENTS ниже.
                            # Аналогично, неизвестный формат/география здесь
                            # не переопределяет решение evaluator: если формат
                            # действительно офисный, check_geography выше уже
                            # дал REJECT; если он не распознан — не надо
                            # превращать нормальный Junior APPLY в REVIEW.


                print()
                print(
                    f"РЕШЕНИЕ: {decision} | "
                    f"ОЦЕНКА: {score}/100\n"
                    f"Причины:"
                )

                if reasons:
                    for reason in reasons:
                        print(f" • {reason}")
                else:
                    print(" • Причины не указаны.")

                if missing:
                    print("\nЧего не хватает в профиле:")

                    for item in missing:
                        print(f" • {item}")

                print(f"Вывод: {summary}")

                if decision in {
                    "APPLY",
                    "REVIEW",
                    "REJECT",
                }:
                    stats[decision] += 1
                else:
                    stats["ERROR"] += 1

                # ==========================================
                # Лимит откликов за прогон — не на просмотрах.
                # См. config.MAX_APPLIES_PER_RUN. Здесь только
                # сообщение; сама остановка цикла — ниже, после
                # завершения обработки текущей вакансии (чтобы
                # письмо/отклик по ней доделались до конца).
                # ==========================================

                if (
                    decision == "APPLY"
                    and stats["APPLY"]
                    >= config.MAX_APPLIES_PER_RUN
                ):
                    print(
                        f"\nДостигнут лимит откликов "
                        f"за прогон "
                        f"({config.MAX_APPLIES_PER_RUN}). "
                        f"Останавливаю обработку "
                        f"оставшихся вакансий."
                    )

                letter_status = "NOT_GENERATED"

                if (
                    config.GENERATE_COVER_LETTERS
                    and decision in config.COVER_LETTER_DECISIONS
                ):
                    print(
                        "\nВыбираю подтверждённые "
                        "факты для письма..."
                    )

                    selected_facts = select_facts(
                        config.OLLAMA_URL,
                        config.OLLAMA_MODEL,
                        vacancy,
                        profile_facts,
                    )

                    if selected_facts:
                        print("Выбранные факты:")

                        for item in selected_facts:
                            print(
                                f" • {item['fact']}"
                            )

                        print(
                            "\nQwen создаёт сопроводительное..."
                        )

                        letter = generate_cover_letter(
                            config.OLLAMA_URL,
                            config.OLLAMA_MODEL,
                            vacancy,
                            selected_facts,
                        )

                        print(
                            "\nСОПРОВОДИТЕЛЬНОЕ:\n"
                            + "-" * 70
                        )

                        print(
                            letter
                            or "[ПИСЬМО НЕ СОЗДАНО]"
                        )

                        print("-" * 70)

                        print(
                            "\nПроверяю письмо..."
                        )

                        validation = validate_letter(
                            config.OLLAMA_URL,
                            config.OLLAMA_MODEL,
                            letter,
                            profile,
                            profile_facts,
                            selected_facts,
                        )

                    else:
                        letter = ""

                        validation = {
                            "status": "REQUIRES_USER",
                            "problems": [
                                "Не удалось выбрать "
                                "подтверждённые факты."
                            ],
                        }

                    letter_status = validation["status"]

                    print(
                        f"VALIDATION: {letter_status}"
                    )

                    for problem in validation.get(
                        "problems",
                        [],
                    ):
                        print(f" • {problem}")

                    if letter_status == "PASS":
                        stats["LETTER_PASS"] += 1
                    else:
                        stats["LETTER_REQUIRES_USER"] += 1

                    # ==========================================
                    # Отклик работодателю (реальный или DRY_RUN —
                    # решает config.DRY_RUN внутри respond_to_vacancy).
                    #
                    # Отправляем только письмо, прошедшее валидацию —
                    # непроверенное письмо не заполняем в форму даже
                    # в DRY_RUN, чтобы дамп формы был осмысленным.
                    # ==========================================

                    if letter_status == "PASS":
                        print(
                            "\nОткликаюсь на вакансию..."
                        )

                        apply_result = respond_to_vacancy(
                            page,
                            letter,
                            config.DRY_RUN,
                            vacancy_text=vacancy.get(
                                "description",
                                "",
                            ),
                            profile_facts=profile_facts,
                            ollama_url=config.OLLAMA_URL,
                            model_name=config.OLLAMA_MODEL,
                            vacancy_id=vacancy_id,
                            response_kind=vacancy.get(
                                "response_kind",
                                "",
                            ),
                        )

                        apply_status = apply_result["status"]

                        # ==========================================
                        # ФИКС (счётчик ошибок): apply_status == "ERROR"
                        # раньше нигде не попадал в stats["ERROR"] —
                        # этот счётчик увеличивался только в блоке
                        # except ниже, на python-исключениях. Реальные
                        # HH.APPLY: ERROR (например, Playwright не смог
                        # заполнить поле анкеты) проходили мимо
                        # счётчика, поэтому итоговая сводка "Ошибки: 0"
                        # была неверной даже при наличии реальных
                        # ошибок в этом же прогоне.
                        # ==========================================

                        if apply_status == "ERROR":
                            stats["ERROR"] += 1

                        record_applied_id(
                            config.APPLIED_IDS_FILE,
                            applied_ids,
                            vacancy_id,
                            apply_status,
                            vacancy,
                        )

                        # ==========================================
                        # ФИКС №5 (см. hh/apply.py, докстринг): считаем
                        # отдельно подтверждённые и НЕподтверждённые
                        # отклики. "Подтверждённые" — сервер реально
                        # зафиксировал отклик (network-сигнал или
                        # проверка через reload). "НЕподтверждённые" —
                        # именно та ситуация "отклики не доходят":
                        # клик прошёл, DOM изменился, но после
                        # перезагрузки страницы кнопка снова активна,
                        # то есть сервер отклик не зафиксировал.
                        #
                        # ФИКС №6 (этот прогон, КРИТИЧНЫЙ): раньше голый
                        # "SUBMITTED" (обычная модалка, БЕЗ какой-либо
                        # верификации — см. hh/apply.py) считался
                        # подтверждённым наравне с
                        # SUBMITTED_CONFIRMED_NETWORK, хотя для него
                        # вообще не было проверки доставки. Теперь
                        # hh/apply.py для этой ветки тоже проверяет
                        # сеть/reload и возвращает
                        # SUBMITTED_CONFIRMED_NETWORK /
                        # SUBMITTED_CONFIRMED_RELOAD при успехе или
                        # SUBMITTED_NOT_CONFIRMED / REJECTED_BY_SERVER
                        # при неудаче. Голый "SUBMITTED" остаётся только
                        # как редкий случай "ни сеть, ни reload ничего
                        # не дали" — он больше НЕ считается подтверждённым.
                        # ==========================================

                        if apply_status in (
                            "SUBMITTED_CONFIRMED_NETWORK",
                            "SUBMITTED_CONFIRMED_RELOAD",
                            "INSTANT_APPLY_CONFIRMED",
                        ):
                            stats["APPLY_CONFIRMED"] += 1

                        if apply_status in (
                            "INSTANT_APPLY_NOT_CONFIRMED",
                            "SUBMITTED_NOT_CONFIRMED",
                            "REJECTED_BY_SERVER",
                        ):
                            stats["APPLY_NOT_CONFIRMED"] += 1

                        print(
                            f"HH.APPLY: {apply_status}"
                        )

                        if apply_result.get("reason"):
                            print(
                                f" • "
                                f"{apply_result['reason']}"
                            )

                        if apply_result.get(
                            "resume_warning"
                        ):
                            print(
                                f" ⚠ "
                                f"{apply_result['resume_warning']}"
                            )

                    else:
                        print(
                            "\nОткликаться не буду — "
                            "письмо не прошло "
                            "валидацию (PASS)."
                        )

                    if config.DEBUG_MODE:
                        letter_path = save_cover_letter(
                            vacancy_id,
                            vacancy,
                            selected_facts,
                            letter,
                            validation,
                            apply_status,
                        )

                        print(
                            f"Письмо сохранено:\n"
                            f"{letter_path}"
                        )

                if (
                    config.DEBUG_MODE
                    and vacancy is not None
                ):
                    dump_path = save_debug_dump(
                        vacancy_id,
                        vacancy,
                        geography,
                        classification,
                        requirements,
                        evaluation,
                        reject_reason,
                        selected_facts,
                        letter,
                        validation,
                        apply_result,
                    )

                    print(
                        f"[DEBUG] Дамп сохранён:\n"
                        f"{dump_path}"
                    )

                exp_required = ""
                exp_importance = ""
                seniority = ""

                if requirements:
                    seniority = requirements.get(
                        "seniority",
                        "",
                    )

                    exp_struct = requirements.get(
                        "experience",
                        {},
                    )

                    exp_required = exp_struct.get(
                        "years_min",
                        "",
                    )

                    if exp_required is None:
                        exp_required = ""

                    exp_importance = exp_struct.get(
                        "importance",
                        "",
                    )

                append_result_csv(
                    config.RESULTS_CSV_FILE,
                    {
                        "id": vacancy_id,
                        "title": vacancy["title"],
                        "company": vacancy["company"],
                        "salary": vacancy["salary"],
                        "experience": vacancy["experience"],
                        "work_format": work_format.get(
                            "raw",
                            "",
                        ),
                        "location": vacancy["location"],
                        "geography_status": geography[
                            "status"
                        ],
                        "seniority": seniority,
                        "experience_required": exp_required,
                        "experience_importance": exp_importance,
                        "decision": decision,
                        "score": score,
                        "letter_status": letter_status,
                        "apply_status": apply_status,
                        "url": vacancy["url"],
                        "summary": summary,
                    },
                )

                history[vacancy_id] = {
                    "status": decision,
                    "score": score,
                    "geography": geography[
                        "status"
                    ],
                    "seniority": seniority,
                    "letter_status": letter_status,
                    "apply_status": apply_status,
                    "url": vacancy["url"],
                }

            except BlockedPageError as error:
                stats["ERROR"] += 1
                print(
                    "Обнаружена капча/блокировка HH во время "
                    f"обработки вакансии. Причина: {error}"
                )

                if not wait_for_unblock(
                    page,
                    stage="после BlockedPageError",
                    max_wait_sec=config.CAPTCHA_MAX_WAIT_SEC,
                    poll_interval_sec=config.CAPTCHA_POLL_INTERVAL_SEC,
                    vision_enabled=config.CAPTCHA_VISION_ENABLED,
                    vision_ollama_url=config.OLLAMA_URL,
                    vision_model=config.CAPTCHA_VISION_MODEL,
                    vision_region={
                        "x": config.CAPTCHA_SCREENSHOT_X,
                        "y": config.CAPTCHA_SCREENSHOT_Y,
                        "width": config.CAPTCHA_SCREENSHOT_WIDTH,
                        "height": config.CAPTCHA_SCREENSHOT_HEIGHT,
                    },
                ):
                    print(
                        "Без обхода CAPTCHA останавливаю прогон."
                    )
                    break

                print(
                    "Блокировка снята — пропускаю эту вакансию "
                    "и продолжаю прогон со следующей."
                )

            except Exception as error:
                stats["ERROR"] += 1
                print(
                    f"ОШИБКА при обработке вакансии: "
                    f"{error}"
                )

            # ==========================================
            # Сама остановка основного цикла по лимиту
            # откликов — здесь, уже после того как текущая
            # вакансия полностью обработана (письмо/отклик/
            # дамп/CSV/история сохранены), независимо от
            # того, был ли except выше.
            # ==========================================

            if (
                decision == "APPLY"
                and stats["APPLY"]
                >= config.MAX_APPLIES_PER_RUN
            ):
                break

        save_history(
            config.HISTORY_FILE,
            history,
        )

        # Подстраховочное сохранение — на случай, если по какой-то
        # причине запись не прошла в моменте (record_applied_id уже
        # сохраняет на диск сразу при каждом подтверждённом отклике,
        # это просто финальная гарантия целостности файла).
        save_applied_ids(
            config.APPLIED_IDS_FILE,
            applied_ids,
        )

        print("\n" + "=" * 70)
        print("ИТОГ")
        print("=" * 70)

        print(f"APPLY: {stats['APPLY']}")
        print(f"REVIEW: {stats['REVIEW']}")
        print(f"REJECT: {stats['REJECT']}")
        print(
            f"  из них 'уже откликались' (отсечено ДО "
            f"Qwen-конвейера): "
            f"{stats['ALREADY_RESPONDED_EARLY']}"
        )
        print(f"Пропущено (history.json): {stats['SKIPPED']}")
        print(
            f"Пропущено (applied_ids.json, даже без открытия "
            f"страницы): {stats['SKIPPED_PERMANENTLY_APPLIED']}"
        )
        print(f"Ошибки: {stats['ERROR']}")
        print(
            f"Откликов подтверждено сервером: "
            f"{stats['APPLY_CONFIRMED']}"
        )
        print(
            f"Откликов НЕ подтверждено (не дошли): "
            f"{stats['APPLY_NOT_CONFIRMED']}"
        )
        print(
            f"Писем PASS: "
            f"{stats['LETTER_PASS']}"
        )
        print(
            f"Писем REQUIRES_USER: "
            f"{stats['LETTER_REQUIRES_USER']}"
        )

        if config.DRY_RUN:
            print(
                "\nDRY_RUN включён — ни один "
                "отклик не был отправлен по-настоящему."
            )

    except Exception as global_error:
        print(
            f"Критическая ошибка в процессе выполнения: "
            f"{global_error}"
        )

    finally:
        print(
            "\nЗакрываю браузер через 3 секунды..."
        )

        if "page" in locals() and page:
            page.wait_for_timeout(3000)

        if "playwright" in locals():
            stop_browser(playwright, context)


if __name__ == "__main__":
    main()