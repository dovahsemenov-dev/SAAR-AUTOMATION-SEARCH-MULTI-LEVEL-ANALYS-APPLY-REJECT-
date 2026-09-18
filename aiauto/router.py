
# router.py

"""
router.py

Разводит вызовы конвейера по источнику вакансий.

Место в проекте
===============

Лежит в корне aiauto/, рядом с main.py и config.py — на том же
уровне, что и пакеты hh/ и habr/. Отдельной папки под него нет
намеренно: это один модуль-диспетчер на четыре функции, ему
некуда разрастаться.

    aiauto/
        ai/
        filters/
        hh/            <- источник HH (не тронут)
        habr/          <- источник Хабр Карьеры (новый)
        config.py
        main.py
        router.py      <- этот файл

main.py импортирует четыре функции отсюда вместо трёх прямых
импортов из hh.*. Сигнатуры совпадают с прежними один в один,
поэтому остальной код main.py менять не пришлось.


ВАЖНО ПРО ID ВАКАНСИЙ

Раньше id был голым числом HH: "137310637".
У Хабр Карьеры id тоже числовой: "1000162215".

Если оставить голые числа, то data/history.json, seen_ids в
main.py и имена файлов в data/cover_letters/ и data/debug_dumps/
начнут склеивать вакансии с разных площадок. Это тихая ошибка:
прогон не падает, но появляются пропуски и повторные отклики.

Поэтому router возвращает id с префиксом источника:

    hh-137310637
    habr-1000162215

Префикс через дефис, а НЕ через двоеточие — потому что id идёт
прямо в имя файла (data/debug_dumps/<id>.txt), а двоеточие в
путях Windows запрещено.

Старая история с голыми числами после этого не совпадёт с новыми
ключами. Разово прогони migrate_history.py — он допишет префикс
hh- ко всем существующим записям.
"""

from __future__ import annotations

import config


# ============================================================
# Определение источника
# ============================================================

HH_DOMAIN_MARKERS = (
    "hh.ru",
    "headhunter",
)

HABR_DOMAIN_MARKERS = (
    "career.habr.com",
)

SOURCE_HH = "hh"
SOURCE_HABR = "habr"


def detect_source(url_or_id: str) -> str:
    """
    Определяет источник по URL вакансии/поиска или по
    префиксованному id.

    Возвращает "hh" или "habr". По умолчанию — "hh",
    чтобы поведение без Хабра осталось ровно прежним.
    """

    value = str(url_or_id or "").lower()

    for marker in HABR_DOMAIN_MARKERS:
        if marker in value:
            return SOURCE_HABR

    if value.startswith("habr-"):
        return SOURCE_HABR

    for marker in HH_DOMAIN_MARKERS:
        if marker in value:
            return SOURCE_HH

    return SOURCE_HH


def strip_source_prefix(vacancy_id: str) -> str:
    """
    "habr-1000162215" -> "1000162215"
    "hh-137310637"    -> "137310637"
    "137310637"       -> "137310637"
    """

    value = str(vacancy_id or "")

    for prefix in (f"{SOURCE_HH}-", f"{SOURCE_HABR}-"):
        if value.startswith(prefix):
            return value[len(prefix):]

    return value


def _apply_prefix(source: str, vacancy_id) -> str:
    raw = str(vacancy_id or "")

    if raw.startswith(f"{source}-"):
        return raw

    return f"{source}-{raw}"


# ============================================================
# Сбор вакансий
# ============================================================

def collect_vacancies(
    page,
    search_url: str,
    max_count: int,
) -> list[dict]:
    """
    Единая точка входа для main.py.

    Возвращает список коротких карточек:

        {
            "id":      "<source>-<native_id>",
            "title":   str,
            "url":     str,
            "snippet": str,
            "source":  "hh" | "habr",
        }
    """

    source = detect_source(search_url)

    if source == SOURCE_HABR:
        from habr import search as habr_search

        found = habr_search.collect_vacancies(
            page,
            search_url,
            _habr_max_count(max_count),
        )

    else:
        from hh.search import (
            collect_vacancies as hh_collect,
        )

        found = hh_collect(
            page,
            search_url,
            max_count,
        )

    for item in found:
        item["id"] = _apply_prefix(
            source,
            item.get("id"),
        )

        item["source"] = source

    return found


def _habr_max_count(default_max: int) -> int:
    """
    На Хабре база на порядок меньше HH: вся выдача — порядка
    1200 вакансий против сотен тысяч у HH. Отдельный, более
    скромный лимит, чтобы habr-URL не съедал лимит, который
    рассчитан на HH.
    """

    return int(
        getattr(
            config,
            "HABR_MAX_VACANCIES_PER_URL",
            default_max,
        )
    )


# ============================================================
# Открытие вакансии
# ============================================================

def open_vacancy(page, url: str) -> dict:
    source = detect_source(url)

    if source == SOURCE_HABR:
        from habr import vacancy as habr_vacancy

        result = habr_vacancy.open_vacancy(page, url)

    else:
        from hh.vacancy import (
            open_vacancy as hh_open,
        )

        result = hh_open(page, url)

    result["source"] = source

    return result


# ============================================================
# Проверка "уже откликались"
# ============================================================

def check_already_responded(page) -> dict:
    try:
        current_url = str(page.url or "")
    except Exception:
        current_url = ""

    source = detect_source(current_url)

    if source == SOURCE_HABR:
        from habr import apply as habr_apply

        return habr_apply.check_already_responded(page)

    from hh.apply import (
        check_already_responded as hh_check,
    )

    return hh_check(page)


# ============================================================
# Отклик
# ============================================================

def respond_to_vacancy(
    page,
    letter_text: str,
    dry_run: bool,
    vacancy_text: str = "",
    profile_facts: dict | None = None,
    ollama_url: str | None = None,
    model_name: str | None = None,
    vacancy_id: str | None = None,
    response_kind: str = "",
) -> dict:
    try:
        current_url = str(page.url or "")
    except Exception:
        current_url = ""

    source = detect_source(
        current_url
        or str(vacancy_id or "")
    )

    if source == SOURCE_HABR:
        from habr import apply as habr_apply

        return habr_apply.respond_to_vacancy(
            page,
            letter_text,
            dry_run,
            vacancy_text=vacancy_text,
            profile_facts=profile_facts,
            ollama_url=ollama_url,
            model_name=model_name,
            vacancy_id=vacancy_id,
            response_kind=response_kind,
        )

    from hh.apply import (
        respond_to_vacancy as hh_respond,
    )

    return hh_respond(
        page,
        letter_text,
        dry_run,
        vacancy_text=vacancy_text,
        profile_facts=profile_facts,
        ollama_url=ollama_url,
        model_name=model_name,
        vacancy_id=vacancy_id,
    )
