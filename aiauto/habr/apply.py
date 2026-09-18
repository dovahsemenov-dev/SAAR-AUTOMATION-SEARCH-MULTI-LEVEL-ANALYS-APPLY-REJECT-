
# habr/apply.py

"""
habr/apply.py

Отклик на вакансию Хабр Карьеры.

ПРЕДУПРЕЖДЕНИЕ, КОТОРОЕ СТОИТ ПРОЧИТАТЬ ДО ВКЛЮЧЕНИЯ

Сбор и парсинг (search.py, vacancy.py) написаны по реальному
HTML выдачи — там всё опирается на SSR-JSON и проверяемые
атрибуты, и должно заработать сразу.

Отклик — другое дело. HTML страницы САМОЙ вакансии и разметки
модалки отклика на момент написания не было. Поэтому селекторы
здесь построены не на классах (их пришлось бы выдумать), а на
видимом тексте кнопок — "Откликнуться", "Отправить". Это
переживает смену CSS, но не переживает смену формулировок и не
гарантирует, что модалка устроена именно так, как предполагаеФтся.

Из-за этого модуль по умолчанию ВЫКЛЮЧЕН:

    config.HABR_APPLY_ENABLED = False

В этом режиме конвейер по Хабру отрабатывает полностью — сбор,
фильтры, Qwen, письмо, валидация, дампы — и на последнем шаге
возвращает статус HABR_APPLY_DISABLED вместо клика. То есть
получается полный прогон и все дампы, но ни одного реального
отклика, пока разметка не подтверждена.

Порядок включения: сначала inspect_habr.py — он сохранит HTML
вакансии и модалки отклика. По этому HTML селекторы доводятся
до точных, и только после этого HABR_APPLY_ENABLED = True.

ПРОВЕРКА ДОСТАВКИ
=================

Как и в hh/apply.py (ФИКС №5), сам факт клика ничего не значит:
DOM может измениться, а сервер отклик не зафиксировать. Поэтому
здесь тот же подход — слушатель сетевых ответов, и статусы
различают "отправлено и подтверждено" и "отправлено, но не
подтверждено".
"""

from __future__ import annotations

import time

import config


# ============================================================
# Селекторы по тексту
# ============================================================

RESPOND_BUTTON_SELECTORS = (
    "button:has-text('Откликнуться')",
    "a:has-text('Откликнуться')",
    "[class*='vacancy-card__response'] button",
    "[class*='response'] button:has-text('Откликнуться')",
)

# На реальной разметке Хабра после обычного прямого отклика
# сопроводительное письмо находится НЕ в модалке: оно появляется
# в секции #create-vacancy-response на странице вакансии.
# Поле имеет name="body", кнопка — "Дополнить отклик".
LETTER_TEXTAREA_SELECTORS = (
    "#create-vacancy-response textarea[name='body']",
    "#create-vacancy-response textarea.basic-textarea__textarea",
    "textarea[name='body']",
)

SUBMIT_BUTTON_SELECTORS = (
    "#create-vacancy-response button[type='submit']",
    "#create-vacancy-response button:has-text('Дополнить отклик')",
    "button[type='submit']:has-text('Дополнить отклик')",
)


ALREADY_RESPONDED_TEXT_MARKERS = (
    "вы откликнулись",
    "отклик отправлен",
    "уже откликну",
    "отклик уже отправлен",
    "вы уже отправили отклик",
)

MODAL_SELECTORS = (
    "[class*='modal']",
    "[role='dialog']",
    "form[action*='response']",
)


MAX_LETTER_LENGTH = 10_000

POST_CLICK_TIMEOUT_MS = 10_000
POST_CLICK_POLL_INTERVAL_MS = 300

RESPOND_BUTTON_VISIBLE_TIMEOUT_MS = 10_000


DEFAULT_NETWORK_MARKERS = (
    "/api/frontend/responses",
    "/api/frontend/quick_responses",
    "vacancy_response",
    "/responses",
)


# ============================================================
# Утилиты
# ============================================================

def _page_text(page) -> str:
    try:
        return page.locator("body").inner_text(
            timeout=4_000
        ).strip().lower()

    except Exception:
        return ""


def _first_visible(page, selectors, timeout_ms: int = 4_000):
    """
    Возвращает первый ВИДИМЫЙ элемент по списку селекторов или
    None. Перебор идёт от самого точного к самому общему.
    """

    elapsed = 0
    poll = 250

    while elapsed <= timeout_ms:
        for selector in selectors:
            try:
                locator = page.locator(selector)
                count = locator.count()
            except Exception:
                continue

            for index in range(min(count, 10)):
                candidate = locator.nth(index)

                try:
                    if candidate.is_visible():
                        return candidate
                except Exception:
                    continue

        try:
            page.wait_for_timeout(poll)
        except Exception:
            time.sleep(poll / 1000)

        elapsed += poll

    return None


class _NetworkResponseWatcher:
    """
    Тот же приём, что в hh/apply.py: слушаем ответы сервера и по
    HTTP-коду понимаем, дошёл отклик или нет.
    """

    def __init__(self, page):
        self._page = page
        self.events: list[dict] = []

        markers = getattr(
            config,
            "HABR_NETWORK_RESPONSE_URL_MARKERS",
            DEFAULT_NETWORK_MARKERS,
        )

        self._markers = tuple(
            str(marker).lower()
            for marker in markers
        )

    def _on_response(self, response) -> None:
        if not self._markers:
            return

        try:
            url_l = str(response.url or "").lower()
        except Exception:
            return

        if not any(
            marker in url_l
            for marker in self._markers
        ):
            return

        try:
            status = response.status
        except Exception:
            status = None

        self.events.append(
            {
                "url": response.url,
                "status": status,
            }
        )

    def __enter__(self) -> "_NetworkResponseWatcher":
        try:
            self._page.on("response", self._on_response)
        except Exception:
            pass

        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        try:
            self._page.remove_listener(
                "response",
                self._on_response,
            )
        except Exception:
            pass

        return False

    def outcome(self) -> str | None:
        for event in self.events:
            status = event.get("status")

            if status is None:
                continue

            if 200 <= status < 300:
                return "confirmed"

            if status >= 400:
                return "rejected"

        return None

    def last_event_detail(self) -> str:
        if not self.events:
            return ""

        last = self.events[-1]

        return (
            f"{last.get('url', '')} "
            f"-> HTTP {last.get('status')}"
        )


# ============================================================
# Проверка "уже откликались"
# ============================================================

def check_already_responded(page) -> dict:
    """
    Аналог hh/apply.py::check_already_responded.

    Вызывается ДО Qwen-конвейера, поэтому должен быть дешёвым
    и не падать ни при какой вёрстке.
    """

    text = _page_text(page)

    for marker in ALREADY_RESPONDED_TEXT_MARKERS:
        if marker in text:
            return {
                "already_responded": True,
                "reason": (
                    "На странице вакансии Хабра найден "
                    f"маркер '{marker}'."
                ),
            }

    # Кнопка отклика есть, но неактивна.
    try:
        locator = page.locator(
            "button:has-text('Откликнуться')"
        )

        for index in range(min(locator.count(), 5)):
            candidate = locator.nth(index)

            try:
                if not candidate.is_visible():
                    continue

                disabled = (
                    candidate.get_attribute("disabled")
                    is not None
                    or candidate.get_attribute(
                        "aria-disabled"
                    ) == "true"
                )

                if disabled:
                    return {
                        "already_responded": True,
                        "reason": (
                            "Кнопка 'Откликнуться' на Хабре "
                            "неактивна при открытии страницы."
                        ),
                    }

            except Exception:
                continue

    except Exception:
        pass

    return {
        "already_responded": False,
        "reason": "",
    }


# ============================================================
# Отклик
# ============================================================

def _add_cover_letter_after_direct_response(
    page,
    letter_text: str,
    dry_run: bool,
) -> dict:
    """
    Добавляет сопроводительное письмо после обычного прямого
    отклика Хабра.

    Реальная разметка из data/habr_inspect/1000162215_modal.html:

        #create-vacancy-response
          textarea[name="body"]
          button[type="submit"] -> "Дополнить отклик"

    Важно: к моменту появления этой формы сам отклик уже отправлен.
    Поэтому ошибка добавления письма НЕ должна превращать успешный
    прямой отклик в статус неуспешного отклика.
    """
    letter = str(letter_text or "")[:MAX_LETTER_LENGTH]

    if not letter:
        return {
            "status": "LETTER_EMPTY",
            "reason": "Сопроводительное письмо пустое.",
            "resume_warning": "",
        }

    textarea = _first_visible(
        page,
        LETTER_TEXTAREA_SELECTORS,
        POST_CLICK_TIMEOUT_MS,
    )

    if textarea is None:
        return {
            "status": "LETTER_FORM_NOT_FOUND",
            "reason": (
                "Прямой отклик уже отправлен, но форма добавления "
                "сопроводительного письма не найдена."
            ),
            "resume_warning": "",
        }

    try:
        textarea.click(timeout=4_000)
        textarea.fill(letter, timeout=8_000)
    except Exception as error:
        return {
            "status": "LETTER_FILL_ERROR",
            "reason": (
                "Прямой отклик уже отправлен, но не удалось "
                f"заполнить сопроводительное письмо: {error}"
            ),
            "resume_warning": "",
        }

    if dry_run:
        return {
            "status": "DRY_RUN",
            "reason": (
                "DRY_RUN: прямой отклик не отправлялся; "
                "форма сопроводительного письма была найдена "
                "и заполнена без отправки."
            ),
            "resume_warning": "",
        }

    submit_button = _first_visible(
        page,
        SUBMIT_BUTTON_SELECTORS,
        6_000,
    )

    if submit_button is None:
        return {
            "status": "LETTER_SUBMIT_BUTTON_NOT_FOUND",
            "reason": (
                "Прямой отклик уже отправлен, но кнопка "
                "'Дополнить отклик' не найдена."
            ),
            "resume_warning": "",
        }

    with _NetworkResponseWatcher(page) as letter_watcher:
        try:
            submit_button.click(timeout=12_000)
        except Exception:
            submit_button.click(timeout=5_000, force=True)

        elapsed = 0
        while elapsed <= POST_CLICK_TIMEOUT_MS:
            if letter_watcher.outcome() is not None:
                break
            page.wait_for_timeout(POST_CLICK_POLL_INTERVAL_MS)
            elapsed += POST_CLICK_POLL_INTERVAL_MS

        outcome = letter_watcher.outcome()
        detail = letter_watcher.last_event_detail()

    if outcome == "confirmed":
        return {
            "status": "LETTER_ADDED_CONFIRMED_NETWORK",
            "reason": (
                "Сопроводительное письмо добавлено к уже отправленному "
                "отклику; сервер подтвердил запрос: " + detail
            ),
            "resume_warning": "",
        }

    if outcome == "rejected":
        return {
            "status": "LETTER_ADD_REJECTED",
            "reason": (
                "Сам прямой отклик уже был отправлен, но сервер "
                "отклонил добавление сопроводительного письма: " + detail
            ),
            "resume_warning": "",
        }

    return {
        "status": "LETTER_ADD_NOT_CONFIRMED",
        "reason": (
            "Сам прямой отклик уже был отправлен, но добавление "
            "сопроводительного письма не подтвердилось по сети."
        ),
        "resume_warning": "",
    }


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
    """
    Отклик на Хабр Карьере.

    Для response.kind != "direct" отклик пропускается: Хабр уводит
    пользователя на внешний ресурс, поэтому автоотправка внутри
    career.habr.com невозможна.

    Для response.kind == "direct" реальная разметка показывает другой
    сценарий, чем предполагалось первоначально: клик по
    "Откликнуться" отправляет прямой отклик, после чего на странице
    появляется секция #create-vacancy-response с textarea[name="body"]
    и кнопкой "Дополнить отклик". Поэтому письмо добавляется вторым
    запросом уже к отправленному отклику.
    """
    kind = str(response_kind or "").strip().lower()

    if kind and kind != "direct":
        return {
            "status": "SKIPPED_EXTERNAL_RESPONSE",
            "reason": (
                "Отклик на этой вакансии Хабра уводит на внешний ресурс "
                f"(response.kind='{kind}'), автоотклик внутри Хабра невозможен."
            ),
            "resume_warning": "",
        }

    if not bool(
        getattr(config, "HABR_APPLY_ENABLED", False)
    ):
        return {
            "status": "HABR_APPLY_DISABLED",
            "reason": (
                "Отклик на Хабре выключен "
                "(config.HABR_APPLY_ENABLED = False)."
            ),
            "resume_warning": "",
        }

    try:
        respond_button = _first_visible(
            page,
            RESPOND_BUTTON_SELECTORS,
            RESPOND_BUTTON_VISIBLE_TIMEOUT_MS,
        )

        if respond_button is None:
            return {
                "status": "NO_RESPONSE_BUTTON",
                "reason": (
                    "Видимая кнопка 'Откликнуться' не найдена "
                    f"на странице Хабра. URL: {page.url}"
                ),
                "resume_warning": "",
            }

        try:
            respond_button.scroll_into_view_if_needed(timeout=4_000)
        except Exception:
            pass

        # DRY_RUN не должен отправлять прямой отклик.
        if dry_run:
            return {
                "status": "DRY_RUN",
                "reason": (
                    "DRY_RUN: кнопка прямого отклика найдена, "
                    "реальный клик/отправка не выполнялись."
                ),
                "resume_warning": "",
            }

        # --------------------------------------------------------
        # STEP 1 — реальный прямой отклик.
        # --------------------------------------------------------
        with _NetworkResponseWatcher(page) as watcher:
            try:
                respond_button.click(timeout=12_000)
            except Exception:
                respond_button.click(timeout=5_000, force=True)

            elapsed = 0
            while elapsed <= POST_CLICK_TIMEOUT_MS:
                if watcher.outcome() is not None:
                    break
                page.wait_for_timeout(POST_CLICK_POLL_INTERVAL_MS)
                elapsed += POST_CLICK_POLL_INTERVAL_MS

            outcome = watcher.outcome()
            detail = watcher.last_event_detail()

        # Сервер подтвердил прямой отклик. Теперь добавляем письмо
        # через реальную форму #create-vacancy-response.
        if outcome == "confirmed":
            letter_result = _add_cover_letter_after_direct_response(
                page,
                letter_text,
                dry_run=False,
            )

            warning = ""
            if letter_result["status"] != "LETTER_ADDED_CONFIRMED_NETWORK":
                warning = letter_result["reason"]

            return {
                "status": "SUBMITTED_CONFIRMED_NETWORK",
                "reason": (
                    "Прямой отклик на Хабре подтверждён сервером: "
                    + detail
                    + (
                        " Сопроводительное письмо также добавлено."
                        if not warning
                        else " " + warning
                    )
                ),
                "resume_warning": warning,
                "letter_status": letter_result["status"],
            }

        if outcome == "rejected":
            return {
                "status": "REJECTED_BY_SERVER",
                "reason": (
                    "Сервер Хабра отклонил прямой отклик: " + detail
                ),
                "resume_warning": "",
            }

        # --------------------------------------------------------
        # STEP 2 — сетевого подтверждения нет. Проверяем страницу.
        # --------------------------------------------------------
        try:
            page.wait_for_timeout(1_000)
            recheck = check_already_responded(page)

            if recheck["already_responded"]:
                letter_result = _add_cover_letter_after_direct_response(
                    page,
                    letter_text,
                    dry_run=False,
                )

                warning = ""
                if letter_result["status"] != "LETTER_ADDED_CONFIRMED_NETWORK":
                    warning = letter_result["reason"]

                return {
                    "status": "SUBMITTED_CONFIRMED_RELOAD",
                    "reason": (
                        "После клика страница показывает, что прямой "
                        "отклик отправлен: "
                        + recheck["reason"]
                        + (
                            " Сопроводительное письмо также добавлено."
                            if not warning
                            else " " + warning
                        )
                    ),
                    "resume_warning": warning,
                    "letter_status": letter_result["status"],
                }
        except Exception:
            pass

        return {
            "status": "SUBMITTED_NOT_CONFIRMED",
            "reason": (
                "Клик по прямому отклику на Хабре прошёл, но его "
                "доставка не подтвердилась ни сетевым сигналом, ни "
                "состоянием страницы. Считать отклик отправленным нельзя."
            ),
            "resume_warning": "",
        }

    except Exception as error:
        return {
            "status": "ERROR",
            "reason": (
                "Исключение при отклике на Хабре: "
                f"{error}"
            ),
            "resume_warning": "",
        }

