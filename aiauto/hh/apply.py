# hh/apply.py

"""
hh/apply.py

Обработка отклика на вакансию HH.
"""

import os
import random
import time
import config


# ============================================================
# Селекторы
# ============================================================

RESPOND_BUTTON_SELECTOR = (
    "[data-qa='vacancy-response-link-top'], "
    "[data-qa='vacancy-response-link-bottom']"
)

MODAL_SELECTOR = "[data-qa='modal-overlay']"

RELOCATION_WARNING_SELECTOR = "[data-qa='relocation-warning-confirm']"

RESUME_WARNING_SELECTOR = "[data-qa='hidden-resume-warning']"

ADD_COVER_LETTER_BUTTON_SELECTOR = "[data-qa='add-cover-letter']"

LETTER_TEXTAREA_SELECTOR = (
    "[data-qa='vacancy-response-popup-form-letter-input']"
)

SUBMIT_BUTTON_SELECTOR = "[data-qa='vacancy-response-submit-popup']"

CLOSE_BUTTON_SELECTOR = "[data-qa='response-popup-close']"

ERROR_NOTIFICATION_SELECTOR = (
    "[data-qa='bloko-notification'], "
    "[data-qa='notification'], "
    ".bloko-notification_error, "
    "[data-qa='error-notification']"
)

ALREADY_RESPONDED_SELECTOR = (
    "[data-qa='vacancy-response-link-top'][disabled], "
    "[data-qa='vacancy-response-link-bottom'][disabled], "
    "[data-qa='vacancy-response-link-top'][aria-disabled='true'], "
    "[data-qa='vacancy-response-link-bottom'][aria-disabled='true'], "
    "[data-qa='response-already-sent']"
)

_ALREADY_RESPONDED_TEXT_MARKERS = (
    "вы откликнулись",
    "отклик отправлен",
    "уже откликну",
    "уже откликались",
    "отклик уже отправлен",
)

# ФИКС №6 (см. check_already_responded и respond_to_vacancy ниже):
# сколько символов видимого текста страницы сканировать широким
# fallback-поиском маркеров "уже откликались". Ограничение — просто
# защита от аномально длинных страниц, не для тонкой настройки.
BODY_TEXT_SCAN_TIMEOUT_MS = 3_000

_BENIGN_NOTIFICATION_TEXT_MARKERS = (
    "откликайтесь, чтобы работодатель заметил вас",
)


# ============================================================
# Ограничения
# ============================================================

MAX_LETTER_LENGTH = 10_000

POST_CLICK_TIMEOUT_MS = 8_000
POST_CLICK_POLL_INTERVAL_MS = 250

DEBUG_DUMP_DIR = os.environ.get(
    "HH_APPLY_DEBUG_DUMP_DIR",
    "debug_dumps/no_modal",
)

MIN_WAIT_BEFORE_BUTTON_HEURISTIC_MS = 2_500
RESPOND_BUTTON_VISIBLE_TIMEOUT_MS = 10_000


# ============================================================
# Утилиты
# ============================================================

def _safe_text(locator) -> str:
    try:
        if locator.count() == 0:
            return ""

        return locator.first.inner_text(timeout=2_000).strip()

    except Exception:
        return ""


def _has_visible_match(locator) -> bool:
    try:
        count = locator.count()
    except Exception:
        return False

    for i in range(count):
        try:
            if locator.nth(i).is_visible():
                return True
        except Exception:
            continue

    return False


def _pick_visible_respond_button(
    page,
    timeout_ms: int = RESPOND_BUTTON_VISIBLE_TIMEOUT_MS,
    poll_interval_ms: int = 200,
):
    locator = page.locator(RESPOND_BUTTON_SELECTOR)

    elapsed_ms = 0

    while elapsed_ms <= timeout_ms:
        try:
            count = locator.count()
        except Exception:
            count = 0

        for i in range(count):
            candidate = locator.nth(i)

            try:
                if candidate.is_visible():
                    return candidate
            except Exception:
                continue

        try:
            page.wait_for_timeout(poll_interval_ms)
        except Exception:
            time.sleep(poll_interval_ms / 1000)

        elapsed_ms += poll_interval_ms

    return None


class _NetworkResponseWatcher:
    def __init__(self, page):
        self._page = page
        self.events: list[dict] = []

        self._markers = tuple(
            marker.lower()
            for marker in getattr(
                config,
                "NETWORK_RESPONSE_URL_MARKERS",
                (),
            )
        )

    def _on_response(self, response) -> None:
        if not self._markers:
            return

        try:
            url_l = str(response.url or "").lower()
        except Exception:
            return

        if not any(marker in url_l for marker in self._markers):
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


def _respond_button_snapshot(page) -> dict:
    button = page.locator(RESPOND_BUTTON_SELECTOR)

    try:
        count = button.count()
    except Exception:
        count = 0

    if count == 0:
        return {
            "present": False,
            "text": "",
            "disabled": False,
        }

    text = _safe_text(button)

    disabled = False

    try:
        disabled = bool(
            button.first.get_attribute("disabled") is not None
            or button.first.get_attribute("aria-disabled") == "true"
        )
    except Exception:
        pass

    return {
        "present": True,
        "text": text,
        "disabled": disabled,
    }


def _looks_like_already_responded(snapshot_text: str) -> bool:
    low = (snapshot_text or "").strip().lower()

    return any(
        marker in low
        for marker in _ALREADY_RESPONDED_TEXT_MARKERS
    )


# ФИКС №6 (баг "NO_RESPONSE_BUTTON на вакансиях, на которые уже
# откликались"): ALREADY_RESPONDED_SELECTOR и текст самой кнопки
# отклика (см. _looks_like_already_responded выше) покрывают только
# те варианты вёрстки HH, которые уже были замечены раньше. На
# практике часть вакансий (см. дампы no_response_button —
# скриншоты по ним показывают явный текст "вы уже откликнулись"/
# "отклик отправлен" где-то на странице) рендерит это состояние
# другой вёрсткой: например, кнопка "Откликнуться" пропадает со
# страницы целиком, а статус выводится текстом, не попадающим ни
# под один из известных data-qa-селекторов. В таких случаях старая
# логика ошибочно считала вакансию "новой", весь Qwen-конвейер
# отрабатывал заново, а на этапе реального отклика кнопки, конечно,
# не находилось — и вакансия улетала в NO_RESPONSE_BUTTON. Так как
# NO_RESPONSE_BUTTON не попадает в _PERMANENTLY_APPLIED_EXACT_STATUSES
# (см. main.py::record_applied_id), такая вакансия НЕ сохранялась в
# applied_ids.json — и при следующем прогоне процесс повторялся
# заново до бесконечности, вхолостую съедая весь Qwen-конвейер на
# уже отвеченных вакансиях.
#
# Это последний рубеж проверки: сканируем весь видимый текст
# страницы (а не только кнопку и известные селекторы) на маркеры
# "уже откликались". Он медленнее точечного селектора, поэтому
# вызывается только когда более быстрые проверки уже не сработали.
def _page_body_text(page) -> str:
    try:
        return (
            page.locator("body")
            .inner_text(timeout=BODY_TEXT_SCAN_TIMEOUT_MS)
            .strip()
            .lower()
        )
    except Exception:
        return ""


def _page_looks_like_already_responded(page) -> bool:
    body_text = _page_body_text(page)

    if not body_text:
        return False

    return any(
        marker in body_text
        for marker in _ALREADY_RESPONDED_TEXT_MARKERS
    )


def _baseline_looks_already_responded(
    baseline_button_snapshot: dict,
) -> bool:
    if not isinstance(baseline_button_snapshot, dict):
        return False

    if baseline_button_snapshot.get("disabled"):
        return True

    return _looks_like_already_responded(
        baseline_button_snapshot.get("text", "")
    )


def _looks_like_benign_notification(
    notification_text: str,
) -> bool:
    low = (notification_text or "").strip().lower()

    return any(
        marker in low
        for marker in _BENIGN_NOTIFICATION_TEXT_MARKERS
    )


def _dump_debug_state(
    page,
    vacancy_id: str | None,
    state_label: str = "no_modal",
) -> None:
    if not config.DEBUG_MODE:
        return

    try:
        os.makedirs(
            DEBUG_DUMP_DIR,
            exist_ok=True,
        )

        stamp = time.strftime("%Y%m%d_%H%M%S")

        safe_id = str(
            vacancy_id or "unknown"
        ).replace("/", "_")

        safe_label = str(
            state_label or "unknown"
        ).replace("/", "_")

        base_name = (
            f"{stamp}_{safe_label}_{safe_id}"
        )

        screenshot_path = os.path.join(
            DEBUG_DUMP_DIR,
            f"{base_name}.png",
        )

        html_path = os.path.join(
            DEBUG_DUMP_DIR,
            f"{base_name}.html",
        )

        try:
            page.screenshot(
                path=screenshot_path,
                full_page=True,
            )
        except Exception:
            pass

        try:
            html = page.content()

            with open(
                html_path,
                "w",
                encoding="utf-8",
            ) as file:
                file.write(html)

        except Exception:
            pass

    except Exception:
        pass


# ============================================================
# Проверка результата через reload
# ============================================================

def _confirm_via_reload(page) -> dict:
    try:
        page.reload(
            wait_until="domcontentloaded",
            timeout=60_000,
        )

    except Exception as error:
        return {
            "confirmed": None,
            "reason": (
                "Не удалось перезагрузить страницу вакансии: "
                f"{error}"
            ),
        }

    try:
        page.wait_for_timeout(
            random.randint(1200, 2200)
        )
    except Exception:
        pass

    try:
        from hh.browser import check_blocked

        blocked = check_blocked(page)

        if blocked.get("blocked"):
            return {
                "confirmed": None,
                "reason": (
                    "Обнаружена капча "
                    f"({blocked.get('reason')})"
                ),
            }

    except Exception:
        pass

    snapshot = _respond_button_snapshot(page)

    if not snapshot["present"]:
        return {
            "confirmed": True,
            "reason": (
                "Кнопка отсутствует — сервер считает "
                "отклик отправленным."
            ),
        }

    if (
        snapshot["disabled"]
        or _looks_like_already_responded(
            snapshot["text"]
        )
    ):
        return {
            "confirmed": True,
            "reason": (
                "Кнопка заблокирована "
                f"(текст='{snapshot['text']}')"
            ),
        }

    return {
        "confirmed": False,
        "reason": (
            "Кнопка активна "
            f"(текст='{snapshot['text']}') — "
            "отклик не дошел."
        ),
    }


# ============================================================
# Ожидание состояния после клика "Откликнуться"
# ============================================================

def _wait_for_post_click_state(
    page,
    modal_locator,
    baseline_button_snapshot: dict,
    network_watcher: _NetworkResponseWatcher | None = None,
    timeout_ms: int = POST_CLICK_TIMEOUT_MS,
    poll_interval_ms: int = POST_CLICK_POLL_INTERVAL_MS,
    min_wait_before_button_heuristic_ms: int = (
        MIN_WAIT_BEFORE_BUTTON_HEURISTIC_MS
    ),
) -> str:
    error_locator = page.locator(
        ERROR_NOTIFICATION_SELECTOR
    )

    already_responded_locator = page.locator(
        ALREADY_RESPONDED_SELECTOR
    )

    baseline_already_like = (
        _baseline_looks_already_responded(
            baseline_button_snapshot
        )
    )

    elapsed_ms = 0

    while elapsed_ms <= timeout_ms:
        # ----------------------------------------------------
        # Проверяем сетевой результат
        # ----------------------------------------------------

        if network_watcher is not None:
            try:
                network_outcome = (
                    network_watcher.outcome()
                )
            except Exception:
                network_outcome = None

            if network_outcome == "confirmed":
                return "network_confirmed"

            if network_outcome == "rejected":
                return "network_rejected"

        # ----------------------------------------------------
        # Предупреждение HH о вакансии в другой стране
        # ----------------------------------------------------

        try:
            if _has_visible_match(
                page.locator(RELOCATION_WARNING_SELECTOR)
            ):
                return "relocation_warning"
        except Exception:
            pass

        # ----------------------------------------------------
        # Обычная модалка
        # ----------------------------------------------------

        try:
            if modal_locator.count() > 0:
                return "modal"
        except Exception:
            pass

        # ----------------------------------------------------
        # Сложная анкета
        # ----------------------------------------------------

        try:
            from hh.complex_application import (
                is_complex_application_page,
            )

            if is_complex_application_page(page):
                return "complex"

        except Exception:
            pass

        # ----------------------------------------------------
        # Ошибка HH
        # ----------------------------------------------------

        try:
            if error_locator.count() > 0:
                notification_text = _safe_text(
                    error_locator
                )

                if not _looks_like_benign_notification(
                    notification_text
                ):
                    return "error_notification"

        except Exception:
            pass

        # ----------------------------------------------------
        # Не делаем эвристику кнопки слишком рано
        # ----------------------------------------------------

        if (
            elapsed_ms
            < min_wait_before_button_heuristic_ms
        ):
            page.wait_for_timeout(
                poll_interval_ms
            )

            elapsed_ms += poll_interval_ms
            continue

        # ----------------------------------------------------
        # Проверяем состояние "уже откликнулись"
        # ----------------------------------------------------

        try:
            if _has_visible_match(
                already_responded_locator
            ):
                if baseline_already_like:
                    return "already_responded"

                _dump_debug_state(
                    page,
                    None,
                    state_label=(
                        "instant_apply_after_click"
                    ),
                )

                return "instant_apply"

        except Exception:
            pass

        current_snapshot = (
            _respond_button_snapshot(page)
        )

        if _looks_like_already_responded(
            current_snapshot["text"]
        ):
            if baseline_already_like:
                return "already_responded"

            _dump_debug_state(
                page,
                None,
                state_label=(
                    "instant_apply_after_click"
                ),
            )

            return "instant_apply"

        # ----------------------------------------------------
        # Сравниваем состояние кнопки до и после клика
        # ----------------------------------------------------

        if baseline_button_snapshot.get("present"):
            if not current_snapshot["present"]:
                return "instant_apply"

            if (
                current_snapshot["disabled"]
                and not baseline_button_snapshot.get(
                    "disabled"
                )
            ):
                return "instant_apply"

            baseline_text = (
                baseline_button_snapshot.get("text")
            )

            current_text = (
                current_snapshot.get("text")
            )

            if (
                current_text
                and baseline_text
                and current_text != baseline_text
            ):
                return "instant_apply"

        page.wait_for_timeout(
            poll_interval_ms
        )

        elapsed_ms += poll_interval_ms

    return "no_modal"


# ============================================================
# Предварительная проверка "уже откликались"
# ============================================================

def check_already_responded(page) -> dict:
    # ФИКС (баг "открывает уже отвеченные вакансии и падает в
    # NO_RESPONSE_BUTTON"): раньше отсутствие самой кнопки
    # (snapshot["present"] == False) считалось равносильным "не
    # откликались" и функция выходила СРАЗУ, до проверки
    # ALREADY_RESPONDED_SELECTOR. Но в ALREADY_RESPONDED_SELECTOR есть
    # [data-qa='response-already-sent'] — отдельный от кнопки элемент,
    # который HH в части случаев рендерит ВМЕСТО кнопки целиком (не
    # как задизейбленную кнопку с тем же data-qa), когда отклик уже
    # был отправлен раньше. Из-за раннего return такие вакансии
    # проходили как "новые": весь Qwen-конвейер отрабатывал заново, а
    # на этапе реального отклика кнопки, разумеется, снова не
    # оказывалось, и вакансия улетала в NO_RESPONSE_BUTTON вместо
    # ALREADY_RESPONDED. Теперь эта проверка выполняется первой и не
    # зависит от присутствия кнопки.
    try:
        if _has_visible_match(
            page.locator(
                ALREADY_RESPONDED_SELECTOR
            )
        ):
            return {
                "already_responded": True,
                "reason": (
                    "На странице присутствует видимый "
                    "элемент ALREADY_RESPONDED_SELECTOR "
                    "(кнопка 'Откликнуться' при этом может "
                    "отсутствовать на странице целиком)."
                ),
            }

    except Exception:
        pass

    snapshot = _respond_button_snapshot(page)

    if snapshot["present"]:
        if snapshot["disabled"]:
            return {
                "already_responded": True,
                "reason": (
                    "Кнопка 'Откликнуться' уже неактивна "
                    "при открытии страницы."
                ),
            }

        if _looks_like_already_responded(
            snapshot["text"]
        ):
            return {
                "already_responded": True,
                "reason": (
                    "Текст кнопки уже содержит маркер "
                    f"('{snapshot['text']}')."
                ),
            }

    # ФИКС №6 (см. докстринг _page_looks_like_already_responded выше):
    # ни специфичный селектор, ни состояние/текст самой кнопки не
    # опознали "уже откликались" — но кнопка при этом либо
    # отсутствует на странице целиком, либо выглядит обычной. Прежде
    # чем считать вакансию новой и пускать её в Qwen-конвейер,
    # сканируем весь видимый текст страницы на те же маркеры. Именно
    # отсутствие этой проверки раньше приводило к тому, что бот
    # заново прогонял через Qwen вакансии, на которые уже откликался,
    # и в итоге получал NO_RESPONSE_BUTTON на этапе клика.
    if _page_looks_like_already_responded(page):
        return {
            "already_responded": True,
            "reason": (
                "Специфичный селектор и текст/состояние кнопки не "
                "опознали статус, но широкий скан видимого текста "
                "страницы нашёл маркер 'уже откликались'/"
                "'отклик отправлен'."
            ),
        }

    return {
        "already_responded": False,
        "reason": "",
    }


# ============================================================
# Основной отклик
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
) -> dict:
    try:
        # ----------------------------------------------------
        # Проверяем наличие кнопки
        # ----------------------------------------------------

        if (
            page.locator(
                RESPOND_BUTTON_SELECTOR
            ).count()
            == 0
        ):
            current_url = str(getattr(page, "url", "") or "")

            # ФИКС (второй эшелон, см. check_already_responded в этом
            # же файле): если между вызовом check_already_responded()
            # и этим моментом страница успела показать состояние
            # "уже откликались" (например, respond_to_vacancy вызвана
            # без предварительной проверки, либо страница
            # перерисовалась) — не сдаёмся в NO_RESPONSE_BUTTON,
            # а сначала проверяем явный маркер "уже откликались".
            try:
                if _has_visible_match(
                    page.locator(
                        ALREADY_RESPONDED_SELECTOR
                    )
                ):
                    return {
                        "status": "ALREADY_RESPONDED",
                        "reason": (
                            "Кнопка 'Откликнуться' отсутствует "
                            "на странице целиком, но присутствует "
                            "видимый элемент "
                            "ALREADY_RESPONDED_SELECTOR — отклик "
                            "уже был отправлен ранее."
                        ),
                        "resume_warning": "",
                    }
            except Exception:
                pass

            # ФИКС №6 (второй эшелон, см. _page_looks_like_already_
            # responded в этом же файле): тот же широкий скан текста
            # страницы, что и в check_already_responded(). Нужен
            # здесь на случай, если check_already_responded() уже
            # был вызван раньше (в main.py, до Qwen-конвейера) и не
            # нашёл маркер, а к моменту реального клика страница
            # успела перерисоваться — либо respond_to_vacancy была
            # вызвана без предварительной проверки вообще. Раньше в
            # этой точке код без дополнительных вопросов сдавался в
            # NO_RESPONSE_BUTTON, из-за чего такая вакансия не
            # попадала в applied_ids.json как окончательно отвеченная
            # и при каждом следующем прогоне анализировалась заново.
            try:
                if _page_looks_like_already_responded(page):
                    return {
                        "status": "ALREADY_RESPONDED",
                        "reason": (
                            "Кнопка 'Откликнуться' отсутствует на "
                            "странице целиком, известный селектор "
                            "ALREADY_RESPONDED_SELECTOR тоже не "
                            "совпал, но широкий скан видимого текста "
                            "страницы нашёл маркер 'уже "
                            "откликались'/'отклик отправлен' — "
                            "отклик уже был отправлен ранее."
                        ),
                        "resume_warning": "",
                    }
            except Exception:
                pass

            # ФИКС: часть вакансий с доп. вопросами рендерит
            # анкету (task-body) сразу инлайново на странице
            # вакансии, без отдельной кнопки-ссылки
            # "Откликнуться" сверху/снизу — то есть у них просто
            # нет элемента RESPOND_BUTTON_SELECTOR, а есть сразу
            # анкета. До этого фикса такие вакансии безусловно
            # улетали в NO_RESPONSE_BUTTON, а детектор сложной
            # анкеты (is_complex_application_page) вызывался
            # только внутри _wait_for_post_click_state() — то
            # есть ПОСЛЕ клика по кнопке отклика, которого в
            # этом случае нет и быть не может. Поэтому перед тем
            # как сдаться, проверяем: может, это уже открытая
            # сложная анкета.
            try:
                from hh.complex_application import (
                    is_complex_application_page,
                )

                if is_complex_application_page(page):
                    if (
                        profile_facts is None
                        or ollama_url is None
                        or model_name is None
                    ):
                        return {
                            "status": "NO_COMPLEX_CONTEXT",
                            "reason": (
                                "Кнопка 'Откликнуться' не "
                                "найдена, анкета отрендерена "
                                "инлайново на странице вакансии "
                                "(без клика), но отсутствует "
                                "AI-контекст для сложной анкеты."
                            ),
                            "resume_warning": "",
                        }

                    from hh.complex_application import (
                        handle_complex_application,
                    )

                    return handle_complex_application(
                        page=page,
                        vacancy_text=vacancy_text,
                        profile_facts=profile_facts,
                        ollama_url=ollama_url,
                        model_name=model_name,
                        dry_run=dry_run,
                        vacancy_id=vacancy_id,
                    )

            except Exception:
                # Детектор не должен уронить основной путь —
                # если что-то пошло не так, просто продолжаем
                # считать, что кнопки нет.
                pass

            _dump_debug_state(
                page,
                vacancy_id,
                state_label="no_response_button",
            )

            return {
                "status": "NO_RESPONSE_BUTTON",
                "reason": (
                    "Кнопка 'Откликнуться' не найдена на странице,"
                    " инлайновая сложная анкета тоже не"
                    f" обнаружена. URL: {current_url}"
                ),
                "resume_warning": "",
            }

        respond_button = (
            _pick_visible_respond_button(page)
        )

        if respond_button is None:
            _dump_debug_state(
                page,
                vacancy_id,
                state_label=(
                    "respond_button_not_visible"
                ),
            )

            return {
                "status": (
                    "RESPOND_BUTTON_NOT_VISIBLE"
                ),
                "reason": (
                    "Кнопка присутствует, но "
                    "не стала видимой."
                ),
                "resume_warning": "",
            }

        try:
            respond_button.scroll_into_view_if_needed(
                timeout=5_000
            )
        except Exception:
            pass

        baseline_snapshot = (
            _respond_button_snapshot(page)
        )

        # ----------------------------------------------------
        # Кликаем "Откликнуться"
        # ----------------------------------------------------

        try:
            respond_button.click(
                timeout=15_000
            )

        except Exception as click_error:
            try:
                respond_button.click(
                    timeout=5_000,
                    force=True,
                )

            except Exception:
                _dump_debug_state(
                    page,
                    vacancy_id,
                    state_label=(
                        "respond_button_click_failed"
                    ),
                )

                return {
                    "status": (
                        "RESPOND_BUTTON_CLICK_FAILED"
                    ),
                    "reason": (
                        f"Клик не удался: "
                        f"{click_error}"
                    ),
                    "resume_warning": "",
                }

        modal = page.locator(
            MODAL_SELECTOR
        )

        network_watcher = (
            _NetworkResponseWatcher(page)
        )

        network_watcher.__enter__()

        try:
            # ------------------------------------------------
            # Определяем состояние после клика
            # ------------------------------------------------

            post_click_state = (
                _wait_for_post_click_state(
                    page,
                    modal,
                    baseline_snapshot,
                    network_watcher=network_watcher,
                )
            )

            network_detail = (
                network_watcher.last_event_detail()
            )

            # ------------------------------------------------
            # Сеть подтвердила успешную отправку
            # ------------------------------------------------

            if (
                post_click_state
                == "network_confirmed"
            ):
                return {
                    "status": (
                        "SUBMITTED_CONFIRMED_NETWORK"
                    ),
                    "reason": (
                        "Доставка отклика подтверждена "
                        "на сетевом уровне: "
                        f"{network_detail}"
                    ),
                    "resume_warning": "",
                }

            # ------------------------------------------------
            # Сервер отклонил запрос
            # ------------------------------------------------

            if (
                post_click_state
                == "network_rejected"
            ):
                _dump_debug_state(
                    page,
                    vacancy_id,
                    state_label="network_rejected",
                )

                return {
                    "status": "REJECTED_BY_SERVER",
                    "reason": (
                        "Сервер вернул ошибку: "
                        f"{network_detail}"
                    ),
                    "resume_warning": "",
                }

            # ------------------------------------------------
            # Предупреждение о вакансии в другой стране
            # ------------------------------------------------

            if post_click_state == "relocation_warning":
                relocation_confirm = page.locator(
                    RELOCATION_WARNING_SELECTOR
                )

                try:
                    if relocation_confirm.count() == 0:
                        _dump_debug_state(
                            page,
                            vacancy_id,
                            state_label="relocation_warning_confirm_missing",
                        )

                        return {
                            "status": "RELOCATION_WARNING_CONFIRM_MISSING",
                            "reason": (
                                "HH показал предупреждение о вакансии "
                                "в другой стране, но кнопка 'Все равно откликнуться' "
                                "не найдена."
                            ),
                            "resume_warning": "",
                        }

                    relocation_confirm.first.click(
                        timeout=10_000
                    )

                except Exception as confirm_error:
                    try:
                        relocation_confirm.first.click(
                            timeout=5_000,
                            force=True,
                        )
                    except Exception:
                        _dump_debug_state(
                            page,
                            vacancy_id,
                            state_label="relocation_warning_confirm_failed",
                        )

                        return {
                            "status": "RELOCATION_WARNING_CONFIRM_FAILED",
                            "reason": (
                                "Не удалось нажать 'Все равно откликнуться': "
                                f"{confirm_error}"
                            ),
                            "resume_warning": "",
                        }

                # После подтверждения снова ждём уже следующий этап:
                # обычную модалку, сложную анкету, мгновенный отклик
                # или сетевое подтверждение.
                post_click_state = _wait_for_post_click_state(
                    page,
                    modal,
                    baseline_snapshot,
                    network_watcher=network_watcher,
                )

                network_detail = network_watcher.last_event_detail()

                if post_click_state == "relocation_warning":
                    _dump_debug_state(
                        page,
                        vacancy_id,
                        state_label="relocation_warning_loop",
                    )

                    return {
                        "status": "RELOCATION_WARNING_LOOP",
                        "reason": (
                            "После подтверждения HH снова показал "
                            "предупреждение о вакансии в другой стране."
                        ),
                        "resume_warning": "",
                    }

                if post_click_state == "network_confirmed":
                    return {
                        "status": "SUBMITTED_CONFIRMED_NETWORK",
                        "reason": (
                            "Отклик после подтверждения предупреждения "
                            "о другой стране подтвержден на сетевом уровне: "
                            f"{network_detail}"
                        ),
                        "resume_warning": "",
                    }

                if post_click_state == "network_rejected":
                    _dump_debug_state(
                        page,
                        vacancy_id,
                        state_label="relocation_network_rejected",
                    )

                    return {
                        "status": "REJECTED_BY_SERVER",
                        "reason": (
                            "Сервер отклонил отклик после подтверждения "
                            "предупреждения о другой стране: "
                            f"{network_detail}"
                        ),
                        "resume_warning": "",
                    }

            # ------------------------------------------------
            # Сложная анкета
            # ------------------------------------------------

            if post_click_state == "complex":
                if (
                    profile_facts is None
                    or ollama_url is None
                    or model_name is None
                ):
                    return {
                        "status": (
                            "NO_COMPLEX_CONTEXT"
                        ),
                        "reason": (
                            "Отсутствует AI-контекст "
                            "для сложной анкеты."
                        ),
                        "resume_warning": "",
                    }

                from hh.complex_application import (
                    handle_complex_application,
                )

                return handle_complex_application(
                    page=page,
                    vacancy_text=vacancy_text,
                    profile_facts=profile_facts,
                    ollama_url=ollama_url,
                    model_name=model_name,
                    dry_run=dry_run,
                    vacancy_id=vacancy_id,
                )

            # ------------------------------------------------
            # Мгновенный отклик без модалки
            # ------------------------------------------------

            if post_click_state == "instant_apply":
                base_reason = (
                    "Мгновенная отправка без окна "
                    "подтверждения."
                )

                if not getattr(
                    config,
                    "VERIFY_INSTANT_APPLY_VIA_RELOAD",
                    True,
                ):
                    return {
                        "status": "INSTANT_APPLY",
                        "reason": base_reason,
                        "resume_warning": "",
                    }

                confirmation = (
                    _confirm_via_reload(page)
                )

                if (
                    confirmation["confirmed"]
                    is True
                ):
                    return {
                        "status": (
                            "INSTANT_APPLY_CONFIRMED"
                        ),
                        "reason": (
                            f"{base_reason} "
                            f"{confirmation['reason']}"
                        ),
                        "resume_warning": "",
                    }

                if (
                    confirmation["confirmed"]
                    is False
                ):
                    _dump_debug_state(
                        page,
                        vacancy_id,
                        state_label=(
                            "instant_apply_not_confirmed"
                        ),
                    )

                    return {
                        "status": (
                            "INSTANT_APPLY_NOT_CONFIRMED"
                        ),
                        "reason": (
                            f"{base_reason} "
                            f"{confirmation['reason']}"
                        ),
                        "resume_warning": "",
                    }

                return {
                    "status": "INSTANT_APPLY",
                    "reason": base_reason,
                    "resume_warning": "",
                }

            # ------------------------------------------------
            # Отклик уже был
            # ------------------------------------------------

            if (
                post_click_state
                == "already_responded"
            ):
                return {
                    "status": "ALREADY_RESPONDED",
                    "reason": (
                        "Отклик уже был отправлен ранее."
                    ),
                    "resume_warning": "",
                }

            # ------------------------------------------------
            # Ошибка HH после клика
            # ------------------------------------------------

            if (
                post_click_state
                == "error_notification"
            ):
                notification_text = _safe_text(
                    page.locator(
                        ERROR_NOTIFICATION_SELECTOR
                    )
                )

                _dump_debug_state(
                    page,
                    vacancy_id,
                    state_label=(
                        "error_notification"
                    ),
                )

                return {
                    "status": "ERROR_NOTIFICATION",
                    "reason": (
                        "Уведомление после клика: "
                        f"{notification_text}"
                    ),
                    "resume_warning": "",
                }

            # ------------------------------------------------
            # Ничего не произошло
            # ------------------------------------------------

            if post_click_state == "no_modal":
                _dump_debug_state(
                    page,
                    vacancy_id,
                    state_label="no_modal",
                )

                return {
                    "status": "NO_MODAL",
                    "reason": (
                        "После нажатия 'Откликнуться' и ожидания "
                        "не появилось ни одного известного состояния. "
                        "Если это предупреждение о другой стране, "
                        "оно должно определяться по relocation-warning-confirm."
                    ),
                    "resume_warning": "",
                }

            # ------------------------------------------------
            # Обычная модалка
            # ------------------------------------------------

            resume_warning_text = _safe_text(
                page.locator(
                    RESUME_WARNING_SELECTOR
                )
            )

            add_letter_button = page.locator(
                ADD_COVER_LETTER_BUTTON_SELECTOR
            )

            if add_letter_button.count() > 0:
                add_letter_button.first.click()

                page.wait_for_timeout(
                    1_000
                )

            textarea = page.locator(
                LETTER_TEXTAREA_SELECTOR
            )

            if textarea.count() == 0:
                return {
                    "status": "NO_LETTER_FIELD",
                    "reason": (
                        "Поле сопроводительного "
                        "письма не найдено."
                    ),
                    "resume_warning": (
                        resume_warning_text
                    ),
                }

            safe_letter_text = str(
                letter_text or ""
            )[:MAX_LETTER_LENGTH]

            textarea.first.fill(
                safe_letter_text
            )

            page.wait_for_timeout(
                500
            )

            submit_button = page.locator(
                SUBMIT_BUTTON_SELECTOR
            )

            if submit_button.count() == 0:
                return {
                    "status": "NO_SUBMIT_BUTTON",
                    "reason": (
                        "Кнопка финальной отправки "
                        "отклика не найдена."
                    ),
                    "resume_warning": (
                        resume_warning_text
                    ),
                }

            # ------------------------------------------------
            # DRY RUN
            # ------------------------------------------------

            if dry_run:
                close_button = page.locator(
                    CLOSE_BUTTON_SELECTOR
                )

                if close_button.count() > 0:
                    try:
                        close_button.first.click()
                    except Exception:
                        pass

                page.wait_for_timeout(
                    500
                )

                return {
                    "status": "DRY_RUN",
                    "reason": (
                        "Реальная отправка "
                        "заблокирована DRY_RUN."
                    ),
                    "resume_warning": (
                        resume_warning_text
                    ),
                }

            # ------------------------------------------------
            # Реальная отправка
            # ------------------------------------------------

            submit_button.first.click()

            submit_elapsed_ms = 0

            while (
                submit_elapsed_ms
                <= POST_CLICK_TIMEOUT_MS
            ):
                try:
                    submit_outcome = (
                        network_watcher.outcome()
                    )
                except Exception:
                    submit_outcome = None

                if submit_outcome in (
                    "confirmed",
                    "rejected",
                ):
                    break

                page.wait_for_timeout(
                    POST_CLICK_POLL_INTERVAL_MS
                )

                submit_elapsed_ms += (
                    POST_CLICK_POLL_INTERVAL_MS
                )

            submit_outcome = (
                network_watcher.outcome()
            )

            network_detail = (
                network_watcher.last_event_detail()
            )

            # ------------------------------------------------
            # Подтверждение по сети
            # ------------------------------------------------

            if submit_outcome == "confirmed":
                return {
                    "status": (
                        "SUBMITTED_CONFIRMED_NETWORK"
                    ),
                    "reason": (
                        "Доставка подтверждена "
                        "на сетевом уровне: "
                        f"{network_detail}"
                    ),
                    "resume_warning": (
                        resume_warning_text
                    ),
                }

            if submit_outcome == "rejected":
                _dump_debug_state(
                    page,
                    vacancy_id,
                    state_label=(
                        "modal_submit_network_rejected"
                    ),
                )

                return {
                    "status": "REJECTED_BY_SERVER",
                    "reason": (
                        "Сервер вернул ошибку "
                        "при отправке из модалки: "
                        f"{network_detail}"
                    ),
                    "resume_warning": (
                        resume_warning_text
                    ),
                }

            # ------------------------------------------------
            # Если сеть ничего не сказала —
            # проверяем результат через reload
            # ------------------------------------------------

            if getattr(
                config,
                "VERIFY_INSTANT_APPLY_VIA_RELOAD",
                True,
            ):
                confirmation = (
                    _confirm_via_reload(page)
                )

                if (
                    confirmation["confirmed"]
                    is True
                ):
                    return {
                        "status": (
                            "SUBMITTED_CONFIRMED_RELOAD"
                        ),
                        "reason": (
                            "Отклик отправлен. "
                            f"{confirmation['reason']}"
                        ),
                        "resume_warning": (
                            resume_warning_text
                        ),
                    }

                if (
                    confirmation["confirmed"]
                    is False
                ):
                    _dump_debug_state(
                        page,
                        vacancy_id,
                        state_label=(
                            "modal_submit_not_confirmed"
                        ),
                    )

                    return {
                        "status": (
                            "SUBMITTED_NOT_CONFIRMED"
                        ),
                        "reason": (
                            "После перезагрузки "
                            "отклик не подтвержден: "
                            f"{confirmation['reason']}"
                        ),
                        "resume_warning": (
                            resume_warning_text
                        ),
                    }

            return {
                "status": "SUBMITTED",
                "reason": (
                    "Доставка не подтверждена "
                    "ни сетью, ни reload-проверкой."
                ),
                "resume_warning": (
                    resume_warning_text
                ),
            }

        finally:
            try:
                network_watcher.__exit__(
                    None,
                    None,
                    None,
                )
            except Exception:
                pass

    except Exception as error:
        return {
            "status": "ERROR",
            "reason": (
                "Ошибка при заполнении/отправке "
                f"формы отклика: {error}"
            ),
            "resume_warning": "",
        }