import json

from ai.ollama_client import ask_json
from ai.profile_facts_matcher import match_requirements_to_profile


VALID_DECISIONS = {
    "APPLY",
    "REVIEW",
    "REJECT",
}

PLACEHOLDER_PHRASES = {
    "пример причины",
    "пример действительно неподтверждённого требования",
    "пример краткого вывода",
    "конкретная причина на основе этой вакансии",
    "конкретное недостающее требование этой вакансии",
    "конкретный вывод по этой вакансии",
}

FIRST_PERSON_MARKERS = (
    " я ",
    " мне ",
    " мой ",
    " моя ",
    " мои ",
    " моему ",
    " могу ",
)

# Ключевые слова навыков из profile_facts.json, для которых
# уже неоднократно наблюдалась галлюцинация "отсутствует",
# хотя в profile_facts факт подтверждён хотя бы на базовом
# уровне. Ключ словаря — имя поля в profile_facts["skills"],
# значение — маркеры, по которым ищем упоминание этого навыка
# в тексте missing/reasons.
#
# ВАЖНО: это ВТОРАЯ, подстраховочная линия защиты — на случай
# свободного текста в missing, который не совпадает дословно
# ни с одним required_skill из REQUIREMENTS. Первая и основная
# линия защиты — FACT_MATCH (см. ai/profile_facts_matcher.py),
# который сопоставляет требования с профилем один раз,
# программно, ДО того как evaluator вообще начинает рассуждать.
# Расширять этот словарь новыми частными случаями не нужно —
# вместо этого добавляй synонимы в SKILL_ALIASES матчера.
CONFIRMED_SKILL_MARKERS = {
    "test_design": ("теори", "test design", "тест-дизайн"),
    "manual_qa": (
        "мануальн",
        "manual qa",
        "ручное тестирован",
        "ручного тестирован",
    ),
    "sql": ("sql",),
    "postman": ("postman",),
    "api": (" api", "api-", "апи"),
    "rest_api": ("rest api", "rest-api", "restful"),
    "json": ("json",),
    "postgresql": ("postgresql", "postgres"),
    "devtools": ("devtools", "dev tools"),
    "jira": ("jira", "джира"),
    "testit": ("testit", "test it"),
    "test_documentation": (
        "тестовая документация",
        "тест-кейс",
        "тест-кейсы",
        "чек-лист",
        "чек-листы",
        "баг-репорт",
    ),
    "docker": ("docker", "докер"),
    "python": ("python", "питон"),
    "computer_networks": (
        "сетев",
        "сети",
        "network",
    ),
}

# Программная страховка от IndigoSoft-бага: если строка missing
# описывает ДЛИТЕЛЬНОСТЬ/УРОВЕНЬ коммерческого опыта
# ("опыт в коммерческом тестировании... от 2-3 лет"), нельзя
# вычёркивать её только потому, что внутри фразы случайно
# упомянута технология, которая подтверждена на базовом уровне.
# Такая фраза по сути про стаж, а не про сам навык.
EXPERIENCE_DURATION_MARKERS = (
    "опыт",
    "лет",
    "года",
    "год ",
    "коммерческ",
    "years",
    "commercial",
)

# Уровни, для которых при жёстких условиях применяется
# принудительное программное REJECT (см. _apply_deterministic_seniority_guard).
HARD_SENIOR_LEVELS = {
    "senior",
    "lead",
}

# Минимальное количество обязательных лет опыта, начиная с которого
# senior/lead-вакансия без признаков гибкости считается нереалистичной
# для начинающего кандидата.
HARD_SENIOR_YEARS_THRESHOLD = 4


def build_prompt(
    vacancy: dict,
    profile: str,
    preferences: str,
    profile_facts: dict,
    requirements: dict,
    fact_match: dict,
) -> str:
    profile_facts_json = json.dumps(
        profile_facts,
        ensure_ascii=False,
        indent=2,
    )

    requirements_json = json.dumps(
        requirements,
        ensure_ascii=False,
        indent=2,
    )

    fact_match_json = json.dumps(
        fact_match,
        ensure_ascii=False,
        indent=2,
    )

    description = (
        vacancy.get("description")
        or ""
    )

    return f"""
Ты — внутренний аналитический модуль системы поиска вакансий.

Ты НЕ пишешь сопроводительное письмо.
Ты НЕ говоришь от имени кандидата.

До тебя уже выполнены:
1. IT/non-IT классификация;
2. детерминированная проверка географии;
3. отдельный структурированный анализ требований вакансии;
4. программное сопоставление требований с профилем кандидата
   (FACT_MATCH ниже).

============================================================
ГЕОГРАФИЯ УЖЕ ПРОВЕРЕНА
============================================================

Эта вакансия дошла до тебя только после того,
как внешний Python-модуль признал географию допустимой
либо специально разрешил дальнейший REVIEW.

ЗАПРЕЩЕНО повторно использовать:
- город;
- страну;
- физический адрес;
- офис;
- удалёнку;
- гибрид;

как причину decision, score, reasons или missing.

Не пиши:
"Москва неудобна кандидату"
"Ташкент не подходит"
"работа требует офиса"
и подобное.

География НЕ входит в твою задачу.

============================================================
ИСТОЧНИКИ ИСТИНЫ (по приоритету)
============================================================

FACT_MATCH — САМЫЙ АВТОРИТЕТНЫЙ источник. Это уже готовый,
программно вычисленный результат сопоставления REQUIREMENTS
и PROFILE_FACTS. Он посчитан один раз, детерминированно,
без участия языковой модели.

ЗАПРЕЩЕНО пересчитывать то, что уже есть в FACT_MATCH.
ЗАПРЕЩЕНО переопределять статус "confirmed_practical",
"confirmed_educational" или "confirmed_familiar" на
"не подтверждено" — эти статусы уже означают подтверждение.
ЗАПРЕЩЕНО переопределять статус "not_confirmed" на
"подтверждено".

Единственные статусы FACT_MATCH, которые ТЕБЕ разрешено
дообдумывать текстом вакансии, — это "unknown_skill" (нет
словаря синонимов для сопоставления) и "unknown"/"partial"
(данных недостаточно для однозначного автоматического вывода).
Для них можно использовать своё суждение по тексту вакансии
и PROFILE.

PROFILE_FACTS — первичный машинный источник
подтверждённых фактов кандидата (сырые данные,
из которых посчитан FACT_MATCH).

PROFILE — подробный источник дополнительных деталей,
не покрытых structured-фактами.

REQUIREMENTS — структурированное представление
требований работодателя. Это авторитетный источник
по опыту, образованию, seniority и гибкости требований.
Не переопределяй эти поля заново на основе сырого текста
вакансии — используй именно REQUIREMENTS.

PREFERENCES — стратегия отбора возможностей.

При любом конфликте порядок доверия:
FACT_MATCH > REQUIREMENTS > PROFILE_FACTS > PROFILE > твоё
собственное впечатление от текста вакансии.

============================================================
ЗАПРЕТ НА ВЫДУМЫВАНИЕ
============================================================

Нельзя придумывать:
- коммерческий опыт;
- образование;
- диплом;
- работодателей;
- проекты;
- достижения;
- продолжительность опыта;
- иностранные языки;
- навыки;
- технологии.

Нельзя превращать:
"basic" в "professional";
"educational" в "commercial";
"familiar" в "experienced".

============================================================
ПОДТВЕРЖДЁННЫЕ НАВЫКИ — САМОЕ ВАЖНОЕ ПРАВИЛО
============================================================

Смотри FACT_MATCH.required_skills и FACT_MATCH.preferred_skills.

Для каждого элемента там уже указан статус:
- confirmed_practical / confirmed_educational / confirmed_familiar
  → навык ПОДТВЕРЖДЁН. ЗАПРЕЩЕНО писать, что он отсутствует,
  добавлять его в missing как отсутствующий, или писать
  "нет опыта с X" / "X не подтверждён".
- not_confirmed → навык действительно отсутствует в PROFILE_FACTS,
  можно писать в missing.
- unknown_skill → автоматическое сопоставление не удалось.
  Прочитай описание вакансии и PROFILE сам и реши по существу,
  но не утверждай уверенно ни подтверждение, ни отсутствие —
  формулируй как "уровень владения X не подтверждён" в
  крайнем случае, без категоричных заявлений.

Если вакансия требует БОЛЕЕ ВЫСОКИЙ уровень, чем указано в
FACT_MATCH (например, confirmed_educational, а нужен practical
commercial), можно написать разницу уровней в missing/reasons —
но нельзя писать про полное отсутствие навыка.

============================================================
ВАЖНОЕ УТОЧНЕНИЕ: ОПЫТ vs НАВЫК
============================================================

Отдельно подтверждённый базовый навык (например, "api = basic")
НЕ означает, что подтверждён многолетний коммерческий опыт
работы с этой технологией.

Если требование звучит как:
"Опыт коммерческого тестирования сложного ПО (Web, Desktop, API)
от 2-3 лет"

это требование о ДЛИТЕЛЬНОСТИ И УРОВНЕ КОММЕРЧЕСКОГО ОПЫТА,
а не про сам факт знакомства с API.

Даже если API у кандидата подтверждён на базовом уровне,
многолетний коммерческий опыт всё равно остаётся
неподтверждённым и должен фигурировать в missing.
Смотри также FACT_MATCH.experience — там уже посчитан статус
именно по длительности коммерческого опыта отдельно от
навыков.

============================================================
ОБРАЗОВАНИЕ — НЕ HARD FILTER
============================================================

Смотри FACT_MATCH.education.status:
- "confirmed" → образование подтверждено, не пиши обратное.
- "not_confirmed" → формальное требование не выполнено,
  можно отразить как несоответствие.
- "partial" → требование мягкое (preferred) и не выполнено
  полностью — не повод для REJECT.
- "unknown" / "not_applicable" → данных недостаточно или
  требования нет, не выдумывай.

Даже при FACT_MATCH.education.status = "not_confirmed" это
НЕ должно автоматически приводить к REJECT. Работодатели
иногда отступают от формальных требований. Образование
учитывается как несоответствие, может снизить score, может
привести к REVIEW, но само по себе не должно быть
единственной причиной REJECT.

============================================================
ОПЫТ И SENIORITY
============================================================

Основная цель: intern, trainee, junior, начинающий специалист.

Если REQUIREMENTS.seniority = senior или lead и
одновременно требуется 4+ года ОБЯЗАТЕЛЬНОГО коммерческого
опыта без признаков гибкости — используй REJECT. Это
сильное и однозначное несоответствие уровню кандидата,
не оставляй его в REVIEW "на всякий случай".

Если senior/middle указан, но requirements.flexibility=true,
можно использовать REVIEW.

Если experience.importance=required и требуется 3+ года
коммерческого опыта — сильная причина REJECT, если нет
явной гибкости.

Если experience.importance=preferred — не отклоняй
вакансию автоматически из-за опыта.

Если experience.years_min меньше 1 (например, 0.25 — то есть
исходно опыт был указан в месяцах, а не в годах), это очень
низкий порог входа, а не многолетний коммерческий опыт. Даже
если importance=required, такое требование НЕ равнозначно
"required 3+ года" и не должно приводить к REJECT или резкому
занижению score только из-за этого. Честно отражай в missing
отсутствие подтверждённого коммерческого опыта (это видно
и в FACT_MATCH.experience), но при выполнении остальных
требований такая вакансия — реалистичный кандидат на APPLY
или как минимум крепкий REVIEW, а не REJECT.

Если hard_blockers прямо говорят, что кандидат без опыта
не рассматривается — это сильный аргумент REJECT.

============================================================
ЯЗЫКИ
============================================================

Если обязательный язык указан, но его уровень у кандидата
неизвестен — не утверждай, что кандидат язык не знает.
Правильно: "Уровень английского не подтверждён PROFILE."
Обычно это REVIEW, если нет других критических блокеров.

============================================================
DECISION
============================================================

APPLY: реалистичная возможность для текущего уровня,
нет существенного обязательного профессионального
несоответствия.

REVIEW: вакансия потенциально интересна, но есть реальные
пробелы, формальные требования, неизвестный язык,
образование, отдельные технологии, либо умеренное
требование опыта.

REJECT: явно существенно более высокий профессиональный
уровень или обязательный коммерческий опыт, который
делает стартовую кандидатуру нереалистичной.

При сомнении между REVIEW и REJECT выбирай REVIEW,
НО если seniority senior/lead и опыт 4+ лет обязателен
без гибкости — сомнений быть не должно, это REJECT.

============================================================
SCORE
============================================================

Score вторичен.

0-39: сильное несоответствие.
40-64: сомнительно.
65-79: потенциально интересно, нужна проверка.
80-100: реалистичная возможность.

Не повышай score только потому, что профессия относится к IT.

============================================================
FACT_MATCH (авторитетный источник — см. правила выше)
============================================================
{fact_match_json}

============================================================
PROFILE_FACTS
============================================================
{profile_facts_json}

============================================================
STRUCTURED REQUIREMENTS
============================================================
{requirements_json}

============================================================
PROFILE
============================================================
{profile}

============================================================
PREFERENCES
============================================================
{preferences}

============================================================
ВАКАНСИЯ
============================================================

Название:
{vacancy.get("title", "")}

Опыт HH:
{vacancy.get("experience", "")}

Ключевые навыки HH:
{", ".join(vacancy.get("skills") or [])}

Описание:
{description[:7000]}

============================================================
ОТВЕТ
============================================================

Верни ТОЛЬКО JSON:

{{
  "decision": "REVIEW",
  "score": 60,
  "reasons": [
    "конкретная причина"
  ],
  "missing": [
    "только реально неподтверждённое требование"
  ],
  "summary": "краткий вывод"
}}

reasons и summary пиши только в третьем лице или безлично.
Не используй первое лицо.
""".strip()


def _is_placeholder(
    value: str,
) -> bool:
    return (
        value.strip().lower()
        in PLACEHOLDER_PHRASES
    )


def _contains_first_person(
    reasons: list[str],
    summary: str,
) -> bool:
    text = (
        " "
        + " ".join(reasons)
        + " "
        + summary
        + " "
    ).lower()

    return any(
        marker in text
        for marker in FIRST_PERSON_MARKERS
    )


def _collect_confirmed_skill_keys(
    profile_facts: dict,
) -> set[str]:
    """
    Возвращает набор ключей навыков из profile_facts["skills"],
    которые подтверждены хотя бы на каком-то уровне
    (то есть присутствуют как ключ вообще).
    """
    skills = profile_facts.get("skills", {})

    if not isinstance(skills, dict):
        return set()

    return {
        key.lower()
        for key in skills.keys()
    }


def _text_mentions_confirmed_skill(
    text: str,
    confirmed_keys: set[str],
) -> bool:
    """
    Проверяет, упоминает ли строка (например, из missing)
    навык, который прямо подтверждён в profile_facts,
    используя словарь маркеров CONFIRMED_SKILL_MARKERS.
    """
    normalized = text.lower()

    for skill_key, markers in CONFIRMED_SKILL_MARKERS.items():
        if skill_key not in confirmed_keys:
            continue

        if any(marker in normalized for marker in markers):
            return True

    return False


def _stem_ru_word(word: str) -> str:
    """
    Очень грубый эвристический стеммер для русских слов:
    отбрасывает 2-3 последних символа, чтобы падежные/числовые
    окончания ("теория" / "теории" / "теорию") сворачивались
    к общему префиксу. Это не полноценная морфология (для неё
    нет сетевого доступа к словарям pymorphy2 в рантайме), но
    для сравнения "совпадает ли слово из REQUIREMENTS со словом
    в свободном тексте missing" этого достаточно и это гораздо
    безопаснее нового частного regex-правила под каждый случай.

    Короткие слова (предлоги, союзы: "и", "по", "на") не режем —
    они и так короткие и с большой вероятностью не несут
    смысловой нагрузки для сравнения.
    """
    length = len(word)
    if length <= 4:
        return word
    if length <= 6:
        return word[:-2]
    return word[:-3]


def _requirement_word_stems(
    requirement: str,
) -> set[str]:
    """
    Разбивает формулировку требования на значимые слова (длиннее
    3 символов, чтобы не учитывать предлоги/союзы) и возвращает
    их стеммы.
    """
    words = [
        w for w in requirement.lower().split()
        if len(w) > 3
    ]
    return {_stem_ru_word(w) for w in words}


def _collect_confirmed_requirement_stems(
    fact_match: dict,
) -> list[set[str]]:
    """
    Достаёт из FACT_MATCH формулировки требований, которые
    матчер уже признал подтверждёнными, и возвращает их в виде
    множеств стеммированных слов (по одному множеству на
    требование). Это первая линия защиты missing от
    галлюцинаций — она устойчива к падежным окончаниям
    ("теория тестирования" в REQUIREMENTS vs "теории
    тестирования не подтверждена" в свободном тексте модели),
    и поэтому надёжнее CONFIRMED_SKILL_MARKERS.
    """
    if not isinstance(fact_match, dict):
        return []

    confirmed_statuses = {
        "confirmed_practical",
        "confirmed_educational",
        "confirmed_familiar",
    }

    stem_sets = []

    for item in fact_match.get("required_skills", []):
        if not isinstance(item, dict):
            continue
        if item.get("status") in confirmed_statuses:
            requirement = str(
                item.get("requirement", "")
            ).strip()
            stems = _requirement_word_stems(requirement)
            if stems:
                stem_sets.append(stems)

    return stem_sets


def _text_matches_confirmed_requirement(
    text: str,
    confirmed_stem_sets: list[set[str]],
) -> bool:
    """
    Строка (например, из missing) считается ссылающейся на уже
    подтверждённое требование, если ВСЕ значимые стеммы этого
    требования встречаются как подстроки где-то в тексте.
    Требование "ALL stems present", а не "ANY", нужно чтобы не
    ловить случайные частичные совпадения по одному общему слову.
    """
    if not confirmed_stem_sets:
        return False

    normalized = text.lower()

    for stems in confirmed_stem_sets:
        if all(stem in normalized for stem in stems):
            return True

    return False


def _mentions_experience_duration(
    text: str,
) -> bool:
    """
    Защита от IndigoSoft-бага: если строка missing
    описывает длительность/уровень коммерческого опыта
    ("опыт ... от 2-3 лет"), она НЕ должна вычёркиваться
    только потому, что внутри фразы упомянута технология,
    подтверждённая у кандидата на базовом уровне.

    Такая фраза по сути про стаж, а не про сам навык,
    и подтверждённый базовый навык не закрывает
    требование к многолетнему коммерческому опыту.
    """
    normalized = text.lower()

    return any(
        marker in normalized
        for marker in EXPERIENCE_DURATION_MARKERS
    )


def _strip_confirmed_facts_from_missing(
    missing: list[str],
    profile_facts: dict,
    fact_match: dict | None = None,
) -> tuple[list[str], list[str]]:
    """
    Программная страховка против уже неоднократно
    наблюдавшейся галлюцинации: модель пишет, что навык
    отсутствует, хотя он прямо подтверждён.

    Две линии защиты, в порядке приоритета:
    1. fact_match — точное совпадение с requirement, который
       FACT_MATCH уже пометил как confirmed_*. Это основной,
       надёжный путь.
    2. CONFIRMED_SKILL_MARKERS — эвристические маркеры по
       ключам profile_facts.skills, подстраховка на случай
       свободного текста в missing, не совпадающего дословно
       ни с одним required_skill.

    Важно: НЕ вычёркивает пункты, которые по сути описывают
    длительность/уровень коммерческого опыта, даже если
    внутри такой фразы случайно упомянута подтверждённая
    технология (см. _mentions_experience_duration).

    Возвращает (очищенный missing, список удалённых пунктов
    для диагностики в reasons).
    """
    confirmed_keys = _collect_confirmed_skill_keys(profile_facts)
    confirmed_stem_sets = _collect_confirmed_requirement_stems(
        fact_match or {}
    )

    if not confirmed_keys and not confirmed_stem_sets:
        return missing, []

    kept = []
    removed = []

    for item in missing:
        if _mentions_experience_duration(item):
            kept.append(item)
            continue

        stem_match = _text_matches_confirmed_requirement(
            item, confirmed_stem_sets
        )

        if stem_match or _text_mentions_confirmed_skill(
            item, confirmed_keys
        ):
            removed.append(item)
        else:
            kept.append(item)

    return kept, removed


def _apply_deterministic_seniority_guard(
    decision: str,
    score: int,
    reasons: list[str],
    requirements: dict,
) -> tuple[str, int]:
    """
    Программная страховка против того, что модель систематически
    выбирает REVIEW вместо REJECT для явных senior/lead вакансий
    с жёстким обязательным многолетним опытом.

    Пример реального бага: "Head of AI", seniority=senior,
    experience.years_min=5, importance=required, flexibility=False,
    образование required — модель вернула REVIEW/60, хотя по
    собственным правилам промпта это должен быть REJECT.

    Правило нарочно узкое и консервативное:
    - трогает только seniority in {senior, lead};
    - только если опыт ОБЯЗАТЕЛЕН (importance == required);
    - только если years_min >= HARD_SENIOR_YEARS_THRESHOLD;
    - только если НЕТ явной гибкости требований (flexibility=False).

    years_min может быть int (целые годы) или float (дробные
    годы для требований, указанных в месяцах, например 0.25 —
    см. requirements_analyzer.py). Дробные значения меньше
    HARD_SENIOR_YEARS_THRESHOLD естественно не срабатывают
    здесь — это осознанное поведение.

    Middle-вакансии, preferred-опыт и вакансии с явной гибкостью
    это правило не затрагивает — там решение остаётся за моделью.
    """
    if not isinstance(requirements, dict):
        return decision, score

    seniority = str(
        requirements.get("seniority", "unknown")
    ).strip().lower()

    experience = requirements.get("experience", {})
    if not isinstance(experience, dict):
        experience = {}

    importance = str(
        experience.get("importance", "unknown")
    ).strip().lower()

    years_min = experience.get("years_min")

    if not isinstance(years_min, (int, float)):
        years_min = None

    flexibility = bool(
        requirements.get("flexibility", False)
    )

    if (
        seniority in HARD_SENIOR_LEVELS
        and importance == "required"
        and years_min is not None
        and years_min >= HARD_SENIOR_YEARS_THRESHOLD
        and not flexibility
        and decision != "REJECT"
    ):
        reasons.insert(
            0,
            (
                "Программное правило: вакансия уровня "
                f"'{seniority}' с обязательным опытом "
                f"{years_min}+ лет и без признаков гибкости "
                "требований. Автоматически переведено в REJECT "
                "как нереалистичное для начинающего уровня."
            ),
        )
        decision = "REJECT"
        score = min(score, 15)

    return decision, score


def normalize(
    result: dict,
    profile_facts: dict | None = None,
    requirements: dict | None = None,
    fact_match: dict | None = None,
) -> dict:
    decision = str(
        result.get(
            "decision",
            "REVIEW",
        )
    ).strip().upper()

    if decision not in VALID_DECISIONS:
        decision = "REVIEW"

    try:
        score = int(
            result.get(
                "score",
                50,
            )
        )
    except (
        TypeError,
        ValueError,
    ):
        score = 50

    score = max(
        0,
        min(
            100,
            score,
        ),
    )

    reasons = result.get(
        "reasons",
        [],
    )

    if not isinstance(
        reasons,
        list,
    ):
        reasons = [
            str(reasons)
        ]

    reasons = [
        str(item).strip()
        for item in reasons
        if (
            str(item).strip()
            and not _is_placeholder(
                str(item)
            )
        )
    ]

    missing = result.get(
        "missing",
        [],
    )

    if not isinstance(
        missing,
        list,
    ):
        missing = [
            str(missing)
        ]

    missing = [
        str(item).strip()
        for item in missing
        if (
            str(item).strip()
            and not _is_placeholder(
                str(item)
            )
        )
    ]

    # ----------------------------------------------------
    # Программная страховка против галлюцинации
    # "навык отсутствует", хотя он подтверждён —
    # либо напрямую в FACT_MATCH (основной путь), либо
    # эвристически в profile_facts.json (запасной путь).
    # С защитой от вычёркивания пунктов про длительность
    # коммерческого опыта (IndigoSoft-баг).
    # ----------------------------------------------------
    removed_from_missing = []

    if profile_facts:
        missing, removed_from_missing = (
            _strip_confirmed_facts_from_missing(
                missing,
                profile_facts,
                fact_match,
            )
        )

    summary = str(
        result.get(
            "summary",
            "",
        )
    ).strip()

    if _is_placeholder(summary):
        summary = ""

    if removed_from_missing:
        reasons.append(
            (
                "Программная проверка удалила из missing "
                "пункты, противоречащие подтверждённым фактам: "
                + "; ".join(removed_from_missing)
            )
        )

    # APPLY с низкой оценкой противоречив.
    if (
        decision == "APPLY"
        and score < 60
    ):
        reasons.insert(
            0,
            (
                "Decision и score модели "
                "противоречат друг другу; "
                "APPLY автоматически "
                "переведён в REVIEW."
            ),
        )
        decision = "REVIEW"

    # REJECT с очень высокой оценкой тоже противоречив.
    if (
        decision == "REJECT"
        and score > 80
    ):
        reasons.insert(
            0,
            (
                "Decision и score модели "
                "противоречат друг другу; "
                "REJECT автоматически "
                "переведён в REVIEW."
            ),
        )
        decision = "REVIEW"

    # Аналитик не должен говорить от первого лица.
    if (
        decision == "APPLY"
        and _contains_first_person(
            reasons,
            summary,
        )
    ):
        reasons.insert(
            0,
            (
                "Evaluator использовал "
                "первое лицо. APPLY "
                "автоматически заблокирован "
                "и переведён в REVIEW."
            ),
        )
        decision = "REVIEW"

    # ----------------------------------------------------
    # Программная страховка против систематического REVIEW
    # там, где по structured requirements явно должен быть
    # REJECT (senior/lead + 4+ года обязательного опыта
    # без гибкости). Применяется последней, после всех
    # остальных проверок согласованности.
    # ----------------------------------------------------
    if requirements:
        decision, score = _apply_deterministic_seniority_guard(
            decision,
            score,
            reasons,
            requirements,
        )

    return {
        "decision": decision,
        "score": score,
        "reasons": reasons,
        "missing": missing,
        "summary": summary,
    }


def evaluate_vacancy(
    ollama_url: str,
    model_name: str,
    vacancy: dict,
    profile: str,
    preferences: str,
    profile_facts: dict,
    requirements: dict,
) -> dict:
    # Программное сопоставление требований и профиля — считается
    # один раз, детерминированно, ДО обращения к модели. Результат
    # передаётся в промпт как авторитетный источник (FACT_MATCH) и
    # используется повторно после ответа модели как страховка для
    # очистки missing. Модель не должна заново решать то, что уже
    # решено здесь программно.
    fact_match = match_requirements_to_profile(
        requirements,
        profile_facts,
    )

    prompt = build_prompt(
        vacancy=vacancy,
        profile=profile,
        preferences=preferences,
        profile_facts=profile_facts,
        requirements=requirements,
        fact_match=fact_match,
    )

    raw_result = ask_json(
        ollama_url=ollama_url,
        model_name=model_name,
        prompt=prompt,
    )

    if not isinstance(
        raw_result,
        dict,
    ):
        raise RuntimeError(
            "Evaluator вернул JSON, "
            "но верхний уровень "
            "не является объектом."
        )

    return normalize(
        raw_result,
        profile_facts,
        requirements,
        fact_match,
    )