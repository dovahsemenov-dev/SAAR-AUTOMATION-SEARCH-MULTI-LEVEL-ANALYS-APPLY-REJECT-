

# filters/rules.py

import re

from filters.fast_filter import (
    detect_extended_target_role,
    EXTENDED_TARGET_TITLE_HARD_REJECT_MARKERS,
)


NON_IT_ROLE_MARKERS = [
    "call-центра",
    "оператор call",

    # Сознательное решение пользователя: "консультант"
    # и "техническая поддержка"/"техподдержка" — НЕ
    # чистое IT-направление (разработка/тестирование),
    # даже если формально относится к IT-отрасли.
    # Режем по префиксу, чтобы поймать все словоформы:
    # "техническая поддержка", "техподдержка",
    # "технической поддержки", "технический специалист"
    # и т.п. Причина явная: LLM-классификатор оказался
    # непоследовательным на одинаковых по сути вакансиях
    # (одна и та же должность в одном прогоне получала
    # is_it_role=True, в другом — False), поэтому здесь
    # используется детерминированное правило вместо
    # повторной попытки полагаться на Qwen.
    "консультант",
    "технич",
    "поддержк",

]



# ============================================================
# Дополнительные целевые профессии: ограничения пользователя
# ============================================================

# Только прямые обязанности по продажам/звонкам/клиентскому
# сопровождению. Намеренно НЕ включены общие слова "продажи",
# "клиенты", "лиды", потому что в performance/SEO они часто
# описывают бизнес-метрики, а не работу продавцом.
EXTENDED_TARGET_CONTACT_BLOCKERS: tuple[str, ...] = (
    "холодные звонки",
    "теплые звонки",
    "входящие звонки",
    "исходящие звонки",
    "обзвон клиентов",
    "обзванивать клиентов",
    "звонки клиентам",
    "звонить клиентам",
    "совершать звонки",
    "принимать звонки",
    "телефонные переговоры",
    "переговоры с клиентами",
    "созвоны с клиентами",
    "созвон с клиентами",
    "встречи с клиентами",
    "общение с клиентами",
    "коммуникация с клиентами",
    "коммуникации с клиентами",
    "ведение клиентов",
    "вести клиентов",
    "сопровождение клиентов",
    "сопровождать клиентов",
    "консультирование клиентов",
    "консультировать клиентов",
    "поддержка клиентов",
    "поддержка пользователей",
    "обработка входящих заявок",
    "обрабатывать входящие заявки",
    "активный поиск клиентов",
    "самостоятельный поиск клиентов",
    "поиск новых клиентов",
    "привлечение новых клиентов через звонки",
    "план продаж",
    "выполнение плана продаж",
    "закрытие сделок",
    "закрывать сделки",
    "ведение сделок",
    "продавать услуги",
    "продажа услуг",
    "продавать продукт",
    "продажа продукта",
    "customer support",
    "customer service",
    "client support",
    "account management",
    "account manager",
    "client manager",
    "cold calls",
    "outbound calls",
    "inbound calls",
)

NO_EXPERIENCE_MARKERS: tuple[str, ...] = (
    "не требуется",
    "без опыта",
    "нет опыта",
    "опыт не требуется",
    "no experience",
)


def _extended_target_contact_blocker(vacancy: dict) -> str | None:
    title = _normalize_text(vacancy.get("title") or "")
    description = _normalize_text(vacancy.get("description") or "")
    combined = f"{title} {description}".strip()

    for marker in EXTENDED_TARGET_TITLE_HARD_REJECT_MARKERS:
        normalized = _normalize_text(marker)
        if normalized and normalized in title:
            return marker

    for marker in EXTENDED_TARGET_CONTACT_BLOCKERS:
        normalized = _normalize_text(marker)
        if normalized and normalized in combined:
            return marker

    return None


def check_extended_target_constraints(vacancy: dict) -> dict:
    """
    Специальный deterministic gate только для трёх новых веток:
    Performance / SEO(+Technical SEO) / Data-BI.

    Для них пользователь требует одновременно:
      - явную удалёнку;
      - HH-опыт строго "не требуется/без опыта";
      - отсутствие прямых продаж, звонков и постоянного клиентского
        сопровождения.

    Для всех старых профессий возвращает NOT_TARGET и ничего не
    меняет в существующей логике.
    """
    role = detect_extended_target_role(vacancy.get("title") or "")
    if role is None:
        return {
            "status": "NOT_TARGET",
            "role": None,
            "reason": "Не относится к новым целевым профессиям.",
        }

    blocker = _extended_target_contact_blocker(vacancy)
    if blocker:
        return {
            "status": "REJECT",
            "role": role,
            "reason": (
                "Новая целевая профессия отклонена: обнаружена прямая "
                "продажная/клиентская обязанность или роль "
                f"('{blocker}')."
            ),
        }

    parsed_format = _parse_work_format(vacancy)
    if not parsed_format["remote"]:
        return {
            "status": "REJECT",
            "role": role,
            "reason": (
                "Для Performance/SEO/Data-BI разрешена только явная "
                "удалённая работа; HH не подтвердил REMOTE."
            ),
        }

    raw_experience = _normalize_text(vacancy.get("experience") or "")
    if not any(marker in raw_experience for marker in NO_EXPERIENCE_MARKERS):
        return {
            "status": "REJECT",
            "role": role,
            "reason": (
                "Для Performance/SEO/Data-BI разрешены только вакансии "
                "с HH-опытом 'не требуется/без опыта'. Получено: "
                f"'{vacancy.get('experience', '')}'."
            ),
        }

    return {
        "status": "PASS",
        "role": role,
        "reason": (
            "Новая целевая профессия разрешена: HH явно указывает "
            "REMOTE и отсутствие требуемого опыта; прямые продажи/"
            "звонки/клиентское сопровождение не обнаружены."
        ),
    }


# Разрешаем офис/гибрид только в Башкортостане и Татарстане.
# Основные города перечислены как дополнительная страховка,
# поскольку HH часто отдаёт именно город, а не субъект РФ.
ALLOWED_LOCAL_LOCATIONS = (
    # Башкортостан
    "республика башкортостан",
    "башкортостан",
    "уфа",
    "стерлитамак",
    "салават",
    "нефтекамск",
    "октябрьский",
    "туймазы",
    "белорецк",
    "ишимбай",
    "сибай",

    # Татарстан
    "республика татарстан",
    "татарстан",
    "казань",
    "набережные челны",
    "нижнекамск",
    "альметьевск",
    "елабуга",
    "зеленодольск",
)


def _normalize_text(value: str) -> str:
    """
    Нормализация текста перед сравнением.

    Важно: нормализуем и значение HH, и наши маркеры
    одинаковым способом.
    """
    return " ".join(
        str(value or "")
        .lower()
        .replace("ё", "е")
        .split()
    )


def quick_reject(
    vacancy: dict,
    stop_words: list[str],
) -> str | None:
    """
    Самый ранний hard-filter.

    Здесь разрешены только очевидные случаи, которые
    не требуют смыслового анализа LLM.
    """
    title = vacancy.get("title") or ""
    description = vacancy.get("description") or ""

    # ФИКС (реальный прогон, вакансия [77/460], Playrix,
    # "Game Designer (Playables)"): title у вакансии оказался
    # пустой строкой (не удалось распарсить со страницы), но
    # раньше это никак не проверялось — пустая вакансия спокойно
    # проходила geography/experience/classify_vacancy и в итоге
    # получила APPLY. Название — не менее критичные данные, чем
    # описание (см. проверку description.strip() ниже), поэтому
    # добавляем симметричную защиту.
    if not title.strip():
        return "Не удалось получить название вакансии"

    title_normalized = _normalize_text(title)

    for word in stop_words:
        word_normalized = _normalize_text(word)

        if (
            word_normalized
            and word_normalized in title_normalized
        ):
            return (
                "Стоп-слово в названии: "
                f"'{word}'"
            )

    extended_role = detect_extended_target_role(title)

    # Для новых целевых веток не применяем старый общий NON_IT-
    # blacklist: он содержит слишком широкие маркеры вроде
    # "маркетолог" и "технич", которые убили бы Performance и
    # Technical SEO. Их собственные ограничения проверяются
    # отдельным check_extended_target_constraints() в main.py.
    if extended_role is None:
        for marker in NON_IT_ROLE_MARKERS:
            marker_normalized = _normalize_text(marker)

            if marker_normalized in title_normalized:
                return (
                    "Явно не-IT профессия "
                    f"(маркер в названии: '{marker}')"
                )

    if not description.strip():
        return "Не удалось получить описание вакансии"

    return None


def _is_allowed_local_location(location: str) -> bool:
    normalized_location = _normalize_text(location)

    return any(
        _normalize_text(marker) in normalized_location
        for marker in ALLOWED_LOCAL_LOCATIONS
    )


def _parse_work_format(vacancy: dict) -> dict:
    """
    Повторно проверяет исходную строку HH.

    Мы НЕ доверяем слепо boolean-флагам из vacancy.py:
    исходный raw остаётся источником истины.

    Это защищает от уже обнаруженного бага:
    'Формат работы: на месте работодателя'
    ошибочно превращался в unknown.
    """
    source = vacancy.get("work_format") or {}

    if isinstance(source, dict):
        raw = str(source.get("raw", "") or "")
    else:
        raw = str(source or "")

    text = _normalize_text(raw)

    remote_markers = (
        "удаленно",
        "удаленная",
        "удаленный",
        "дистанционно",
        "дистанционная",
        "remote",
    )

    hybrid_markers = (
        "гибрид",
        "hybrid",
    )

    office_markers = (
        "на месте работодателя",
        "офисный",
        "в офисе",
        "работа в офисе",
    )

    remote = any(
        _normalize_text(marker) in text
        for marker in remote_markers
    )

    hybrid = any(
        _normalize_text(marker) in text
        for marker in hybrid_markers
    )

    office = any(
        _normalize_text(marker) in text
        for marker in office_markers
    )

    return {
        "raw": raw,
        "remote": remote,
        "hybrid": hybrid,
        "office": office,
        "unknown": not (
            remote
            or hybrid
            or office
        ),
    }


def check_geography(vacancy: dict) -> dict:
    """
    Детерминированная проверка географии.

    Правила пользователя:

    1. Если HH ЯВНО разрешает удалённую работу:
       PASS независимо от адреса офиса.

    2. Если работа только офисная или гибридная:
       PASS только для Башкортостана/Татарстана.

    3. Офис/гибрид в Москве, Санкт-Петербурге,
       Минске, Ташкенте, Нижнем Новгороде и т.д.:
       REJECT.

    4. Если HH не дал достаточно структурированных
       данных:
       REVIEW_REQUIRED.

    Qwen здесь ничего не решает.
    """
    parsed_format = _parse_work_format(vacancy)

    raw_format = parsed_format["raw"]
    remote = parsed_format["remote"]
    hybrid = parsed_format["hybrid"]
    office = parsed_format["office"]
    unknown = parsed_format["unknown"]

    location = str(
        vacancy.get("location", "") or ""
    ).strip()

    location_known = (
        bool(location)
        and _normalize_text(location)
        not in {
            "",
            "не указано",
            "не указан",
            "unknown",
        }
    )

    # Если среди допустимых форматов HH явно есть удалёнка,
    # физический адрес работодателя не блокирует вакансию.
    if remote:
        return {
            "status": "PASS",
            "reason": (
                "HH явно допускает удалённый "
                "формат работы."
            ),
            "work_format": raw_format,
            "location": location,
        }

    # Гибрид означает обязательное присутствие хотя бы
    # часть времени, поэтому применяем локальную географию.
    if hybrid or office:
        if not location_known:
            return {
                "status": "REVIEW_REQUIRED",
                "reason": (
                    "HH указал офисный/гибридный "
                    "формат, но местоположение "
                    "не удалось достоверно получить."
                ),
                "work_format": raw_format,
                "location": location,
            }

        if _is_allowed_local_location(location):
            return {
                "status": "PASS",
                "reason": (
                    "Офисный/гибридный формат "
                    "находится в допустимом регионе: "
                    "Башкортостан или Татарстан."
                ),
                "work_format": raw_format,
                "location": location,
            }

        return {
            "status": "REJECT",
            "reason": (
                "Офисный/гибридный формат за "
                "пределами Башкортостана "
                "и Татарстана."
            ),
            "work_format": raw_format,
            "location": location,
        }

    if unknown:
        return {
            "status": "REVIEW_REQUIRED",
            "reason": (
                "Формат работы не удалось "
                "однозначно определить по "
                "структурированному полю HH."
            ),
            "work_format": raw_format,
            "location": location,
        }

    return {
        "status": "REVIEW_REQUIRED",
        "reason": (
            "Недостаточно данных для проверки "
            "географии."
        ),
        "work_format": raw_format,
        "location": location,
    }


def _parse_experience_years_min(raw: str) -> int | None:
    """
    Извлекает минимальное количество лет опыта из
    сырой строки HH вида '3–6 лет', '1–3 года',
    'более 6 лет', 'не требуется'.

    Намеренно не парсит формулировки по словам —
    берёт минимальное число из строки. Это устойчиво
    к любому виду тире (обычный '-' или юникодный '–'/'—'),
    потому что ищет только цифры через regex, а не режет
    строку по конкретному символу-разделителю.

    Возвращает None, если цифр в строке нет вообще
    и это не похоже на 'опыт не нужен' — то есть данные
    отсутствуют/непонятны, а не действительно нулевой опыт.
    """
    text = _normalize_text(raw)

    if not text:
        return None

    no_experience_markers = (
        "не требуется",
        "нет опыта",
        "без опыта",
    )

    if any(
        marker in text
        for marker in no_experience_markers
    ):
        return 0

    numbers = [
        int(match)
        for match in re.findall(r"\d+", text)
    ]

    if not numbers:
        return None

    return min(numbers)


def check_experience(
    vacancy: dict,
    max_allowed_years_min: int,
) -> dict:
    """
    Детерминированный ранний фильтр по требуемому опыту.

    Сознательный trade-off (обсуждён с пользователем):
    режем по грубой вилке HH ДО любого обращения к Qwen,
    даже зная, что теряем редкие случаи, где в тексте
    вакансии вилка описана как "ориентир, а не строгий
    фильтр" (кейс Cropix). Пользователь явно выбрал
    скорость вместо этих редких спасённых случаев.

    max_allowed_years_min: максимальный допустимый
    years_min ВКЛЮЧИТЕЛЬНО. Например, 2 означает:
    '1-3 года' проходит, '3-6 лет' отклоняется.
    """
    raw = str(vacancy.get("experience", "") or "")
    years_min = _parse_experience_years_min(raw)

    if years_min is None:
        return {
            "status": "REVIEW_REQUIRED",
            "reason": (
                "Не удалось разобрать требуемый опыт "
                f"из значения HH: '{raw}'"
            ),
            "years_min": None,
        }

    if years_min > max_allowed_years_min:
        return {
            "status": "REJECT",
            "reason": (
                "Ранний отказ по вилке опыта HH "
                f"('{raw}', years_min={years_min}), "
                f"допустимый максимум: {max_allowed_years_min}."
            ),
            "years_min": years_min,
        }

    return {
        "status": "PASS",
        "reason": (
            f"Вилка опыта HH ('{raw}', "
            f"years_min={years_min}) в допустимых "
            "пределах."
        ),
        "years_min": years_min,
    }


