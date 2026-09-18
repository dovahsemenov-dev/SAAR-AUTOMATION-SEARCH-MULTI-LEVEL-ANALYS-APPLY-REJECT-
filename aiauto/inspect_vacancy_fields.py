from pathlib import Path
from playwright.sync_api import sync_playwright


PROFILE_DIR = Path("./chrome_profile").resolve()

VACANCY_URL = "https://hh.ru/vacancy/136519968"


def safe_text(locator) -> str:
    try:
        if locator.count() == 0:
            return ""
        return locator.first.inner_text(timeout=3000).strip()
    except Exception:
        return ""


def dump_data_qa_elements(page, title: str) -> None:
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)

    elements = page.locator("[data-qa]")
    count = elements.count()

    print(f"\nВсего элементов [data-qa]: {count}")

    records = []

    for index in range(count):
        element = elements.nth(index)

        try:
            data_qa = element.get_attribute("data-qa") or ""
        except Exception:
            continue

        text = safe_text(element)
        text_one_line = " ".join(text.split())

        try:
            tag_name = element.evaluate("(el) => el.tagName")
        except Exception:
            tag_name = "?"

        records.append(
            {
                "data_qa": data_qa,
                "text": text_one_line,
                "tag": tag_name,
            }
        )

    unique_records = []
    seen = set()

    for record in records:
        key = (
            record["data_qa"],
            record["text"],
            record["tag"],
        )

        if key in seen:
            continue

        seen.add(key)
        unique_records.append(record)

    for number, record in enumerate(unique_records, start=1):
        print(f"\n[{number}]")
        print(f"TAG     = {record['tag']}")
        print(f"data-qa = {record['data_qa']}")
        print(f"text    = {record['text'][:500]}")


def dump_form_inputs(page, title: str) -> None:
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)

    selectors = "input, textarea, select"
    elements = page.locator(selectors)
    count = elements.count()

    print(f"\nВсего input/textarea/select: {count}")

    for index in range(count):
        element = elements.nth(index)

        try:
            tag_name = element.evaluate("(el) => el.tagName")
        except Exception:
            tag_name = "?"

        try:
            input_type = element.get_attribute("type") or ""
        except Exception:
            input_type = ""

        try:
            name_attr = element.get_attribute("name") or ""
        except Exception:
            name_attr = ""

        try:
            data_qa = element.get_attribute("data-qa") or ""
        except Exception:
            data_qa = ""

        try:
            placeholder = element.get_attribute("placeholder") or ""
        except Exception:
            placeholder = ""

        try:
            aria_label = element.get_attribute("aria-label") or ""
        except Exception:
            aria_label = ""

        try:
            current_value = element.input_value(timeout=500)
        except Exception:
            current_value = ""

        print(f"\n[{index + 1}]")
        print(f"TAG         = {tag_name}")
        print(f"type        = {input_type}")
        print(f"name        = {name_attr}")
        print(f"data-qa     = {data_qa}")
        print(f"placeholder = {placeholder}")
        print(f"aria-label  = {aria_label}")
        print(f"value       = {current_value[:200]}")


def main():
    print("=" * 80)
    print(
        "ДИАГНОСТИКА ФОРМЫ ОТКЛИКА HH — С РАСКРЫТИЕМ "
        "ПОЛЯ СОПРОВОДИТЕЛЬНОГО ПИСЬМА"
    )
    print("=" * 80)

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            channel="chrome",
            headless=False,
            viewport={
                "width": 1400,
                "height": 900,
            },
        )

        page = (
            context.pages[0]
            if context.pages
            else context.new_page()
        )

        try:
            print("\nОткрываю вакансию:")
            print(VACANCY_URL)

            page.goto(
                VACANCY_URL,
                wait_until="domcontentloaded",
                timeout=60_000,
            )

            page.wait_for_timeout(2500)

            respond_button = page.locator(
                "[data-qa='vacancy-response-link-top'], "
                "[data-qa='vacancy-response-link-bottom']"
            )

            if respond_button.count() == 0:
                print(
                    "\nКнопка 'Откликнуться' не найдена "
                    "на странице вакансии."
                )

                input(
                    "\nНажми Enter для закрытия Chrome..."
                )

                return

            print(
                "\nНажимаю 'Откликнуться' на странице "
                "вакансии..."
            )

            respond_button.first.click()

            page.wait_for_timeout(2000)

            # ==========================================
            # Ищем кнопку "Добавить сопроводительное"
            # ВНУТРИ уже открывшегося модального окна.
            # ==========================================
            add_cover_letter_button = page.locator(
                "[data-qa='add-cover-letter']"
            )

            if add_cover_letter_button.count() == 0:
                print(
                    "\nКнопка 'Добавить сопроводительное' "
                    "не найдена. Возможно, форма "
                    "отклика выглядит иначе на этот раз."
                )

                dump_data_qa_elements(
                    page,
                    "ВСЕ ЭЛЕМЕНТЫ С data-qa "
                    "(БЕЗ РАСКРЫТИЯ ПИСЬМА)",
                )

                input(
                    "\nНажми Enter для закрытия Chrome..."
                )

                return

            print(
                "\nНажимаю 'Добавить сопроводительное' "
                "(письмо пока пустое, ничего не "
                "отправляется)..."
            )

            add_cover_letter_button.first.click()

            page.wait_for_timeout(2000)

            print("\nURL после раскрытия письма:")
            print(page.url)

            dump_data_qa_elements(
                page,
                "ВСЕ ЭЛЕМЕНТЫ С data-qa ПОСЛЕ "
                "'ДОБАВИТЬ СОПРОВОДИТЕЛЬНОЕ'",
            )

            dump_form_inputs(
                page,
                "ВСЕ ПОЛЯ ВВОДА (input/textarea/select)",
            )

            print("\n" + "=" * 80)
            print("BODY — ПОЛНЫЙ ТЕКСТ ВИДИМОЙ СТРАНИЦЫ")
            print("=" * 80)

            body = page.locator("body").inner_text(
                timeout=10_000
            )

            print(body)

            print("\n" + "=" * 80)
            print("ГОТОВО")
            print(
                "Кнопка финальной отправки НЕ была "
                "нажата. Ничего не отправлено "
                "работодателю."
            )
            print("=" * 80)

            input(
                "\nПосмотри также глазами на открывшееся "
                "окно в Chrome (там должно быть видно "
                "поле для текста письма), затем нажми "
                "Enter здесь для закрытия..."
            )

        finally:
            context.close()


if __name__ == "__main__":
    main()