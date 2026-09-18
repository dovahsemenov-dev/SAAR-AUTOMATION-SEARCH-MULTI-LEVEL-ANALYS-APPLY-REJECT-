"""
filters/decision_guard.py
Детерминированный слой принятия решений.

Состоит из трёх независимых частей:

0. _detect_seniority_block() — АБСОЛЮТНАЯ, ни от чего не
   зависящая проверка уровня вакансии (Middle/Senior/Lead).
   Вызывается и в apply_decision_guard() (до evaluator), и
   в самом начале apply_post_evaluator_guard() (после
   evaluator, включая уже готовый APPLY от evaluator напрямую).
   См. ФИКС #3 ниже.

1. apply_decision_guard() — применяется ПОСЛЕ requirements_analyzer
   и ДО evaluator. Отсекает явно нереалистичные вакансии как REJECT
   без вызова модели вообще.

2. apply_post_evaluator_guard() — применяется ПОСЛЕ evaluator.
   Чистит от evaluator ответа галлюцинации про географию/формат
   работы (эти параметры уже проверены детерминированно до
   evaluator, но 7B-модель иногда всё равно их упоминает, нарушая
   явный запрет в своём промпте) и переопределяет REVIEW в APPLY —
   но ТОЛЬКО если не осталось необязательного объяснимого сомнения
   (см. ниже, "ФИКС #2").

Идея та же для всех частей: комбинированную логику вида
"если A и B и не C — то решение X" нельзя надёжно доверить
7B-модели (см. историю с Head of AI, QA Lead, WebBee — модель
либо игнорировала собственные правила, либо неверно определяла
seniority; и позже — с одинаковыми по географии вакансиями,
которые она то помечала форматом работы как минус, то нет).
Python может решить эту логику детерминированно и без единого
шанса на галлюцинацию.

ВАЖНО: apply_decision_guard() (собственно "hard experience"
проверка ниже) намеренно НЕ смотрит на seniority для решения
REJECT по годам опыта — эта логика опирается только на
experience.years_min/importance/flexibility, потому что они
определяются стабильно. Но начиная с ФИКС #3 в этом файле
есть ОТДЕЛЬНАЯ, более ранняя и более жёсткая проверка именно
seniority (_detect_seniority_block) — она не про "нереалистичный
опыт", а про то, что Middle/Senior/Lead вакансии в принципе не
должны получать отклик, независимо от требуемого опыта.

years_min теперь может быть дробным (например, 0.25 для
"опыт от 3 месяцев" — см. requirements_analyzer.py). Порог
HARD_EXPERIENCE_YEARS_THRESHOLD = 3 остаётся в годах, поэтому
такие дробные, менее-года требования естественным образом НЕ
попадают под автоматический REJECT здесь — это осознанно:
несколько месяцев формального опыта это принципиально другой
по строгости барьер, чем несколько лет, и такие вакансии
должны уходить в evaluator для содержательной оценки, а не
отсекаться наравне с "required 3+ года".

ПРОДУКТОВОЕ РЕШЕНИЕ (важно для понимания второй части файла):
это автокликер, а не анализатор вакансий. REVIEW пользователь
не читает — то есть с точки зрения продукта REVIEW эквивалентен
потерянной вакансии. Жёсткие, однозначно нереалистичные случаи
уже отсеиваются как REJECT в apply_decision_guard() ДО того,
как вакансия вообще попадает в evaluator. Значит любой REVIEW,
который всё-таки дошёл от evaluator, — по определению пограничный
случай с сомнением, а не откровенный мискмэтч.

ФИКС #2 (169 вакансий):
Подтверждённый на реальном прогоне баг — п.2 (переопределение
REVIEW -> APPLY) раньше делал это БЕЗУСЛОВНО, для любого REVIEW,
исходя из предпосылки "жёсткие случаи уже отсеяны в
apply_decision_guard() до evaluator". Эта предпосылка была
неверна: apply_decision_guard() проверяет только hard_blockers
и experience.importance == "required" с years_min >= 3. Он НЕ
проверяет:
    - education.importance == "required" (образование вообще не
      участвовало в pre-guard логике);
    - experience.importance == "required" с years_min < 3
      (например, "обязателен опыт от 2 лет" — required, но ниже
      трёхлетнего порога, пропускается pre-guard'ом как "мягкий"
      случай, хотя для кандидата без единого дня коммерческого
      опыта required остаётся required независимо от порога);
    - required_skills (например, конкретная обязательная
      технология вроде "Xilinx Vivado" для FPGA-вакансии).

Новая логика apply_post_evaluator_guard(): прежде чем перевести
REVIEW -> APPLY, guard повторно проверяет requirements (тот же
объект, что видел apply_decision_guard) и очищенные reasons/
missing самого evaluator. Если там остался необязательный
("required" и не flexible) пробел по опыту/образованию, который
pre-guard не поймал, ЛИБО в самом тексте evaluator'а сохранились
явные формулировки о нарушенном обязательном требовании —
REVIEW переводится не в APPLY, а в REJECT (с явной программной
причиной, чтобы решение осталось аудируемым, а не тихо потерялось
как раньше в виде непрочитанного REVIEW). Только если ни одного
такого сигнала нет — сохраняется старое поведение: перевод в
APPLY, потому что оставшееся сомнение действительно нельзя
объяснить формальным required-требованием, а значит это
пограничный случай в пользу отклика.

ИСПРАВЛЕНИЕ (реальный прогон, 0 APPLY из 218 обработанных):
Обнаружен разрыв между докстрингом ФИКС #2 (выше) и фактическим
кодом apply_post_evaluator_guard(): структурные функции
_has_unflexible_required_gap() и _has_hard_requirement_language()
(именно они реализуют логику, описанную в ФИКС #2) были
определены в файле, но НЕ вызывались. Вместо них тело функции
использовало гораздо более грубые _has_substantive_missing() /
_has_explicit_mismatch_language(), которые считают блокирующим
ЛЮБОЙ непустой пункт missing (кроме чисто образовательного) —
а Qwen для junior/начинающего профиля практически всегда находит
хотя бы один такой пункт (не хватает конкретного инструмента,
нет опыта с конкретной технологией и т.п.), даже когда вакансия
в целом подходящая. Плюс правило "REVIEW остаётся REVIEW"
применялось БЕЗУСЛОВНО, без единого пути REVIEW -> APPLY.

Итог на практике: результат от evaluator почти никогда не может
остаться/стать APPLY. Реальный прогон подтвердил это буквально:
72 REVIEW, 146 REJECT, 0 APPLY из 218 обработанных вакансий —
автокликер не откликался ни на одну вакансию независимо от
качества совпадения.

Решение: apply_post_evaluator_guard() переписан так, чтобы
реально использовать _has_unflexible_required_gap() (структурная
проверка: experience/education действительно required И не
flexible) и _has_hard_requirement_language() (текстовый фоллбэк
только на явные формулировки об обязательности, а не на любое
упоминание нехватки чего-либо) — то есть именно то поведение,
которое было изначально описано в ФИКС #2, но не реализовано в
коде. Блок с REVIEW -> APPLY восстановлен: конвертация происходит,
только если НИ структурного, НИ текстового сигнала об
обязательном нарушенном требовании не найдено. Если сигнал
найден — REVIEW идёт не в тихо забытый REVIEW, а в явный REJECT
с аудируемой причиной (как и было задумано). Старые, слишком
грубые _has_substantive_missing()/_is_education_only_missing()/
_has_explicit_mismatch_language() удалены — они и были источником
бага, оставлять их как мёртвый код рискованно (кто-то может
случайно снова начать их использовать).

ФИКС #3 (этот прогон, seniority-guard):
Подтверждённый на реальном прогоне баг, ДВА разных механизма
пропуска Middle/Senior в APPLY одновременно:

    1) "QA Engineer gamedev" — в названии Middle нет вообще, но
       requirements_analyzer определил seniority: "middle" И
       experience: 2 года | required. Тем не менее итоговый
       decision был APPLY. Значит опора только на experience
       (years_min < 3 -> "мягкий" случай) недостаточна ИМЕННО
       для явно определённого seniority — тут нужен отдельный,
       не завязанный на годы опыта, абсолютный REJECT.

    2) "Старший тестировщик Альфа-Банка" — Qwen верно определил
       seniority: "middle", но decision получился APPLY НЕ через
       путь REVIEW->APPLY (старая точка контроля в п.2 этого
       файла), а напрямую от evaluator. То есть проверки только
       в момент "REVIEW -> APPLY" недостаточно: нужна проверка,
       которая срабатывает для ЛЮБОГО текущего decision, включая
       уже готовый APPLY.

Решение: _detect_seniority_block() — абсолютная, независимая от
experience/evaluator/score проверка по ДВУМ источникам сразу
(название вакансии по регэкспу + requirements["seniority"]).
Она вызывается:

    - в apply_decision_guard() — как самая первая проверка, до
      hard_blockers и до experience-порога, чтобы Middle/Senior/
      Lead вообще не доходили до evaluator;
    - в apply_post_evaluator_guard() — тоже как самая первая
      проверка, ДО текстовой очистки и ДО ветки REVIEW/APPLY,
      и она принудительно переводит decision в REJECT независимо
      от того, что вернул evaluator (APPLY, REVIEW или REJECT).

Это тот самый "второй предохранитель": даже если название
вакансии не содержит Middle/Senior ("QA Engineer gamedev"),
поле seniority от requirements_analyzer всё равно остановит
вакансию. И даже если evaluator сходу вернул APPLY, минуя REVIEW
("Старший тестировщик Альфа-Банка"), post-evaluator guard всё
равно её перехватит, потому что проверка больше не привязана к
текущему значению result["decision"].

ВАЖНО ДЛЯ ВЫЗЫВАЮЩЕГО КОДА (main.py): чтобы seniority-guard
реально работал по названию вакансии (а не только по полю
requirements["seniority"]), в apply_decision_guard() и
apply_post_evaluator_guard() нужно передавать vacancy_title.
Раньше эти функции title не принимали — сигнатуры расширены
новым optional-параметром, старые вызовы без title продолжат
работать (тогда сработает только проверка по
requirements["seniority"]), но для полного покрытия título
следует прокинуть.

--------------------------------------------------------------
ФИКС #4 (по прямому указанию пользователя): required-образование
"среднее" больше не блокирует отклик автоматически.

Баг: _has_unflexible_required_gap() считала ЛЮБОЕ
education.importance == "required" (без признаков гибкости)
безусловным поводом для REJECT ещё до evaluator — независимо от
того, ЧТО именно требуется: законченное высшее образование (то,
чего у кандидата действительно нет) или среднее специальное/ССУЗ
(кандидат сейчас учится именно по такой специальности). На
реальном прогоне это привело к тому, что вакансии с формулировкой
вроде "высшее или среднее специальное образование" отсекались
программным правилом наравне с вакансиями, где требуется
исключительно законченное высшее, — хотя пользователь прямо
просил продолжать откликаться на вакансии, где достаточно
среднего/среднего специального образования.

Исправление: перед тем как считать required-образование
блокирующим разрывом, requirement_text проверяется на признаки
того, что среднее специальное/ССУЗ образование само по себе
удовлетворяет требованию (см. _EDUCATION_VOCATIONAL_MARKERS и
_education_allows_vocational() ниже). Если такие признаки есть —
это НЕ считается непреодолимым разрывом здесь, и вакансия
уходит дальше по обычному пути (evaluator/post-evaluator guard),
вместо автоматического REJECT. Блокирующим structural-разрывом
по-прежнему считается только требование, явно и исключительно
про высшее образование (например, "высшее образование в области
информационных технологий" без упоминания среднего/ССУЗ как
альтернативы).
--------------------------------------------------------------
"""

import re

# Начиная с скольки ОБЯЗАТЕЛЬНЫХ лет опыта вакансия без
# признаков гибкости считается нереалистичной для кандидата
# без единого дня коммерческого опыта. Порог сознательно
# не завязан на seniority.
HARD_EXPERIENCE_YEARS_THRESHOLD = 3

# Дефолтные значения decision/score/summary для случаев,
# когда guard принял решение сам, без Qwen.
GUARD_SCORE_REJECT = 5

# Минимальный score, который проставляется вакансии, чья
# decision была программно переведена из REVIEW в APPLY.
# Не завышаем искусственно выше — score вторичен, важен
# сам decision.
POST_GUARD_APPLY_SCORE_FLOOR = 65

# --------------------------------------------------------------
# ФИКС #3: seniority-guard.
# --------------------------------------------------------------

# Значения requirements["seniority"], при которых вакансия
# абсолютно REJECT независимо от опыта, evaluator и score.
SENIORITY_REJECT_LEVELS = {
    "middle",
    "middle+",
    "senior",
    "senior+",
    "lead",
    "team lead",
    "teamlead",
    "tech lead",
    "techlead",
}

# Маркеры уровня прямо в названии вакансии. \b работает и для
# латиницы (Middle, Senior, Lead), для кириллицы используем явные
# группы окончаний вместо \b (в Python re \b по кириллице ведёт
# себя нестабильно в зависимости от локали/флагов).
_TITLE_SENIORITY_PATTERN = re.compile(
    r"(?ix)"
    r"(?:\bmiddle\+?\b|\bmiddle/senior\b|\bsenior\+?\b|\blead\b|"
    r"\bteam\s*lead\b|\btech\s*lead\b)"
    r"|"
    r"(?:старш(?:ий|его|ему|им|ем|ая|ую|ие)|"
    r"ведущ(?:ий|его|ему|им|ем|ая|ую|ие))"
)


def _detect_seniority_block(
    requirements: dict | None,
    vacancy_title: str | None = None,
) -> str | None:
    """
    Жёсткая, независимая от evaluator/experience проверка
    seniority. Возвращает человекочитаемое объяснение найденного
    признака Middle/Senior/Lead, либо None, если признаков нет.

    Два независимых источника (см. ФИКС #3 в докстринге модуля:
    Qwen то отражает "Middle" в названии, то нет; поле seniority
    от requirements_analyzer тоже иногда даёт middle там, где в
    названии этого нет вообще, — "QA Engineer gamedev"):

        1) Название вакансии — регэксп на Middle/Middle+/Senior/
           Lead/Старший/Ведущий как отдельное слово/форма.
        2) requirements["seniority"] — если requirements_analyzer
           определил middle/senior/lead, этого достаточно, даже
           если в названии ничего похожего нет.

    Правило абсолютное: результат не зависит от experience,
    evaluator, score или того, дошла ли вакансия до REVIEW.
    Проверяется ОБА источника независимо — сработавшего одного
    достаточно.
    """
    if isinstance(vacancy_title, str) and vacancy_title.strip():
        match = _TITLE_SENIORITY_PATTERN.search(vacancy_title)
        if match:
            return (
                "в названии вакансии обнаружен маркер уровня "
                f"'{match.group(0)}' (название: "
                f"'{vacancy_title.strip()}')"
            )

    if isinstance(requirements, dict):
        seniority = str(
            requirements.get("seniority", "")
        ).strip().lower()
        if seniority in SENIORITY_REJECT_LEVELS:
            return (
                f"requirements_analyzer определил seniority = "
                f"'{seniority}'"
            )

    return None


# --------------------------------------------------------------
# Маркеры географии/формата работы, которые evaluator'у прямо
# запрещено использовать как причину decision/score/reasons/missing
# --------------------------------------------------------------

# (см. блок "ГЕОГРАФИЯ УЖЕ ПРОВЕРЕНА" в ai/evaluator.py build_prompt()).
# Подтверждённый на реальном прогоне баг: 7B-модель это правило
# иногда всё равно нарушает — по двум вакансиям с одинаковым
# GEOGRAPHY CHECK: PASS (Казань, Уфа) она то писала про офисный
# формат как про минус, то нет. Чиним программно, не полагаясь
# на то, что модель в 100% случаев послушается текста промпта.
_FORBIDDEN_REASON_MARKERS = (
    "офисн",
    "удалён",
    "удален",
    "гибрид",
    "формат работы",
    "командировк",
    "переезд",
    "переезжать",
)

# ФИКС #2: текстовые маркеры того, что evaluator сам указал на
# нарушенное ОБЯЗАТЕЛЬНОЕ требование (а не просто на общее
# сомнение/предпочтение). Используются только как fallback —
# когда структурные поля requirements (experience/education)
# уже проверены и разрыва не нашли, но evaluator всё равно явно
# пишет о нарушенном required-условии (типичный случай —
# required_skills, которые guard структурно не проверяет,
# например конкретная обязательная технология).
#
# Список сознательно короткий и специфичный, чтобы не ловить
# общие рассуждения evaluator'а о плюсах/минусах кандидата —
# только прямые формулировки об обязательности.
_HARD_REQUIREMENT_TEXT_MARKERS = (
    "обязательн",
    "обязателен",
    "обязательное требование",
    "без этого не рассматрива",
    "жёсткое требование",
    "жесткое требование",
    "hard requirement",
    "hard blocker",
    "required skill",
    "mandatory",
)

# --------------------------------------------------------------
# ФИКС #4 (по прямому указанию пользователя): маркеры того, что
# формулировка требования к образованию допускает среднее
# специальное/ССУЗ как достаточный вариант — см. докстринг модуля.
# --------------------------------------------------------------
_EDUCATION_VOCATIONAL_MARKERS = (
    "средне",
    "среднее",
    "ссуз",
    "техникум",
    "колледж",
    "профтех",
)


def _education_allows_vocational(requirement_text: str | None) -> bool:
    """
    True, если текст требования к образованию упоминает среднее/
    среднее специальное образование (ССУЗ, техникум, колледж) как
    приемлемый вариант — то есть требование НЕ ограничено только
    законченным высшим образованием.

    Используется в _has_unflexible_required_gap(), чтобы НЕ
    считать такие вакансии автоматическим REJECT: пользователь
    прямо просил продолжать откликаться на вакансии, где
    достаточно среднего/среднего специального образования, даже
    если формально это поле помечено как "required".
    """
    if not requirement_text:
        return False
    low = requirement_text.strip().lower()
    return any(
        marker in low for marker in _EDUCATION_VOCATIONAL_MARKERS
    )


def _is_program_duration_text(text: object) -> bool:
    low = str(text or "").lower().replace("ё", "е")
    if not any(marker in low for marker in ("стажировк", "стажерск", "internship", "trainee")):
        return False
    if any(marker in low for marker in ("длительностью", "длится", "рассчитан", "рассчитана", "продолжительностью", "программа", "обучение")):
        return True
    return bool(re.search(
        r"стажиров\w*[^.\n]{0,100}\b\d+(?:[.,]\d+)?\s*(?:год|года|лет|месяц|месяца|месяцев|мес\.?)",
        low,
    ))


def _has_structured_hard_requirement_language(text: object, requirements: dict | None) -> bool:
    low = str(text or "").lower().replace("ё", "е")
    if _is_program_duration_text(low):
        return False
    if not any(marker in low for marker in _HARD_REQUIREMENT_TEXT_MARKERS):
        return False
    if not isinstance(requirements, dict):
        return False

    exp_importance, years_min, _ = _extract_experience(requirements)
    edu_importance, edu_text, _ = _extract_education(requirements)

    if any(marker in low for marker in ("опыт", "стаж", "коммерческ")):
        return exp_importance == "required" and years_min is not None and years_min > 0

    if any(marker in low for marker in ("образован", "диплом", "высш", "ссуз", "средн специаль")):
        return edu_importance == "required" and not _education_allows_vocational(edu_text)

    required_skills = requirements.get("required_skills", [])
    if isinstance(required_skills, list):
        return any(
            str(skill or "").strip().lower() and
            str(skill or "").strip().lower() in low
            for skill in required_skills
        )
    return False


def _extract_experience(requirements: dict) -> tuple[str, int | float | None, bool]:
    """
    Возвращает (importance, years_min, flexibility) из
    STRUCTURED REQUIREMENTS, устойчиво к некорректным типам.

    years_min может быть int (целые годы) или float (дробные
    годы для требований, указанных в месяцах).
    """
    if not isinstance(requirements, dict):
        return "unknown", None, False

    experience = requirements.get("experience", {})
    if not isinstance(experience, dict):
        experience = {}

    importance = str(
        experience.get("importance", "unknown")
    ).strip().lower()

    years_min = experience.get("years_min")
    if not isinstance(years_min, (int, float)):
        years_min = None

    flexibility = bool(requirements.get("flexibility", False))

    return importance, years_min, flexibility


def _extract_education(requirements: dict) -> tuple[str, str | None, bool]:
    """
    Возвращает (importance, requirement_text, flexibility) из
    STRUCTURED REQUIREMENTS["education"].
    """
    if not isinstance(requirements, dict):
        return "unknown", None, False

    education = requirements.get("education", {})
    if not isinstance(education, dict):
        education = {}

    importance = str(
        education.get("importance", "unknown")
    ).strip().lower()

    requirement_text = education.get("requirement")
    if not isinstance(requirement_text, str) or not requirement_text.strip():
        requirement_text = None

    flexibility = bool(requirements.get("flexibility", False))

    return importance, requirement_text, flexibility


def _extract_hard_blockers(requirements: dict) -> list[str]:
    if not isinstance(requirements, dict):
        return []

    hard_blockers = requirements.get("hard_blockers", [])
    if not isinstance(hard_blockers, list):
        return []

    return [
        str(item).strip()
        for item in hard_blockers
        if str(item).strip() and not _is_program_duration_text(item)
    ]


def apply_decision_guard(
    requirements: dict,
    vacancy_title: str | None = None,
) -> dict | None:
    """
    Пытается принять детерминированное решение по вакансии
    на основе STRUCTURED REQUIREMENTS, без вызова Qwen.

    vacancy_title — заголовок вакансии, опционален, но нужен
    для полного покрытия seniority-guard (ФИКС #3): без него
    сработает только проверка по requirements["seniority"].

    Возвращает готовый результат в том же формате, что и
    evaluator.normalize(), либо None, если решение нельзя
    принять однозначно (вакансия должна пойти в evaluator).
    """
    if not isinstance(requirements, dict):
        # seniority-guard по названию всё равно может сработать,
        # даже если requirements битые/отсутствуют.
        seniority_block = _detect_seniority_block(None, vacancy_title)
        if seniority_block:
            return _seniority_reject_result(seniority_block)
        return None

    # --------------------------------------------------------
    # ФИКС #3: абсолютная проверка seniority — САМАЯ ПЕРВАЯ,
    # раньше hard_blockers и раньше experience-порога. Middle/
    # Senior/Lead не должны доходить до evaluator вообще, вне
    # зависимости от того, что там с опытом.
    # --------------------------------------------------------
    seniority_block = _detect_seniority_block(requirements, vacancy_title)
    if seniority_block:
        return _seniority_reject_result(seniority_block)

    hard_blockers = _extract_hard_blockers(requirements)
    if hard_blockers:
        return {
            "decision": "REJECT",
            "score": GUARD_SCORE_REJECT,
            "reasons": [
                (
                    "Программное правило (decision_guard): работодатель "
                    "прямо указал жёсткое обязательное условие приёма: "
                    + "; ".join(hard_blockers)
                )
            ],
            "missing": [],
            "summary": (
                "Вакансия содержит явный обязательный блокер, "
                "делающий отклик нереалистичным."
            ),
        }

    importance, years_min, flexibility = _extract_experience(
        requirements
    )

    # Явная обязательность опыта в тексте вакансии — hard blocker.
    # В отличие от одного только HH-поля "1–3 года", этот флаг означает,
    # что работодатель прямо требует опыт и не предлагает вход без него.
    if (
        requirements.get("mandatory_experience")
        and isinstance(years_min, (int, float))
        and years_min > 0
    ):
        return {
            "decision": "REJECT",
            "score": GUARD_SCORE_REJECT,
            "reasons": [
                "Программное правило (decision_guard): в тексте вакансии явно указан обязательный профильный/коммерческий опыт от "
                f"{years_min} лет. У кандидата нет подтверждённого коммерческого опыта."
            ],
            "missing": [f"Обязательный опыт от {years_min} лет"],
            "summary": "Отклик исключён: работодатель явно требует обязательный опыт."
        }

    if (
        importance == "required"
        and years_min is not None
        and years_min >= HARD_EXPERIENCE_YEARS_THRESHOLD
        and not flexibility
    ):
        seniority = str(
            requirements.get("seniority", "unknown")
        ).strip().lower()

        return {
            "decision": "REJECT",
            "score": GUARD_SCORE_REJECT,
            "reasons": [
                (
                    "Программное правило (decision_guard): обязательный "
                    f"коммерческий опыт {years_min}+ лет без признаков "
                    "гибкости требований. Нереалистично для кандидата "
                    "без коммерческого опыта, независимо от заявленного "
                    f"уровня вакансии ('{seniority}')."
                )
            ],
            "missing": [
                f"Обязательный коммерческий опыт от {years_min} лет"
            ],
            "summary": (
                "Вакансия требует обязательный многолетний "
                "коммерческий опыт без признаков гибкости."
            ),
        }

    # ИСПРАВЛЕНИЕ (экономия вызовов evaluator):
    # _has_unflexible_required_gap() (см. ниже в этом файле, ФИКС #2)
    # раньше вызывалась ТОЛЬКО в apply_post_evaluator_guard(), уже
    # ПОСЛЕ самого дорогого вызова Qwen (evaluate_vacancy). На
    # реальном прогоне из 49 случаев REVIEW -> REJECT через эту
    # функцию 45 (33 по опыту + 12 по образованию) были структурными
    # разрывами, полностью вычислимыми из requirements — то есть
    # evaluator вызывался и полностью впустую: итоговое решение всё
    # равно было REJECT. Тот же чек теперь выполняется и здесь, ДО
    # evaluator, — итоговое решение не меняется, но обязательное
    # required-образование (искючительно высшее — см. ФИКС #4) и
    # required-опыт ниже HARD_EXPERIENCE_YEARS_THRESHOLD (но выше
    # нуля) теперь отсекают вакансию без единого обращения к модели.
    early_gap = _has_unflexible_required_gap(requirements)
    if early_gap:
        return {
            "decision": "REJECT",
            "score": GUARD_SCORE_REJECT,
            "reasons": [
                "Программное правило (decision_guard, ранняя проверка "
                f"required-разрыва): {early_gap}."
            ],
            "missing": [],
            "summary": (
                "Отклонено программным правилом до обращения к Qwen: "
                "обязательное требование по опыту/образованию не может "
                "быть подтверждено профилем кандидата."
            ),
        }

    # Однозначного решения нет — передаём вакансию в evaluator.
    # Сюда попадают, в частности, требования опыта менее года
    # (например, years_min=0.25 из "от 3 месяцев") — это
    # осознанно: такой барьер слишком мягкий, чтобы решать его
    # детерминированно как REJECT.
    return None


def _seniority_reject_result(explanation: str) -> dict:
    """Единый формат REJECT-результата от seniority-guard."""
    return {
        "decision": "REJECT",
        "score": GUARD_SCORE_REJECT,
        "reasons": [
            (
                "Программное правило (decision_guard, seniority-guard, "
                f"ФИКС #3): {explanation}. Middle/Senior/Lead — "
                "абсолютный REJECT независимо от experience, evaluator "
                "и score."
            )
        ],
        "missing": [],
        "summary": (
            "Вакансия уровня Middle/Senior/Lead — отклик исключён "
            "программным правилом."
        ),
    }


def _strip_forbidden_markers(items: list[str]) -> tuple[list[str], bool]:
    """
    Убирает из списка причин/пробелов те пункты, которые
    упоминают географию/формат работы — эти параметры уже
    проверены детерминированно до evaluator и не могут быть
    легитимной причиной его решения.

    Возвращает (очищенный список, был ли хоть один пункт удалён).
    """
    kept: list[str] = []
    dropped_any = False

    for item in items:
        text = str(item)
        low = text.lower()
        if any(marker in low for marker in _FORBIDDEN_REASON_MARKERS):
            dropped_any = True
            continue
        kept.append(text)

    return kept, dropped_any


def _has_unflexible_required_gap(requirements: dict | None) -> str | None:
    """
    ФИКС #2, структурная часть.

    Проверяет requirements ещё раз (те же поля, что видел
    apply_decision_guard, но с более широким охватом) на предмет
    required + не-flexible требования по опыту или образованию,
    которое apply_decision_guard() НЕ отсёк как REJECT до
    evaluator'а:

        - experience.importance == "required", not flexible,
          years_min есть, но < HARD_EXPERIENCE_YEARS_THRESHOLD
          (например, "обязателен опыт от 2 лет" — required
          остаётся required и ниже трёхлетнего порога);
        - education.importance == "required", not flexible, И
          ИСКЛЮЧИТЕЛЬНО про высшее образование — см. ФИКС #4 в
          докстринге модуля. Если формулировка допускает среднее
          специальное/ССУЗ (_education_allows_vocational() вернула
          True), это НЕ считается разрывом здесь: пользователь
          прямо просил продолжать откликаться на такие вакансии.

    Возвращает человекочитаемое объяснение найденного разрыва,
    либо None, если структурного разрыва нет.
    """
    if not isinstance(requirements, dict):
        return None

    exp_importance, years_min, exp_flexible = _extract_experience(
        requirements
    )
    if (
        exp_importance == "required"
        and years_min is not None
        and not exp_flexible
        and years_min > 0
        and years_min < HARD_EXPERIENCE_YEARS_THRESHOLD
    ):
        return (
            f"обязательный (required, без признаков гибкости) "
            f"коммерческий опыт от {years_min} лет — ниже порога "
            f"{HARD_EXPERIENCE_YEARS_THRESHOLD} лет, поэтому не был "
            "отсечён как REJECT до evaluator, но остаётся required"
        )

    edu_importance, edu_text, edu_flexible = _extract_education(
        requirements
    )
    if (
        edu_importance == "required"
        and not edu_flexible
        and not _education_allows_vocational(edu_text)
    ):
        detail = f" ('{edu_text}')" if edu_text else ""
        return (
            f"обязательное (required, без признаков гибкости) "
            f"требование к высшему образованию{detail}, без варианта "
            "среднего специального/ССУЗ — формально не может быть "
            "подтверждено профилем кандидата"
        )

    return None


def _has_hard_requirement_language(
    items: list[str],
    requirements: dict | None = None,
) -> bool:
    for item in items:
        if _has_structured_hard_requirement_language(item, requirements):
            return True
    return False


def _normalize_decision(value: object) -> str:
    return str(value or "REVIEW").strip().upper()


def apply_post_evaluator_guard(
    result: dict,
    requirements: dict | None = None,
    vacancy_title: str | None = None,
) -> dict:
    """
    Финальный детерминированный предохранитель после evaluator.

    ФИКС (см. докстринг модуля выше, "ИСПРАВЛЕНИЕ 0 APPLY"):
    восстановлена логика ФИКС #2 в том виде, в котором она
    описана — с реальным вызовом _has_unflexible_required_gap()
    и _has_hard_requirement_language() вместо грубой блокировки
    по любому непустому missing.

    Правила:
        1. Middle/Senior/Lead — абсолютный REJECT (без изменений).
        2. APPLY от evaluator понижается до REVIEW, ТОЛЬКО если
           найден структурный required-разрыв ИЛИ явная текстовая
           формулировка об обязательном требовании. Обычный
           "не хватает практики с X" для junior-профиля САМ ПО
           СЕБЕ больше не блокирует APPLY — это ожидаемо для
           начинающего кандидата, а не причина отказа от отклика.
        3. REVIEW от evaluator:
             - если найден структурный/текстовый required-разрыв —
               переводится в явный REJECT (не теряется как
               непрочитанный REVIEW);
             - если разрыва нет — переводится в APPLY с полом
               score = POST_GUARD_APPLY_SCORE_FLOOR (пограничный
               случай без объяснимого формального препятствия —
               это в пользу отклика, а не игнорирования вакансии).
        4. REJECT от evaluator остаётся REJECT.
    """
    if not isinstance(result, dict):
        return result

    # 1. Абсолютный seniority guard.
    seniority_block = _detect_seniority_block(
        requirements,
        vacancy_title,
    )
    if seniority_block:
        reasons = result.get("reasons", [])
        if not isinstance(reasons, list):
            reasons = [str(reasons)] if reasons else []
        original = _normalize_decision(result.get("decision"))
        reasons.insert(
            0,
            (
                "Программное правило (post-evaluator seniority-guard): "
                f"{seniority_block}. Исходное решение evaluator '{original}' "
                "заменено на REJECT. Middle/Senior/Lead не допускаются "
                "к автоматическому отклику."
            ),
        )
        result["decision"] = "REJECT"
        result["score"] = min(int(result.get("score", GUARD_SCORE_REJECT) or GUARD_SCORE_REJECT), GUARD_SCORE_REJECT)
        result["reasons"] = reasons
        result["summary"] = "Вакансия уровня Middle/Senior/Lead — отклик исключён программным правилом."
        return result

    reasons = result.get("reasons", [])
    if not isinstance(reasons, list):
        reasons = [str(reasons)] if reasons else []
    missing = result.get("missing", [])
    if not isinstance(missing, list):
        missing = [str(missing)] if missing else []

    reasons, dropped_r = _strip_forbidden_markers(reasons)
    missing, dropped_m = _strip_forbidden_markers(missing)
    if dropped_r or dropped_m:
        reasons.append(
            "Программная проверка удалила из evaluator-ответа "
            "упоминания географии/формата работы: они проверяются отдельно."
        )

    decision = _normalize_decision(result.get("decision"))

    # Единая проверка "есть ли реально нарушенное required-условие",
    # используется и для APPLY-понижения, и для REVIEW-развилки.
    structural_gap = _has_unflexible_required_gap(requirements)
    # mandatory_experience уже отражён в structured requirements.
    # Не добавляем здесь отдельный text-only blocker.
    hard_language_hit = _has_hard_requirement_language(
        reasons + missing,
        requirements,
    )
    has_required_gap = bool(structural_gap or hard_language_hit)

    def _gap_explanation() -> str:
        if structural_gap:
            return structural_gap
        return (
            "evaluator явно указал на нарушенное обязательное "
            "требование (формулировка об обязательности в "
            "reasons/missing)"
        )

    # 2. APPLY понижается до REVIEW, только если есть реальный
    #    required-разрыв — а не любое упоминание нехватки чего-либо.
    if decision == "APPLY":
        if has_required_gap:
            reasons.insert(
                0,
                (
                    "Программное правило (post-evaluator guard): "
                    "автоматический APPLY понижен до REVIEW, потому что "
                    f"найден нарушенный required-требование: {_gap_explanation()}."
                ),
            )
            result["decision"] = "REVIEW"
            result["reasons"] = reasons
            result["missing"] = missing
            result["summary"] = (
                "Требуется ручной просмотр: найдено обязательное "
                "требование, не подтверждённое профилем; автоматический "
                "отклик НЕ отправляется."
            )
            return result

        result["decision"] = "APPLY"
        result["reasons"] = reasons
        result["missing"] = missing
        return result

    # 3. REVIEW — терминальное решение.
    # REVIEW никогда не превращается автоматически в APPLY.
    if decision == "REVIEW":
        if has_required_gap:
            reasons.insert(
                0,
                (
                    "Программное правило (post-evaluator guard): REVIEW "
                    f"переведён в REJECT — найден нарушенный required-требование: {_gap_explanation()}."
                ),
            )
            result["decision"] = "REJECT"
            result["score"] = min(int(result.get("score", GUARD_SCORE_REJECT) or GUARD_SCORE_REJECT), GUARD_SCORE_REJECT)
            result["reasons"] = reasons
            result["missing"] = missing
            result["summary"] = "Отклонено программным правилом: обязательное требование не подтверждено профилем."
            return result

        # ИСПРАВЛЕНИЕ ("0 APPLY из 218/из 387 обработанных"):
        # докстринг модуля (см. выше, "ФИКС #2" и правило 3 в
        # докстринге apply_post_evaluator_guard) описывает, что при
        # отсутствии required-разрыва REVIEW должен переводиться в
        # APPLY с полом score = POST_GUARD_APPLY_SCORE_FLOOR. В коде
        # этой ветки не было — REVIEW безусловно оставался REVIEW,
        # то есть автокликер в принципе не мог отправить ни одного
        # отклика, даже когда качество совпадения было хорошим.
        # Восстановлено ровно то поведение, которое уже было
        # задокументировано выше.
        reasons.insert(
            0,
            (
                "Программное правило (post-evaluator guard): REVIEW "
                "переведён в APPLY — явного нарушенного required-"
                "требования не найдено, оставшееся сомнение evaluator'а "
                "не подкреплено формальным требованием вакансии."
            ),
        )
        result["decision"] = "APPLY"
        result["score"] = max(
            int(result.get("score", POST_GUARD_APPLY_SCORE_FLOOR) or POST_GUARD_APPLY_SCORE_FLOOR),
            POST_GUARD_APPLY_SCORE_FLOOR,
        )
        result["reasons"] = reasons
        result["missing"] = missing
        result["summary"] = (
            "Пограничный случай без объяснимого формального "
            "препятствия — автоматический отклик отправлен."
        )
        return result

    result["decision"] = decision
    result["reasons"] = reasons
    result["missing"] = missing
    return result

