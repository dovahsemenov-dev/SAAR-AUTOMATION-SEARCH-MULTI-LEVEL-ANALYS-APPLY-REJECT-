# inspect_habr.py

"""
inspect_habr.py

Диагностический скрипт под Хабр Карьеру. Аналог твоего
inspect_vacancy_fields.py, но для второго источника.

Зачем он нужен
==============

Сбор и парсинг вакансий Хабра написаны по реальному HTML выдачи,
который был на руках. А вот разметки страницы САМОЙ вакансии и
модалки отклика не было, поэтому habr/apply.py по
умолчанию выключен.

Этот скрипт открывает одну вакансию Хабра, снимает с неё всё,
что нужно для калибровки, и складывает в data/habr_inspect/:

    <id>_vacancy.html        полный HTML страницы вакансии
    <id>_vacancy.png         скриншот
    <id>_report.txt          отчёт: что нашлось по каким селекторам
    <id>_modal.html          HTML после клика по "Откликнуться"
    <id>_modal.png           скриншот модалки

Клик по "Откликнуться" выполняется, НО отправка не делается
никогда: скрипт только открывает форму, снимает разметку и
закрывает страницу. Ни одного отклика он не отправляет.

Запуск
======

    python inspect_habr.py https://career.habr.com/vacancies/1000162215

Без аргумента возьмёт первую вакансию из первой страницы выдачи
по config.HABR_SEARCH_URLS.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import config
from hh.browser import start_browser, stop_browser
from habr.search import (
    SSR_STATE_SELECTOR,
    open_search_page,
    _extract_from_ssr,
)
from habr.vacancy import (
    DESCRIPTION_SELECTORS,
    TITLE_SELECTORS,
    COMPANY_SELECTORS,
)
from habr.apply import (
    RESPOND_BUTTON_SELECTORS,
    LETTER_TEXTAREA_SELECTORS,
    SUBMIT_BUTTON_SELECTORS,
    MODAL_SELECTORS,
)


OUTPUT_DIR = Path(config.DATA_DIR) / "habr_inspect"


def _probe(page, label: str, selectors) -> list[str]:
    lines = [f"--- {label} ---"]

    for selector in selectors:
        try:
            locator = page.locator(selector)
            count = locator.count()
        except Exception as error:
            lines.append(
                f"  {selector!r}: ОШИБКА ({error})"
            )
            continue

        if count == 0:
            lines.append(f"  {selector!r}: не найдено")
            continue

        visible = 0
        sample = ""

        for index in range(min(count, 5)):
            node = locator.nth(index)

            try:
                if node.is_visible():
                    visible += 1

                    if not sample:
                        sample = node.inner_text(
                            timeout=2_000
                        ).strip()

            except Exception:
                continue

        preview = sample.replace("\n", " ")[:160]

        lines.append(
            f"  {selector!r}: найдено {count}, "
            f"видимых {visible}, len(text)={len(sample)}"
        )

        if preview:
            lines.append(f"      текст: {preview}")

    lines.append("")

    return lines


def _pick_first_vacancy_url(page) -> str:
    urls = getattr(config, "HABR_SEARCH_URLS", [])

    if not urls:
        raise RuntimeError(
            "config.HABR_SEARCH_URLS пуст — передай ссылку "
            "на вакансию аргументом."
        )

    open_search_page(page, urls[0])

    found, _meta = _extract_from_ssr(page)

    if not found:
        raise RuntimeError(
            "Не удалось прочитать SSR-состояние выдачи. "
            "Передай ссылку на вакансию аргументом."
        )

    first = next(iter(found.values()))

    return first["url"]


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    playwright, context, page = start_browser(
        config.CHROME_PROFILE_DIR,
        False,
    )

    try:
        if len(sys.argv) > 1:
            vacancy_url = sys.argv[1]
        else:
            print(
                "Ссылка не передана — беру первую вакансию "
                "из выдачи."
            )
            vacancy_url = _pick_first_vacancy_url(page)

        print(f"\nОткрываю вакансию: {vacancy_url}")

        page.goto(
            vacancy_url,
            wait_until="domcontentloaded",
            timeout=60_000,
        )

        page.wait_for_timeout(3_000)

        vacancy_id = vacancy_url.rstrip("/").split("/")[-1]

        report: list[str] = [
            "ОТЧЁТ ПО СТРАНИЦЕ ВАКАНСИИ ХАБР КАРЬЕРЫ",
            "=" * 60,
            f"URL: {page.url}",
            f"TITLE: {page.title()}",
            "",
        ]

        # SSR-состояние страницы вакансии
        try:
            locator = page.locator(SSR_STATE_SELECTOR)

            if locator.count() > 0:
                raw = locator.first.text_content(
                    timeout=10_000
                )

                report.append(
                    "SSR-состояние: НАЙДЕНО, "
                    f"{len(raw or '')} символов"
                )

                try:
                    parsed = json.loads(raw)

                    if isinstance(parsed, dict):
                        report.append(
                            "  ключи верхнего уровня: "
                            + ", ".join(
                                sorted(parsed.keys())
                            )[:500]
                        )

                    (
                        OUTPUT_DIR
                        / f"{vacancy_id}_ssr.json"
                    ).write_text(
                        json.dumps(
                            parsed,
                            ensure_ascii=False,
                            indent=2,
                        ),
                        encoding="utf-8",
                    )

                except json.JSONDecodeError:
                    report.append(
                        "  JSON не разобрался"
                    )

            else:
                report.append(
                    "SSR-состояние: НЕ НАЙДЕНО"
                )

        except Exception as error:
            report.append(f"SSR-состояние: ошибка {error}")

        report.append("")

        report.extend(
            _probe(page, "ЗАГОЛОВОК", TITLE_SELECTORS)
        )
        report.extend(
            _probe(page, "КОМПАНИЯ", COMPANY_SELECTORS)
        )
        report.extend(
            _probe(
                page,
                "ОПИСАНИЕ",
                DESCRIPTION_SELECTORS,
            )
        )
        report.extend(
            _probe(
                page,
                "КНОПКА ОТКЛИКА",
                RESPOND_BUTTON_SELECTORS,
            )
        )

        (
            OUTPUT_DIR / f"{vacancy_id}_vacancy.html"
        ).write_text(page.content(), encoding="utf-8")

        try:
            page.screenshot(
                path=str(
                    OUTPUT_DIR
                    / f"{vacancy_id}_vacancy.png"
                ),
                full_page=True,
            )
        except Exception:
            pass

        # ----------------------------------------------------
        # Клик по "Откликнуться" — ТОЛЬКО чтобы снять разметку
        # формы. Отправка не выполняется ни при каких условиях.
        # ----------------------------------------------------

        report.append("=" * 60)
        report.append("МОДАЛКА ОТКЛИКА")
        report.append("=" * 60)

        clicked = False

        for selector in RESPOND_BUTTON_SELECTORS:
            try:
                locator = page.locator(selector)

                for index in range(
                    min(locator.count(), 5)
                ):
                    node = locator.nth(index)

                    if not node.is_visible():
                        continue

                    node.scroll_into_view_if_needed(
                        timeout=3_000
                    )

                    node.click(timeout=8_000)

                    clicked = True

                    report.append(
                        "Кликнул по селектору: "
                        f"{selector!r} (индекс {index})"
                    )
                    break

            except Exception as error:
                report.append(
                    f"Клик по {selector!r}: ошибка {error}"
                )

            if clicked:
                break

        if not clicked:
            report.append(
                "Кнопку отклика нажать не удалось — "
                "ни один селектор не сработал."
            )

        else:
            page.wait_for_timeout(3_500)

            report.append("")
            report.extend(
                _probe(page, "МОДАЛКА", MODAL_SELECTORS)
            )
            report.extend(
                _probe(
                    page,
                    "ПОЛЕ ПИСЬМА",
                    LETTER_TEXTAREA_SELECTORS,
                )
            )
            report.extend(
                _probe(
                    page,
                    "КНОПКА ОТПРАВКИ",
                    SUBMIT_BUTTON_SELECTORS,
                )
            )

            (
                OUTPUT_DIR / f"{vacancy_id}_modal.html"
            ).write_text(
                page.content(),
                encoding="utf-8",
            )

            try:
                page.screenshot(
                    path=str(
                        OUTPUT_DIR
                        / f"{vacancy_id}_modal.png"
                    ),
                    full_page=True,
                )
            except Exception:
                pass

        report.append("")
        report.append(
            "ОТПРАВКА НЕ ВЫПОЛНЯЛАСЬ. Отклик не отправлен."
        )

        report_path = (
            OUTPUT_DIR / f"{vacancy_id}_report.txt"
        )

        report_path.write_text(
            "\n".join(report),
            encoding="utf-8",
        )

        print("\n" + "\n".join(report))
        print(f"\nВсё сохранено в: {OUTPUT_DIR}")

    finally:
        stop_browser(playwright, context)


if __name__ == "__main__":
    main()
