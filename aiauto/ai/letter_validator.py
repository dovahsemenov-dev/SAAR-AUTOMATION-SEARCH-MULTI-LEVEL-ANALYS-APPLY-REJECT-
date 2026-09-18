"""ai/letter_validator.py

Детерминированный валидатор сопроводительного письма.

LLM здесь НЕ используется.

Проверки:

1. письмо не пустое;
2. нет placeholders;
3. нет опасных заявлений о коммерческом опыте;
4. selected_facts входят в confirmed_actions;
5. selected_facts не входят в explicitly_not_confirmed;
6. письмо содержит выбранный факт;
7. явно запрещённые технологии не появляются;
8. неподтверждённые образовательные числовые данные блокируются.
"""

from __future__ import annotations

import re
from typing import Any


# ============================================================
# Placeholders
# ============================================================

FORBIDDEN_PLACEHOLDERS = (
    "[ваше имя]",
    "[имя]",
    "<имя>",
    "{имя}",
    "{{имя}}",
    "[название компании]",
    "[название вакансии]",
    "<название компании>",
    "<название вакансии>",
    "[компания]",
    "[вакансия]",
    "<компания>",
    "<вакансия>",
)


# ============================================================
# Опасные заявления
# ============================================================

FORBIDDEN_CLAIM_PATTERNS = (
    r"\bкоммерческ\w+\s+опыт\b",
    r"\bпрофессиональн\w+\s+опыт\b",
    r"\bопыт\s+работы\b",
    r"\bработал(?:а)?\s+в\s+компани",
    r"\bработал(?:а)?\s+на\s+позици",
    r"\bзанимал(?:а)?\s+должност",
    r"\bнастраивал(?:а)?\b",
    r"\bадминистрировал(?:а)?\b",
    r"\bразрабатывал(?:а)?\b",
)


# ============================================================
# Утилиты
# ============================================================

def _clean(
    value: Any,
) -> str:

    return (
        " ".join(
            str(value or "")
            .replace("\x00", " ")
            .split()
        )
        .strip()
    )


def _norm(
    value: Any,
) -> str:

    return (
        _clean(value)
        .lower()
        .replace("ё", "е")
    )


# ============================================================
# selected_facts
# ============================================================

def _facts(
    selected_facts: Any,
) -> list[str]:

    result: list[str] = []

    if not isinstance(
        selected_facts,
        list,
    ):
        return result

    for item in selected_facts:

        if isinstance(item, str):

            value = _clean(item)

        elif isinstance(item, dict):

            value = _clean(
                item.get("fact")
                or item.get("text")
            )

        else:

            value = ""

        if value and value not in result:
            result.append(value)

    return result


# ============================================================
# WHITE LIST
# ============================================================

def _confirmed_actions(
    profile_facts: Any,
) -> set[str]:

    if not isinstance(
        profile_facts,
        dict,
    ):
        return set()

    raw = profile_facts.get(
        "confirmed_actions",
        [],
    )

    if not isinstance(
        raw,
        list,
    ):
        return set()

    result: set[str] = set()

    for item in raw:

        if not isinstance(
            item,
            str,
        ):
            continue

        value = _norm(item)

        if value:
            result.add(value)

    return result


# ============================================================
# BLACK LIST
# ============================================================

def _forbidden_actions(
    profile_facts: Any,
) -> set[str]:

    if not isinstance(
        profile_facts,
        dict,
    ):
        return set()

    raw = profile_facts.get(
        "explicitly_not_confirmed",
        [],
    )

    if not isinstance(
        raw,
        list,
    ):
        return set()

    result: set[str] = set()

    for item in raw:

        if not isinstance(
            item,
            str,
        ):
            continue

        value = _norm(item)

        if value:
            result.add(value)

    return result


# ============================================================
# Проверка selected_facts
# ============================================================

def _validate_selected_facts(
    selected_facts: Any,
    profile_facts: Any,
) -> list[str]:

    problems: list[str] = []

    facts = _facts(
        selected_facts
    )

    confirmed = _confirmed_actions(
        profile_facts
    )

    forbidden = _forbidden_actions(
        profile_facts
    )

    for fact in facts:

        key = _norm(fact)

        # ----------------------------------------------------
        # Не входит в whitelist.
        # ----------------------------------------------------

        if key not in confirmed:

            problems.append(
                "Выбранный факт отсутствует "
                "в profile_facts['confirmed_actions']: "
                f"{fact}"
            )

        # ----------------------------------------------------
        # Одновременно оказался в blacklist.
        # ----------------------------------------------------

        if key in forbidden:

            problems.append(
                "Выбранный факт присутствует "
                "в profile_facts['explicitly_not_confirmed']: "
                f"{fact}"
            )

    return problems


# ============================================================
# Проверка запрещённых технологий
# ============================================================

def _validate_forbidden_domains(
    text: str,
    profile_facts: Any,
) -> list[str]:

    problems: list[str] = []

    if not isinstance(
        profile_facts,
        dict,
    ):
        return problems

    raw_forbidden = profile_facts.get(
        "explicitly_not_confirmed",
        [],
    )

    if not isinstance(
        raw_forbidden,
        list,
    ):
        return problems

    lowered = _norm(text)

    domain_markers = {
        "selenium": (
            "selenium",
        ),
        "playwright": (
            "playwright",
        ),
        "kubernetes": (
            "kubernetes",
            "k8s",
        ),
        "professional python": (
            "professional python",
            "профессиональный python",
            "профессиональный питон",
        ),
        "javascript": (
            "javascript",
            "java script",
        ),
        "typescript": (
            "typescript",
        ),
        "react": (
            "react",
        ),
        "jenkins": (
            "jenkins",
        ),
        "ci/cd": (
            "ci/cd",
            "cicd",
            "continuous integration",
        ),
        "linux administration": (
            "администрирование linux",
            "linux administration",
        ),
        "network administration": (
            "администрирование сетей",
            "сетевое администрирование",
        ),
    }

    for domain, markers in domain_markers.items():

        domain_is_forbidden = False

        for forbidden in raw_forbidden:

            if not isinstance(
                forbidden,
                str,
            ):
                continue

            forbidden_low = _norm(
                forbidden
            )

            if (
                domain in forbidden_low
                or any(
                    marker in forbidden_low
                    for marker in markers
                )
            ):
                domain_is_forbidden = True
                break

        if not domain_is_forbidden:
            continue

        if any(
            marker in lowered
            for marker in markers
        ):

            problems.append(
                "В письме обнаружено явно "
                f"неподтверждённое направление/технология: "
                f"{domain}"
            )

    return problems


# ============================================================
# Образовательные числа
# ============================================================

def _validate_education_numbers(
    text: str,
    profile: str | None,
    profile_facts: dict | None,
) -> list[str]:

    problems: list[str] = []

    education_markers = (
        r"\bегэ\b",
        r"\bсредн\w+\s+балл",
        r"\bбалл\w+\s+диплом",
    )

    if not any(
        re.search(
            pattern,
            text,
            flags=re.I,
        )
        for pattern in education_markers
    ):
        return problems

    profile_text = _clean(
        profile
    )

    profile_fact_text = _clean(
        profile_facts
    )

    source = (
        profile_text
        + " "
        + profile_fact_text
    ).lower()

    matches = re.findall(
        r"(?:ЕГЭ|средн\w+\s+балл|балл\w+\s+диплом)"
        r"[^.!?]{0,80}\d+(?:[.,]\d+)?",
        text,
        flags=re.I,
    )

    for match in matches:

        if match.lower() not in source:

            problems.append(
                "В письме обнаружены конкретные "
                "образовательные числовые данные, "
                "которые не подтверждены источником."
            )

            break

    return problems


# ============================================================
# Публичный API
# ============================================================

def validate_letter(
    ollama_url: str | None,
    model_name: str | None,
    letter: str | None,
    profile: str | None,
    profile_facts: dict | None,
    selected_facts: list[dict] | None,
) -> dict:

    problems: list[str] = []

    text = _clean(
        letter
    )

    # --------------------------------------------------------
    # 1. Пустое письмо
    # --------------------------------------------------------

    if not text:

        return {
            "status": "REQUIRES_USER",
            "problems": [
                "Сопроводительное письмо пустое."
            ],
        }

    lowered = _norm(text)

    # --------------------------------------------------------
    # 2. Placeholders
    # --------------------------------------------------------

    for placeholder in FORBIDDEN_PLACEHOLDERS:

        if _norm(placeholder) in lowered:

            problems.append(
                "Обнаружен незаполненный "
                f"placeholder: {placeholder}"
            )

    # --------------------------------------------------------
    # 3. Опасные заявления
    # --------------------------------------------------------

    for pattern in FORBIDDEN_CLAIM_PATTERNS:

        if re.search(
            pattern,
            lowered,
        ):

            problems.append(
                "Обнаружена формулировка, которая "
                "может ложно заявлять о профессиональном "
                f"опыте: {pattern}"
            )

    # --------------------------------------------------------
    # 4. Независимая проверка selected_facts
    # --------------------------------------------------------

    problems.extend(
        _validate_selected_facts(
            selected_facts,
            profile_facts,
        )
    )

    # --------------------------------------------------------
    # 5. Письмо должно содержать выбранный факт.
    # --------------------------------------------------------

    facts = _facts(
        selected_facts
    )

    if facts:

        if not any(
            _norm(fact) in lowered
            for fact in facts
        ):

            problems.append(
                "Письмо не содержит ни одного "
                "выбранного подтверждённого факта."
            )

    # --------------------------------------------------------
    # 6. Запрещённые технологии.
    # --------------------------------------------------------

    problems.extend(
        _validate_forbidden_domains(
            text,
            profile_facts,
        )
    )

    # --------------------------------------------------------
    # 7. Образовательные числовые данные.
    # --------------------------------------------------------

    problems.extend(
        _validate_education_numbers(
            text,
            profile,
            profile_facts,
        )
    )

    # --------------------------------------------------------
    # Удаление дублей.
    # --------------------------------------------------------

    unique_problems: list[str] = []
    seen: set[str] = set()

    for problem in problems:

        key = str(problem)

        if key in seen:
            continue

        seen.add(key)
        unique_problems.append(key)

    # --------------------------------------------------------
    # Финальный результат.
    # --------------------------------------------------------

    if unique_problems:

        return {
            "status": "REQUIRES_USER",
            "problems": unique_problems,
        }

    return {
        "status": "PASS",
        "problems": [],
    }