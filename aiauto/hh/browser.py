# hh/browser.py
import base64
import random
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, Page

from ai.ollama_client import ask_vision

BLOCK_MARKERS = (
    "подтвердите, что вы не робот",
    "подтвердите что вы не робот",
    "captcha",
    "капча",
    "проверка безопасности",
    "проверка браузера",
    "доступ ограничен",
    "слишком много запросов",
    "too many requests",
    "access denied",
)

BLOCK_URL_MARKERS = (
    "captcha",
    "challenge",
    "blocked",
    "security-check",
)

BLOCK_SELECTORS = (
    'iframe[src*="captcha"]',
    'iframe[src*="challenge"]',
    '[data-captcha]',
    '[class*="captcha"]',
    '[id*="captcha"]',
)

SAFE_CAPTCHA_MARKERS = (
    "grecaptcha-badge",
    "g-recaptcha-badge",
    "recaptcha-badge",
)

MAX_BLOCK_PAGE_TEXT_LEN = 2000

ALERT_INTERVAL_SEC = 20


def _alert_beep() -> None:
    try:
        import winsound

        for _ in range(3):
            winsound.Beep(1200, 250)
            time.sleep(0.15)

        return
    except Exception:
        pass

    try:
        print("\a", end="", flush=True)
    except Exception:
        pass


def start_browser(profile_dir, headless: bool):
    playwright = sync_playwright().start()

    screen_width = random.randint(1366, 1600)
    screen_height = random.randint(850, 1000)

    context = playwright.chromium.launch_persistent_context(
        user_data_dir=str(profile_dir),
        channel="chrome",
        headless=headless,
        no_viewport=True,
        args=[
            f"--window-size={screen_width},{screen_height}",
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
            "--start-maximized",
            "--disable-use-side-by-side-windowlayout",
        ],
    )

    context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        });
    """)

    context.add_init_script("""
        Object.defineProperty(navigator, 'languages', {
            get: () => ['ru-RU', 'ru', 'en-US', 'en']
        });

        Object.defineProperty(navigator, 'plugins', {
            get: () => [
                {
                    name: 'PDF Viewer',
                    filename: 'internal-pdf-viewer',
                    description: 'Portable Document Format'
                },
                {
                    name: 'Chrome PDF Viewer',
                    filename: 'mhjfbmdgcfjbbpaeojofohoefgieooff',
                    description: ''
                }
            ]
        });

        const getParameter = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function(parameter) {
            if (parameter === 37445) return 'Intel Inc.';
            if (parameter === 37446) return 'Intel(R) Iris(R) Xe Graphics';
            return getParameter.apply(this, arguments);
        };
    """)

    page = context.pages[0] if context.pages else context.new_page()

    page.set_extra_http_headers({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/128.0.0.0 Safari/537.36"
        )
    })

    return playwright, context, page


def stop_browser(playwright, context):
    context.close()
    playwright.stop()


def _element_is_visibly_rendered(locator) -> bool:
    try:
        if not locator.first.is_visible(timeout=1000):
            return False
    except Exception:
        return False

    try:
        box = locator.first.bounding_box()
    except Exception:
        box = None

    if not box:
        return False

    if box.get("width", 0) < 5 or box.get("height", 0) < 5:
        return False

    return True


def _selector_matches_are_safe(page, selector: str) -> bool:
    try:
        locator = page.locator(selector)
        count = locator.count()
    except Exception:
        return False

    if count == 0:
        return True

    for i in range(count):
        try:
            el = locator.nth(i)
            class_attr = (el.get_attribute("class") or "").lower()
            id_attr = (el.get_attribute("id") or "").lower()
            src_attr = (el.get_attribute("src") or "").lower()
        except Exception:
            class_attr = id_attr = src_attr = ""

        combined = f"{class_attr} {id_attr} {src_attr}"
        is_known_safe = any(marker in combined for marker in SAFE_CAPTCHA_MARKERS)

        if is_known_safe:
            continue

        return False

    return True


def check_blocked(page) -> dict:
    try:
        url = str(page.url or "").lower()
    except Exception:
        url = ""

    for marker in BLOCK_URL_MARKERS:
        if marker in url:
            return {
                "blocked": True,
                "reason": "url_marker",
                "detail": f"'{marker}' in URL: {url}",
            }

    try:
        title = page.title().strip().lower()
    except Exception:
        title = ""

    for marker in BLOCK_MARKERS:
        if marker in title:
            return {
                "blocked": True,
                "reason": "title_marker",
                "detail": f"'{marker}' in title: '{title}'",
            }

    try:
        body = page.locator("body")
        text = body.inner_text(timeout=3000).lower()
    except Exception:
        text = ""

    if text:
        if len(text) <= MAX_BLOCK_PAGE_TEXT_LEN:
            for marker in BLOCK_MARKERS:
                if marker in text:
                    snippet_start = max(text.find(marker) - 40, 0)
                    snippet = text[snippet_start:snippet_start + 120]
                    return {
                        "blocked": True,
                        "reason": "text_marker",
                        "detail": f"'{marker}' в тексте страницы (len={len(text)}): ...{snippet}...",
                    }
        else:
            pass

    for selector in BLOCK_SELECTORS:
        try:
            locator = page.locator(selector)
            count = locator.count()
        except Exception:
            continue

        if count == 0:
            continue

        if _selector_matches_are_safe(page, selector):
            continue

        if _element_is_visibly_rendered(locator):
            try:
                class_attr = locator.first.get_attribute("class") or ""
                id_attr = locator.first.get_attribute("id") or ""
            except Exception:
                class_attr = id_attr = ""
            return {
                "blocked": True,
                "reason": "dom_selector",
                "detail": (
                    f"селектор '{selector}' совпал и видим на экране "
                    f"(class='{class_attr}', id='{id_attr}')"
                ),
            }

    return {"blocked": False, "reason": "none", "detail": ""}


def is_blocked(page) -> bool:
    return check_blocked(page)["blocked"]


def _save_block_diagnostics(page, stage: str, reason: str, detail: str, debug_dir=None) -> None:
    try:
        target_dir = Path(debug_dir) if debug_dir else Path("data/debug_dumps")
        target_dir.mkdir(parents=True, exist_ok=True)

        ts = int(time.time())
        base = target_dir / f"BLOCK_{ts}"

        try:
            page.screenshot(path=str(base) + ".png", full_page=True)
        except Exception:
            pass

        try:
            html = page.content()
        except Exception:
            html = ""

        with open(str(base) + ".html", "w", encoding="utf-8") as f:
            f.write(html)

        with open(str(base) + "_reason.txt", "w", encoding="utf-8") as f:
            f.write(f"stage: {stage}\n")
            f.write(f"reason: {reason}\n")
            f.write(f"detail: {detail}\n")
            try:
                f.write(f"url: {page.url}\n")
            except Exception:
                pass

        print(f"[CAPTCHA][DEBUG] Диагностика сохранена: {base}.png / .html / _reason.txt")
    except Exception as exc:
        print(f"[CAPTCHA][DEBUG] Не удалось сохранить диагностику блокировки: {exc}")


def ensure_not_blocked(page, stage: str = "", debug_dir=None) -> None:
    result = check_blocked(page)
    if result["blocked"]:
        _save_block_diagnostics(page, stage, result["reason"], result["detail"], debug_dir)
        suffix = f" ({stage})" if stage else ""
        raise BlockedPageError(
            f"HH CAPTCHA/блокировка обнаружена{suffix}. "
            f"[{result['reason']}] {result['detail']}"
        )


def capture_captcha_region(
        page,
        x: int,
        y: int,
        width: int,
        height: int,
        debug_dir=None,
):
    try:
        image_bytes = page.screenshot(
            clip={
                "x": x,
                "y": y,
                "width": width,
                "height": height,
            },
        )
    except Exception as exc:
        print(
            f"[CAPTCHA VISION] Не удалось сделать скриншот "
            f"области ({x}, {y}, {width}x{height}): {exc}"
        )
        return None

    if debug_dir:
        try:
            target_dir = Path(debug_dir)
            target_dir.mkdir(parents=True, exist_ok=True)
            ts = int(time.time())
            with open(
                    target_dir / f"CAPTCHA_VISION_{ts}.png",
                    "wb",
            ) as f:
                f.write(image_bytes)
        except Exception:
            pass

    return image_bytes


def send_captcha_screenshot_to_vision(
    image_bytes,
    ollama_url: str,
    model_name: str,
):
    try:
        image_base64 = base64.b64encode(image_bytes).decode("ascii")

        return ask_vision(
            ollama_url,
            model_name,
            (
                "Ты — прецизионный OCR-сканер. Твоя задача — считать символы с капчи hh.ru.\n\n"
                "ОСОБЕННОСТИ КАРТИНКИ, КОТОРЫЕ ТЫ ДОЛЖЕН УЧЕСТЬ:\n"
                "1. Текст на картинке ИЗОГНУТ ПО ДУГЕ или волной. Внимательно прослеживай траекторию каждой буквы от начала до конца.\n"
                "2. На картинке написан СЛУЧАЙНЫЙ НАБОР РУССКИХ БУКВ, а не реальные слова. Таких слов не существует в словаре! "
                "Категорически запрещено «додумывать» или «исправлять» буквы под знакомые слова. Читай только то, что нарисовано физически.\n"
                "3. Обычно на картинке две отдельные группы букв (два псевдо-слова).\n\n"
                "ПРАВИЛА ОТВЕТА:\n"
                "- Выведи первую группу букв слитно, затем сделай ОДИН ПРОБЕЛ, затем выведи вторую группу букв слитно.\n"
                "- Не пиши никаких пояснений, вводных слов, знаков препинания. В ответе должен быть ТОЛЬКО финальный текст."
            ),
            image_base64,
        )
    except Exception as exc:
        print(f"[CAPTCHA VISION] Ошибка при обращении к Qwen-VL: {exc}")
        return None


def analyze_captcha_with_vision(
        page,
        vision_enabled: bool,
        ollama_url: str,
        model_name: str,
        region: dict,
        debug_dir=None,
) -> str | None:
    if not vision_enabled:
        return None

    try:
        print("[CAPTCHA VISION] Динамический поиск элемента капчи на странице...")

        # Точный селектор картинки капчи из вашего out_html
        captcha_element = page.locator("img[data-qa='account-captcha-picture']").first

        if captcha_element.count() == 0 or not captcha_element.is_visible(timeout=3000):
            # Пробуем запасной вариант по классу
            captcha_element = page.locator("img[class*='hhcaptcha-picture']").first

        if captcha_element.count() == 0:
            print("[CAPTCHA VISION] Ошибка: Картинка капчи не найдена на странице. Проверяю по координатам...")
            # Если элемент вообще не найден, откатываемся на старый метод по координатам
            image_bytes = capture_captcha_region(
                page,
                x=region.get("x", 0),
                y=region.get("y", 0),
                width=region.get("width", 0),
                height=region.get("height", 0),
                debug_dir=debug_dir,
            )
        else:
            # ДЕЛАЕМ СНИМОК КОНКРЕТНОГО ЭЛЕМЕНТА КАРТИНКИ
            print("[CAPTCHA VISION] Элемент найден. Делаю целевой скриншот капчи.")
            image_bytes = captcha_element.screenshot()

            if debug_dir:
                try:
                    from pathlib import Path
                    target_dir = Path(debug_dir)
                    target_dir.mkdir(parents=True, exist_ok=True)
                    with open(target_dir / f"CAPTCHA_TARGET_{int(time.time())}.png", "wb") as f:
                        f.write(image_bytes)
                except Exception:
                    pass

        if not image_bytes:
            return None

        result = send_captcha_screenshot_to_vision(
            image_bytes,
            ollama_url,
            model_name,
        )

        if result:
            print(f"[CAPTCHA VISION] Qwen: {result}")
            return result
        else:
            print("[CAPTCHA VISION] Qwen не вернул ответ.")
            return None

    except Exception as exc:
        print(f"[CAPTCHA VISION] Неожиданная ошибка анализа: {exc}")
        return None


def auto_input_and_submit_captcha(page: Page, captcha_text: str) -> bool:
    if not captcha_text:
        print("[CAPTCHA AUTO] Текст капчи пустой, вводить нечего.")
        return False

    cleaned_text = captcha_text.strip()
    print(f"[CAPTCHA AUTO] Попытка автоматического ввода текста: '{cleaned_text}'")

    try:
        # Ищем строгое поле ввода по разметке Magritte из вашего out_html
        captcha_input = page.locator("[data-qa='account-captcha-input']").first

        if captcha_input.count() == 0 or not captcha_input.is_visible(timeout=2000):
            print("[CAPTCHA AUTO] Не удалось найти видимое поле [data-qa='account-captcha-input'].")
            return False

        # 1. Фокусируемся и очищаем поле (имитируем человека)
        captcha_input.scroll_into_view_if_needed(timeout=2000)
        captcha_input.focus(timeout=2000)
        captcha_input.press("Control+A")
        captcha_input.press("Backspace")
        page.wait_for_timeout(200)

        # 2. Посимвольный ввод для триггера React-состояния
        captcha_input.press_sequentially(cleaned_text, delay=random.randint(50, 120))

        # 3. Жесткий фоллбэк обхода React State через JS-инъекцию
        captcha_input.evaluate("""
                               (el, val) => {
                                   const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                                   nativeSetter.call(el, val);
                                   el.dispatchEvent(new Event('input', {bubbles: true}));
                                   el.dispatchEvent(new Event('change', {bubbles: true}));
                                   el.dispatchEvent(new Event('blur', {bubbles: true}));
                               }
                               """, cleaned_text)

        page.wait_for_timeout(500)

        # 4. Отправка формы. Сначала жмем Enter
        print("[CAPTCHA AUTO] Отправка формы через Enter...")
        page.keyboard.press("Enter")
        page.wait_for_timeout(1500)

        # 5. Если страница всё ещё заблокирована, ищем кнопку "Отправить" по data-qa
        submit_btn = page.locator("[data-qa='account-captcha-submit']").first
        if submit_btn.count() > 0 and submit_btn.is_visible(timeout=500):
            print("[CAPTCHA AUTO] Enter не сработал. Кликаем по кнопке [data-qa='account-captcha-submit']")
            submit_btn.click(timeout=3000)
            page.wait_for_timeout(1500)

        return True

    except Exception as e:
        print(f"[CAPTCHA AUTO] Ошибка при автоматическом вводе: {e}")
        return False

    try:
        captcha_input.scroll_into_view_if_needed(timeout=2000)
        captcha_input.focus(timeout=2000)
        captcha_input.press("Control+A")
        captcha_input.press("Backspace")

        captcha_input.press_sequentially(cleaned_text, delay=random.randint(50, 150))

        captcha_input.evaluate("""
                               (el, val) => {
                                   const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                                   nativeSetter.call(el, val);
                                   el.dispatchEvent(new Event('input', {bubbles: true}));
                                   el.dispatchEvent(new Event('change', {bubbles: true}));
                               }
                               """, cleaned_text)

        page.wait_for_timeout(500)

        print("[CAPTCHA AUTO] Отправка формы через Enter...")
        page.keyboard.press("Enter")
        page.wait_for_timeout(2000)

        button_selectors = [
            "button[type='submit']",
            "[class*='captcha'] button",
            "button[class*='captcha']",
            "[data-qa*='submit']",
        ]

        for btn_selector in button_selectors:
            try:
                btn = page.locator(btn_selector).first
                if btn.count() > 0 and btn.is_visible(timeout=500):
                    print(f"[CAPTCHA AUTO] Клик по кнопке отправки: '{btn_selector}'")
                    btn.click(timeout=3000)
                    page.wait_for_timeout(2000)
                    break
            except Exception:
                continue

        return True

    except Exception as e:
        print(f"[CAPTCHA AUTO] Ошибка при автоматическом вводе: {e}")
        return False


class BlockedPageError(RuntimeError):
    """HH показал страницу блокировки/CAPTCHA вместо обычной страницы."""


def auto_input_and_submit_captcha(page: Page, captcha_text: str) -> bool:
    if not captcha_text:
        print("[CAPTCHA AUTO] Текст капчи пустой, вводить нечего.")
        return False

    # Очищаем текст от случайных двойных пробелов, переводим в нижний регистр, как любит HH
    cleaned_text = " ".join(captcha_text.strip().lower().split())
    print(f"[CAPTCHA AUTO] Попытка автоматического ввода текста: '{cleaned_text}'")

    try:
        captcha_input = page.locator("[data-qa='account-captcha-input']").first
        if captcha_input.count() == 0 or not captcha_input.is_visible(timeout=2000):
            return False

        # Фокусируемся и плавно очищаем поле
        captcha_input.focus(timeout=2000)
        page.wait_for_timeout(random.randint(150, 300))
        captcha_input.press("Control+A")
        page.wait_for_timeout(100)
        captcha_input.press("Backspace")
        page.wait_for_timeout(random.randint(200, 400))

        # Симулируем человеческий посимвольный ввод
        for char in cleaned_text:
            captcha_input.type(char)
            page.wait_for_timeout(random.randint(60, 200))  # Человеческая скорость

        page.wait_for_timeout(random.randint(400, 800))

        # Принудительно пихаем стейт в React на случай сбоя
        captcha_input.evaluate("""
                               (el, val) => {
                                   const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                                   nativeSetter.call(el, val);
                                   el.dispatchEvent(new Event('input', {bubbles: true}));
                                   el.dispatchEvent(new Event('change', {bubbles: true}));
                                   el.dispatchEvent(new Event('blur', {bubbles: true}));
                               }
                               """, cleaned_text)

        page.wait_for_timeout(400)

        # Кликаем по кнопке отправки вместо Enter (так надежнее для Magritte UI)
        submit_btn = page.locator("[data-qa='account-captcha-submit']").first
        if submit_btn.count() > 0 and submit_btn.is_visible(timeout=1000):
            print("[CAPTCHA AUTO] Кликаем по кнопке [data-qa='account-captcha-submit']...")
            submit_btn.click(timeout=3000)
            page.wait_for_timeout(2500)
            return True

        return False

    except Exception as e:
        print(f"[CAPTCHA AUTO] Ошибка при автоматическом вводе: {e}")
        return False


def wait_for_unblock(
        page,
        stage: str = "",
        max_wait_sec: int = 600,
        poll_interval_sec: int = 5,
        debug_dir=None,
        vision_enabled: bool = False,
        vision_ollama_url: str = "",
        vision_model: str = "",
        vision_region: dict = None,
) -> bool:
    first = check_blocked(page)
    if not first["blocked"]:
        return True

    suffix = f" ({stage})" if stage else ""
    print(f"\n[CAPTCHA] Обнаружена капча/блокировка HH{suffix}.")
    _save_block_diagnostics(page, stage, first["reason"], first["detail"], debug_dir)

    max_auto_attempts = 7  # Поднимем до 7 безопасных попыток

    if vision_enabled:
        for attempt in range(1, max_auto_attempts + 1):
            print(f"[CAPTCHA] Автоматическая попытка решения {attempt} из {max_auto_attempts}...")

            # Делаем скриншот строгого элемента
            captcha_text = analyze_captcha_with_vision(
                page,
                vision_enabled=vision_enabled,
                ollama_url=vision_ollama_url,
                model_name=vision_model,
                region=vision_region,
                debug_dir=debug_dir,
            )

            if captcha_text and len(captcha_text) > 3:  # Игнорируем слишком короткие галлюцинации
                success = auto_input_and_submit_captcha(page, captcha_text)
                if success:
                    page.wait_for_timeout(2000)
                    check = check_blocked(page)
                    if not check["blocked"]:
                        print(f"[CAPTCHA] УСПЕХ! Капча решена на попытке {attempt}!")
                        return True
                    else:
                        print(f"[CAPTCHA] Код не подошел на попытке {attempt}.")
            else:
                print(f"[CAPTCHA] Модель выдала мусор или пустой ответ на попытке {attempt}.")

            # ЕСЛИ НЕ СРАБОТАЛО — СТРОГО ОБНОВЛЯЕМ КАРТИНКУ И ЖДЕМ ЕЕ ПЕРЕРИСОВКИ
            if attempt < max_auto_attempts:
                try:
                    renew_btn = page.locator("[data-qa='captcha-renew-text']").first
                    if renew_btn.count() > 0 and renew_btn.is_visible(timeout=1000):
                        print("[CAPTCHA] Запрашиваем новый текст капчи...")

                        # Запоминаем текущий src картинки, чтобы понять, когда она обновится
                        captcha_img = page.locator("img[data-qa='account-captcha-picture']").first
                        old_src = captcha_img.get_attribute("src") if captcha_img.count() > 0 else ""

                        renew_btn.click(timeout=2000)

                        # Ждем до 5 секунд, пока src картинки реально поменяется на новый
                        for _ in range(50):
                            page.wait_for_timeout(100)
                            current_src = captcha_img.get_attribute("src") if captcha_img.count() > 0 else ""
                            if current_src and current_src != old_src:
                                print("[CAPTCHA] Картинка успешно обновилась в DOM.")
                                break
                        page.wait_for_timeout(1000)  # Дополнительный фикс на прогрузку текстуры
                    else:
                        page.reload()
                        page.wait_for_timeout(4000)
                except Exception as e:
                    print(f"[CAPTCHA] Ошибка обновления: {e}. Перезагружаю страницу...")
                    page.reload()
                    page.wait_for_timeout(4000)

        print(f"[CAPTCHA] Автоматика исчерпала все {max_auto_attempts} попыток.")

    # Фоллбэк на ручной ввод
    print("\n[CAPTCHA] Перехожу к ручному ожиданию...")
    _alert_beep()

    waited = 0
    since_last_alert = 0
    while waited < max_wait_sec:
        try:
            page.wait_for_timeout(poll_interval_sec * 1000)
        except Exception:
            time.sleep(poll_interval_sec)
        waited += poll_interval_sec
        since_last_alert += poll_interval_sec
        current = check_blocked(page)
        if not current["blocked"]:
            print(f"[CAPTCHA] Блокировка снята вручную. Продолжаю.")
            return True
        if since_last_alert >= ALERT_INTERVAL_SEC:
            _alert_beep()
            since_last_alert = 0
    return False
