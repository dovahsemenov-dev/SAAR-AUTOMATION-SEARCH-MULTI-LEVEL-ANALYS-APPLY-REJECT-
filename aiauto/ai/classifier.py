# ai/classifier.py

from ai.ollama_client import ask_json
from filters.fast_filter import (
    EXTENDED_TARGET_TITLE_HARD_REJECT_MARKERS,
    _text_has_any,
    detect_extended_target_role,
)


OBVIOUS_IT_TITLE_MARKERS = (
    "qa ",
    "qa-",
    "qa_",
    "qa engineer",
    "qa-инженер",
    "тестировщик",
    "тестирование по",
    "software tester",
    "developer",
    "разработчик",
    "devops",
    "data engineer",
    "data analyst",
    "system analyst",
    "системный аналитик",
    "frontend",
    "backend",
    "fullstack",
    "full stack",
    "programmer",
    "программист",
)


def build_classification_prompt(
    vacancy: dict,
) -> str:
    description = (
        vacancy.get("description")
        or ""
    )

    return f"""
Ты выполняешь ОДНУ задачу:
определяешь, является ли сама ПРОФЕССИЯ
в вакансии IT-профессией.

Тебе НЕ известен профиль кандидата.
Не анализируй соответствие кандидата.
Не анализируй зарплату.
Не анализируй образование кандидата.
Не анализируй географию.

IT-профессии:
разработка ПО, QA и тестирование ПО,
QA Automation, frontend, backend,
mobile development, DevOps,
системное администрирование,
компьютерные сети,
информационная безопасность,
базы данных, системный анализ,
IT-бизнес-анализ, data, AI/ML,
UX/UI, автоматизация, API,
интеграции и техническая поддержка
IT-продуктов.

ОТДЕЛЬНО РАЗРЕШЁННЫЕ ЦЕЛЕВЫЕ DIGITAL/DATA-ПРОФЕССИИ:
Performance Marketing / PPC / контекстная реклама,
SEO и Technical SEO, Data Analyst и BI Analyst.
Эти направления считаются допустимыми целевыми профессиями
и должны получать is_it_role=true, даже если Performance/SEO
формально относятся к digital-маркетингу, а не к разработке ПО.

НЕ IT-профессии:
горное дело, строительство,Мастер по ремонту,Специалист поддержки,консультант,менеджер
производственные инженерные должности,
HR, рекрутинг, продажи,
бухгалтерия, юриспруденция,
обычный call-центр,
академическая администрация вуза
и другие нетехнические профессии.

КРИТИЧЕСКОЕ ПРАВИЛО:
если должность — тестировщик ПО,
QA Engineer, разработчик ПО или другая
очевидная техническая IT-должность,
is_it_role должен быть true,
даже если продукт используется
в горной, банковской, образовательной
или любой другой отрасли.

Оценивай профессию, а не отрасль клиента.

Название:
{vacancy.get("title", "")}

Компания:
{vacancy.get("company", "")}

Описание:
{description[:4000]}

Верни ТОЛЬКО JSON:

{{
  "is_it_role": true,
  "role_summary": "краткое название профессии",
  "reason": "почему это IT или не IT"
}}
""".strip()


def _parse_bool(value) -> bool | None:
    if isinstance(value, bool):
        return value

    text = str(value).strip().lower()

    if text in {
        "true",
        "1",
        "yes",
        "да",
    }:
        return True

    if text in {
        "false",
        "0",
        "no",
        "нет",
    }:
        return False

    return None


HARDWARE_TESTING_MARKERS = (
    "тестировщик оборудования",
    "тестировщик техники",
    "тестировщик электроники",
    "тестирование оборудования",
    "тестирование техники",
    "испытатель оборудования",
    "испытатель техники",
    "испытатель электроники",
    "испытания оборудования",
    "испытания техники",
    "электронное оборудование",
    "электроника",
    "электротехник",
    "электрические схемы",
    "печатные платы",
    "контроллеры",
    "осциллограф",
    "измерительное оборудование",
    "измерительные приборы",
    "радиоэлектрон",
    "стенд испытаний",
    "стенды испытаний",
    "сервисный центр",
    "мастерская",
)


IT_DOMAIN_MARKERS = (
    "api", "postman", "sql", "jira", "git", "gitlab",
    "тест-кейс", "тест кейс", "баг-репорт", "баг репорт",
    "программн", "по ", "software", "web", "мобильн",
    "frontend", "backend", "fullstack", "python", "java",
    "javascript", "typescript", "selenium", "playwright",
    "devtools", "http", "rest", "json", "docker", "kubernetes",
    "ci/cd", "qa automation", "автоматизац", "интеграционн",
    "база данных", "бд", "микросервис", "github", "testit",
)


def _is_hardware_testing_role(
    title: str,
    description: str,
) -> bool:
    text = (str(title or "") + " " + str(description or "")).lower().replace("ё", "е")
    hardware_hits = sum(1 for marker in HARDWARE_TESTING_MARKERS if marker in text)
    if hardware_hits < 1:
        return False

    # Если в описании есть явный IT/QA-стек, это может быть тестирование
    # ПО для аппаратного продукта — тогда не режем вакансию.
    it_hits = sum(1 for marker in IT_DOMAIN_MARKERS if marker in text)
    return it_hits == 0


def _title_is_obviously_it(
    title: str,
) -> bool:
    normalized = (
        title
        .lower()
        .replace("ё", "е")
    )

    return any(
        marker in normalized
        for marker in OBVIOUS_IT_TITLE_MARKERS
    )


def classify_vacancy(
    ollama_url: str,
    model_name: str,
    vacancy: dict,
) -> dict:
    title = str(vacancy.get("title", ""))
    description = str(vacancy.get("description", ""))

    # Performance / SEO(+Technical SEO) / Data-BI разрешены
    # пользователем явно. Не отдаём их на нестабильную бинарную
    # IT/non-IT классификацию Qwen: иначе Performance/SEO могут
    # случайно получить False просто потому, что это digital, а не
    # классическая разработка. Ограничения REMOTE/NO EXPERIENCE/
    # отсутствие продаж проверяются отдельным Python-guard раньше.
    extended_role = detect_extended_target_role(title)
    if extended_role is not None:
        # Защита от контаминации: "вайб-кодинг"/"нейросети" в названии
        # не значит, что сама профессия — разработка. Бизнес-ассистенты,
        # секретари, рекрутеры и HR тоже пишут в названии "нейросети" и
        # "вайб-кодинг", имея в виду использование ИИ как инструмента
        # для НЕ-IT работы (звонки, договоры, подбор персонала), а не
        # саму профессию. Та же проверка, что и в filters/fast_filter.py
        # classify_fast(), чтобы оба слоя классификации были согласованы.
        extended_block = _text_has_any(
            title,
            EXTENDED_TARGET_TITLE_HARD_REJECT_MARKERS,
        )
        if extended_block is None:
            labels = {
                "performance": "Performance Marketing / PPC",
                "seo": "SEO / Technical SEO",
                "data_bi": "Data / BI Analytics",
                "vibecoder": "VibeCoder",
            }
            return {
                "is_it_role": True,
                "role_summary": labels.get(extended_role, extended_role),
                "reason": (
                    "Профессия входит в отдельный пользовательский whitelist "
                    "Performance / SEO / Data-BI."
                ),
                "guard_applied": True,
            }
        # extended_role сработал, но в названии есть маркер НЕ-IT роли
        # (ассистент/секретарь/рекрутер и т.п.) — не выдаём автопропуск,
        # падаем дальше в обычную классификацию Qwen/hardware-guard.

    # Тестировщик техники/оборудования без IT-стека — это не QA ПО.
    # Не позволяем Qwen смешивать эти профессии только из-за слова
    # "тестировщик" в названии.
    if _is_hardware_testing_role(title, description):
        return {
            "is_it_role": False,
            "role_summary": "Тестировщик/испытатель техники или оборудования",
            "reason": (
                "В вакансии преобладают маркеры физического оборудования/"
                "испытаний, при этом явный IT/QA-стек не обнаружен."
            ),
            "guard_applied": True,
        }

    prompt = build_classification_prompt(
        vacancy
    )

    raw = ask_json(
        ollama_url,
        model_name,
        prompt,
    )

    if not isinstance(raw, dict):
        return {
            "is_it_role": True,
            "role_summary": (
                "Не удалось надёжно "
                "классифицировать профессию"
            ),
            "reason": (
                "Некорректный ответ "
                "классификатора; вакансия "
                "не отклонена автоматически."
            ),
            "guard_applied": True,
        }

    parsed = _parse_bool(
        raw.get("is_it_role")
    )

    role_summary = str(
        raw.get(
            "role_summary",
            "",
        )
    ).strip()

    reason = str(
        raw.get(
            "reason",
            "",
        )
    ).strip()

    title = str(
        vacancy.get(
            "title",
            "",
        )
    )

    # Fail-safe:
    # QA-инженер не может стать non-IT только
    # из-за нестабильного ответа маленькой LLM.
    if (
        parsed is False
        and _title_is_obviously_it(title)
    ):
        return {
            "is_it_role": True,
            "role_summary": (
                role_summary
                or "Очевидная IT-профессия "
                   "по названию вакансии"
            ),
            "reason": (
                "Классификатор вернул non-IT, "
                "но название вакансии содержит "
                "однозначный маркер технической "
                "IT-профессии. Применён "
                "защитный sanity-check."
            ),
            "guard_applied": True,
        }

    if parsed is None:
        return {
            "is_it_role": True,
            "role_summary": (
                role_summary
                or "Неоднозначная классификация"
            ),
            "reason": (
                "Поле is_it_role невозможно "
                "надёжно разобрать; вакансия "
                "не отклонена автоматически."
            ),
            "guard_applied": True,
        }

    return {
        "is_it_role": parsed,
        "role_summary": role_summary,
        "reason": reason,
        "guard_applied": False,
    }