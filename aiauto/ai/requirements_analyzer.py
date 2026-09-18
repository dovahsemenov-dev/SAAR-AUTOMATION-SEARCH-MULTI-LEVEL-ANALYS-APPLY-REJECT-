import re

from ai.ollama_client import ask_json


VALID_SENIORITY = {
    "intern",
    "junior",
    "middle",
    "senior",
    "lead",
    "unknown",
}

VALID_IMPORTANCE = {
    "required",
    "preferred",
    "unknown",
}

_CJK_PATTERN = re.compile(
    r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]"
)

_COMPOUND_SKILL_SEPARATORS = re.compile(
    r"\s*[/,]\s*|\s+(?:или|и)\s+"
)

_MAX_SPLIT_FRAGMENT_LENGTH = 40
_MIN_GROUNDING_WORD_LENGTH = 3

_GROUNDING_WORD_PATTERN = re.compile(
    r"[a-zA-Zа-яА-ЯёЁ0-9+#.]+"
)


# ============================================================
# ДЕТЕКТОР ЯВНО ОБЯЗАТЕЛЬНОГО ОПЫТА
# ============================================================

_MANDATORY_EXPERIENCE_PATTERNS = (
    # Опыт от N лет / года
    re.compile(
        r"""
        (?P<full>
            (?:требуется|нужен|необходим|обязателен|обязательно|"
            требуется\s+наличие|"
            кандидаты\s+должны\s+иметь|"
            иметь|"
            наличие)
            [^.\n]{0,120}?
            (?P<years>\d+(?:[.,]\d+)?)
            \s*
            (?:года|год|лет)
            (?:\s+опыта|\s+коммерческого\s+опыта|\s+опыт[а]?)?
        )
        """,
        re.IGNORECASE | re.VERBOSE,
    ),
    re.compile(
        r"""
        (?P<full>
            опыт
            [^.\n]{0,100}?
            (?:от\s+)?
            (?P<years>\d+(?:[.,]\d+)?)
            \s*
            (?:года|год|лет)
        )
        """,
        re.IGNORECASE | re.VERBOSE,
    ),

    # "опыт работы от 2 лет"
    re.compile(
        r"""
        (?P<full>
            опыт\s+(?:работы|работы\s+в\s+qa|работы\s+тестировщиком)?
            [^.\n]{0,100}?
            от\s+
            (?P<years>\d+(?:[.,]\d+)?)
            \s*
            (?:года|год|лет)
        )
        """,
        re.IGNORECASE | re.VERBOSE,
    ),

    # Опыт в месяцах
    re.compile(
        r"""
        (?P<full>
            (?:требуется|нужен|необходим|обязателен|обязательно)?
            [^.\n]{0,100}?
            (?:опыт|опыта)
            [^.\n]{0,80}?
            (?:от\s+)?
            (?P<months>\d+)
            \s*
            (?:месяц|месяца|месяцев|мес\.?)
        )
        """,
        re.IGNORECASE | re.VERBOSE,
    ),
    # "стаж работы от 6 месяцев" — прошлый опыт работы.
    re.compile(
        r"""
        (?P<full>
            стаж\s+работы
            [^.\n]{0,80}?
            (?:от\s+)?
            (?P<months>\d+)
            \s*
            (?:месяц|месяца|месяцев|мес\.?)
        )
        """,
        re.IGNORECASE | re.VERBOSE,
    ),
)


_SOFT_EXPERIENCE_MARKERS = (
    "желател",
    "желательн",
    "будет преимуществом",
    "будет плюсом",
    "будет большим плюсом",
    "плюсом",
    "преимуществом",
    "рассматриваем без опыта",
    "рассматриваем кандидатов без опыта",
    "готовы обучить",
    "готовы рассмотреть без опыта",
    "без опыта можно",
    "опыт не обязателен",
    "опыт не требуется",
    "опыт не нужен",
    "можно без опыта",
)


_HARD_EXPERIENCE_MARKERS = (
    "обязател",
    "обязательно",
    "требуется",
    "требуем",
    "необходим",
    "необходимо",
    "кандидаты должны",
    "без опыта не рассматриваем",
    "без опыта не рассматриваются",
    "кандидатов без опыта не рассматриваем",
    "кандидаты без опыта не рассматриваются",
    "не рассматриваем без опыта",
    "не рассматриваются без опыта",
)


_INTERNSHIP_DURATION_MARKERS = (
    "стажировк", "стажерск", "trainee", "internship",
)
_PROGRAM_DURATION_MARKERS = (
    "длительностью", "длится", "рассчитан", "рассчитана",
    "продолжительностью", "на период", "в течение",
    "месяцев обучения", "месяца обучения", "месяц обучения",
)
_PRIOR_EXPERIENCE_MARKERS = (
    "опыт", "опыт работы", "коммерческий опыт", "коммерческого опыта",
    "профессиональный опыт", "профессионального опыта",
    "опыт в qa", "опыт в тестирован", "стаж работы",
    "работал", "работала", "работали", "занимал должност",
    "занимала должност", "на позиции", "в должности",
)

def _is_internship_or_program_duration(text: str) -> bool:
    low = str(text or "").lower().replace("ё", "е")
    if not any(marker in low for marker in _INTERNSHIP_DURATION_MARKERS):
        return False
    if any(marker in low for marker in _PROGRAM_DURATION_MARKERS):
        return True
    return bool(re.search(
        r"стажиров\w*[^.\n]{0,100}\b\d+(?:[.,]\d+)?\s*(?:год|года|лет|месяц|месяца|месяцев|мес\.?)",
        low,
    ))

def _looks_like_prior_experience(text: str) -> bool:
    low = str(text or "").lower().replace("ё", "е")
    if _is_internship_or_program_duration(low):
        return False
    return any(marker in low for marker in _PRIOR_EXPERIENCE_MARKERS)

def _parse_hh_experience_years(raw_value) -> int | float | None:
    text = str(raw_value or "").strip().lower().replace("ё", "е")
    if not text:
        return None
    if any(marker in text for marker in (
        "не требуется", "без опыта", "нет опыта",
        "опыт не нужен", "опыт не требуется",
    )):
        return 0
    numbers = re.findall(r"\d+(?:[.,]\d+)?", text)
    if not numbers:
        return None
    try:
        value = float(numbers[0].replace(",", "."))
    except (TypeError, ValueError):
        return None
    return int(value) if value.is_integer() else value


def _normalize_number(value: str):
    try:
        number = float(
            str(value)
            .replace(",", ".")
            .strip()
        )
    except (TypeError, ValueError):
        return None

    if number < 0:
        return None

    if number.is_integer():
        return int(number)

    return number


def _has_soft_experience_marker(text: str) -> bool:
    lowered = text.lower()

    return any(
        marker in lowered
        for marker in _SOFT_EXPERIENCE_MARKERS
    )


def _has_hard_experience_marker(text: str) -> bool:
    lowered = text.lower()

    return any(
        marker in lowered
        for marker in _HARD_EXPERIENCE_MARKERS
    )


def _is_explicit_mandatory_context(
    text: str,
    start: int,
    end: int,
) -> bool:
    """
    Проверяет контекст вокруг найденного требования.

    Важный принцип:
    "опыт от 2 лет" сам по себе является сильным требованием,
    но если рядом явно сказано "желательно", "будет плюсом",
    "рассматриваем без опыта" — это не hard requirement.
    """

    left = max(0, start - 180)
    right = min(len(text), end + 180)

    context = text[left:right].lower()

    if _has_soft_experience_marker(context):
        return False

    if _has_hard_experience_marker(context):
        return True

    # Самостоятельная конструкция
    # "опыт работы от 2 лет" в блоке требований
    # считается обязательным требованием.
    return True


def _detect_explicit_mandatory_experience(
    description: str,
):
    """
    Детерминированно ищет в описании вакансии явное
    обязательное требование к опыту.

    Возвращает:

        mandatory_experience: bool
        mandatory_years: int | float | None
        mandatory_evidence: str

    Важные правила:

    - "опыт от 2 лет" -> mandatory
    - "опыт работы тестировщиком от 2 лет" -> mandatory
    - "опыт работы в QA от 1 года" -> mandatory
    - "опыт от 3 месяцев" -> 0.25 года
    - "опыт будет преимуществом" -> НЕ mandatory
    - "опыт желателен" -> НЕ mandatory
    - "рассматриваем без опыта" -> НЕ mandatory
    - "готовы обучить" -> НЕ mandatory
    """

    description = str(
        description or ""
    ).strip()

    if not description:
        return False, None, ""

    best_match = None
    best_years = None

    for pattern in _MANDATORY_EXPERIENCE_PATTERNS:
        for match in pattern.finditer(description):
            full_text = match.group("full").strip()

            if not full_text:
                continue

            if _is_internship_or_program_duration(full_text):
                continue

            if match.groupdict().get("months") is not None and not _looks_like_prior_experience(full_text):
                continue

            start = match.start()
            end = match.end()

            if not _is_explicit_mandatory_context(
                description,
                start,
                end,
            ):
                continue

            months = match.groupdict().get(
                "months"
            )

            years = match.groupdict().get(
                "years"
            )

            if months is not None:
                try:
                    mandatory_years = float(months) / 12.0
                except (TypeError, ValueError):
                    continue

                if mandatory_years.is_integer():
                    mandatory_years = int(
                        mandatory_years
                    )
            elif years is not None:
                mandatory_years = _normalize_number(
                    years
                )
            else:
                continue

            if mandatory_years is None:
                continue

            best_match = full_text
            best_years = mandatory_years

            # Берём первое реальное hard requirement.
            break

        if best_match:
            break

    if best_match:
        return (
            True,
            best_years,
            best_match,
        )

    # Отдельное жёсткое правило:
    # "кандидаты без опыта не рассматриваются".
    lowered = description.lower()

    no_experience_patterns = (
        r"без\s+опыта\s+не\s+рассматрива",
        r"кандидат(?:ы|ов)?\s+без\s+опыта\s+не\s+рассматрива",
        r"не\s+рассматрива[ею]\w*\s+кандидат(?:ов)?\s+без\s+опыта",
    )

    for pattern in no_experience_patterns:
        match = re.search(
            pattern,
            lowered,
            re.IGNORECASE,
        )

        if match:
            evidence = description[
                max(0, match.start() - 80):
                min(len(description), match.end() + 80)
            ].strip()

            return (
                True,
                0,
                evidence,
            )

    return False, None, ""


# ============================================================
# PROMPT
# ============================================================

def build_prompt(
    vacancy: dict,
) -> str:
    """
    Анализирует исключительно требования вакансии.

    PROFILE кандидата сюда намеренно НЕ передаётся.
    Модель не должна решать, подходит кандидат или нет.
    """

    description = (
        vacancy.get("description")
        or ""
    )

    hh_skills = (
        vacancy.get("skills")
        or []
    )

    return f"""
Ты — модуль структурированного анализа требований вакансии.

У тебя НЕТ информации о кандидате.

ЗАПРЕЩЕНО:
- решать APPLY / REVIEW / REJECT;
- предполагать навыки кандидата;
- анализировать географическую совместимость;
- анализировать предпочтения кандидата.

Твоя единственная задача:
извлечь из вакансии фактические требования работодателя.

============================================================
1. SENIORITY
============================================================

Определи реальный уровень вакансии:

intern
junior
middle
senior
lead
unknown

Учитывай не только название, но и содержание.

Например:
"стажёр", "trainee", "без опыта" -> intern/junior.

Senior/Lead в названии — сильный сигнал
соответствующего уровня.

============================================================
2. ОПЫТ
============================================================

Определи минимально требуемый коммерческий опыт.

years_min:
число (может быть дробным) или null.

importance:
required
preferred
unknown

КРИТИЧЕСКИ ВАЖНО — ОПЫТ В МЕСЯЦАХ:

Если вакансия указывает опыт в МЕСЯЦАХ, а не в годах
(например: "опыт от 3 месяцев", "от 6 месяцев коммерческого
опыта"), НЕ теряй это требование в null и НЕ округляй до 0.
Переведи месяцы в годы дробным числом:

years_min = месяцы / 12

Пример:
"Имеете коммерческий опыт в написании автотестов от 3х месяцев"

Правильное извлечение:

{{
  "years_min": 0.25,
  "importance": "required",
  "evidence": "Имеете коммерческий опыт в написании автотестов от 3х месяцев"
}}

КРИТИЧЕСКИ ВАЖНО — ГИБКОСТЬ:

Если вакансия пишет:
"3 года — ориентир, а не строгий фильтр"
или
"готовы рассматривать кандидатов с меньшим опытом",

то years_min может оставаться 3,
НО importance должен быть preferred.

Если написано:
"опыт от 1 года обязателен"
или
"кандидаты без опыта не рассматриваются",

importance = required.

Не превращай пожелание в обязательное условие.

КРИТИЧЕСКОЕ ПРАВИЛО ПРО СТАЖИРОВКУ/ОБУЧЕНИЕ:
Срок будущей стажировки, обучения или программы НЕ является
предыдущим коммерческим опытом кандидата. Фразы вроде
"стажировка длительностью 6-12 месяцев", "стажировка рассчитана
на 6 месяцев", "программа длится 3 месяца" должны давать
years_min=null и importance=unknown.

Если HH в поле "Опыт" указывает "не требуется", это сильный
источник истины. Переопределить его можно только однозначной
фразой именно о ПРЕДЫДУЩЕМ опыте работы: "опыт работы от 1 года",
"коммерческий опыт от 6 месяцев", "без опыта не рассматриваем".

============================================================
3. ОБРАЗОВАНИЕ
============================================================

Извлеки требование к образованию.

requirement:
краткая формулировка или null.

importance:
required
preferred
unknown

Если образование находится в основном списке
обязательных требований без слов
"желательно", "будет плюсом",
обычно importance = required.

КРИТИЧЕСКИ ВАЖНО — АЛЬТЕРНАТИВНЫЕ ФОРМУЛИРОВКИ:

Если написано:

"Имеете законченное высшее или среднее специальное образование."

верни:

{{
  "requirement": "законченное высшее или среднее специальное образование",
  "importance": "required",
  "evidence": "Имеете законченное высшее или среднее специальное образование."
}}

Если требования к образованию действительно нет:
requirement = null,
importance = unknown.

============================================================
4. ЯЗЫКИ
============================================================

Извлеки иностранные языки.

Для каждого языка верни объект:

{{
  "language": "English",
  "level": "B1",
  "importance": "required"
}}

Языки складывай ТОЛЬКО в поле "languages".

НЕЛЬЗЯ помещать языки в required_skills
или preferred_skills.

============================================================
5. НАВЫКИ
============================================================

required_skills и preferred_skills —
простые строки.

Правильно:

"required_skills": ["SQL", "Git", "Postman"]

Не включай навыки, которых нет в тексте вакансии.

Не подставляй типичный стек профессии самостоятельно.

Если конкретная технология нигде не упомянута,
не добавляй её.

Не включай в required_skills то,
что прямо помечено как:
"будет плюсом",
"желательно",
"приветствуется".

============================================================
6. ГИБКОСТЬ
============================================================

Определи, говорит ли работодатель прямо,
что требования являются гибкими.

flexibility:
true / false

flexibility_reason:
конкретная короткая цитата/пересказ причины.

Если flexibility = true и это касается именно опыта,
experience.importance должен быть "preferred".

============================================================
7. ЖЁСТКИЕ БЛОКЕРЫ
============================================================

hard_blockers — список требований,
где работодатель прямо сообщает,
что без этого кандидата не рассматривает.

Если таких формулировок нет:
пустой массив.

============================================================
ДАННЫЕ HH
============================================================

Название:
{vacancy.get("title", "")}

Опыт HH:
{vacancy.get("experience", "")}

Ключевые навыки HH:
{", ".join(hh_skills) if hh_skills else "Не указаны"}

============================================================
ОПИСАНИЕ ВАКАНСИИ
============================================================

{description[:8000]}

============================================================
ФОРМАТ ОТВЕТА
============================================================

Верни ТОЛЬКО JSON.

{{
  "seniority": "junior",
  "experience": {{
    "years_min": null,
    "importance": "unknown",
    "evidence": ""
  }},
  "education": {{
    "requirement": null,
    "importance": "unknown",
    "evidence": ""
  }},
  "languages": [],
  "required_skills": [],
  "preferred_skills": [],
  "flexibility": false,
  "flexibility_reason": "",
  "hard_blockers": []
}}
""".strip()


# ============================================================
# NORMALIZATION
# ============================================================

def _normalize_importance(
    value,
) -> str:
    normalized = str(
        value or "unknown"
    ).strip().lower()

    if normalized not in VALID_IMPORTANCE:
        return "unknown"

    return normalized


def _contains_disallowed_script(
    text: str,
) -> bool:
    return bool(
        _CJK_PATTERN.search(text)
    )


def _split_compound_skill(
    text: str,
) -> list[str]:
    text = str(
        text or ""
    ).strip()

    if not text:
        return []

    # Не дробим содержимое скобок:
    # "сетевые технологии (HTTP, HTTPS, REST API)"
    # остаются одним требованием.
    if "(" in text and ")" in text:
        return [text]

    parts = _COMPOUND_SKILL_SEPARATORS.split(
        text
    )

    if len(parts) <= 1:
        return [text]

    cleaned = []

    for part in parts:
        part = part.strip()

        if not part:
            continue

        if len(part) > _MAX_SPLIT_FRAGMENT_LENGTH:
            return [text]

        if part not in cleaned:
            cleaned.append(part)

    return cleaned or [text]


def _flatten_skill_item(
    item,
) -> list[str]:
    if isinstance(item, str):
        text = item.strip()

        if (
            not text
            or _contains_disallowed_script(text)
        ):
            return []

        return _split_compound_skill(
            text
        )

    if isinstance(item, dict):
        for key in (
            "skill",
            "name",
            "title",
            "language",
        ):
            value = item.get(key)

            if (
                isinstance(value, str)
                and value.strip()
            ):
                text = value.strip()

                if _contains_disallowed_script(
                    text
                ):
                    return []

                return _split_compound_skill(
                    text
                )

        return []

    text = str(
        item
    ).strip()

    if (
        not text
        or _contains_disallowed_script(text)
    ):
        return []

    return _split_compound_skill(
        text
    )


def _is_grounded_in_vacancy(
    skill: str,
    hh_skills: list[str],
    description: str,
) -> bool:
    haystack = (
        " ".join(
            str(x)
            for x in hh_skills
        )
        + " "
        + str(description or "")
    ).lower()

    words = [
        word
        for word in _GROUNDING_WORD_PATTERN.findall(
            skill
        )
        if len(word) >= _MIN_GROUNDING_WORD_LENGTH
    ]

    if not words:
        return True

    return any(
        word.lower() in haystack
        for word in words
    )


def _normalize_skill_list(
    value,
    hh_skills: list[str],
    description: str,
) -> list[str]:
    if not isinstance(
        value,
        list,
    ):
        return []

    result = []

    for item in value:
        for flattened in _flatten_skill_item(
            item
        ):
            if (
                not flattened
                or flattened in result
            ):
                continue

            if not _is_grounded_in_vacancy(
                flattened,
                hh_skills,
                description,
            ):
                continue

            result.append(
                flattened
            )

    return result


def _normalize_string_list(
    value,
) -> list[str]:
    if not isinstance(
        value,
        list,
    ):
        return []

    result = []

    for item in value:
        text = str(
            item
        ).strip()

        if (
            text
            and text not in result
        ):
            result.append(text)

    return result


# ============================================================
# MAIN ANALYZER
# ============================================================

def analyze_requirements(
    ollama_url: str,
    model_name: str,
    vacancy: dict,
) -> dict:

    # --------------------------------------------------------
    # ВАЖНО:
    # description определяется ЗДЕСЬ ДО ЛЮБОГО
    # использования в analyze_requirements().
    # --------------------------------------------------------

    description = (
        vacancy.get("description")
        or ""
    )

    hh_skills = (
        vacancy.get("skills")
        or []
    )

    # --------------------------------------------------------
    # Сначала получаем ответ Qwen.
    # --------------------------------------------------------

    raw = ask_json(
        ollama_url,
        model_name,
        build_prompt(vacancy),
    )

    if not isinstance(
        raw,
        dict,
    ):
        raise RuntimeError(
            "Requirements analyzer вернул "
            "некорректный JSON-объект."
        )

    # --------------------------------------------------------
    # SENIORITY
    # --------------------------------------------------------

    seniority = str(
        raw.get(
            "seniority",
            "unknown",
        )
    ).strip().lower()

    if seniority not in VALID_SENIORITY:
        seniority = "unknown"

    # --------------------------------------------------------
    # EXPERIENCE
    # --------------------------------------------------------

    raw_experience = raw.get(
        "experience",
        {},
    )

    if not isinstance(
        raw_experience,
        dict,
    ):
        raw_experience = {}

    years_min = raw_experience.get(
        "years_min"
    )

    if years_min is not None:
        try:
            years_min = float(
                years_min
            )

            if years_min < 0:
                years_min = None

            elif years_min == int(
                years_min
            ):
                years_min = int(
                    years_min
                )

        except (
            TypeError,
            ValueError,
        ):
            years_min = None

    experience_importance = (
        _normalize_importance(
            raw_experience.get(
                "importance"
            )
        )
    )

    experience_evidence = str(
        raw_experience.get(
            "evidence",
            "",
        )
    ).strip()

    experience = {
        "years_min": years_min,
        "importance": experience_importance,
        "evidence": experience_evidence,
    }

    # --------------------------------------------------------
    # ДЕТЕРМИНИРОВАННАЯ ПРОВЕРКА ОПЫТА
    #
    # Здесь используется УЖЕ определённый description.
    # --------------------------------------------------------

    (
        mandatory_experience,
        mandatory_years,
        mandatory_evidence,
    ) = _detect_explicit_mandatory_experience(
        description
    )

    if mandatory_experience:
        experience["years_min"] = mandatory_years
        experience["importance"] = "required"
        if mandatory_evidence:
            experience["evidence"] = mandatory_evidence
    else:
        hh_experience_years = _parse_hh_experience_years(
            vacancy.get("experience", "")
        )
        if hh_experience_years == 0:
            experience["years_min"] = 0
            experience["importance"] = "unknown"
            experience["evidence"] = (
                "HH: опыт не требуется; отдельного обязательного "
                "требования к предыдущему опыту работы не найдено."
            )
        elif _is_internship_or_program_duration(experience_evidence):
            experience["years_min"] = None
            experience["importance"] = "unknown"
            experience["evidence"] = (
                "Срок стажировки/обучения не считается предыдущим "
                "коммерческим опытом."
            )

    # --------------------------------------------------------
    # EDUCATION
    # --------------------------------------------------------

    raw_education = raw.get(
        "education",
        {},
    )

    if not isinstance(
        raw_education,
        dict,
    ):
        raw_education = {}

    requirement = raw_education.get(
        "requirement"
    )

    if requirement is not None:
        requirement = str(
            requirement
        ).strip()

        if not requirement:
            requirement = None

    education = {
        "requirement": requirement,
        "importance": _normalize_importance(
            raw_education.get(
                "importance"
            )
        ),
        "evidence": str(
            raw_education.get(
                "evidence",
                "",
            )
        ).strip(),
    }

    # --------------------------------------------------------
    # LANGUAGES
    # --------------------------------------------------------

    raw_languages = raw.get(
        "languages",
        [],
    )

    languages = []

    if isinstance(
        raw_languages,
        list,
    ):
        for item in raw_languages:

            if not isinstance(
                item,
                dict,
            ):
                continue

            language = str(
                item.get(
                    "language",
                    "",
                )
            ).strip()

            if not language:
                continue

            languages.append(
                {
                    "language": language,
                    "level": str(
                        item.get(
                            "level",
                            "",
                        )
                    ).strip(),
                    "importance":
                        _normalize_importance(
                            item.get(
                                "importance"
                            )
                        ),
                }
            )

    # --------------------------------------------------------
    # FLEXIBILITY
    # --------------------------------------------------------

    flexibility_raw = raw.get(
        "flexibility",
        False,
    )

    if isinstance(
        flexibility_raw,
        bool,
    ):
        flexibility = flexibility_raw

    else:
        flexibility = (
            str(
                flexibility_raw
            )
            .strip()
            .lower()
            in {
                "true",
                "1",
                "yes",
                "да",
            }
        )

    # Если работодатель явно говорит,
    # что опыт — гибкое пожелание, он не должен
    # превращаться в hard requirement только
    # из-за ошибки модели.
    #
    # Но если наш детерминированный детектор уже нашёл
    # ЯВНЫЙ обязательный опыт — он имеет приоритет.
    if (
        flexibility
        and experience["importance"] == "required"
        and not mandatory_experience
    ):
        experience["importance"] = "preferred"

    # --------------------------------------------------------
    # SKILLS
    # --------------------------------------------------------

    required_skills = _normalize_skill_list(
        raw.get(
            "required_skills",
            [],
        ),
        hh_skills,
        description,
    )

    preferred_skills = _normalize_skill_list(
        raw.get(
            "preferred_skills",
            [],
        ),
        hh_skills,
        description,
    )

    # --------------------------------------------------------
    # FLEXIBILITY REASON
    # --------------------------------------------------------

    flexibility_reason = str(
        raw.get(
            "flexibility_reason",
            "",
        )
    ).strip()

    # --------------------------------------------------------
    # HARD BLOCKERS
    # --------------------------------------------------------

    hard_blockers = _normalize_string_list(
        raw.get(
            "hard_blockers",
            [],
        )
    )
    hard_blockers = [
        item for item in hard_blockers
        if not _is_internship_or_program_duration(item)
    ]

    # --------------------------------------------------------
    # FINAL RESULT
    # --------------------------------------------------------

    return {
        "seniority": seniority,
        "experience": experience,
        "education": education,
        "languages": languages,
        "required_skills": required_skills,
        "preferred_skills": preferred_skills,
        "flexibility": flexibility,
        "flexibility_reason": flexibility_reason,
        "hard_blockers": hard_blockers,
        "mandatory_experience": mandatory_experience,
        "mandatory_experience_evidence": mandatory_evidence,
    }

