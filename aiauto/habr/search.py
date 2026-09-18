# habr/search.py

"""
habr/search.py

Сбор вакансий из выдачи career.habr.com.

ГЛАВНОЕ ОТЛИЧИЕ ОТ hh/search.py
===============================

hh/search.py вынужден скрести DOM: ходить по a[href*="/vacancy/"],
вытаскивать сниппет через [data-qa='vacancy-serp__...'] и так далее.
Любая правка вёрстки HH ломает сбор.

Хабр Карьера — приложение на Rails + Vue с server-side rendering,
и оно кладёт в HTML страницы готовый JSON состояния:

    <script type="application/json" data-ssr-state="true">{...}</script>

Внутри, по ключу "vacancies", лежит полностью структурированный
список вакансий текущей страницы:

    {
      "vacancies": {
        "list": [
          {
            "id": 1000162215,
            "href": "/vacancies/1000162215",
            "title": "Стажер Frontend-разработчик (React)",
            "remoteWork": true,
            "qualification": "Intern",
            "employment": "part_time",
            "archived": false,
            "company":   {"title": "PREAX", "accredited": false, ...},
            "salary":    {"from": null, "to": null, "formatted": ""},
            "divisions": [{"title": "Фронтенд разработчик"}],
            "skills":    [{"title": "CSS"}, {"title": "React"}, ...],
            "locations": [{"title": "Москва"}] | null,
            "response":  {"kind": "direct"}
          },
          ...
        ],
        "meta": {"totalResults": 1195, "perPage": 25,
                 "currentPage": 1, "totalPages": 40}
      }
    }

Поэтому сбор здесь идёт из JSON, а не из DOM. Это:

  1. на порядок устойчивее к редизайну — JSON это контракт их
     собственного фронтенда, его ломают заметно реже вёрстки;
  2. даёт сразу компанию, зарплату, скиллы, квалификацию,
     удалёнку и города, то есть почти всю карточку, кроме
     полного текста описания.

Пункт 2 важен: собранная здесь карточка кладётся в CARD_CACHE,
и habr/vacancy.py потом берёт эти поля оттуда, а со страницы
вакансии тянет только описание. Это и быстрее, и устойчивее,
чем парсить всё заново из DOM вакансии.

DOM-парсинг оставлен как запасной путь (_extract_from_dom) на
случай, если SSR-JSON однажды пропадёт или поменяет форму.


FAST FILTER: ОСОБЫЙ РЕЖИМ ДЛЯ ХАБРА
====================================

filters/fast_filter.py писался под HH, где выдача забита не-IT
мусором: комплектовщики, курьеры, чарджеры, операторы контактного
центра. По логам прогонов на HH: 2831 HARD_REJECT против 233
TARGET, и подавляющее большинство отказов — "not_in_whitelist".

На Хабре такого мусора нет: площадка изначально IT-only. Там
"not_in_whitelist" будет резать нормальные вакансии, названия
которых просто не попали в whitelist.

Поэтому для Хабра HARD_REJECT понижается до REVIEW_BY_AI везде,
КРОМЕ отказов вида force_non_it_title — то есть явных чёрных
маркеров ('курьер', 'кладовщик', 'преподаватель'), которые
остаются жёсткими.

Управляется флагом config.HABR_SOFT_FAST_FILTER (по умолчанию True).
"""

from __future__ import annotations

import json
import random
import re
from urllib.parse import (
    urlparse,
    urlunparse,
    parse_qs,
    urlencode,
)

from playwright.sync_api import (
    TimeoutError as PlaywrightTimeoutError,
    Error as PlaywrightError,
)

import config
from filters.fast_filter import classify_fast


BASE_URL = "https://career.habr.com"

VACANCY_HREF_RE = re.compile(r"/vacancies/(\d+)")

SSR_STATE_SELECTOR = "script[data-ssr-state]"

MAX_PAGES_PER_URL = 60


# ============================================================
# Кэш карточек из выдачи
# ============================================================

# id вакансии (голый, без префикса источника) -> dict полей,
# полученных из SSR-JSON выдачи. Используется в habr/vacancy.py,
# чтобы не парсить эти поля повторно из DOM страницы вакансии.
CARD_CACHE: dict[str, dict] = {}


# ============================================================
# Квалификация Хабра -> строка опыта в формате HH
# ============================================================

# filters/rules.py::_parse_experience_years_min разбирает строку
# опыта в стиле HH ('1–3 года', 'не требуется', '3–6 лет') и
# берёт минимальное число. Чтобы не трогать rules.py и не ломать
# уже отлаженную раннюю отсечку по опыту, адаптер Хабра просто
# синтезирует ту же самую строку из грейда.
#
# Это сознательное упрощение: у Хабра нет вилки опыта в годах,
# есть только грейд. Маппинг подобран так, чтобы при текущем
# config.MAX_EXPERIENCE_YEARS_MIN = 2 проходили Intern и Junior,
# а Middle/Senior/Lead отсекались ДО обращения к Qwen — ровно
# как это уже происходит на HH.
QUALIFICATION_TO_EXPERIENCE = {
    "intern": "Не требуется",
    "junior": "1–3 года",
    "middle": "3–6 лет",
    "senior": "более 6 лет",
    "lead": "более 6 лет",
}

EMPLOYMENT_TITLES = {
    "full_time": "Полная занятость",
    "part_time": "Неполный рабочий день",
}


# ============================================================
# Человекоподобное поведение
# ============================================================

def _human_mouse_wander(page) -> None:
    try:
        viewport = page.viewport_size or {
            "width": 1280,
            "height": 800,
        }

        for _ in range(random.randint(2, 4)):
            x = random.randint(
                40,
                max(41, viewport["width"] - 40),
            )

            y = random.randint(
                40,
                max(41, viewport["height"] - 40),
            )

            page.mouse.move(
                x,
                y,
                steps=random.randint(5, 15),
            )

            page.wait_for_timeout(
                random.randint(80, 260)
            )

    except Exception:
        pass


# ============================================================
# Пагинация
# ============================================================

def _with_page_param(
    url: str,
    page_number: int,
) -> str:
    """
    Проставляет page=<N> в URL выдачи Хабра.

    В отличие от HH, нумерация страниц у Хабра начинается с 1,
    а не с 0, и параметра items_on_page нет — размер страницы
    фиксирован (perPage=25 в meta).
    """

    parsed = urlparse(url)

    query = parse_qs(
        parsed.query,
        keep_blank_values=True,
    )

    query["page"] = [str(page_number)]

    if "type" not in query:
        query["type"] = ["all"]

    return urlunparse(
        parsed._replace(
            query=urlencode(query, doseq=True),
        )
    )


# ============================================================
# Открытие страницы выдачи
# ============================================================

def open_search_page(page, search_url: str) -> None:
    print("Открываю Хабр Карьеру:")
    print(search_url)

    try:
        response = page.goto(
            search_url,
            wait_until="domcontentloaded",
            timeout=90_000,
        )

    except (
        PlaywrightTimeoutError,
        PlaywrightError,
    ) as error:
        raise RuntimeError(
            "Не удалось загрузить страницу выдачи "
            f"Хабр Карьеры: {error}"
        ) from error

    page.wait_for_timeout(
        random.randint(1800, 3800)
    )

    _human_mouse_wander(page)

    print("Фактический URL:", page.url)

    if response is not None:
        print("HTTP status:", response.status)

    print("Страница Хабр Карьеры загружена.")


# ============================================================
# Извлечение SSR-состояния
# ============================================================

def _read_ssr_state(page) -> dict | None:
    """
    Достаёт <script type="application/json" data-ssr-state="true">.

    Возвращает распарсенный dict или None, если скрипта нет либо
    он не разбирается как JSON.
    """

    try:
        locator = page.locator(SSR_STATE_SELECTOR)

        if locator.count() == 0:
            return None

        raw = locator.first.text_content(timeout=10_000)

    except Exception:
        return None

    if not raw or not raw.strip():
        return None

    try:
        data = json.loads(raw)

    except json.JSONDecodeError:
        return None

    if not isinstance(data, dict):
        return None

    return data


def _titles(items) -> list[str]:
    result: list[str] = []

    if not isinstance(items, list):
        return result

    for item in items:
        if isinstance(item, dict):
            title = str(item.get("title") or "").strip()
        else:
            title = str(item or "").strip()

        if title and title not in result:
            result.append(title)

    return result


def _normalize_ssr_item(item: dict) -> dict | None:
    """
    Приводит один элемент vacancies.list к нашей карточке.
    """

    if not isinstance(item, dict):
        return None

    vacancy_id = item.get("id")

    if vacancy_id in (None, ""):
        return None

    vacancy_id = str(vacancy_id)

    title = str(item.get("title") or "").strip()

    href = str(item.get("href") or "").strip()

    if not href:
        href = f"/vacancies/{vacancy_id}"

    url = (
        href
        if href.startswith("http")
        else BASE_URL + href
    )

    company = item.get("company") or {}

    if not isinstance(company, dict):
        company = {}

    salary = item.get("salary") or {}

    if not isinstance(salary, dict):
        salary = {}

    salary_formatted = str(
        salary.get("formatted") or ""
    ).strip()

    # ВАЖНО: predictedSalary — это оценка САМОГО Хабра
    # ("похожие специалисты получают 30 000 - 92 000 ₽"),
    # а не предложение работодателя. В поле salary её класть
    # нельзя, иначе Qwen примет её за условия вакансии и
    # начнёт строить на ней письмо.
    if not salary_formatted:
        salary_formatted = "Не указана"

    qualification = item.get("qualification")

    qualification_key = str(
        qualification or ""
    ).strip().lower()

    experience = QUALIFICATION_TO_EXPERIENCE.get(
        qualification_key,
        "Не указано",
    )

    skills = _titles(item.get("skills"))
    divisions = _titles(item.get("divisions"))
    locations = _titles(item.get("locations"))

    employment_raw = str(
        item.get("employment") or ""
    ).strip().lower()

    employment = EMPLOYMENT_TITLES.get(
        employment_raw,
        "Не указано",
    )

    remote = bool(item.get("remoteWork"))

    # У Хабра нет отдельного признака "гибрид". Есть флаг
    # "Можно удалённо" и список городов. Трактовка:
    #   remoteWork = true            -> удалёнка разрешена
    #   remoteWork = false + города  -> офис в этих городах
    #   remoteWork = false + пусто   -> формат неизвестен
    office = (not remote) and bool(locations)

    if remote:
        work_format_raw = "Можно удалённо"
    elif office:
        work_format_raw = (
            "На месте работодателя: "
            + ", ".join(locations)
        )
    else:
        work_format_raw = ""

    work_format = {
        "raw": work_format_raw,
        "remote": remote,
        "office": office,
        "hybrid": False,
        "unknown": not (remote or office),
    }

    response_info = item.get("response") or {}

    if isinstance(response_info, dict):
        response_kind = str(
            response_info.get("kind") or ""
        ).strip().lower()
    else:
        response_kind = ""

    # Сниппет для fast-filter. У Хабра в выдаче нет текстового
    # сниппета обязанностей, как у HH, зато есть специализация
    # и навыки — по смыслу это даже более плотный сигнал.
    snippet_parts = divisions + skills

    if qualification:
        snippet_parts.append(str(qualification))

    snippet = ", ".join(snippet_parts)

    return {
        "id": vacancy_id,
        "title": title,
        "url": url,
        "snippet": snippet,
        "archived": bool(item.get("archived")),
        "card": {
            "title": title,
            "url": url,
            "company": (
                str(company.get("title") or "").strip()
                or "Не указана"
            ),
            "company_accredited": bool(
                company.get("accredited")
            ),
            "salary": salary_formatted,
            "experience": experience,
            "qualification": (
                str(qualification or "").strip()
                or "Не указана"
            ),
            "employment": employment,
            "schedule": "Не указано",
            "working_hours": "Не указано",
            "work_format": work_format,
            "location": (
                ", ".join(locations)
                if locations
                else (
                    "Удалённо"
                    if remote
                    else "Не указано"
                )
            ),
            "skills": skills,
            "divisions": divisions,
            "response_kind": response_kind,
        },
    }


def _extract_from_ssr(page) -> tuple[dict[str, dict], dict]:
    """
    Возвращает (карточки по id, meta пагинации).
    """

    state = _read_ssr_state(page)

    if not state:
        return {}, {}

    vacancies = state.get("vacancies")

    if not isinstance(vacancies, dict):
        return {}, {}

    raw_list = vacancies.get("list")

    if not isinstance(raw_list, list):
        return {}, {}

    meta = vacancies.get("meta")

    if not isinstance(meta, dict):
        meta = {}

    found: dict[str, dict] = {}

    for item in raw_list:
        normalized = _normalize_ssr_item(item)

        if normalized is None:
            continue

        found[normalized["id"]] = normalized

    return found, meta


# ============================================================
# Запасной DOM-парсинг
# ============================================================

def _extract_from_dom(page) -> dict[str, dict]:
    """
    Резервный путь: если SSR-JSON пропал, собираем минимум
    (id, название, ссылку) прямо из карточек выдачи.

    Карточка в вёрстке Хабра:
        <div data-vacancy-card data-vacancy-id="1000162215" ...>
            <a class="vacancy-card__title-link" href="/vacancies/...">
    """

    found: dict[str, dict] = {}

    try:
        cards = page.locator("[data-vacancy-card]")
        count = cards.count()

    except Exception:
        count = 0

    print(
        "SSR-состояние не найдено, читаю DOM. "
        f"Карточек в DOM: {count}"
    )

    for index in range(count):
        card = cards.nth(index)

        try:
            vacancy_id = card.get_attribute(
                "data-vacancy-id"
            )
        except Exception:
            vacancy_id = None

        if not vacancy_id:
            continue

        vacancy_id = str(vacancy_id).strip()

        if vacancy_id in found:
            continue

        title = ""

        for selector in (
            ".vacancy-card__title-link",
            ".vacancy-card__title",
            "a[href*='/vacancies/']",
        ):
            try:
                node = card.locator(selector).first

                if node.count() == 0:
                    continue

                title = node.inner_text(
                    timeout=1500
                ).strip()

                if title:
                    break

            except Exception:
                continue

        skills: list[str] = []

        try:
            chips = card.locator(
                ".vacancy-card__skills-chip"
            )

            for chip_index in range(chips.count()):
                text = chips.nth(chip_index).inner_text(
                    timeout=800
                ).strip()

                if text and text not in skills:
                    skills.append(text)

        except Exception:
            pass

        url = f"{BASE_URL}/vacancies/{vacancy_id}"

        found[vacancy_id] = {
            "id": vacancy_id,
            "title": title,
            "url": url,
            "snippet": ", ".join(skills),
            "archived": False,
            "card": {
                "title": title,
                "url": url,
                "company": "Не указана",
                "salary": "Не указана",
                "experience": "Не указано",
                "qualification": "Не указана",
                "employment": "Не указано",
                "schedule": "Не указано",
                "working_hours": "Не указано",
                "work_format": {
                    "raw": "",
                    "remote": False,
                    "office": False,
                    "hybrid": False,
                    "unknown": True,
                },
                "location": "Не указано",
                "skills": skills,
                "divisions": [],
                "response_kind": "",
            },
        }

    return found


# ============================================================
# Fast filter
# ============================================================

def _is_hard_black_marker(reason: str) -> bool:
    """
    Отличает жёсткий чёрный маркер названия (force_non_it_title:
    'курьер', 'кладовщик', 'преподаватель') от мягкого отказа
    "названия нет в whitelist".
    """

    low = str(reason or "").strip().lower()

    return (
        low.startswith("force_non_it_title")
        or "force_non_it" in low
    )


def _apply_fast_filter(card: dict) -> dict:
    if not config.FAST_FILTER_ENABLED:
        result = {
            "status": "REVIEW_BY_AI",
            "reason": (
                "fast-filter отключён "
                "(FAST_FILTER_ENABLED=False)"
            ),
        }

    else:
        result = classify_fast(
            card.get("title", ""),
            card.get("snippet", ""),
            it_protect_markers=(
                config.FAST_FILTER_IT_PROTECT_MARKERS
            ),
            hard_reject_markers=(
                config.FAST_FILTER_HARD_REJECT_MARKERS
            ),
        )

        soft_mode = bool(
            getattr(
                config,
                "HABR_SOFT_FAST_FILTER",
                True,
            )
        )

        if (
            soft_mode
            and result["status"] == "HARD_REJECT"
            and not _is_hard_black_marker(
                result.get("reason", "")
            )
        ):
            result = {
                "status": "REVIEW_BY_AI",
                "reason": (
                    "habr soft-mode: понижено с HARD_REJECT — "
                    "на Хабре площадка изначально IT-only, "
                    "отсутствие названия в whitelist не повод "
                    "резать без Qwen. Исходная причина: "
                    + str(result.get("reason", ""))
                ),
            }

    print(
        "\n[FAST FILTER][HABR] "
        f"{result['status']}\n"
        f"Название: {card.get('title', '')}\n"
        f"Причина: {result['reason']}"
    )

    return result


# ============================================================
# Сбор вакансий
# ============================================================

def collect_vacancies(
    page,
    search_url: str,
    max_count: int,
) -> list[dict]:
    """
    Собирает вакансии по одному поисковому URL Хабр Карьеры.

    Контракт совпадает с hh/search.py::collect_vacancies:
    max_count ограничивает число ПРОСМОТРЕННЫХ карточек,
    а не число прошедших fast-filter.
    """

    kept: dict[str, dict] = {}
    seen_ids: set[str] = set()

    hard_reject_count = 0
    target_count = 0
    review_count = 0
    archived_count = 0

    total_pages: int | None = None

    def _summary() -> None:
        print(
            "\n[FAST FILTER][HABR] Итог по URL: "
            f"просмотрено {len(seen_ids)}, "
            f"HARD_REJECT: {hard_reject_count}, "
            f"TARGET: {target_count}, "
            f"REVIEW_BY_AI: {review_count}, "
            f"архивных пропущено: {archived_count}, "
            f"дальше всего: {len(kept)}"
        )

    for page_number in range(1, MAX_PAGES_PER_URL + 1):

        page_url = _with_page_param(
            search_url,
            page_number,
        )

        print(
            "\n--- Страница выдачи Хабр Карьеры "
            f"№{page_number} ---"
        )

        open_search_page(page, page_url)

        page_vacancies, meta = _extract_from_ssr(page)

        if not page_vacancies:
            page_vacancies = _extract_from_dom(page)

        else:
            print(
                "Вакансий в SSR-состоянии страницы: "
                f"{len(page_vacancies)}"
            )

        if meta:
            try:
                total_pages = int(
                    meta.get("totalPages")
                )
            except (TypeError, ValueError):
                total_pages = None

            if page_number == 1:
                print(
                    "Всего в выдаче по этому URL: "
                    f"{meta.get('totalResults')} "
                    f"(страниц: {meta.get('totalPages')})"
                )

        new_on_this_page = 0

        for vacancy_id, item in page_vacancies.items():

            if vacancy_id in seen_ids:
                continue

            seen_ids.add(vacancy_id)
            new_on_this_page += 1

            # Архивная вакансия — работодатель её снял.
            # Откликнуться нельзя, гонять через Qwen бессмысленно.
            if item.get("archived"):
                archived_count += 1
                continue

            CARD_CACHE[vacancy_id] = item["card"]

            card = {
                "id": vacancy_id,
                "title": item["title"],
                "url": item["url"],
                "snippet": item["snippet"],
            }

            fast_result = _apply_fast_filter(card)

            status = fast_result["status"]

            if status == "HARD_REJECT":
                hard_reject_count += 1
                continue

            if status == "TARGET":
                target_count += 1

            elif status == "REVIEW_BY_AI":
                review_count += 1

            kept[vacancy_id] = card

            if len(seen_ids) >= max_count:
                print(
                    "\nДостигнут лимит max_count "
                    f"({max_count}) просмотренных карточек."
                )

                _summary()

                return list(kept.values())

        print(
            "Новых вакансий на странице "
            f"№{page_number}: {new_on_this_page}"
        )

        if new_on_this_page == 0:
            print(
                "Страница не дала новых вакансий — "
                "выдача Хабра по этому URL закончилась."
            )

            _summary()

            return list(kept.values())

        if (
            total_pages is not None
            and page_number >= total_pages
        ):
            print(
                "Достигнута последняя страница выдачи "
                f"({total_pages})."
            )

            _summary()

            return list(kept.values())

        _human_mouse_wander(page)

        page.wait_for_timeout(
            random.randint(900, 2200)
        )

    print(
        "Достигнут страховочный предел "
        f"MAX_PAGES_PER_URL ({MAX_PAGES_PER_URL})."
    )

    _summary()

    return list(kept.values())
