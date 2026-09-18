"""hh/complex_application.py
Безопасная обработка сложных анкет HH.

Пайплайн:
HH DOM
    ↓
_extract_questions()
    ↓
ai.test_answerer.answer_test_questions()
    ↓
структурная проверка ответов
    ↓
межвопросный consistency guard
    ↓
если конфликт → MANUAL_INPUT_REQUIRED
    ↓
если всё нормально → Playwright
    ↓
DRY_RUN / SUBMITTED

LLM никогда напрямую не управляет браузером.

Ключевой принцип:
если два ответа одной анкеты утверждают взаимоисключающие
персональные факты, бот НЕ выбирает за кандидата правильный ответ.
Анкета останавливается и требует ручного ввода.
"""

from __future__ import annotations

import re

from config import DATA_DIR
from ai.test_answerer import (
    answer_test_questions,
    has_manual_input_required,
    manual_input_reasons,
)


# ============================================================
# Селекторы HH
# ============================================================

TITLE_SELECTOR = "h1[data-qa='title']"

COMPLEX_FORM_URL_MARKER = "applicant/vacancy_response"

TASK_BODY_SELECTOR = "[data-qa='task-body']"
TASK_QUESTION_SELECTOR = "[data-qa='task-question']"

RADIO_INPUT_SELECTOR = "input[type='radio']"
OPTION_TEXT_SELECTOR = "[data-qa='cell-text-content']"

SUBMIT_BUTTON_SELECTOR = (
    "[data-qa='vacancy-response-submit-popup']"
)

COOKIE_INFORMER_SELECTOR = (
    "[data-qa='cookies-policy-informer']"
)

COOKIE_ACCEPT_SELECTOR = (
    "[data-qa='cookies-policy-informer-accept']"
)

CUSTOM_OPTION_VALUE = "open"

MAX_ANSWER_LENGTH = 10_000

COMPLEX_ANSWERS_DIR = (
    DATA_DIR / "complex_answers"
)


# ============================================================
# Нормализация текста
# ============================================================

def _norm(value: object) -> str:
    return (
        " ".join(
            str(value or "")
            .lower()
            .replace("ё", "е")
            .replace("\xa0", " ")
            .split()
        )
        .strip()
    )


# ============================================================
# Определение страницы
# ============================================================

def is_complex_application_page(page) -> bool:
    """
    Определяет реальную сложную анкету HH.

    Не полагаемся только на URL: HH может открыть анкету внутри
    SPA/modal без перехода на URL, содержащий applicant/vacancy_response.

    При наличии URL-маркера достаточно самого task-body в DOM.
    Без URL-маркера требуем, чтобы хотя бы один task-body был реально
    видимым — это защищает от скрытых шаблонов HH.
    """
    try:
        url = str(page.url or "")
        task_bodies = page.locator(TASK_BODY_SELECTOR)
        count = task_bodies.count()

        if count == 0:
            return False

        if COMPLEX_FORM_URL_MARKER in url:
            return True

        for i in range(count):
            try:
                if task_bodies.nth(i).is_visible(timeout=500):
                    return True
            except Exception:
                continue

        return False

    except Exception:
        return False


# ============================================================
# Cookie
# ============================================================

def _dismiss_cookie_informer(page) -> bool:
    """
    Cookie-информер обрабатывается ДО любого действия с вопросами.

    Если кнопка HH недоступна, fallback отключает pointer-events
    самого информера, чтобы он не перехватывал клики radio.
    """

    try:
        informer = page.locator(
            COOKIE_INFORMER_SELECTOR
        ).first

        if informer.count() == 0:
            return False

        try:
            if not informer.is_visible(
                timeout=1500
            ):
                return False
        except Exception:
            return False

        accept = informer.locator(
            COOKIE_ACCEPT_SELECTOR
        ).first

        if accept.count() > 0:
            try:
                accept.scroll_into_view_if_needed(
                    timeout=3000
                )
            except Exception:
                pass

            try:
                accept.click(
                    timeout=5000
                )
            except Exception:
                accept.click(
                    timeout=5000,
                    force=True,
                )

            try:
                informer.wait_for(
                    state="hidden",
                    timeout=5000,
                )
            except Exception:
                pass

            print(
                "[complex_application] "
                "Cookie-информер HH закрыт."
            )
            return True

        try:
            informer.evaluate(
                """
                (el) => {
                    el.style.pointerEvents = 'none';
                }
                """
            )

            print(
                "[complex_application] "
                "Cookie-информер найден, "
                "pointer-events отключены."
            )
            return True

        except Exception:
            return False

    except Exception as error:
        print(
            "[WARN] Не удалось обработать "
            f"cookie-информер HH: {error}"
        )
        return False


# ============================================================
# Radio extraction
# ============================================================

def _extract_radio_options(task_body) -> list[dict]:
    options: list[dict] = []

    radios = task_body.locator(
        RADIO_INPUT_SELECTOR
    )

    count = radios.count()

    for i in range(count):
        radio = radios.nth(i)

        value = (
            radio.get_attribute("value")
            or ""
        )

        label_text = ""

        try:
            label = radio.locator(
                "xpath=ancestor::label[1]"
            ).first

            if label.count() > 0:
                text_locator = label.locator(
                    OPTION_TEXT_SELECTOR
                ).first

                if text_locator.count() > 0:
                    label_text = (
                        text_locator.inner_text(
                            timeout=2000
                        ).strip()
                    )
                else:
                    label_text = (
                        label.inner_text(
                            timeout=2000
                        ).strip()
                    )
        except Exception:
            pass

        if not label_text:
            label_text = (
                value
                or f"(вариант {i})"
            )

        try:
            is_default = radio.is_checked()
        except Exception:
            is_default = False

        options.append(
            {
                "id": value,
                "text": label_text,
                "locator": radio,
                "is_default": is_default,
                "is_custom": (
                    value == CUSTOM_OPTION_VALUE
                ),
            }
        )

    return options


# ============================================================
# Извлечение вопросов
# ============================================================

def _extract_questions(page) -> list[dict]:
    questions: list[dict] = []

    task_bodies = page.locator(
        TASK_BODY_SELECTOR
    )

    count = task_bodies.count()

    for i in range(count):
        task_body = task_bodies.nth(i)

        question_locator = (
            task_body.locator(
                TASK_QUESTION_SELECTOR
            ).first
        )

        try:
            question_text = (
                question_locator.inner_text(
                    timeout=2000
                ).strip()
            )
        except Exception:
            question_text = (
                "(не удалось прочитать "
                "текст вопроса)"
            )

        try:
            question_html = (
                question_locator.inner_html(
                    timeout=2000
                )
            )
        except Exception:
            question_html = question_text

        options = _extract_radio_options(
            task_body
        )

        if options:
            questions.append(
                {
                    "task_id": i,
                    "type": "choice",
                    "description": question_text,
                    "question_html": question_html,
                    "options": [
                        {
                            "id": option["id"],
                            "text": option["text"],
                        }
                        for option in options
                    ],
                    "dom_options": options,
                    "body": task_body,
                }
            )
            continue

        textarea = task_body.locator(
            "textarea"
        )

        if textarea.count() == 0:
            print(
                "[WARN] Вопрос "
                f"{i} найден, но "
                "textarea/radio отсутствуют."
            )

            questions.append(
                {
                    "task_id": i,
                    "type": "open",
                    "description": question_text,
                    "question_html": question_html,
                    "options": [],
                    "textarea": None,
                    "body": task_body,
                    "unsupported": True,
                }
            )
            continue

        questions.append(
            {
                "task_id": i,
                "type": "open",
                "description": question_text,
                "question_html": question_html,
                "options": [],
                "textarea": textarea.first,
                "body": task_body,
            }
        )

    return questions


# ============================================================
# CONSISTENCY GUARD
# ============================================================

# Эти маркеры описывают один и тот же факт в разных формах.
# Важно: мы проверяем только явные положительные/отрицательные
# утверждения. Нейтральные формулировки сами по себе конфликтом
# не считаются.

_CONSISTENCY_GROUPS: dict[str, dict[str, tuple[str, ...]]] = {
    "mobile_games_played": {
        "positive": (
            "играл в мобильн",
            "играла в мобильн",
            "играл на мобильн",
            "играла на мобильн",
            "играл в игры",
            "играла в игры",
            "играл в игру",
            "играла в игру",
            "играю в мобильн",
            "играю в игры",
            "игры, в которые я играл",
            "игры, в которые я играла",
        ),
        "negative": (
            "не играл в мобильн",
            "не играла в мобильн",
            "не играл на мобильн",
            "не играла на мобильн",
            "не играл в игры",
            "не играла в игры",
            "не играл в игру",
            "не играла в игру",
            "не играл в мобильные игры",
            "не играла в мобильные игры",
        ),
    },
    "work_experience": {
        "positive": (
            "есть опыт работы",
            "имею опыт работы",
            "имеется опыт работы",
            "у меня есть опыт",
            "имею коммерческий опыт",
            "есть коммерческий опыт",
            "работал в компании",
            "работала в компании",
            "работал на позиции",
            "работала на позиции",
            "работал тестировщиком",
            "работала тестировщиком",
            "работал qa",
            "работала qa",
        ),
        "negative": (
            "нет опыта работы",
            "нет опыта",
            "не имею опыта работы",
            "не имею опыта",
            "коммерческого опыта нет",
            "нет коммерческого опыта",
            "не работал в компании",
            "не работала в компании",
            "не работал тестировщиком",
            "не работала тестировщиком",
            "не работал qa",
            "не работала qa",
        ),
    },
    "commercial_qa": {
        "positive": (
            "коммерческий опыт тестирования",
            "коммерческий опыт qa",
            "коммерческий опыт тестиров",
            "работал тестировщиком",
            "работала тестировщиком",
            "работал qa",
            "работала qa",
        ),
        "negative": (
            "нет коммерческого опыта тестирования",
            "нет коммерческого опыта qa",
            "нет коммерческого опыта тестиров",
            "коммерческого опыта тестирования нет",
            "коммерческого опыта qa нет",
            "коммерческого опыта тестиров нет",
        ),
    },
    "technology_experience": {
        "positive": (
            "имею опыт работы с ",
            "есть опыт работы с ",
            "использовал ",
            "использовала ",
            "работал с ",
            "работала с ",
            "знаком с ",
            "знакома с ",
            "изучал ",
            "изучала ",
            "использую ",
        ),
        "negative": (
            "не использовал ",
            "не использовала ",
            "не работал с ",
            "не работала с ",
            "не имею опыта работы с ",
            "нет опыта работы с ",
            "не знаком с ",
            "не знакома с ",
            "не изучал ",
            "не изучала ",
        ),
    },
    "education": {
        "positive": (
            "есть диплом",
            "имею диплом",
            "закончил колледж",
            "закончила колледж",
            "закончил вуз",
            "закончила вуз",
            "имею высшее образование",
            "есть высшее образование",
        ),
        "negative": (
            "нет диплома",
            "не имею диплома",
            "не закончил колледж",
            "не закончила колледж",
            "не закончил вуз",
            "не закончила вуз",
            "нет высшего образования",
            "не имею высшего образования",
        ),
    },
    "certificate": {
        "positive": (
            "есть сертификат",
            "имею сертификат",
            "получил сертификат",
            "получила сертификат",
        ),
        "negative": (
            "нет сертификата",
            "не имею сертификата",
            "не получал сертификат",
            "не получала сертификат",
        ),
    },
}


def _answer_text(answer: dict) -> str:
    """
    Получает именно утверждение, которое собираются отправить.

    choice:
        берём тексты выбранных option'ов.

    own_text:
        берём text.

    needs_manual_input:
        такой ответ уже останавливает анкету и здесь не анализируется.
    """

    if not isinstance(answer, dict):
        return ""

    mode = str(
        answer.get("mode", "")
    ).strip()

    if mode == "choice":
        values = answer.get(
            "selected_options",
            answer.get("solution_ids", []),
        )

        if isinstance(values, list):
            return " ".join(
                str(value)
                for value in values
            )

        return str(values or "")

    if mode == "own_text":
        return str(
            answer.get("text", "")
        )

    return ""


def _question_text(
    questions_by_id: dict,
    task_id: object,
) -> str:
    value = questions_by_id.get(task_id)

    if isinstance(value, dict):
        return str(
            value.get("description", "")
        )

    return str(value or "")


def _contains_positive(
    text: str,
    markers: tuple[str, ...],
) -> bool:
    return any(
        marker in text
        for marker in markers
    )


def _contains_negative(
    text: str,
    markers: tuple[str, ...],
) -> bool:
    return any(
        marker in text
        for marker in markers
    )


def _validate_cross_answer_consistency(
    questions: list[dict],
    answers: list[dict],
) -> list[str]:
    """
    Проверяет всю анкету после генерации ответов.

    Не исправляет ответы.

    Если один ответ утверждает X, а другой утверждает
    "не X", возвращает проблему.

    Особый случай:
    вопросы о конкретной технологии не должны сравниваться
    как единый факт только потому, что в них есть слово
    "использовал". Поэтому technology_experience дополнительно
    проверяется по общим токенам технологии.
    """

    by_id = {
        question.get("task_id"): question
        for question in questions
        if isinstance(question, dict)
    }

    records: list[tuple[int, str, str]] = []

    for answer in answers:
        if not isinstance(answer, dict):
            continue

        task_id = answer.get("task_id")
        text = _norm(
            _answer_text(answer)
        )

        if not text:
            continue

        records.append(
            (
                int(task_id)
                if str(task_id).isdigit()
                else -1,
                _question_text(by_id, task_id),
                text,
            )
        )

    problems: list[str] = []

    # --------------------------------------------------------
    # Общие группы.
    # --------------------------------------------------------
    for group_name, markers in _CONSISTENCY_GROUPS.items():
        positives: list[tuple[int, str, str]] = []
        negatives: list[tuple[int, str, str]] = []

        for record in records:
            task_id, question, answer = record

            if _contains_positive(
                answer,
                markers["positive"],
            ):
                positives.append(record)

            if _contains_negative(
                answer,
                markers["negative"],
            ):
                negatives.append(record)

        if not positives or not negatives:
            continue

        # Для technology_experience нужен ещё один общий
        # технический объект, иначе "использовал Postman" и
        # "не использовал Docker" ошибочно станут конфликтом.
        if group_name == "technology_experience":
            continue

        for positive in positives:
            for negative in negatives:
                if positive[0] == negative[0]:
                    continue

                problems.append(
                    (
                        f"противоречие: вопрос "
                        f"{positive[0]} содержит положительное "
                        f"утверждение ({positive[2]!r}), а вопрос "
                        f"{negative[0]} — отрицательное "
                        f"утверждение ({negative[2]!r})"
                    )
                )

    # --------------------------------------------------------
    # Технологии: сравниваем только если одна и та же
    # технология присутствует в обоих ответах.
    # --------------------------------------------------------
    technology_markers = (
        "1с",
        "1c",
        "selenium",
        "playwright",
        "python",
        "postman",
        "api",
        "docker",
        "linux",
        "jira",
        "testit",
        "sql",
        "postgresql",
        "n8n",
        "react",
        "kubernetes",
        "k8s",
    )

    for technology in technology_markers:
        positive_records: list[tuple[int, str, str]] = []
        negative_records: list[tuple[int, str, str]] = []

        for record in records:
            task_id, question, answer = record

            if technology not in answer:
                continue

            negative = (
                f"не {technology}" in answer
                or f"нет опыта с {technology}" in answer
                or f"не имею опыта с {technology}" in answer
                or f"не работал с {technology}" in answer
                or f"не работала с {technology}" in answer
                or f"не использовал {technology}" in answer
                or f"не использовала {technology}" in answer
            )

            if negative:
                negative_records.append(record)
            else:
                positive_records.append(record)

        if positive_records and negative_records:
            for positive in positive_records:
                for negative in negative_records:
                    if positive[0] == negative[0]:
                        continue

                    problems.append(
                        (
                            f"противоречие по технологии "
                            f"'{technology}': вопрос "
                            f"{positive[0]} утверждает наличие "
                            f"опыта, вопрос {negative[0]} "
                            f"утверждает его отсутствие"
                        )
                    )

    # --------------------------------------------------------
    # Удаляем дубликаты.
    # --------------------------------------------------------
    unique: list[str] = []
    seen: set[str] = set()

    for problem in problems:
        if problem not in seen:
            seen.add(problem)
            unique.append(problem)

    return unique

# ============================================================
# Textarea
# ============================================================
#
# ИСПРАВЛЕНИЕ (2 однотипные ошибки из отчёта):
#
#   1) "HH textarea не приняла значение через force=True"
#      Причина: HH использует React-контролируемые поля (Magritte).
#      Playwright .fill(force=True) действительно записывает
#      значение в DOM textarea в обход проверок видимости, но
#      React в некоторых случаях не подхватывает это как реальный
#      ввод пользователя (его внутренний value setter переопределён,
#      и просто установка .value без правильного nativeInputValueSetter
#      + dispatchEvent('input') не долетает до React state) — value
#      в DOM физически стоит, но при повторном рендере React
#      затирает его обратно на старое (обычно пустое) значение.
#
#   2) "Не найден textarea для свободного вопроса"
#      Причина: у части "ленивых" вопросов реальный <textarea>
#      Magritte остаётся НЕ "visible" по определению Playwright
#      (нулевые размеры / opacity 0) НАВСЕГДА, а не только до
#      раскрытия — видимым становится только стилизованный div
#      поверх него. Прежняя _find_visible_textarea() искала
#      строго is_visible()==True и после исчерпания retry просто
#      сдавалась, даже если textarea физически присутствует в DOM.
#
# Решение:
#   - _find_visible_textarea() теперь, если ни один <textarea> не
#     прошёл проверку видимости, но textarea вообще есть в DOM
#     (count() > 0), пробует альтернативные селекторы
#     (ALT_TEXTAREA_SELECTORS) и как последний шанс возвращает
#     первый присутствующий в DOM textarea (даже "невидимый") —
#     вызывающий код (_fill_textarea_safely) в этом случае
#     обязан заполнять его через принудительный JS-путь, а не
#     обычный .fill().
#   - _fill_hidden_magritte_textarea() теперь пробует 3 способа
#     по очереди, проверяя результат через input_value() после
#     каждого, и падает только если ВСЕ три не сработали:
#       a) textarea.fill(..., force=True)              — как раньше
#       b) посимвольный ввод через press_sequentially() — реальные
#          keydown/keypress/input события, которые React слушает
#          гарантированно, если поле в принципе фокусируемо
#       c) JS: нативный value setter + dispatchEvent('input'/
#          'change', {bubbles: true}) — прямой обход React,
#          работает даже для elements с opacity:0/height:0
#   - _fill_textarea_safely() при полном отсутствии видимого
#     textarea после всех retry больше не сдаётся сразу — делает
#     финальную попытку через "любой присутствующий в DOM
#     textarea" (см. выше) перед тем как бросить RuntimeError.

ALT_TEXTAREA_SELECTORS = (
    "textarea",
    "[data-qa*='textarea']",
    "[data-qa='task-answer'] textarea",
    "[data-qa*='task'] textarea",
    "[contenteditable='true']",
)


# JS-код для прямой записи значения в React-контролируемый
# textarea в обход перехваченного React'ом value-setter'а.
# Вызывается через locator.evaluate(script, value).
_JS_SET_REACT_TEXTAREA_VALUE = """
(el, value) => {
    const proto = window.HTMLTextAreaElement.prototype;
    const nativeSetter = Object.getOwnPropertyDescriptor(
        proto, 'value'
    ).set;

    nativeSetter.call(el, value);

    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
}
"""


def _find_visible_textarea(question: dict):
    body = question.get("body")

    if body is None:
        return None

    candidate_locators = []

    try:
        candidate_locators.append(body.locator("textarea"))
    except Exception:
        pass

    # --------------------------------------------------------
    # Первый проход: ищем textarea, реально проходящую проверку
    # is_visible() — это по-прежнему приоритетный путь, т.к. для
    # видимых полей обычный .fill() работает надёжнее всего.
    # --------------------------------------------------------
    for textareas in candidate_locators:
        try:
            count = textareas.count()
        except Exception:
            continue

        for i in range(count):
            candidate = textareas.nth(i)

            try:
                if candidate.is_visible(timeout=1000):
                    return candidate
            except Exception:
                continue

    # --------------------------------------------------------
    # Второй проход: ни одна textarea не "видима" по Playwright,
    # но, возможно, дело в альтернативном селекторе (обёртка
    # Magritte может рендерить поле не как голый <textarea>
    # первого уровня, а глубже во вложенном контейнере).
    # --------------------------------------------------------
    for selector in ALT_TEXTAREA_SELECTORS:
        try:
            alt = body.locator(selector)
            if alt.count() > 0:
                for i in range(alt.count()):
                    candidate = alt.nth(i)
                    try:
                        if candidate.is_visible(timeout=500):
                            return candidate
                    except Exception:
                        continue
        except Exception:
            continue

    # --------------------------------------------------------
    # Последний шанс: textarea физически присутствует в DOM
    # (count() > 0), но никогда не станет "visible" по Playwright
    # (Magritte намеренно держит реальный <textarea> с нулевыми
    # размерами/opacity:0, а видна только стилизованная накладка).
    # Возвращаем её как есть — заполнение такого элемента ниже
    # ОБЯЗАНО идти через _fill_hidden_magritte_textarea(), которая
    # умеет работать с невидимыми полями.
    # --------------------------------------------------------
    try:
        textareas = body.locator("textarea")
        if textareas.count() > 0:
            return textareas.first
    except Exception:
        pass

    return None


def _try_expand_text_question(
    question: dict,
) -> None:
    body = question.get("body")

    if body is None:
        return

    try:
        body.scroll_into_view_if_needed(
            timeout=5000
        )
    except Exception:
        pass

    try:
        question_locator = body.locator(
            TASK_QUESTION_SELECTOR
        ).first

        if question_locator.count() > 0:
            try:
                question_locator.click(
                    timeout=3000,
                    force=False,
                )
                return
            except Exception:
                pass
    except Exception:
        pass

    try:
        button = body.locator(
            "button"
        ).first

        if (
            button.count() > 0
            and button.is_visible()
        ):
            button.click(
                timeout=3000
            )
    except Exception:
        pass


def _fill_hidden_magritte_textarea(
    textarea,
    answer_text: str,
) -> None:
    """
    Заполняет "ленивую"/невидимую textarea Magritte, пробуя три
    независимых способа по очереди. Каждый способ сразу проверяется
    через input_value() — переходим к следующему, только если
    текущий не сработал. RuntimeError бросается, только если НИ
    ОДИН из трёх способов не дал совпадающего значения.
    """

    attempts_log: list[str] = []

    def _current_value() -> str:
        try:
            return textarea.input_value(timeout=3000)
        except Exception:
            return ""

    # --- Способ (a): обычный fill с force=True, как раньше -------
    try:
        textarea.fill(
            answer_text,
            timeout=10_000,
            force=True,
        )

        if _current_value() == answer_text:
            return

        attempts_log.append(
            "fill(force=True): значение не сохранилось"
        )
    except Exception as error:
        attempts_log.append(f"fill(force=True): {error}")

    # --- Способ (b): посимвольный ввод через press_sequentially --
    # Реальные клавиатурные события — то, что React слушает
    # гарантированно, если поле в принципе фокусируемо. Работает
    # не для всех "ленивых" полей (некоторые нефокусируемы, пока
    # не раскрыты стилизованной накладкой), поэтому оборачиваем
    # в try и не считаем провал фатальным.
    try:
        textarea.click(
            timeout=3000,
            force=True,
        )

        try:
            textarea.fill("", timeout=3000, force=True)
        except Exception:
            pass

        textarea.press_sequentially(
            answer_text,
            timeout=15_000,
            delay=15,
        )

        if _current_value() == answer_text:
            return

        attempts_log.append(
            "press_sequentially: значение не сохранилось"
        )
    except Exception as error:
        attempts_log.append(f"press_sequentially: {error}")

    # --- Способ (c): нативный setter + dispatchEvent (JS) --------
    # Прямой обход перехваченного React'ом value-setter'а. Работает
    # даже для полностью невидимых (opacity:0/height:0) элементов,
    # т.к. не требует фокуса или actionability-проверок Playwright.
    try:
        textarea.evaluate(
            _JS_SET_REACT_TEXTAREA_VALUE,
            answer_text,
        )

        if _current_value() == answer_text:
            return

        attempts_log.append(
            "JS native-setter+dispatchEvent: значение не сохранилось"
        )
    except Exception as error:
        attempts_log.append(
            f"JS native-setter+dispatchEvent: {error}"
        )

    actual = _current_value()

    raise RuntimeError(
        "HH textarea не приняла значение ни одним из трёх способов "
        "(fill(force=True) / press_sequentially / JS native-setter). "
        f"Ожидалось {answer_text!r}, получено {actual!r}. "
        f"Подробности попыток: {'; '.join(attempts_log)}"
    )


def _fill_textarea_safely(
    question: dict,
    answer_text: str,
    timeout_ms: int = 15_000,
) -> None:
    body = question.get("body")

    textarea = None

    retry_delays = (
        0,
        250,
        500,
        750,
        1000,
        1500,
    )

    for delay_ms in retry_delays:
        if delay_ms and body is not None:
            try:
                body.page.wait_for_timeout(
                    delay_ms
                )
            except Exception:
                pass

        textarea = _find_visible_textarea(
            question
        )

        if textarea is not None:
            break

        _try_expand_text_question(
            question
        )

        if body is not None:
            try:
                body.page.wait_for_timeout(
                    250
                )
            except Exception:
                pass

    if textarea is not None:
        last_error = None

        for _ in range(3):
            try:
                textarea.scroll_into_view_if_needed(
                    timeout=5000
                )

                textarea.wait_for(
                    state="attached",
                    timeout=5000,
                )

                textarea.fill(
                    answer_text,
                    timeout=timeout_ms,
                )

                actual = textarea.input_value(
                    timeout=3000
                )

                if actual == answer_text:
                    return

                last_error = RuntimeError(
                    "Textarea не сохранило "
                    "ожидаемое значение."
                )

            except Exception as error:
                last_error = error

            try:
                if body is not None:
                    body.page.wait_for_timeout(
                        300
                    )
            except Exception:
                pass

            textarea = _find_visible_textarea(
                question
            )

            if textarea is None:
                _try_expand_text_question(
                    question
                )

        if textarea is not None:
            try:
                _fill_hidden_magritte_textarea(
                    textarea,
                    answer_text,
                )
                return
            except Exception as force_error:
                raise RuntimeError(
                    "Не удалось заполнить textarea "
                    "ни одним из способов (обычный fill, "
                    "посимвольный ввод, JS-обход React). "
                    f"Обычная ошибка: {last_error}; "
                    f"итоговая ошибка: {force_error}"
                ) from force_error

    # --------------------------------------------------------
    # ДОБАВЛЕНО: последняя попытка, даже если question["textarea"]
    # изначально было None (то есть вопрос был помечен unsupported
    # ещё на этапе _extract_questions). Раньше здесь сразу бросался
    # RuntimeError без единой дополнительной попытки — хотя к
    # моменту заполнения формы (STEP 4 в handle_complex_application)
    # проходит время на генерацию ответа LLM для ВСЕХ вопросов
    # анкеты, и лениво рендерящееся поле вполне может успеть
    # появиться в DOM само по себе. Раз уж мы дошли до реального
    # заполнения — стоит попробовать найти textarea заново, прежде
    # чем сдаваться.
    # --------------------------------------------------------
    textarea = question.get("textarea")

    if (
        textarea is None
        or textarea.count() == 0
    ):
        _try_expand_text_question(
            question
        )

        if body is not None:
            try:
                body.page.wait_for_timeout(
                    500
                )
            except Exception:
                pass

        textarea = _find_visible_textarea(
            question
        )

    # --------------------------------------------------------
    # ИСПРАВЛЕНИЕ ("Не найден textarea для свободного вопроса"):
    # раньше здесь при textarea is None сразу бросался RuntimeError.
    # Добавлена последняя, максимально широкая попытка: раскрыть
    # вопрос ещё раз, подождать дольше обычного и напрямую
    # проверить body.locator("textarea") без фильтра видимости —
    # покрывает случай, когда поле физически есть в DOM, но никогда
    # не станет "visible" (см. докстринг секции выше).
    # --------------------------------------------------------
    if (
        textarea is None
        or textarea.count() == 0
    ):
        _try_expand_text_question(question)

        if body is not None:
            try:
                body.page.wait_for_timeout(800)
            except Exception:
                pass

        if body is not None:
            try:
                raw = body.locator("textarea")
                if raw.count() > 0:
                    textarea = raw.first
            except Exception:
                pass

    if (
        textarea is None
        or textarea.count() == 0
    ):
        raise RuntimeError(
            "Не найден textarea для "
            "свободного вопроса."
        )

    _try_expand_text_question(
        question
    )

    if body is not None:
        try:
            body.page.wait_for_timeout(
                300
            )
        except Exception:
            pass

    _fill_hidden_magritte_textarea(
        textarea,
        answer_text,
    )

# ============================================================
# Radio
# ============================================================

def _click_visible_radio_control(
    option: dict,
    timeout_ms: int = 10_000,
) -> None:
    """
    Приоритет:
    1. label;
    2. видимый контейнер label;
    3. radio.check();
    4. force=True.

    Сначала закрываем cookie, затем работаем с DOM.
    """

    radio = option["locator"]

    label = None

    try:
        label = radio.locator(
            "xpath=ancestor::label[1]"
        ).first
    except Exception:
        label = None

    # 1. Кликаем по видимому label.
    if (
        label is not None
        and label.count() > 0
    ):
        try:
            label.scroll_into_view_if_needed(
                timeout=5000
            )
        except Exception:
            pass

        try:
            if label.is_visible():
                label.click(
                    timeout=timeout_ms
                )

                if radio.is_checked():
                    return
        except Exception:
            pass

        # Иногда label виден, но его дочерний контрол
        # закрывает другой слой. force по label надёжнее,
        # чем force по hidden input.
        try:
            label.click(
                timeout=timeout_ms,
                force=True,
            )

            if radio.is_checked():
                return
        except Exception:
            pass

    # 2. Штатный Playwright check.
    try:
        radio.check(
            timeout=timeout_ms
        )

        if radio.is_checked():
            return
    except Exception:
        pass

    # 3. Последний fallback.
    radio.check(
        timeout=timeout_ms,
        force=True,
    )

    if not radio.is_checked():
        raise RuntimeError(
            "Radio не удалось выбрать. "
            f"Вариант: {option.get('text', '')!r}"
        )


def _resolve_choice_answer(
    question: dict,
    answer: dict,
) -> dict:
    """
    AI возвращает solution_ids.
    Python сопоставляет их только с реальными DOM-option.

    Для legacy-ответа с text поддерживается и literal
    сопоставление по тексту.
    """

    dom_options = question.get(
        "dom_options",
        [],
    )

    valid_options = [
        option
        for option in dom_options
        if not option.get("is_custom")
    ]

    if not isinstance(answer, dict):
        return {
            "action": "skip",
            "option": None,
            "note": "Некорректный AI-ответ.",
        }

    mode = str(
        answer.get("mode", "")
    ).strip()

    if mode == "choice":
        ids = answer.get(
            "solution_ids",
            [],
        )

        if not isinstance(ids, list):
            ids = [ids]

        ids = {
            str(value)
            for value in ids
        }

        for option in valid_options:
            if str(option.get("id", "")) in ids:
                return {
                    "action": "click",
                    "option": option,
                    "note": (
                        "выбран вариант AI: "
                        f"'{option['text']}'"
                    ),
                }

        # Поддержка старого формата.
        answer_text = _norm(
            answer.get("text", "")
        )

        if answer_text:
            for option in valid_options:
                if _norm(
                    option.get("text", "")
                ) == answer_text:
                    return {
                        "action": "click",
                        "option": option,
                        "note": (
                            "выбран вариант "
                            "по точному тексту: "
                            f"'{option['text']}'"
                        ),
                    }

    # Если AI не выбрала валидный option,
    # НЕ гадаем.
    return {
        "action": "skip",
        "option": None,
        "note": (
            "AI не вернула валидный вариант "
            "из реальных options."
        ),
    }


# ============================================================
# Логирование
# ============================================================

def _log_answers(
    vacancy_id: str | None,
    qa_log: list[dict],
    status: str,
) -> None:
    if not qa_log:
        return

    lines = [
        "=" * 70,
        (
            "СЛОЖНАЯ АНКЕТА — ВОПРОСЫ И ОТВЕТЫ "
            f"(status={status})"
        ),
        "=" * 70,
    ]

    for item in qa_log:
        lines.append(
            f"\nВопрос {item['index']}:"
        )
        lines.append(
            item["question_text"]
        )
        lines.append("\nОтвет:")
        lines.append(
            item["answer_text"]
        )
        lines.append(
            "-" * 70
        )

    text = "\n".join(lines)

    print(f"\n{text}\n")

    if not vacancy_id:
        return

    try:
        COMPLEX_ANSWERS_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )

        out_path = (
            COMPLEX_ANSWERS_DIR
            / f"{vacancy_id}.txt"
        )

        out_path.write_text(
            text,
            encoding="utf-8",
        )

        print(
            "Вопросы и ответы сложной анкеты "
            f"сохранены:\n{out_path}"
        )

    except Exception as save_error:
        print(
            "[WARN] Не удалось сохранить "
            "вопросы и ответы сложной анкеты: "
            f"{save_error}"
        )


# ============================================================
# Главная функция
# ============================================================

def handle_complex_application(
    page,
    vacancy_text: str,
    profile_facts: dict,
    ollama_url: str,
    model_name: str,
    dry_run: bool,
    vacancy_id: str | None = None,
) -> dict:
    """
    Статусы:
        DRY_RUN
        SUBMITTED
        NO_QUESTIONS
        NO_SUBMIT_BUTTON
        AI_ERROR
        MANUAL_INPUT_REQUIRED
        ERROR
    """

    qa_log: list[dict] = []

    try:
        # =====================================================
        # STEP 0 — фиксируем, что мы действительно вошли
        # в обработчик сложной анкеты
        # =====================================================
        print(
            "\n[complex_application] "
            "HANDLER START — сложная анкета обнаружена."
        )
        print(
            f"[complex_application] URL: {page.url}"
        )

        # =====================================================
        # STEP 0.1 — cookie ДО ЛЮБОГО КЛИКА
        # =====================================================
        _dismiss_cookie_informer(page)

        # =====================================================
        # STEP 1 — вопросы
        # =====================================================
        questions = _extract_questions(page)

        if not questions:
            return {
                "status": "NO_QUESTIONS",
                "reason": (
                    "Страница похожа на сложную "
                    "анкету, но вопросы не найдены."
                ),
                "resume_warning": "",
                "qa_log": qa_log,
            }

        print(
            "\n[complex_application] "
            f"Найдено вопросов: {len(questions)}"
        )

        for question in questions:
            print(
                f"  [{question['task_id']}] "
                f"{question['type']} — "
                f"{question['description']}"
            )

        # =====================================================
        # STEP 2 — универсальный формат AI
        # =====================================================
        ai_questions = [
            {
                "task_id": question["task_id"],
                "type": question["type"],
                "description": question["description"],
                "options": question["options"],
            }
            for question in questions
        ]

        # =====================================================
        # STEP 3 — AI
        # =====================================================
        try:
            answers = answer_test_questions(
                ollama_url,
                model_name,
                {
                    "title": "",
                    "company": "",
                    "description": vacancy_text,
                },
                profile_facts,
                ai_questions,
            )

        except Exception as error:
            return {
                "status": "AI_ERROR",
                "reason": (
                    "Ошибка AI при обработке "
                    f"вопросов анкеты: {error}"
                ),
                "resume_warning": "",
                "qa_log": qa_log,
            }

        if not isinstance(
            answers,
            list,
        ):
            return {
                "status": "AI_ERROR",
                "reason": (
                    "AI вернул некорректную "
                    "структуру ответов."
                ),
                "resume_warning": "",
                "qa_log": qa_log,
            }

        # =====================================================
        # STEP 3.5 — структура ответов
        # =====================================================
        expected_ids = {
            question["task_id"]
            for question in questions
        }

        actual_ids = {
            answer.get("task_id")
            for answer in answers
            if isinstance(answer, dict)
        }

        missing_ids = (
            expected_ids - actual_ids
        )

        if missing_ids:
            return {
                "status": "AI_ERROR",
                "reason": (
                    "AI не вернул ответы "
                    "на вопросы: "
                    + ", ".join(
                        str(value)
                        for value in sorted(
                            missing_ids
                        )
                    )
                ),
                "resume_warning": "",
                "qa_log": qa_log,
            }

        # =====================================================
        # STEP 3.6 — уже существующий MANUAL_INPUT_REQUIRED
        # =====================================================
        if has_manual_input_required(
            answers
        ):
            reasons = manual_input_reasons(
                answers,
                ai_questions,
            )

            for answer in answers:
                if not isinstance(
                    answer,
                    dict,
                ):
                    continue

                task_id = answer.get(
                    "task_id"
                )

                question = next(
                    (
                        item
                        for item in questions
                        if item["task_id"] == task_id
                    ),
                    None,
                )

                if question is None:
                    continue

                qa_log.append(
                    {
                        "index": task_id,
                        "question_text": question[
                            "description"
                        ],
                        "answer_text": (
                            answer.get(
                                "reason",
                                "MANUAL_INPUT_REQUIRED",
                            )
                        ),
                    }
                )

            reason = (
                "Не все вопросы можно безопасно "
                "закрыть автоматически."
            )

            if reasons:
                reason += " " + " | ".join(
                    reasons
                )

            _log_answers(
                vacancy_id,
                qa_log,
                "MANUAL_INPUT_REQUIRED",
            )

            return {
                "status": "MANUAL_INPUT_REQUIRED",
                "reason": reason,
                "resume_warning": (
                    "Автоматическая отправка "
                    "заблокирована."
                ),
                "qa_log": qa_log,
            }

        # =====================================================
        # STEP 3.7 — НОВЫЙ CONSISTENCY GUARD
        # =====================================================
        consistency_problems = (
            _validate_cross_answer_consistency(
                questions,
                answers,
            )
        )

        if consistency_problems:
            print(
                "\n[complex_application] "
                "Обнаружены противоречия "
                "между ответами анкеты:"
            )

            for problem in consistency_problems:
                print(
                    f"  • {problem}"
                )

            # Сохраняем ВСЕ ответы, а не только
            # конфликтующие — для ручной проверки.
            for answer in answers:
                if not isinstance(
                    answer,
                    dict,
                ):
                    continue

                task_id = answer.get(
                    "task_id"
                )

                question = next(
                    (
                        item
                        for item in questions
                        if item["task_id"] == task_id
                    ),
                    None,
                )

                if question is None:
                    continue

                answer_text = (
                    _answer_text(answer)
                    or answer.get(
                        "reason",
                        "",
                    )
                )

                qa_log.append(
                    {
                        "index": task_id,
                        "question_text": question[
                            "description"
                        ],
                        "answer_text": str(
                            answer_text
                        ),
                    }
                )

            _log_answers(
                vacancy_id,
                qa_log,
                "MANUAL_INPUT_REQUIRED",
            )

            return {
                "status": "MANUAL_INPUT_REQUIRED",
                "reason": (
                    "В ответах сложной анкеты "
                    "обнаружены противоречия. "
                    "Бот не будет самостоятельно "
                    "выбирать, какой персональный "
                    "факт является правильным. "
                    + " | ".join(
                        consistency_problems
                    )
                ),
                "resume_warning": (
                    "Автоматическая отправка "
                    "заблокирована до проверки "
                    "ответов пользователем."
                ),
                "qa_log": qa_log,
            }

        # =====================================================
        # STEP 4 — ответы → браузер
        # =====================================================
        for question in questions:
            task_id = question["task_id"]

            answer = next(
                (
                    item
                    for item in answers
                    if isinstance(item, dict)
                    and item.get("task_id")
                    == task_id
                ),
                None,
            )

            if answer is None:
                raise RuntimeError(
                    f"Нет ответа для вопроса {task_id}."
                )

            mode = str(
                answer.get("mode", "")
            ).strip()

            # -------------------------------------------------
            # OPEN
            # -------------------------------------------------
            if question["type"] == "open":
                answer_text = str(
                    answer.get(
                        "text",
                        "",
                    )
                ).strip()

                answer_text = (
                    answer_text[:MAX_ANSWER_LENGTH]
                )

                if not answer_text:
                    raise RuntimeError(
                        f"Пустой open-ответ "
                        f"для вопроса {task_id}."
                    )

                qa_log.append(
                    {
                        "index": task_id,
                        "question_text": question[
                            "description"
                        ],
                        "answer_text": answer_text,
                    }
                )

                _fill_textarea_safely(
                    question,
                    answer_text,
                )

            # -------------------------------------------------
            # CHOICE
            # -------------------------------------------------
            else:
                resolution = (
                    _resolve_choice_answer(
                        question,
                        answer,
                    )
                )

                qa_log.append(
                    {
                        "index": task_id,
                        "question_text": question[
                            "description"
                        ],
                        "answer_text": resolution[
                            "note"
                        ],
                    }
                )

                if (
                    resolution["action"]
                    != "click"
                    or resolution["option"]
                    is None
                ):
                    raise RuntimeError(
                        "Не удалось безопасно "
                        "определить radio-вариант "
                        f"для вопроса {task_id}. "
                        f"{resolution['note']}"
                    )

                # Cookie мог появиться/вернуться
                # после SPA-перерисовки.
                _dismiss_cookie_informer(
                    page
                )

                _click_visible_radio_control(
                    resolution["option"]
                )

            try:
                page.wait_for_timeout(
                    300
                )
            except Exception:
                pass

        # =====================================================
        # STEP 5 — submit button
        # =====================================================
        submit_button = page.locator(
            SUBMIT_BUTTON_SELECTOR
        ).first

        if submit_button.count() == 0:
            _log_answers(
                vacancy_id,
                qa_log,
                "NO_SUBMIT_BUTTON",
            )

            return {
                "status": "NO_SUBMIT_BUTTON",
                "reason": (
                    "Все вопросы обработаны, "
                    "но кнопка финальной отправки "
                    "сложной анкеты не найдена."
                ),
                "resume_warning": "",
                "qa_log": qa_log,
            }

        # =====================================================
        # STEP 6 — DRY RUN
        # =====================================================
        if dry_run:
            _log_answers(
                vacancy_id,
                qa_log,
                "DRY_RUN",
            )

            return {
                "status": "DRY_RUN",
                "reason": (
                    "Сложная анкета заполнена, "
                    "реальная отправка заблокирована "
                    "настройкой DRY_RUN."
                ),
                "resume_warning": "",
                "qa_log": qa_log,
            }

        # =====================================================
        # STEP 7 — реальная отправка
        # =====================================================
        _dismiss_cookie_informer(page)

        submit_button.scroll_into_view_if_needed(
            timeout=5000
        )

        submit_button.click(
            timeout=10_000
        )

        page.wait_for_timeout(
            2000
        )

        _log_answers(
            vacancy_id,
            qa_log,
            "SUBMITTED",
        )

        return {
            "status": "SUBMITTED",
            "reason": (
                "Сложная анкета заполнена "
                "и отклик реально отправлен."
            ),
            "resume_warning": "",
            "qa_log": qa_log,
        }

    except Exception as error:
        _log_answers(
            vacancy_id,
            qa_log,
            "ERROR",
        )

        return {
            "status": "ERROR",
            "reason": (
                "Ошибка при заполнении/отправке "
                f"сложной анкеты: {error}"
            ),
            "resume_warning": "",
            "qa_log": qa_log,
        }
