# habr/vacancy.py

"""
habr/vacancy.py

Открытие страницы вакансии Хабр Карьеры и нормализация полей
к тому же виду, что отдаёт hh/vacancy.py::open_vacancy.

СТРАТЕГИЯ
=========

У hh/vacancy.py нет выбора: он тянет из DOM все 12 полей по
селекторам [data-qa='...'], потому что выдача HH почти ничего
структурированного не отдаёт.

На Хабре ситуация другая. habr/search.py уже получил из SSR-JSON
выдачи компанию, зарплату, грейд, занятость, удалёнку, города и
навыки, и положил их в CARD_CACHE. Со страницы вакансии остаётся
забрать ровно одно поле — полный текст описания.

Это важно с практической стороны: чем меньше селекторов, тем
меньше точек отказа. Единственный селектор, который может
потребовать калибровки, — это описание, и под него есть каскад
кандидатов плюс грубый запасной вариант (текст всей страницы с
обрезкой хвостов). Прогон не упадёт, даже если вёрстка
поменяется — в худшем случае в описание попадёт лишний текст.

Если вакансия попала в обработку без предварительного сбора
(CARD_CACHE пуст — например, при точечном прогоне по прямой
ссылке), поля добираются из SSR-состояния самой страницы
вакансии, а затем из DOM.
"""

from __future__ import annotations

import json
import random
import re

from playwright.sync_api import Page

from habr.search import (
    CARD_CACHE,
    SSR_STATE_SELECTOR,
    VACANCY_HREF_RE,
    QUALIFICATION_TO_EXPERIENCE,
)


# ============================================================
# Селекторы описания: от точного к грубому
# ============================================================

DESCRIPTION_SELECTORS = (
    ".vacancy-description__text",
    ".vacancy-description",
    ".style-ugc",
    ".basic-section--appearance-vacancy-description",
    ".content-wrapper__main",
    "main",
)

TITLE_SELECTORS = (
    "h1.page-title__title",
    ".page-title__title",
    "h1",
)

COMPANY_SELECTORS = (
    ".company_name a",
    ".company_name",
    ".vacancy-company__title",
    ".vacancy-company-title",
)

MIN_GOOD_DESCRIPTION_LEN = 300


# Хвосты страницы, которые не относятся к вакансии. Если описание
# пришлось брать грубым способом (.content-wrapper__main или main),
# текст режется по первому встреченному маркеру.
TAIL_CUT_MARKERS = (
    "Похожие вакансии",
    "Смотреть ещё вакансии",
    "Рассылка про карьеру в IT",
    "Телеграм-бот Хабр Карьеры",
    "Все сервисы Хабра",
    "Соглашение с пользователем",
    "Комментарии",
)

# Шапка страницы, которая может попасть в грубый вариант.
HEAD_CUT_MARKERS = (
    "Требуемый опыт",
    "Местоположение и тип занятости",
    "Обязанности",
    "Чем предстоит заниматься",
    "Что мы ожидаем",
    "Требования",
    "Описание вакансии",
)


# ============================================================
# Утилиты
# ============================================================

def _safe_text(page: Page, selector: str) -> str:
    try:
        locator = page.locator(selector).first

        if locator.count() == 0:
            return ""

        return locator.inner_text(timeout=5_000).strip()

    except Exception:
        return ""


def _human_read_pause(page: Page) -> None:
    try:
        page.wait_for_timeout(
            random.randint(700, 1700)
        )

        viewport = page.viewport_size or {
            "width": 1280,
            "height": 800,
        }

        page.mouse.move(
            random.randint(
                60, max(61, viewport["width"] - 60)
            ),
            random.randint(
                60, max(61, viewport["height"] - 60)
            ),
            steps=random.randint(5, 12),
        )

        page.mouse.wheel(
            0,
            random.randint(300, 900),
        )

        page.wait_for_timeout(
            random.randint(500, 1400)
        )

    except Exception:
        pass


def _vacancy_id_from_url(url: str) -> str:
    match = VACANCY_HREF_RE.search(str(url or ""))

    if match:
        return match.group(1)

    return ""


def _collapse_blank_lines(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _trim_page_noise(text: str, was_coarse: bool) -> str:
    """
    Обрезает хвосты и шапку, если описание бралось грубым
    селектором (контейнер страницы, а не блок описания).
    """

    if not text:
        return ""

    cleaned = text

    if was_coarse:
        for marker in HEAD_CUT_MARKERS:
            position = cleaned.find(marker)

            if 0 < position < len(cleaned) // 2:
                cleaned = cleaned[position:]
                break

    for marker in TAIL_CUT_MARKERS:
        position = cleaned.find(marker)

        if position > MIN_GOOD_DESCRIPTION_LEN:
            cleaned = cleaned[:position]

    return _collapse_blank_lines(cleaned)


def _extract_description(page: Page) -> str:
    """
    Пробует селекторы по очереди. Берёт первый достаточно
    длинный результат; если такого нет — самый длинный из
    найденных.
    """

    best_text = ""
    best_is_coarse = True

    coarse_selectors = {
        ".content-wrapper__main",
        "main",
    }

    for selector in DESCRIPTION_SELECTORS:
        text = _safe_text(page, selector)

        if not text:
            continue

        is_coarse = selector in coarse_selectors

        if (
            len(text) >= MIN_GOOD_DESCRIPTION_LEN
            and not is_coarse
        ):
            return _trim_page_noise(text, False)

        if len(text) > len(best_text):
            best_text = text
            best_is_coarse = is_coarse

    if not best_text:
        best_text = _safe_text(page, "body")
        best_is_coarse = True

    return _trim_page_noise(best_text, best_is_coarse)


# ============================================================
# Поля из SSR-состояния самой страницы вакансии
# ============================================================

def _card_from_page_ssr(page: Page, vacancy_id: str) -> dict:
    """
    Запасной источник полей, если вакансия не проходила через
    habr/search.py (CARD_CACHE пуст).

    Страница вакансии тоже отдаёт data-ssr-state, но её структура
    может отличаться от выдачи, поэтому здесь нарочно очень
    терпимый разбор: ищем где угодно объект с нужным id, а чего
    не нашли — оставляем пустым.
    """

    try:
        locator = page.locator(SSR_STATE_SELECTOR)

        if locator.count() == 0:
            return {}

        raw = locator.first.text_content(timeout=8_000)

    except Exception:
        return {}

    if not raw:
        return {}

    try:
        state = json.loads(raw)
    except json.JSONDecodeError:
        return {}

    found: dict = {}

    def _walk(node) -> None:
        nonlocal found

        if found:
            return

        if isinstance(node, dict):
            node_id = node.get("id")

            if (
                node_id is not None
                and str(node_id) == str(vacancy_id)
                and "title" in node
            ):
                found = node
                return

            for value in node.values():
                _walk(value)

        elif isinstance(node, list):
            for value in node:
                _walk(value)

    _walk(state)

    if not found:
        return {}

    company = found.get("company") or {}

    if not isinstance(company, dict):
        company = {}

    salary = found.get("salary") or {}

    if not isinstance(salary, dict):
        salary = {}

    qualification = str(
        found.get("qualification") or ""
    ).strip()

    remote = bool(found.get("remoteWork"))

    locations = []

    raw_locations = found.get("locations")

    if isinstance(raw_locations, list):
        for entry in raw_locations:
            if isinstance(entry, dict):
                title = str(
                    entry.get("title") or ""
                ).strip()

                if title:
                    locations.append(title)

    office = (not remote) and bool(locations)

    skills = []

    raw_skills = found.get("skills")

    if isinstance(raw_skills, list):
        for entry in raw_skills:
            if isinstance(entry, dict):
                title = str(
                    entry.get("title") or ""
                ).strip()

                if title:
                    skills.append(title)

    return {
        "title": str(found.get("title") or "").strip(),
        "company": (
            str(company.get("title") or "").strip()
            or "Не указана"
        ),
        "salary": (
            str(salary.get("formatted") or "").strip()
            or "Не указана"
        ),
        "experience": QUALIFICATION_TO_EXPERIENCE.get(
            qualification.lower(),
            "Не указано",
        ),
        "qualification": qualification or "Не указана",
        "employment": "Не указано",
        "schedule": "Не указано",
        "working_hours": "Не указано",
        "work_format": {
            "raw": (
                "Можно удалённо"
                if remote
                else (
                    "На месте работодателя: "
                    + ", ".join(locations)
                    if office
                    else ""
                )
            ),
            "remote": remote,
            "office": office,
            "hybrid": False,
            "unknown": not (remote or office),
        },
        "location": (
            ", ".join(locations)
            if locations
            else ("Удалённо" if remote else "Не указано")
        ),
        "skills": skills,
        "divisions": [],
        "response_kind": "",
    }


# ============================================================
# Основная функция
# ============================================================

def open_vacancy(page: Page, url: str) -> dict:
    """
    Открывает страницу вакансии Хабр Карьеры и возвращает dict
    ровно той же формы, что hh/vacancy.py::open_vacancy.
    """

    page.goto(
        url,
        wait_until="domcontentloaded",
        timeout=60_000,
    )

    page.wait_for_timeout(
        random.randint(1200, 2400)
    )

    _human_read_pause(page)

    vacancy_id = _vacancy_id_from_url(page.url) or (
        _vacancy_id_from_url(url)
    )

    card = dict(
        CARD_CACHE.get(vacancy_id) or {}
    )

    if not card:
        card = _card_from_page_ssr(page, vacancy_id)

    description = _extract_description(page)

    title = card.get("title") or ""

    if not title:
        for selector in TITLE_SELECTORS:
            title = _safe_text(page, selector)

            if title:
                break

    company = card.get("company") or ""

    if not company or company == "Не указана":
        for selector in COMPANY_SELECTORS:
            candidate = _safe_text(page, selector)

            if candidate:
                company = candidate
                break

    work_format = card.get("work_format") or {
        "raw": "",
        "remote": False,
        "office": False,
        "hybrid": False,
        "unknown": True,
    }

    return {
        "url": page.url,
        "title": title,
        "company": company or "Не указана",
        "salary": card.get("salary") or "Не указана",
        "description": description or "",
        "experience": card.get("experience") or "Не указано",
        "employment": card.get("employment") or "Не указано",
        "schedule": card.get("schedule") or "Не указано",
        "working_hours": (
            card.get("working_hours") or "Не указано"
        ),
        "work_format": work_format,
        "location": card.get("location") or "Не указано",
        "skills": card.get("skills") or [],

        # Дополнительные поля, которых нет у HH. Конвейер их не
        # использует, но они попадают в debug-дамп и пригодятся
        # при разборе прогона: qualification — грейд Хабра как
        # есть, response_kind — "direct" (отклик внутри Хабра)
        # или иное значение (отклик уводит на сайт работодателя).
        "qualification": (
            card.get("qualification") or "Не указана"
        ),
        "response_kind": card.get("response_kind") or "",
    }
