# hh/search.py

from __future__ import annotations

import random
import re
from urllib.parse import (
    urljoin,
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


VACANCY_RE = re.compile(r"/vacancy/(\d+)")


# ============================================================
# Безопасный потолок страниц
# ============================================================

MAX_PAGES_PER_URL = 50


# ============================================================
# Сниппеты HH
# ============================================================

_SNIPPET_TEXT_SELECTORS = (
    "[data-qa='vacancy-serp__vacancy-snippet-responsibility']",
    "[data-qa='vacancy-serp__vacancy-snippet-requirement']",
)


# ============================================================
# Вспомогательное движение мыши
# ============================================================

def _human_mouse_wander(page) -> None:
    """
    Несколько случайных перемещений курсора по видимой
    области страницы.
    """

    try:
        viewport = page.viewport_size or {
            "width": 1280,
            "height": 800,
        }

        steps = random.randint(2, 4)

        for _ in range(steps):
            x = random.randint(
                40,
                max(
                    41,
                    viewport["width"] - 40,
                ),
            )

            y = random.randint(
                40,
                max(
                    41,
                    viewport["height"] - 40,
                ),
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
# URL pagination
# ============================================================

# Сколько карточек вакансий запрашивать у HH на одной странице
# выдачи. Это штатная настройка самого сайта (выпадающий список
# "Показывать: 20 / 50 / 100 вакансий" над результатами поиска),
# не обход и не подделка запроса — тот же параметр, что ставит
# обычный пользователь руками. Эффект: при том же количестве
# вакансий нужно в ~5 раз меньше загрузок страниц (100 вместо
# дефолтных 20 за раз), а значит и в ~5 раз меньше времени на
# человекоподобные паузы между страницами в collect_vacancies().
ITEMS_ON_PAGE = 100


def _with_page_param(
    url: str,
    page_number: int,
) -> str:
    """
    Возвращает URL с параметром page=<page_number> и
    items_on_page=ITEMS_ON_PAGE (см. константу выше).
    """

    parsed = urlparse(url)

    query = parse_qs(
        parsed.query,
        keep_blank_values=True,
    )

    query["page"] = [str(page_number)]
    query["items_on_page"] = [str(ITEMS_ON_PAGE)]

    new_query = urlencode(
        query,
        doseq=True,
    )

    return urlunparse(
        parsed._replace(
            query=new_query,
        )
    )


# ============================================================
# Открытие страницы поиска
# ============================================================

def open_search_page(
    page,
    search_url: str,
) -> None:
    """
    Открывает страницу поиска HH.

    Если hh.ru не отвечает/не загружает DOM,
    пробует региональный ufa.hh.ru.
    """

    urls_to_try = [
        search_url,
    ]

    if "://hh.ru/" in search_url:
        urls_to_try.append(
            search_url.replace(
                "://hh.ru/",
                "://ufa.hh.ru/",
                1,
            )
        )

    last_error = None

    for attempt, url in enumerate(
        urls_to_try,
        start=1,
    ):
        print(
            f"Попытка открыть HH "
            f"[{attempt}/{len(urls_to_try)}]:"
        )

        print(url)

        try:
            response = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=90_000,
            )

            page.wait_for_timeout(
                random.randint(
                    2000,
                    4500,
                )
            )

            _human_mouse_wander(page)

            print(
                "Фактический URL:",
                page.url,
            )

            if response is not None:
                print(
                    "HTTP status:",
                    response.status,
                )

            body = page.locator("body")

            if body.count() > 0:
                text = body.inner_text(
                    timeout=10_000
                )

                if text.strip():
                    print(
                        "Страница HH успешно загружена."
                    )
                    return

        except (
            PlaywrightTimeoutError,
            PlaywrightError,
        ) as error:

            last_error = error

            print(
                "Не удалось открыть этот адрес:",
                error,
            )

        print(
            "Пробую следующий вариант...\n"
        )

    raise RuntimeError(
        "Не удалось загрузить страницу поиска HH "
        "ни через hh.ru, ни через ufa.hh.ru."
    ) from last_error


# ============================================================
# Сниппет карточки
# ============================================================

def _extract_snippet_for_link(
    element,
) -> str:
    """
    Извлекает короткий сниппет обязанностей/требований
    непосредственно из DOM карточки HH.

    Если разметка HH изменилась — возвращает пустую строку.
    Это не критическая ошибка.
    """

    try:
        card = element.locator(
            "xpath=ancestor::*[@data-qa][1]"
        ).first

        if card.count() == 0:
            return ""

        parts: list[str] = []

        for selector in _SNIPPET_TEXT_SELECTORS:
            try:
                node = card.locator(
                    selector
                ).first

                if node.count() == 0:
                    continue

                text = node.inner_text(
                    timeout=800
                ).strip()

                if text:
                    parts.append(text)

            except Exception:
                continue

        return " ".join(parts)

    except Exception:
        return ""


# ============================================================
# Извлечение вакансий
# ============================================================

def _extract_vacancy_links(
    page,
) -> dict[str, dict]:
    """
    Извлекает уникальные вакансии с текущей страницы.

    Возвращает:

        {
            vacancy_id: {
                id,
                title,
                url,
                snippet,
            }
        }
    """

    found: dict[str, dict] = {}

    links = page.locator(
        'a[href*="/vacancy/"]'
    )

    count = links.count()

    print(
        "Ссылок /vacancy/ в текущем DOM:",
        count,
    )

    for i in range(count):

        element = links.nth(i)

        try:
            href = (
                element.get_attribute("href")
                or ""
            )

        except Exception:
            continue

        absolute_url = urljoin(
            "https://hh.ru",
            href,
        )

        match = VACANCY_RE.search(
            absolute_url
        )

        if not match:
            continue

        vacancy_id = match.group(1)

        if vacancy_id in found:
            continue

        try:
            title = element.inner_text(
                timeout=1000
            ).strip()

        except Exception:
            title = ""

        snippet = _extract_snippet_for_link(
            element
        )

        found[vacancy_id] = {
            "id": vacancy_id,
            "title": title,
            "url": (
                "https://hh.ru/vacancy/"
                f"{vacancy_id}"
            ),
            "snippet": snippet,
        }

    return found


# ============================================================
# Fast filter
# ============================================================

def _apply_fast_filter(
    card: dict,
) -> dict:
    """
    Прогоняет короткую карточку через fast-filter.

    ВАЖНО:
        Здесь НЕ открывается вакансия.

        HARD_REJECT остаётся на уровне списка и никогда
        не передаётся дальше.

        TARGET и REVIEW_BY_AI сохраняются.
    """

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

    print(
        "\n[FAST FILTER] "
        f"{result['status']}\n"
        f"Название: "
        f"{card.get('title', '')}\n"
        f"Причина: "
        f"{result['reason']}"
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
    Собирает вакансии по одному поисковому URL.

    ВАЖНО:
        max_count ограничивает число ПРОСМОТРЕННЫХ
        карточек, а не число прошедших fast-filter.

    Это означает:

        200 карточек HH
            ↓
        fast-filter
            ↓
        например:
            130 HARD_REJECT
            40 REVIEW_BY_AI
            30 TARGET

        дальше идут только 70,
        но парсер не начинает дополнительно копать
        HH ради набора ещё 200 "выживших".

    Остановка:
        1. просмотрено max_count новых вакансий;
        2. страница не дала новых вакансий;
        3. достигнут MAX_PAGES_PER_URL.
    """

    kept: dict[str, dict] = {}

    seen_ids: set[str] = set()

    hard_reject_count = 0
    target_count = 0
    review_count = 0

    def _summary() -> None:
        print(
            "\n[FAST FILTER] Итог по URL: "
            f"просмотрено {len(seen_ids)}, "
            f"HARD_REJECT: {hard_reject_count}, "
            f"TARGET: {target_count}, "
            f"REVIEW_BY_AI: {review_count}, "
            f"дальше всего: {len(kept)}"
        )

    for page_number in range(
        MAX_PAGES_PER_URL
    ):

        page_url = _with_page_param(
            search_url,
            page_number,
        )

        print(
            "\n--- Страница выдачи HH "
            f"№{page_number} ---"
        )

        open_search_page(
            page,
            page_url,
        )

        page_vacancies = (
            _extract_vacancy_links(page)
        )

        new_on_this_page = 0

        for (
            vacancy_id,
            card,
        ) in page_vacancies.items():

            if vacancy_id in seen_ids:
                continue

            # --------------------------------------------
            # Карточка считается просмотренной именно
            # здесь — до fast-filter.
            # --------------------------------------------

            seen_ids.add(vacancy_id)

            new_on_this_page += 1

            # --------------------------------------------
            # FAST FILTER
            # --------------------------------------------

            fast_result = _apply_fast_filter(
                card
            )

            status = fast_result[
                "status"
            ]

            # --------------------------------------------
            # HARD REJECT
            # --------------------------------------------

            if status == "HARD_REJECT":

                hard_reject_count += 1

                # НЕ добавляем в kept.
                # Вакансия никогда не открывается.
                continue

            # --------------------------------------------
            # TARGET
            # --------------------------------------------

            if status == "TARGET":
                target_count += 1

            # --------------------------------------------
            # REVIEW BY AI
            # --------------------------------------------

            elif status == "REVIEW_BY_AI":
                review_count += 1

            # --------------------------------------------
            # Сохраняем только то, что прошло fast-filter
            # --------------------------------------------

            kept[vacancy_id] = card

            # --------------------------------------------
            # max_count — именно число просмотренных
            # --------------------------------------------

            if len(seen_ids) >= max_count:

                print(
                    "\nДостигнут лимит "
                    f"max_count ({max_count}) "
                    "просмотренных карточек."
                )

                _summary()

                return list(
                    kept.values()
                )

        print(
            f"Новых вакансий на странице "
            f"№{page_number}: "
            f"{new_on_this_page}"
        )

        if new_on_this_page == 0:

            print(
                "Страница не дала ни одной "
                "новой вакансии — выдача HH "
                "по этому URL закончилась."
            )

            _summary()

            return list(
                kept.values()
            )

        _human_mouse_wander(
            page
        )

        page.wait_for_timeout(
            random.randint(
                700,
                1800,
            )
        )

    print(
        "Достигнут страховочный предел "
        f"MAX_PAGES_PER_URL "
        f"({MAX_PAGES_PER_URL}) — "
        "останавливаюсь на этом URL."
    )

    _summary()

    return list(
        kept.values()
    )