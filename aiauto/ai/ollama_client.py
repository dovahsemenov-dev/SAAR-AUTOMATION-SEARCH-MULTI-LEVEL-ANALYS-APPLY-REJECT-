import json

import requests


# Ollama всегда работает локально (127.0.0.1 / localhost).
# Если в системе включён прокси (например, Hiddify в режиме
# System Proxy), requests по умолчанию подхватывает системные
# переменные прокси и пытается завернуть в них даже локальные
# запросы — из-за чего Ollama становится недоступна, пока прокси
# включён. NO_PROXY явно отключает прокси для ЭТИХ конкретных
# запросов, не трогая остальной трафик (например, Playwright,
# который ходит на hh.ru и должен использовать прокси как обычно).
NO_PROXY = {
    "http": None,
    "https": None,
}


def check_ready(ollama_url: str, model_name: str) -> bool:
    try:
        response = requests.get(
            f"{ollama_url}/api/tags",
            timeout=5,
            proxies=NO_PROXY,
        )
        response.raise_for_status()

        models = response.json().get("models", [])
        names = [
            model.get("name")
            for model in models
        ]

        return model_name in names

    except requests.RequestException:
        return False


def ask_json(
    ollama_url: str,
    model_name: str,
    prompt: str,
) -> dict:
    payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0,
        },
    }

    response = requests.post(
        f"{ollama_url}/api/generate",
        json=payload,
        timeout=300,
        proxies=NO_PROXY,
    )
    response.raise_for_status()

    raw_text = response.json()["response"]

    try:
        return json.loads(raw_text)

    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"Qwen вернула невалидный JSON:\n{raw_text}"
        ) from error


def ask_vision(
    ollama_url: str,
    model_name: str,
    prompt: str,
    image_base64: str,
    num_predict: int = 300,
) -> str:
    """
    Вызов vision-модели (например, qwen2.5vl:3b) с одним изображением.

    Используется для анализа скриншота области CAPTCHA после
    того, как её обнаружил hh/browser.py (check_blocked/
    wait_for_unblock). Теперь функция корректно возвращает текстовый ответ
    модели в вызывающий код, чтобы система могла выполнить автоматический ввод.

    Ошибки (Ollama недоступна, модель не загружена и т.п.) эта
    функция не глотает — поднимает их как обычно (requests.
    raise_for_status и т.п.). Гасить их и не давать уронить основной
    цикл кликера — забота вызывающего кода в hh/browser.py.
    """
    payload = {
        "model": model_name,
        "prompt": prompt,
        "images": [image_base64],
        "stream": False,
        "options": {
            "temperature": 0,
            "num_predict": num_predict,
        },
    }

    response = requests.post(
        f"{ollama_url}/api/generate",
        json=payload,
        timeout=300,
        proxies=NO_PROXY,
    )
    response.raise_for_status()

    # ИЗМЕНЕНИЕ: Возвращаем очищенный текст для автоматического ввода
    return response.json().get("response", "").strip()


def ask_text(
    ollama_url: str,
    model_name: str,
    prompt: str,
    num_predict: int = 600,
) -> str:
    """
    Вызов модели БЕЗ принудительного "format": "json".

    Причина существования этой функции — подтверждённый баг
    генерации писем: "format": "json" заставляет Ollama делать
    constrained-декодирование под JSON-грамматику на каждом токене.
    Для длинного строкового поля (текст письма на русском, несколько
    предложений) 7B-модель под таким давлением регулярно "сдаётся"
    и закрывает строку пустой — {"letter": ""}. Это СИНТАКСИЧЕСКИ
    валидный JSON, поэтому ask_json() не бросает исключение и не
    логирует ошибку — отказ модели молча проходит как "успешный"
    вызов с пустым результатом. Это и объясняет картину из прогонов:
    "Ошибки: 0", но почти все письма пустые.

    ask_text() отдаёт модели обычный текстовый режим (никакой
    грамматики поверх токенов) — только температура и ограничение на
    число токенов, чтобы не обрезать длинное письмо раньше времени.
    Промпт, вызывающий эту функцию, должен сам попросить модель
    обернуть ответ в текстовые маркеры (см. cover_letter.py) —
    парсинг маркеров надёжнее для многострочного текста, чем
    json.loads с неэкранированными кавычками/переносами строк.

    Используется пока только для генерации письма. Остальные шаги
    (классификация, выбор фактов, валидация письма и т.д.) отдают
    короткий структурированный результат, где формат JSON и раньше
    не показывал этой проблемы, — их менять не нужно.
    """
    payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0,
            "num_predict": num_predict,
        },
    }

    response = requests.post(
        f"{ollama_url}/api/generate",
        json=payload,
        timeout=300,
        proxies=NO_PROXY,
    )
    response.raise_for_status()

    return response.json().get("response", "").strip()
