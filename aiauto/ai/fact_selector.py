"""ai/fact_selector.py
Безопасный выбор подтверждённых фактов для сопроводительного письма.

Архитектура:
1. Источник истины — только profile_facts["confirmed_actions"].
2. explicitly_not_confirmed — абсолютный blacklist.
3. Qwen только предлагает факты.
4. Python проверяет whitelist, blacklist, API-контекст и РЕЛЕВАНТНОСТЬ.
5. Нерелевантные факты не добавляются ради заполнения max_facts.
6. Специально защищены слабые/контекстные факты:
   n8n, PyCharm, AI-assisted coding и т.п. не проходят в письмо,
   если вакансия прямо не связана с ними.
7. Возвращается буквальный текст исходного confirmed_actions.

ИСПРАВЛЕНИЕ №1 (см. кейс "ИТ специалист" — Postman/API/JSON прошли в
письмо на вакансию про Windows/Word/Excel/TCP-IP/DNS/NAT):
из API_TERMS убрано слово "запрос" — слишком общее.

ИСПРАВЛЕНИЕ №2: порог релевантности поднят с score > 0 до
score >= MIN_RELEVANCE_SCORE (6). Единичное случайное совпадение
одного общего слова (+5) больше не проходит само по себе.

ИСПРАВЛЕНИЕ №3 (после добавления в profile_facts.json "очевидных"
фактов — Windows/Office, командная работа, стрессоустойчивость,
грамотная речь, IT-терминология, TCP/IP/DNS/NAT/OSI):
у этих новых фактов, как правило, нет длинного технического
названия — они короткие ("Стрессоустойчив") и раньше при score>=6
почти никогда не проходили бы порог, потому что единичное
совпадение слова даёт всего +5, а тематического бонуса под них
не было вообще. Добавлены отдельные темы и детекторы контекста
(windows_office, teamwork, stress_tolerance, communication,
it_terminology), дающие полноценный тематический бонус (+8),
и сетевые термины дополнены NAT/OSI.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ai.ollama_client import ask_json


# ============================================================
# Порог релевантности
# ============================================================

MIN_RELEVANCE_SCORE = 6


# ============================================================
# Контексты вакансии
# ============================================================

API_TERMS = (
    "api",
    "rest",
    "http",
    "postman",
    "json",
    "swagger",
    "openapi",
    "endpoint",
    "webhook",
    "интеграц",
    "api-тест",
    "api тест",
)

QA_CONTEXT_TERMS = (
    "qa",
    "тестиров",
    "тестирован",
    "тестировщик",
    "quality assurance",
    "software testing",
    "manual testing",
    "manual qa",
    "мануальн",
    "ручное тестирование",
    "функциональн",
    "автоматизац",
    "автотест",
    "регрессион",
    "smoke testing",
    "тест-кейс",
    "тест кейс",
    "test case",
    "баг",
    "bug",
    "quality",
    "нагрузочн",
    "performance testing",
    "performance test",
    "load testing",
    "load test",
    "stress testing",
    "stress test",
    "тест производительности",
)

LOAD_TEST_TERMS = (
    "нагрузочн",
    "нагрузочное тестирование",
    "нагрузочные тесты",
    "performance testing",
    "performance test",
    "load testing",
    "load test",
    "stress testing",
    "stress test",
    "стресс-тест",
    "стресс тест",
    "тест производительности",
    "производительность",
)

SECURITY_TERMS = (
    "информационн",
    "кибербезопас",
    "информационная безопасность",
    "информационной безопасности",
    "иб ",
    "security",
    "cybersecurity",
    "кибербезопасность",
    "forensic",
    "форензик",
    "расследован",
    "инцидент",
    "soc",
    "siem",
    "threat",
    "malware",
    "вредонос",
    "безопасности",
)

NETWORK_TERMS = (
    "компьютерн",
    "сеть",
    "сетев",
    "network",
    "tcp",
    "udp",
    "dns",
    "dhcp",
    "nat",
    "osi",
    "routing",
    "маршрутиз",
    "firewall",
    "межсетев",
    "vpn",
)

PYTHON_DEVELOPMENT_TERMS = (
    "python",
    "питон",
    "python developer",
    "python разработ",
    "разработчик python",
)

AUTOMATION_TERMS = (
    "автоматизац",
    "automation",
    "qa automation",
    "test automation",
    "автотест",
    "автоматизированн",
)

N8N_TERMS = (
    "n8n",
    "автоматизац бизнес-процесс",
    "автоматизация бизнес процессов",
    "workflow automation",
    "workflow",
)

PYCHARM_TERMS = (
    "pycharm",
)

AI_CODING_TERMS = (
    "ai-assisted coding",
    "ai assisted coding",
    "ai coding",
    "искусственн интеллект",
    "генеративн",
    "llm",
    "локальн llm",
    "ollama",
)

VIBECODER_TERMS = (
    "vibecoder",
    "vibe coder",
    "vibe-coder",
    "vibecoding",
    "vibe coding",
    "vibe-coding",
    "вайбкодер",
    "вайб-кодер",
    "вайб кодер",
    "вайбкодинг",
    "вайб-кодинг",
    "вайб кодинг",
)

DOCKER_TERMS = (
    "docker",
    "контейнер",
    "container",
)

LINUX_TERMS = (
    "linux",
    "линукс",
)

JIRA_TERMS = (
    "jira",
    "джира",
)

TESTIT_TERMS = (
    "testit",
    "test it",
)

SQL_TERMS = (
    "sql",
    "postgresql",
    "postgres",
    "база данных",
    "базами данных",
)

DEVTOOLS_TERMS = (
    "devtools",
    "developer tools",
    "инструмент разработчика",
    "инструменты разработчика",
    "браузер",
)

WINDOWS_OFFICE_TERMS = (
    "windows",
    "microsoft office",
    "ms office",
    " word",
    "excel",
    "офисн",
    "офисные программы",
    "пользователь пк",
    "уверенный пользователь пк",
)

TEAMWORK_TERMS = (
    "команде",
    "команда",
    "командн",
    "коллектив",
    "team",
)

STRESS_TOLERANCE_TERMS = (
    "стрессоустойч",
    "стресс",
)

COMMUNICATION_TERMS = (
    "грамотн",
    "коммуникаб",
    "коммуникац",
    "устная и письменная",
    "грамотная речь",
    "деловое общение",
    "деловая коммуникация",
)

IT_TERMINOLOGY_TERMS = (
    "терминолог",
    "it-терминолог",
    "ит-терминолог",
)

# ============================================================
# Темы подтверждённых фактов
# ============================================================

FACT_TOPIC_TERMS: dict[str, tuple[str, ...]] = {
    "postman": ("postman",),
    "api": ("api", "запрос", "запросы"),
    "json": ("json",),
    "json_server": ("json server",),
    "http": ("http",),
    "rest": ("rest",),
    "postgresql": ("postgresql", "postgres"),
    "sql": ("sql", "база данных", "базами данных"),
    "devtools": (
        "devtools",
        "инструмент разработчика",
        "браузерные",
        "браузер",
    ),
    "docker": ("docker",),
    "python": ("python", "питон"),
    "jira": ("jira", "джира"),
    "testit": ("testit", "test it"),
    "network": (
        "сет",
        "network",
        "tcp",
        "udp",
        "dns",
        "dhcp",
        "nat",
        "osi",
        "маршрутиз",
        "firewall",
        "vpn",
    ),
    "linux": ("linux", "линукс"),
    "n8n": ("n8n",),
    "pycharm": ("pycharm",),
    "ai_coding": (
        "ai-assisted coding",
        "ai assisted coding",
    ),
    "vibecoder_project": (
        "vibecoding",
    ),
    "ollama": ("ollama",),
    "local_llm": ("локальн llm", "local llm"),
    "qa": (
        "qa",
        "тест",
        "тестирован",
        "тестиров",
        "баг",
        "bug",
        "checklist",
        "чек-лист",
        "тест-кейс",
        "test case",
    ),
    "windows_office": (
        "windows",
        "word",
        "excel",
        "офисн",
        "пк",
    ),
    "teamwork": (
        "команде",
        "команда",
        "командн",
        "коллектив",
    ),
    "stress_tolerance": (
        "стрессоустойч",
        "стресс",
    ),
    "communication": (
        "грамотн",
        "коммуникаб",
        "коммуникац",
        "речь",
    ),
    "it_terminology": (
        "терминолог",
    ),
}


# ============================================================
# Нормализация
# ============================================================

def _norm(value: Any) -> str:
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


def _vacancy_text(vacancy: dict) -> str:
    parts = (
        vacancy.get("title", ""),
        vacancy.get("description", ""),
        vacancy.get("requirements", ""),
        vacancy.get("key_skills", ""),
        vacancy.get("skills", ""),
    )
    return _norm(" ".join(str(x or "") for x in parts))


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _is_api_context(vacancy: dict) -> bool:
    return _contains_any(_vacancy_text(vacancy), API_TERMS)


def _is_qa_context(vacancy: dict) -> bool:
    return _contains_any(_vacancy_text(vacancy), QA_CONTEXT_TERMS)


def _is_load_test_context(vacancy: dict) -> bool:
    return _contains_any(_vacancy_text(vacancy), LOAD_TEST_TERMS)


def _is_security_context(vacancy: dict) -> bool:
    return _contains_any(_vacancy_text(vacancy), SECURITY_TERMS)


def _is_network_context(vacancy: dict) -> bool:
    return _contains_any(_vacancy_text(vacancy), NETWORK_TERMS)


def _is_python_development_context(vacancy: dict) -> bool:
    text = _vacancy_text(vacancy)
    return _contains_any(text, PYTHON_DEVELOPMENT_TERMS) and (
        "разработ" in text
        or "developer" in text
        or "программист" in text
        or "backend" in text
    )


def _is_automation_context(vacancy: dict) -> bool:
    return _contains_any(_vacancy_text(vacancy), AUTOMATION_TERMS)


def _is_n8n_context(vacancy: dict) -> bool:
    return _contains_any(_vacancy_text(vacancy), N8N_TERMS)


def _is_pycharm_context(vacancy: dict) -> bool:
    return _contains_any(_vacancy_text(vacancy), PYCHARM_TERMS)


def _is_ai_coding_context(vacancy: dict) -> bool:
    return _contains_any(_vacancy_text(vacancy), AI_CODING_TERMS)


def _is_vibecoder_context(vacancy: dict) -> bool:
    return _contains_any(_vacancy_text(vacancy), VIBECODER_TERMS)


def _is_docker_context(vacancy: dict) -> bool:
    return _contains_any(_vacancy_text(vacancy), DOCKER_TERMS)


def _is_linux_context(vacancy: dict) -> bool:
    return _contains_any(_vacancy_text(vacancy), LINUX_TERMS)


def _is_jira_context(vacancy: dict) -> bool:
    return _contains_any(_vacancy_text(vacancy), JIRA_TERMS)


def _is_testit_context(vacancy: dict) -> bool:
    return _contains_any(_vacancy_text(vacancy), TESTIT_TERMS)


def _is_sql_context(vacancy: dict) -> bool:
    return _contains_any(_vacancy_text(vacancy), SQL_TERMS)


def _is_devtools_context(vacancy: dict) -> bool:
    return _contains_any(_vacancy_text(vacancy), DEVTOOLS_TERMS)


def _is_windows_office_context(vacancy: dict) -> bool:
    return _contains_any(_vacancy_text(vacancy), WINDOWS_OFFICE_TERMS)


def _is_teamwork_context(vacancy: dict) -> bool:
    return _contains_any(_vacancy_text(vacancy), TEAMWORK_TERMS)


def _is_stress_tolerance_context(vacancy: dict) -> bool:
    return _contains_any(_vacancy_text(vacancy), STRESS_TOLERANCE_TERMS)


def _is_communication_context(vacancy: dict) -> bool:
    return _contains_any(_vacancy_text(vacancy), COMMUNICATION_TERMS)


def _is_it_terminology_context(vacancy: dict) -> bool:
    return _contains_any(_vacancy_text(vacancy), IT_TERMINOLOGY_TERMS)


def _is_api_fact(fact: str) -> bool:
    return _contains_any(
        _norm(fact),
        (
            "api",
            "postman",
            "json",
            "json server",
            "http",
            "rest",
        ),
    )


# ============================================================
# White / black list
# ============================================================

def _get_confirmed_actions(profile_facts: dict) -> list[dict]:
    raw = profile_facts.get("confirmed_actions", [])

    if not isinstance(raw, list):
        return []

    result: list[dict] = []
    seen: set[str] = set()

    for index, value in enumerate(raw):
        if not isinstance(value, str):
            continue

        fact = value.strip()
        key = _norm(fact)

        if not key or key in seen:
            continue

        seen.add(key)
        result.append(
            {
                "fact": fact,
                "path": f"confirmed_actions[{index}]",
            }
        )

    return result


def _get_forbidden_actions(profile_facts: dict) -> set[str]:
    raw = profile_facts.get("explicitly_not_confirmed", [])

    if not isinstance(raw, list):
        return set()

    return {
        _norm(value)
        for value in raw
        if isinstance(value, str) and _norm(value)
    }


def _build_fact_index(profile_facts: dict) -> dict[str, dict]:
    forbidden = _get_forbidden_actions(profile_facts)
    index: dict[str, dict] = {}

    for item in _get_confirmed_actions(profile_facts):
        key = _norm(item["fact"])

        if not key or key in forbidden:
            continue

        index[key] = item

    return index


# ============================================================
# Ответ Qwen
# ============================================================

def _extract_model_facts(result: Any) -> list[str]:
    if not isinstance(result, dict):
        return []

    raw = result.get(
        "facts",
        result.get("selected_facts", []),
    )

    if not isinstance(raw, list):
        return []

    output: list[str] = []

    for item in raw:
        if isinstance(item, str):
            value = item.strip()
        elif isinstance(item, dict):
            value = str(
                item.get("fact")
                or item.get("text")
                or ""
            ).strip()
        else:
            value = ""

        if value and value not in output:
            output.append(value)

    return output


def json_like_facts(fact_index: dict[str, dict]) -> str:
    return json.dumps(
        list(fact_index.values()),
        ensure_ascii=False,
        indent=2,
    )


# ============================================================
# Темы факта
# ============================================================

def _fact_topics(fact: str) -> set[str]:
    normalized = _norm(fact)
    topics: set[str] = set()

    for topic, markers in FACT_TOPIC_TERMS.items():
        if any(marker in normalized for marker in markers):
            topics.add(topic)

    return topics


# ============================================================
# Релевантность
# ============================================================

def _fact_score(
    fact: str,
    vacancy_text: str,
    qa_context: bool,
    api_context: bool,
    load_test_context: bool,
    security_context: bool,
    network_context: bool,
    python_development_context: bool,
    automation_context: bool,
    n8n_context: bool,
    pycharm_context: bool,
    ai_coding_context: bool,
    vibecoder_context: bool,
    docker_context: bool,
    linux_context: bool,
    jira_context: bool,
    testit_context: bool,
    sql_context: bool,
    devtools_context: bool,
    windows_office_context: bool,
    teamwork_context: bool,
    stress_tolerance_context: bool,
    communication_context: bool,
    it_terminology_context: bool,
) -> int:
    fact_norm = _norm(fact)

    if not fact_norm:
        return 0

    topics = _fact_topics(fact)

    # --------------------------------------------------------
    # Жёсткий API gate.
    # --------------------------------------------------------
    if _is_api_fact(fact) and not api_context:
        return -100

    # --------------------------------------------------------
    # Слабые факты не получают бонус только из-за того,
    # что вакансия относится к IT.
    # --------------------------------------------------------
    if "n8n" in topics and not n8n_context:
        return 0

    if "pycharm" in topics and not pycharm_context:
        return 0

    if "ai_coding" in topics and not ai_coding_context:
        return 0

    if "vibecoder_project" in topics and not vibecoder_context:
        return 0

    score = 0

    # --------------------------------------------------------
    # Прямое совпадение значимых слов.
    # --------------------------------------------------------
    stop_words = {
        "работал",
        "работала",
        "использовал",
        "использовала",
        "изучал",
        "изучала",
        "около",
        "при",
        "для",
        "как",
        "над",
        "через",
        "основы",
        "свой",
        "своя",
        "свои",
        "учебном",
        "учебный",
        "учебная",
        "личном",
        "личный",
        "личная",
        "знакомился",
        "знакомилась",
        "знаю",
        "владею",
        "умею",
    }

    fact_words = {
        word
        for word in re.findall(
            r"[a-zа-я0-9+#.-]{3,}",
            fact_norm,
        )
        if word not in stop_words
    }

    for word in fact_words:
        if word in vacancy_text:
            score += 5

    # --------------------------------------------------------
    # Тематическое совпадение.
    # --------------------------------------------------------
    topic_to_context = {
        "postman": api_context,
        "api": api_context,
        "json": api_context,
        "json_server": api_context,
        "http": api_context,
        "rest": api_context,
        "postgresql": sql_context,
        "sql": sql_context,
        "devtools": devtools_context,
        "docker": docker_context,
        "python": (
            python_development_context
            or automation_context
            or qa_context
        ),
        "jira": jira_context or qa_context,
        "testit": testit_context or qa_context,
        "network": network_context or security_context,
        "linux": linux_context,
        "n8n": n8n_context,
        "pycharm": pycharm_context,
        "ai_coding": ai_coding_context,
        "vibecoder_project": vibecoder_context,
        "ollama": ai_coding_context,
        "local_llm": ai_coding_context,
        "qa": qa_context,
        "windows_office": windows_office_context,
        "teamwork": teamwork_context,
        "stress_tolerance": stress_tolerance_context,
        "communication": communication_context,
        "it_terminology": it_terminology_context,
    }

    for topic in topics:
        if topic_to_context.get(topic, False):
            score += 8

    # --------------------------------------------------------
    # QA-контекст.
    # --------------------------------------------------------
    if qa_context and topics & {
        "qa",
        "devtools",
        "jira",
        "testit",
        "sql",
        "postgresql",
        "python",
        "docker",
        "network",
    }:
        score += 3

    # --------------------------------------------------------
    # Load/performance testing.
    # --------------------------------------------------------
    if load_test_context and topics & {
        "qa",
        "devtools",
        "sql",
        "postgresql",
        "docker",
        "network",
        "python",
    }:
        score += 3

    # --------------------------------------------------------
    # Security/forensic.
    # --------------------------------------------------------
    if security_context and topics & {
        "network",
        "linux",
        "docker",
        "python",
    }:
        score += 5

    # --------------------------------------------------------
    # Network-specific.
    # --------------------------------------------------------
    if network_context and "network" in topics:
        score += 5

    # --------------------------------------------------------
    # Automation-specific.
    # --------------------------------------------------------
    if automation_context and topics & {
        "python",
        "qa",
        "docker",
        "devtools",
        "api",
        "postman",
    }:
        score += 4

    return score


def _relevance_context(vacancy: dict) -> dict[str, bool]:
    return {
        "api_context": _is_api_context(vacancy),
        "qa_context": _is_qa_context(vacancy),
        "load_test_context": _is_load_test_context(vacancy),
        "security_context": _is_security_context(vacancy),
        "network_context": _is_network_context(vacancy),
        "python_development_context": _is_python_development_context(vacancy),
        "automation_context": _is_automation_context(vacancy),
        "n8n_context": _is_n8n_context(vacancy),
        "pycharm_context": _is_pycharm_context(vacancy),
        "ai_coding_context": _is_ai_coding_context(vacancy),
        "vibecoder_context": _is_vibecoder_context(vacancy),
        "docker_context": _is_docker_context(vacancy),
        "linux_context": _is_linux_context(vacancy),
        "jira_context": _is_jira_context(vacancy),
        "testit_context": _is_testit_context(vacancy),
        "sql_context": _is_sql_context(vacancy),
        "devtools_context": _is_devtools_context(vacancy),
        "windows_office_context": _is_windows_office_context(vacancy),
        "teamwork_context": _is_teamwork_context(vacancy),
        "stress_tolerance_context": _is_stress_tolerance_context(vacancy),
        "communication_context": _is_communication_context(vacancy),
        "it_terminology_context": _is_it_terminology_context(vacancy),
    }


def _score_fact_for_vacancy(
    fact: str,
    vacancy: dict,
) -> int:
    text = _vacancy_text(vacancy)
    ctx = _relevance_context(vacancy)

    return _fact_score(
        fact=fact,
        vacancy_text=text,
        **ctx,
    )


def _validate_model_fact_relevance(
    fact: str,
    vacancy: dict,
) -> bool:
    """
    Финальный deterministic gate.

    Факт Qwen может быть принят только если:
    1. он есть в confirmed_actions;
    2. он не находится в blacklist;
    3. его релевантность для конкретной вакансии не ниже
       MIN_RELEVANCE_SCORE.
    """
    return _score_fact_for_vacancy(
        fact,
        vacancy,
    ) >= MIN_RELEVANCE_SCORE


# ============================================================
# Fallback
# ============================================================

def _fallback_select(
    vacancy: dict,
    profile_facts: dict,
    limit: int = 5,
) -> list[dict]:
    all_facts = list(
        _build_fact_index(profile_facts).values()
    )

    if not all_facts:
        return []

    scored: list[tuple[int, dict]] = []

    for item in all_facts:
        score = _score_fact_for_vacancy(
            item["fact"],
            vacancy,
        )

        if score < MIN_RELEVANCE_SCORE:
            continue

        scored.append((score, item))

    scored.sort(
        key=lambda item: (
            -item[0],
            len(item[1]["fact"]),
            item[1]["fact"].lower(),
        )
    )

    result: list[dict] = []

    for score, item in scored[:limit]:
        result.append(
            {
                "fact": item["fact"],
                "path": item.get("path", ""),
                "relevance": "deterministic",
                "relevance_score": score,
            }
        )

    return result


def _supplement_facts(
    vacancy: dict,
    profile_facts: dict,
    selected: list[dict],
    limit: int,
) -> list[dict]:
    if len(selected) >= limit:
        return selected[:limit]

    selected_keys = {
        _norm(item.get("fact", ""))
        for item in selected
    }

    candidates: list[tuple[int, dict]] = []

    for item in _build_fact_index(profile_facts).values():
        key = _norm(item["fact"])

        if not key or key in selected_keys:
            continue

        score = _score_fact_for_vacancy(
            item["fact"],
            vacancy,
        )

        if score < MIN_RELEVANCE_SCORE:
            continue

        candidates.append((score, item))

    candidates.sort(
        key=lambda item: (
            -item[0],
            len(item[1]["fact"]),
            item[1]["fact"].lower(),
        )
    )

    for score, item in candidates:
        selected.append(
            {
                "fact": item["fact"],
                "path": item.get("path", ""),
                "relevance": "deterministic_supplement",
                "relevance_score": score,
            }
        )

        if len(selected) >= limit:
            break

    return selected[:limit]


# ============================================================
# Public API
# ============================================================

def select_facts(
    ollama_url: str,
    model_name: str,
    vacancy: dict,
    profile_facts: dict,
    max_facts: int = 5,
) -> list[dict]:
    """
    Выбирает подтверждённые факты для сопроводительного письма.

    ВАЖНО:
    max_facts — число, а не requirements dict.
    """

    if max_facts <= 0:
        return []

    fact_index = _build_fact_index(profile_facts)

    if not fact_index:
        return []

    vacancy_title = str(
        vacancy.get("title") or ""
    )
    vacancy_description = str(
        vacancy.get("description") or ""
    )
    vacancy_requirements = str(
        vacancy.get("requirements") or ""
    )
    vacancy_skills = vacancy.get("skills") or []

    prompt = f"""
Ты выбираешь подтверждённые факты кандидата
для сопроводительного письма.

ВАКАНСИЯ:
Название:
{vacancy_title}

Ключевые навыки HH:
{", ".join(str(x) for x in vacancy_skills)}

Требования:
{vacancy_requirements}

Описание:
{vacancy_description[:12000]}

ФАКТЫ КАНДИДАТА:
{json_like_facts(fact_index)}

Верни строго JSON:
{{"facts": ["точная строка факта 1", "точная строка факта 2"]}}

ЖЁСТКИЕ ПРАВИЛА:
1. Можно выбирать ТОЛЬКО строки, буквально присутствующие
   в ФАКТАХ КАНДИДАТА.
2. Нельзя переформулировать факты.
3. Нельзя усиливать уровень навыка.
4. Нельзя превращать учебную практику в коммерческий опыт.
5. Нельзя придумывать новые факты.
6. Не выбирай факты только ради количества.
7. API/Postman/JSON выбирай только когда вакансия действительно
   связана с API/HTTP/JSON/Postman.
8. Для QA приоритетны Manual QA, тестирование, тест-дизайн,
   test case/checklist/bug report, DevTools, API/Postman,
   SQL/PostgreSQL и другие факты, реально связанные с вакансией.
9. Для forensic/ИБ не выбирай n8n, PyCharm или AI-assisted coding,
   если вакансия прямо не связана с этими технологиями.
10. n8n, PyCharm и AI-assisted coding нельзя выбирать просто
    потому, что они технические.
11. Не выбирай голые названия артефактов, если они не являются
    подтверждённым действием кандидата.
12. Максимум {max_facts} фактов.
13. Верни только JSON.
""".strip()

    selected: list[dict] = []
    seen: set[str] = set()

    try:
        result = ask_json(
            ollama_url,
            model_name,
            prompt,
        )

        model_facts = _extract_model_facts(result)

        for model_fact in model_facts:
            key = _norm(model_fact)

            if not key or key in seen:
                continue

            if key not in fact_index:
                continue

            if not _validate_model_fact_relevance(
                fact_index[key]["fact"],
                vacancy,
            ):
                continue

            seen.add(key)

            selected.append(
                {
                    "fact": fact_index[key]["fact"],
                    "path": fact_index[key].get("path", ""),
                    "relevance": "qwen",
                    "relevance_score": _score_fact_for_vacancy(
                        fact_index[key]["fact"],
                        vacancy,
                    ),
                }
            )

            if len(selected) >= max_facts:
                break

    except Exception:
        selected = []

    if selected:
        return _supplement_facts(
            vacancy=vacancy,
            profile_facts=profile_facts,
            selected=selected,
            limit=max_facts,
        )

    return _fallback_select(
        vacancy=vacancy,
        profile_facts=profile_facts,
        limit=max_facts,
    )