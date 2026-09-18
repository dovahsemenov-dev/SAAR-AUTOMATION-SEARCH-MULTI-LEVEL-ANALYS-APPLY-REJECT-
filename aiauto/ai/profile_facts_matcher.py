"""
Детерминированный сопоставитель требований вакансии (вывод
requirements_analyzer.py) с фактами о кандидате (profile_facts.json).

Зачем это нужно
================
Раньше evaluator получал сырую вакансию и PROFILE и заново, на
каждом прогоне, решал текстом, подтверждён ли конкретный навык.
Это дважды приводило к прямым фактическим противоречиям:

- ASTON: evaluator написал "теория тестирования не подтверждена",
  хотя profile_facts.skills.test_design и manual_qa содержат её
  напрямую.
- Jira/GitLab Issues: подтверждение Jira substring-логикой
  автоматически "подтверждало" и GitLab Issues, хотя это два
  разных факта.

Этот модуль убирает необходимость решать такие вопросы текстом.
Сопоставление делается один раз, программно, по явному словарю
синонимов (SKILL_ALIASES). Если для навыка синонима нет — он
считается неподтверждённым, а не "вроде похоже". Ложноотрицательный
результат здесь безопаснее ложноположительного: кандидат не будет
автоматически отклонён из-за этого модуля (сюда не входит REJECT/
APPLY-логика), а evaluator увидит явный статус "unknown_skill" и
сможет запросить уточнение у пользователя, а не придумывать факт.

Явно НЕ входит в задачи этого модуля:
- решать APPLY / REVIEW / REJECT (это decision_guard / evaluator);
- расширяться под каждый новый частный случай через regex по
  всему тексту вакансии (это именно та практика, которая уже
  ломала _strip_confirmed_facts_from_missing()).

Расширять этот модуль следует ТОЛЬКО добавлением новых записей в
SKILL_ALIASES с явным canonical-именем из profile_facts.json —
никогда добавлением generic substring-правил.
"""

from __future__ import annotations

STATUS_CONFIRMED_PRACTICAL = "confirmed_practical"
STATUS_CONFIRMED_EDUCATIONAL = "confirmed_educational"
STATUS_FAMILIAR = "confirmed_familiar"
STATUS_NOT_CONFIRMED = "not_confirmed"
STATUS_UNKNOWN_SKILL = "unknown_skill"  # синонима в словаре нет вообще

# canonical_skill_key -> список синонимов/форм, которые может
# вернуть requirements_analyzer. Ключи должны совпадать с ключами
# profile_facts["skills"]. Добавлять новые записи можно и нужно —
# но каждая запись это конкретное, проверяемое соответствие "строка
# из вакансии = этот факт в PROFILE", а не общее правило.
SKILL_ALIASES: dict[str, list[str]] = {
    "manual_qa": [
        "manual qa", "мануальное тестирование", "ручное тестирование",
        "тестирование по", "тестирование программного обеспечения",
        "software testing", "qa",
    ],
    "test_design": [
        "теория тестирования", "test design", "тест-дизайн",
        "техники тест-дизайна", "классы эквивалентности",
        "граничные значения", "таблицы решений",
    ],
    "test_documentation": [
        "тест-кейсы", "test cases", "чек-листы", "checklists",
        "баг-репорты", "bug reports", "тестовая документация",
        "test plan", "тест-план",
    ],
    "postman": ["postman"],
    "api": ["api", "работа с api"],
    "http": ["http", "http-протокол"],
    "rest_api": ["rest api", "rest", "restful api"],
    "json": ["json"],
    "sql": ["sql"],
    "postgresql": ["postgresql", "postgres"],
    "devtools": ["devtools", "browser devtools", "инструменты разработчика"],
    "jira": ["jira"],
    "testit": ["testit", "test it"],
    "computer_networks": ["компьютерные сети", "networking", "сети"],
    "windows": ["windows"],
    "linux": ["linux"],
    "docker": ["docker"],
    "virtualization": ["виртуализация", "virtualization"],
    "nodejs": ["node.js", "nodejs", "node"],
    "python": ["python"],
    "qa_automation": [
        "qa automation", "автоматизация тестирования",
        "test automation",
    ],
    "cicd": ["ci/cd", "cicd", "continuous integration"],
    "jenkins": ["jenkins"],
    "n8n": ["n8n"],
    "react": ["react", "react.js"],
    "photoshop": ["photoshop"],
    # Явно НЕ поддерживаемые синонимами навыки (селениум,
    # плейврайт, ts/js, k8s и т.д.) намеренно отсутствуют в этом
    # словаре: они есть в explicitly_not_confirmed profile_facts,
    # и должны попадать в STATUS_NOT_CONFIRMED, а не угадываться.
}

_LEVEL_TO_STATUS = {
    "familiar": STATUS_FAMILIAR,
}


def _normalize(text: str) -> str:
    return text.strip().lower()


def _build_alias_index() -> dict[str, str]:
    """alias (нормализованный) -> canonical_skill_key"""
    index: dict[str, str] = {}
    for canonical, aliases in SKILL_ALIASES.items():
        index[canonical] = canonical
        for alias in aliases:
            index[_normalize(alias)] = canonical
    return index


_ALIAS_INDEX = _build_alias_index()


def _match_skill_fact(skill_text: str, profile_skills: dict) -> dict:
    canonical = _ALIAS_INDEX.get(_normalize(skill_text))

    if canonical is None:
        return {
            "requirement": skill_text,
            "canonical_key": None,
            "status": STATUS_UNKNOWN_SKILL,
            "note": (
                "Нет соответствия в SKILL_ALIASES — это НЕ значит, "
                "что навыка нет у кандидата, значит только то, что "
                "автоматическое сопоставление невозможно. Требует "
                "решения evaluator/пользователя, не считать "
                "автоматически отсутствующим фактом."
            ),
        }

    fact = profile_skills.get(canonical)

    if fact is None:
        return {
            "requirement": skill_text,
            "canonical_key": canonical,
            "status": STATUS_NOT_CONFIRMED,
            "note": f"'{canonical}' отсутствует в profile_facts.skills.",
        }

    level = str(fact.get("level", "")).lower()
    practice = str(fact.get("practice", "")).lower()
    commercial = fact.get(
        "commercial_experience",
        fact.get("professional_experience"),
    )

    if commercial is True:
        status = STATUS_CONFIRMED_PRACTICAL
    elif level in _LEVEL_TO_STATUS:
        status = _LEVEL_TO_STATUS[level]
    elif practice in {"educational_practical", "practical_personal_use",
                       "practical_personal_educational", "practical_user"}:
        status = STATUS_CONFIRMED_PRACTICAL
    elif practice in {"educational", "learning"} or "basic" in level or "beginner" in level:
        status = STATUS_CONFIRMED_EDUCATIONAL
    else:
        status = STATUS_CONFIRMED_EDUCATIONAL

    return {
        "requirement": skill_text,
        "canonical_key": canonical,
        "status": status,
        "level": fact.get("level"),
        "practice": fact.get("practice"),
        "commercial_experience": commercial,
    }


def _match_education(education_req: dict, profile_education: dict) -> dict:
    requirement = education_req.get("requirement")
    importance = education_req.get("importance", "unknown")

    if not requirement or importance == "unknown":
        return {
            "status": "not_applicable",
            "note": "Требование к образованию в вакансии не выявлено.",
        }

    req_lower = _normalize(requirement)

    wants_higher = "высш" in req_lower
    wants_vocational = (
        "среднее специальн" in req_lower
        or "среднее проф" in req_lower
        or "ссуз" in req_lower
    )
    accepts_in_progress = any(
        kw in req_lower
        for kw in ("неоконч", "студент", "учусь", "обучаю", "без опыта")
    )

    candidate_completed_higher = bool(
        profile_education.get("completed_higher_education")
    )
    candidate_status = profile_education.get("status")
    candidate_level = profile_education.get("level")

    if candidate_completed_higher:
        return {
            "status": "confirmed",
            "note": "У кандидата есть законченное высшее образование.",
        }

    if candidate_status == "currently_studying" and candidate_level == "secondary_vocational_education":
        if accepts_in_progress:
            return {
                "status": "confirmed",
                "note": (
                    "Вакансия явно допускает незаконченное/студенческий "
                    "статус — учёба на ССУЗе (курс 1) удовлетворяет "
                    "требованию."
                ),
            }

        if (wants_higher or wants_vocational) and importance == "required":
            return {
                "status": "not_confirmed",
                "note": (
                    "Требуется ЗАКОНЧЕННОЕ высшее или среднее специальное "
                    "образование. У кандидата обучение по ССУЗ-специальности "
                    "не завершено (курс 1) — формально требование не "
                    "выполнено, даже если направление совпадает."
                ),
            }

        if importance == "preferred":
            return {
                "status": "partial",
                "note": (
                    "Образование указано как пожелание, а не жёсткое "
                    "требование; кандидат учится по релевантной "
                    "специальности, но диплом не завершён."
                ),
            }

    return {
        "status": "unknown",
        "note": "Недостаточно данных для автоматического сопоставления.",
    }


def _match_experience(experience_req: dict, profile: dict) -> dict:
    years_min = experience_req.get("years_min")
    importance = experience_req.get("importance", "unknown")
    commercial_qa = profile.get("professional_profile", {}).get(
        "commercial_qa_experience"
    )

    if years_min is None or importance == "unknown":
        return {
            "status": "not_applicable",
            "note": "Требование к опыту в вакансии не выявлено чётко.",
        }

    if commercial_qa is False:
        if importance == "required" and years_min and years_min > 0:
            return {
                "status": "not_confirmed",
                "note": (
                    f"Требуется коммерческий опыт от {years_min} лет "
                    "(required). У кандидата коммерческого QA-опыта нет "
                    "(profile_facts.commercial_qa_experience = false)."
                ),
            }

        if importance == "preferred":
            return {
                "status": "partial",
                "note": (
                    "Опыт указан как пожелание (preferred), не жёсткий "
                    "фильтр. Коммерческого опыта у кандидата нет, но это "
                    "не должно автоматически блокировать вакансию."
                ),
            }

    return {
        "status": "unknown",
        "note": "Недостаточно данных для автоматического сопоставления.",
    }


def match_requirements_to_profile(
    requirements: dict,
    profile_facts: dict,
) -> dict:
    """
    requirements — результат requirements_analyzer.analyze_requirements()
    profile_facts — распарсенный profile_facts.json

    Возвращает готовую для evaluator структуру: по каждому навыку —
    статус подтверждения, плюс отдельно образование и опыт. Никакого
    текста вакансии сюда заново не подаётся — evaluator должен
    рассматривать только то, что здесь помечено как unknown/partial,
    а не перечитывать вакансию целиком.
    """
    profile_skills = profile_facts.get("skills", {})
    profile_education = profile_facts.get("education", {})

    required_matches = [
        _match_skill_fact(s, profile_skills)
        for s in requirements.get("required_skills", [])
    ]
    preferred_matches = [
        _match_skill_fact(s, profile_skills)
        for s in requirements.get("preferred_skills", [])
    ]

    education_match = _match_education(
        requirements.get("education", {}),
        profile_education,
    )
    experience_match = _match_experience(
        requirements.get("experience", {}),
        profile_facts,
    )

    confirmed_statuses = {
        STATUS_CONFIRMED_PRACTICAL,
        STATUS_CONFIRMED_EDUCATIONAL,
        STATUS_FAMILIAR,
    }

    missing_required = [
        m for m in required_matches
        if m["status"] in (STATUS_NOT_CONFIRMED, STATUS_UNKNOWN_SKILL)
    ]
    confirmed_required = [
        m for m in required_matches if m["status"] in confirmed_statuses
    ]

    return {
        "required_skills": required_matches,
        "preferred_skills": preferred_matches,
        "education": education_match,
        "experience": experience_match,
        "summary": {
            "confirmed_required": [m["requirement"] for m in confirmed_required],
            "missing_required": [m["requirement"] for m in missing_required],
            "unknown_required": [
                m["requirement"] for m in required_matches
                if m["status"] == STATUS_UNKNOWN_SKILL
            ],
        },
    }