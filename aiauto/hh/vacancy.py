# hh/vacancy.py
import random

from playwright.sync_api import Page

from hh.browser import ensure_not_blocked


def _safe_text(
    page: Page,
    selector: str,
) -> str:
    try:
        locator = page.locator(selector).first

        if locator.count() == 0:
            return ""

        return locator.inner_text(
            timeout=5000
        ).strip()

    except Exception:
        return ""


def _safe_all_texts(
    page: Page,
    selector: str,
) -> list[str]:
    result = []

    try:
        locator = page.locator(selector)
        count = locator.count()

        for index in range(count):
            try:
                text = locator.nth(
                    index
                ).inner_text(
                    timeout=2000
                ).strip()
            except Exception:
                continue

            if (
                text
                and text not in result
            ):
                result.append(text)

    except Exception:
        pass

    return result


def _normalize_text(
    value: str,
) -> str:
    return " ".join(
        str(value or "")
        .lower()
        .replace("ё", "е")
        .split()
    )


def _normalize_work_format(
    raw_work_format: str,
) -> dict:
    """
    Преобразует структурированный текст HH
    в отдельные машинные признаки.

    ВАЖНО:
    "на месте работодателя" должно давать office=True.
    """

    raw = str(
        raw_work_format or ""
    ).strip()

    text = _normalize_text(raw)

    remote_markers = (
        "удаленно",
        "удаленная",
        "удаленный",
        "дистанционно",
        "дистанционная",
        "дистанционный",
        "remote",
    )

    hybrid_markers = (
        "гибрид",
        "hybrid",
    )

    office_markers = (
        "на месте работодателя",
        "в офисе",
        "офисный",
        "офисная",
        "офисе",
        "работа в офисе",
    )

    remote = any(
        _normalize_text(marker) in text
        for marker in remote_markers
    )

    hybrid = any(
        _normalize_text(marker) in text
        for marker in hybrid_markers
    )

    office = any(
        _normalize_text(marker) in text
        for marker in office_markers
    )

    return {
        "raw": raw,
        "remote": remote,
        "office": office,
        "hybrid": hybrid,
        "unknown": not (
            remote
            or office
            or hybrid
        ),
    }


def _human_read_pause(page: Page) -> None:
    """
    Небольшая пауза и прокрутка перед чтением DOM.
    Это НЕ механизм обхода CAPTCHA.
    """

    try:
        page.wait_for_timeout(
            random.randint(600, 1600)
        )

        viewport = page.viewport_size or {
            "width": 1280,
            "height": 800,
        }

        x = random.randint(
            60, max(61, viewport["width"] - 60)
        )
        y = random.randint(
            60, max(61, viewport["height"] - 60)
        )

        page.mouse.move(
            x,
            y,
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


def open_vacancy(
    page: Page,
    url: str,
) -> dict:
    """
    Открывает страницу вакансии и извлекает
    структурированные данные непосредственно из DOM HH.

    После перехода на URL обязательно повторно проверяем CAPTCHA/
    блокировку до извлечения данных и до передачи страницы дальше.
    """

    page.goto(
        url,
        wait_until="domcontentloaded",
        timeout=60_000,
    )

    # Проверка сразу после перехода.
    ensure_not_blocked(
        page,
        "сразу после goto",
    )

    page.wait_for_timeout(
        random.randint(1500, 2800)
    )

    # Проверка после ожидания: HH мог показать challenge
    # не в момент первого DOM-состояния.
    ensure_not_blocked(
        page,
        "после ожидания загрузки",
    )

    _human_read_pause(page)

    # Проверка ещё раз после прокрутки/паузы.
    ensure_not_blocked(
        page,
        "после human_read_pause",
    )

    title = _safe_text(
        page,
        '[data-qa="vacancy-title"]',
    )

    company = _safe_text(
        page,
        '[data-qa="vacancy-company-name"]',
    )

    salary = _safe_text(
        page,
        '[data-qa="vacancy-salary"]',
    )

    description = _safe_text(
        page,
        '[data-qa="vacancy-description"]',
    )

    experience = _safe_text(
        page,
        '[data-qa="vacancy-experience"]',
    )

    employment = _safe_text(
        page,
        '[data-qa="common-employment-text"]',
    )

    schedule = _safe_text(
        page,
        '[data-qa="work-schedule-by-days-text"]',
    )

    working_hours = _safe_text(
        page,
        '[data-qa="working-hours-text"]',
    )

    work_format_raw = _safe_text(
        page,
        '[data-qa="work-formats-text"]',
    )

    location = _safe_text(
        page,
        '[data-qa="vacancy-view-raw-address"]',
    )

    if not location:
        location = _safe_text(
            page,
            '[data-qa="vacancy-address-with-map"]',
        )

    skills = _safe_all_texts(
        page,
        '[data-qa="skills-element"]',
    )

    if not title:
        title = _safe_text(
            page,
            "h1",
        )

    # Если CAPTCHA появилась между началом парсинга и fallback,
    # не возвращаем мусорную страницу в pipeline.
    ensure_not_blocked(
        page,
        "после извлечения основных полей",
    )

    if not description:
        description = _safe_text(
            page,
            "body",
        )

    work_format = _normalize_work_format(
        work_format_raw
    )

    return {
        "url": page.url,
        "title": title,
        "company": (
            company
            or "Не указана"
        ),
        "salary": (
            salary
            or "Не указана"
        ),
        "description": description,
        "experience": (
            experience
            or "Не указано"
        ),
        "employment": (
            employment
            or "Не указано"
        ),
        "schedule": (
            schedule
            or "Не указано"
        ),
        "working_hours": (
            working_hours
            or "Не указано"
        ),
        "work_format": work_format,
        "location": (
            location
            or "Не указано"
        ),
        "skills": skills,
    }
