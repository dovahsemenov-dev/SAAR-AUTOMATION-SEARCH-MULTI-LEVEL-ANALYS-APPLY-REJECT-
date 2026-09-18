# config.py

from pathlib import Path

from filters.fast_filter import (
    DEFAULT_IT_PROTECT_MARKERS as FAST_FILTER_IT_PROTECT_MARKERS,
    DEFAULT_FORCE_HARD_REJECT_MARKERS as FAST_FILTER_HARD_REJECT_MARKERS,
)

BASE_DIR = Path(__file__).resolve().parent

# ============================================================
# Chrome / Playwright
# ============================================================

CHROME_PROFILE_DIR = (
        BASE_DIR / "chrome_profile"
)

HEADLESS = False

PAGE_TIMEOUT_MS = 60_000

# ============================================================
# Поисковые URL HH.RU
# ============================================================

SEARCH_URLS = [

    "https://hh.ru/search/vacancy?resume=02f97ad6ff109f78c90039ed1f3674446f6663&from=resumelist&hhtmFrom=applicant_profile",
# ---- Резюме-рекомендации HH (без фильтров, как есть) ----
    "https://hh.ru/search/vacancy?resume=02f97ad6ff109f78c90039ed1f3674446f6663&from=resumelist&hhtmFrom=applicant_profile",

    "https://ufa.hh.ru/search/vacancy?resume=02f97ad6ff109f78c90039ed1f3674446f6663&from=resumelist&hhtmFrom=applicant_profile",

    # ---- QA ----
    # "Тестировщик" (remote)
    "https://hh.ru/search/vacancy?text=%D0%A2%D0%B5%D1%81%D1%82%D0%B8%D1%80%D0%BE%D0%B2%D1%89%D0%B8%D0%BA&experience=noExperience&work_format=REMOTE&search_field=name&search_field=company_name&search_field=description&ored_clusters=true&enable_snippets=true&hhtmFrom=vacancy_search_list&hhtmFromLabel=drawer_filter&hhtmSource=vacancy_search_list&hhtmSourceLabel=vacancy_search_list",

    # "Тестировщик" (Уфа + Казань)
    "https://hh.ru/search/vacancy?text=%D0%A2%D0%B5%D1%81%D1%82%D0%B8%D1%80%D0%BE%D0%B2%D1%89%D0%B8%D0%BA&experience=noExperience&area=99&area=88&search_field=name&search_field=company_name&search_field=description&ored_clusters=true&enable_snippets=true&hhtmFrom=vacancy_search_list&hhtmFromLabel=drawer_filter&hhtmSource=vacancy_search_list&hhtmSourceLabel=vacancy_search_list",

    # "Qa engineer" (remote)
    "https://hh.ru/search/vacancy?text=Qa+engineer&experience=noExperience&work_format=REMOTE&search_field=name&search_field=company_name&search_field=description&ored_clusters=true&enable_snippets=true&hhtmFrom=vacancy_search_list&hhtmFromLabel=drawer_filter&hhtmSource=vacancy_search_list&hhtmSourceLabel=vacancy_search_list",

    # "Qa engineer" (Уфа + Казань)
    "https://hh.ru/search/vacancy?text=Qa+engineer&experience=noExperience&area=99&area=88&search_field=name&search_field=company_name&search_field=description&ored_clusters=true&enable_snippets=true&hhtmFrom=vacancy_search_list&hhtmFromLabel=drawer_filter&hhtmSource=vacancy_search_list&hhtmSourceLabel=vacancy_search_list",

    # ---- development ----
    # "Программист" (remote)
    "https://hh.ru/search/vacancy?text=%D0%9F%D1%80%D0%BE%D0%B3%D1%80%D0%B0%D0%BC%D0%BC%D0%B8%D1%81%D1%82&experience=noExperience&work_format=REMOTE&search_field=name&search_field=company_name&search_field=description&ored_clusters=true&enable_snippets=true&hhtmFrom=vacancy_search_list&hhtmFromLabel=drawer_filter&hhtmSource=vacancy_search_list&hhtmSourceLabel=vacancy_search_list",

    # "Программист" (Уфа + Казань)
    "https://hh.ru/search/vacancy?text=%D0%9F%D1%80%D0%BE%D0%B3%D1%80%D0%B0%D0%BC%D0%BC%D0%B8%D1%81%D1%82&experience=noExperience&area=99&area=88&search_field=name&search_field=company_name&search_field=description&ored_clusters=true&enable_snippets=true&hhtmFrom=vacancy_search_list&hhtmFromLabel=drawer_filter&hhtmSource=vacancy_search_list&hhtmSourceLabel=vacancy_search_list",

    # ---- backend ----
    # "Python разработчик" (remote)
    "https://hh.ru/search/vacancy?text=Python+%D1%80%D0%B0%D0%B7%D1%80%D0%B0%D0%B1%D0%BE%D1%82%D1%87%D0%B8%D0%BA&experience=noExperience&work_format=REMOTE&search_field=name&search_field=company_name&search_field=description&ored_clusters=true&enable_snippets=true&hhtmFrom=vacancy_search_list&hhtmFromLabel=drawer_filter&hhtmSource=vacancy_search_list&hhtmSourceLabel=vacancy_search_list",

    # "Python разработчик" (Уфа + Казань)
    "https://hh.ru/search/vacancy?text=Python+%D1%80%D0%B0%D0%B7%D1%80%D0%B0%D0%B1%D0%BE%D1%82%D1%87%D0%B8%D0%BA&experience=noExperience&area=99&area=88&search_field=name&search_field=company_name&search_field=description&ored_clusters=true&enable_snippets=true&hhtmFrom=vacancy_search_list&hhtmFromLabel=drawer_filter&hhtmSource=vacancy_search_list&hhtmSourceLabel=vacancy_search_list",

    # ---- frontend ----
    # "Frontend разработчик" (remote)
    "https://hh.ru/search/vacancy?text=Frontend+%D1%80%D0%B0%D0%B7%D1%80%D0%B0%D0%B1%D0%BE%D1%82%D1%87%D0%B8%D0%BA&experience=noExperience&work_format=REMOTE&search_field=name&search_field=company_name&search_field=description&ored_clusters=true&enable_snippets=true&hhtmFrom=vacancy_search_list&hhtmFromLabel=drawer_filter&hhtmSource=vacancy_search_list&hhtmSourceLabel=vacancy_search_list",

    # "Frontend разработчик" (Уфа + Казань)
    "https://hh.ru/search/vacancy?text=Frontend+%D1%80%D0%B0%D0%B7%D1%80%D0%B0%D0%B1%D0%BE%D1%82%D1%87%D0%B8%D0%BA&experience=noExperience&area=99&area=88&search_field=name&search_field=company_name&search_field=description&ored_clusters=true&enable_snippets=true&hhtmFrom=vacancy_search_list&hhtmFromLabel=drawer_filter&hhtmSource=vacancy_search_list&hhtmSourceLabel=vacancy_search_list",

    # ---- fullstack ----
    # "Fullstack разработчик" (remote)
    "https://hh.ru/search/vacancy?text=Fullstack+%D1%80%D0%B0%D0%B7%D1%80%D0%B0%D0%B1%D0%BE%D1%82%D1%87%D0%B8%D0%BA&experience=noExperience&work_format=REMOTE&search_field=name&search_field=company_name&search_field=description&ored_clusters=true&enable_snippets=true&hhtmFrom=vacancy_search_list&hhtmFromLabel=drawer_filter&hhtmSource=vacancy_search_list&hhtmSourceLabel=vacancy_search_list",

    # "Fullstack разработчик" (Уфа + Казань)
    "https://hh.ru/search/vacancy?text=Fullstack+%D1%80%D0%B0%D0%B7%D1%80%D0%B0%D0%B1%D0%BE%D1%82%D1%87%D0%B8%D0%BA&experience=noExperience&area=99&area=88&search_field=name&search_field=company_name&search_field=description&ored_clusters=true&enable_snippets=true&hhtmFrom=vacancy_search_list&hhtmFromLabel=drawer_filter&hhtmSource=vacancy_search_list&hhtmSourceLabel=vacancy_search_list",

    # ---- mobile ----
    # "Мобильный разработчик" (remote)
    "https://hh.ru/search/vacancy?text=%D0%9C%D0%BE%D0%B1%D0%B8%D0%BB%D1%8C%D0%BD%D1%8B%D0%B9+%D1%80%D0%B0%D0%B7%D1%80%D0%B0%D0%B1%D0%BE%D1%82%D1%87%D0%B8%D0%BA&experience=noExperience&work_format=REMOTE&search_field=name&search_field=company_name&search_field=description&ored_clusters=true&enable_snippets=true&hhtmFrom=vacancy_search_list&hhtmFromLabel=drawer_filter&hhtmSource=vacancy_search_list&hhtmSourceLabel=vacancy_search_list",

    # "Мобильный разработчик" (Уфа + Казань)
    "https://hh.ru/search/vacancy?text=%D0%9C%D0%BE%D0%B1%D0%B8%D0%BB%D1%8C%D0%BD%D1%8B%D0%B9+%D1%80%D0%B0%D0%B7%D1%80%D0%B0%D0%B1%D0%BE%D1%82%D1%87%D0%B8%D0%BA&experience=noExperience&area=99&area=88&search_field=name&search_field=company_name&search_field=description&ored_clusters=true&enable_snippets=true&hhtmFrom=vacancy_search_list&hhtmFromLabel=drawer_filter&hhtmSource=vacancy_search_list&hhtmSourceLabel=vacancy_search_list",

    # ---- devops ----
    # "DevOps инженер" (remote)
    "https://hh.ru/search/vacancy?text=DevOps+%D0%B8%D0%BD%D0%B6%D0%B5%D0%BD%D0%B5%D1%80&experience=noExperience&work_format=REMOTE&search_field=name&search_field=company_name&search_field=description&ored_clusters=true&enable_snippets=true&hhtmFrom=vacancy_search_list&hhtmFromLabel=drawer_filter&hhtmSource=vacancy_search_list&hhtmSourceLabel=vacancy_search_list",

    # "DevOps инженер" (Уфа + Казань)
    "https://hh.ru/search/vacancy?text=DevOps+%D0%B8%D0%BD%D0%B6%D0%B5%D0%BD%D0%B5%D1%80&experience=noExperience&area=99&area=88&search_field=name&search_field=company_name&search_field=description&ored_clusters=true&enable_snippets=true&hhtmFrom=vacancy_search_list&hhtmFromLabel=drawer_filter&hhtmSource=vacancy_search_list&hhtmSourceLabel=vacancy_search_list",

    # ---- sysadmin ----
    # "Системный администратор" (remote)
    "https://hh.ru/search/vacancy?text=%D0%A1%D0%B8%D1%81%D1%82%D0%B5%D0%BC%D0%BD%D1%8B%D0%B9+%D0%B0%D0%B4%D0%BC%D0%B8%D0%BD%D0%B8%D1%81%D1%82%D1%80%D0%B0%D1%82%D0%BE%D1%80&experience=noExperience&work_format=REMOTE&search_field=name&search_field=company_name&search_field=description&ored_clusters=true&enable_snippets=true&hhtmFrom=vacancy_search_list&hhtmFromLabel=drawer_filter&hhtmSource=vacancy_search_list&hhtmSourceLabel=vacancy_search_list",

    # "Системный администратор" (Уфа + Казань)
    "https://hh.ru/search/vacancy?text=%D0%A1%D0%B8%D1%81%D1%82%D0%B5%D0%BC%D0%BD%D1%8B%D0%B9+%D0%B0%D0%B4%D0%BC%D0%B8%D0%BD%D0%B8%D1%81%D1%82%D1%80%D0%B0%D1%82%D0%BE%D1%80&experience=noExperience&area=99&area=88&search_field=name&search_field=company_name&search_field=description&ored_clusters=true&enable_snippets=true&hhtmFrom=vacancy_search_list&hhtmFromLabel=drawer_filter&hhtmSource=vacancy_search_list&hhtmSourceLabel=vacancy_search_list",

    # ---- network ----
    # "Сетевой инженер" (remote)
    "https://hh.ru/search/vacancy?text=%D0%A1%D0%B5%D1%82%D0%B5%D0%B2%D0%BE%D0%B9+%D0%B8%D0%BD%D0%B6%D0%B5%D0%BD%D0%B5%D1%80&experience=noExperience&work_format=REMOTE&search_field=name&search_field=company_name&search_field=description&ored_clusters=true&enable_snippets=true&hhtmFrom=vacancy_search_list&hhtmFromLabel=drawer_filter&hhtmSource=vacancy_search_list&hhtmSourceLabel=vacancy_search_list",

    # "Сетевой инженер" (Уфа + Казань)
    "https://hh.ru/search/vacancy?text=%D0%A1%D0%B5%D1%82%D0%B5%D0%B2%D0%BE%D0%B9+%D0%B8%D0%BD%D0%B6%D0%B5%D0%BD%D0%B5%D1%80&experience=noExperience&area=99&area=88&search_field=name&search_field=company_name&search_field=description&ored_clusters=true&enable_snippets=true&hhtmFrom=vacancy_search_list&hhtmFromLabel=drawer_filter&hhtmSource=vacancy_search_list&hhtmSourceLabel=vacancy_search_list",

    # ---- security ----
    # "Специалист по информационной безопасности" (remote)
    "https://hh.ru/search/vacancy?text=%D0%A1%D0%BF%D0%B5%D1%86%D0%B8%D0%B0%D0%BB%D0%B8%D1%81%D1%82+%D0%BF%D0%BE+%D0%B8%D0%BD%D1%84%D0%BE%D1%80%D0%BC%D0%B0%D1%86%D0%B8%D0%BE%D0%BD%D0%BD%D0%BE%D0%B9+%D0%B1%D0%B5%D0%B7%D0%BE%D0%BF%D0%B0%D1%81%D0%BD%D0%BE%D1%81%D1%82%D0%B8&experience=noExperience&work_format=REMOTE&search_field=name&search_field=company_name&search_field=description&ored_clusters=true&enable_snippets=true&hhtmFrom=vacancy_search_list&hhtmFromLabel=drawer_filter&hhtmSource=vacancy_search_list&hhtmSourceLabel=vacancy_search_list",

    # "Специалист по информационной безопасности" (Уфа + Казань)
    "https://hh.ru/search/vacancy?text=%D0%A1%D0%BF%D0%B5%D1%86%D0%B8%D0%B0%D0%BB%D0%B8%D1%81%D1%82+%D0%BF%D0%BE+%D0%B8%D0%BD%D1%84%D0%BE%D1%80%D0%BC%D0%B0%D1%86%D0%B8%D0%BE%D0%BD%D0%BD%D0%BE%D0%B9+%D0%B1%D0%B5%D0%B7%D0%BE%D0%BF%D0%B0%D1%81%D0%BD%D0%BE%D1%81%D1%82%D0%B8&experience=noExperience&area=99&area=88&search_field=name&search_field=company_name&search_field=description&ored_clusters=true&enable_snippets=true&hhtmFrom=vacancy_search_list&hhtmFromLabel=drawer_filter&hhtmSource=vacancy_search_list&hhtmSourceLabel=vacancy_search_list",

    # ---- data ----
    # "Аналитик данных" (remote)
    "https://hh.ru/search/vacancy?text=%D0%90%D0%BD%D0%B0%D0%BB%D0%B8%D1%82%D0%B8%D0%BA+%D0%B4%D0%B0%D0%BD%D0%BD%D1%8B%D1%85&experience=noExperience&work_format=REMOTE&search_field=name&search_field=company_name&search_field=description&ored_clusters=true&enable_snippets=true&hhtmFrom=vacancy_search_list&hhtmFromLabel=drawer_filter&hhtmSource=vacancy_search_list&hhtmSourceLabel=vacancy_search_list",

    # "Аналитик данных" (Уфа + Казань)
    "https://hh.ru/search/vacancy?text=%D0%90%D0%BD%D0%B0%D0%BB%D0%B8%D1%82%D0%B8%D0%BA+%D0%B4%D0%B0%D0%BD%D0%BD%D1%8B%D1%85&experience=noExperience&area=99&area=88&search_field=name&search_field=company_name&search_field=description&ored_clusters=true&enable_snippets=true&hhtmFrom=vacancy_search_list&hhtmFromLabel=drawer_filter&hhtmSource=vacancy_search_list&hhtmSourceLabel=vacancy_search_list",

    # ---- database ----
    # "Администратор баз данных" (remote)
    "https://hh.ru/search/vacancy?text=%D0%90%D0%B4%D0%BC%D0%B8%D0%BD%D0%B8%D1%81%D1%82%D1%80%D0%B0%D1%82%D0%BE%D1%80+%D0%B1%D0%B0%D0%B7+%D0%B4%D0%B0%D0%BD%D0%BD%D1%8B%D1%85&experience=noExperience&work_format=REMOTE&search_field=name&search_field=company_name&search_field=description&ored_clusters=true&enable_snippets=true&hhtmFrom=vacancy_search_list&hhtmFromLabel=drawer_filter&hhtmSource=vacancy_search_list&hhtmSourceLabel=vacancy_search_list",

    # "Администратор баз данных" (Уфа + Казань)
    "https://hh.ru/search/vacancy?text=%D0%90%D0%B4%D0%BC%D0%B8%D0%BD%D0%B8%D1%81%D1%82%D1%80%D0%B0%D1%82%D0%BE%D1%80+%D0%B1%D0%B0%D0%B7+%D0%B4%D0%B0%D0%BD%D0%BD%D1%8B%D1%85&experience=noExperience&area=99&area=88&search_field=name&search_field=company_name&search_field=description&ored_clusters=true&enable_snippets=true&hhtmFrom=vacancy_search_list&hhtmFromLabel=drawer_filter&hhtmSource=vacancy_search_list&hhtmSourceLabel=vacancy_search_list",

    # ---- data_engineering ----
    # "Data Engineer" (remote)
    "https://hh.ru/search/vacancy?text=Data+Engineer&experience=noExperience&work_format=REMOTE&search_field=name&search_field=company_name&search_field=description&ored_clusters=true&enable_snippets=true&hhtmFrom=vacancy_search_list&hhtmFromLabel=drawer_filter&hhtmSource=vacancy_search_list&hhtmSourceLabel=vacancy_search_list",

    # "Data Engineer" (Уфа + Казань)
    "https://hh.ru/search/vacancy?text=Data+Engineer&experience=noExperience&area=99&area=88&search_field=name&search_field=company_name&search_field=description&ored_clusters=true&enable_snippets=true&hhtmFrom=vacancy_search_list&hhtmFromLabel=drawer_filter&hhtmSource=vacancy_search_list&hhtmSourceLabel=vacancy_search_list",

    # ---- 1c ----
    # "Программист 1С" (remote)
    "https://hh.ru/search/vacancy?text=%D0%9F%D1%80%D0%BE%D0%B3%D1%80%D0%B0%D0%BC%D0%BC%D0%B8%D1%81%D1%82+1%D0%A1&experience=noExperience&work_format=REMOTE&search_field=name&search_field=company_name&search_field=description&ored_clusters=true&enable_snippets=true&hhtmFrom=vacancy_search_list&hhtmFromLabel=drawer_filter&hhtmSource=vacancy_search_list&hhtmSourceLabel=vacancy_search_list",

    # "Программист 1С" (Уфа + Казань)
    "https://hh.ru/search/vacancy?text=%D0%9F%D1%80%D0%BE%D0%B3%D1%80%D0%B0%D0%BC%D0%BC%D0%B8%D1%81%D1%82+1%D0%A1&experience=noExperience&area=99&area=88&search_field=name&search_field=company_name&search_field=description&ored_clusters=true&enable_snippets=true&hhtmFrom=vacancy_search_list&hhtmFromLabel=drawer_filter&hhtmSource=vacancy_search_list&hhtmSourceLabel=vacancy_search_list",

    # ---- game_dev ----
    # "Разработчик игр" (remote)
    "https://hh.ru/search/vacancy?text=%D0%A0%D0%B0%D0%B7%D1%80%D0%B0%D0%B1%D0%BE%D1%82%D1%87%D0%B8%D0%BA+%D0%B8%D0%B3%D1%80&experience=noExperience&work_format=REMOTE&search_field=name&search_field=company_name&search_field=description&ored_clusters=true&enable_snippets=true&hhtmFrom=vacancy_search_list&hhtmFromLabel=drawer_filter&hhtmSource=vacancy_search_list&hhtmSourceLabel=vacancy_search_list",

    # "Разработчик игр" (Уфа + Казань)
    "https://hh.ru/search/vacancy?text=%D0%A0%D0%B0%D0%B7%D1%80%D0%B0%D0%B1%D0%BE%D1%82%D1%87%D0%B8%D0%BA+%D0%B8%D0%B3%D1%80&experience=noExperience&area=99&area=88&search_field=name&search_field=company_name&search_field=description&ored_clusters=true&enable_snippets=true&hhtmFrom=vacancy_search_list&hhtmFromLabel=drawer_filter&hhtmSource=vacancy_search_list&hhtmSourceLabel=vacancy_search_list",

    # ---- embedded ----
    # "Embedded разработчик" (remote)
    "https://hh.ru/search/vacancy?text=Embedded+%D1%80%D0%B0%D0%B7%D1%80%D0%B0%D0%B1%D0%BE%D1%82%D1%87%D0%B8%D0%BA&experience=noExperience&work_format=REMOTE&search_field=name&search_field=company_name&search_field=description&ored_clusters=true&enable_snippets=true&hhtmFrom=vacancy_search_list&hhtmFromLabel=drawer_filter&hhtmSource=vacancy_search_list&hhtmSourceLabel=vacancy_search_list",

    # "Embedded разработчик" (Уфа + Казань)
    "https://hh.ru/search/vacancy?text=Embedded+%D1%80%D0%B0%D0%B7%D1%80%D0%B0%D0%B1%D0%BE%D1%82%D1%87%D0%B8%D0%BA&experience=noExperience&area=99&area=88&search_field=name&search_field=company_name&search_field=description&ored_clusters=true&enable_snippets=true&hhtmFrom=vacancy_search_list&hhtmFromLabel=drawer_filter&hhtmSource=vacancy_search_list&hhtmSourceLabel=vacancy_search_list",

    # ---- hardware ----
    # "Hardware Engineer" (remote)
    "https://hh.ru/search/vacancy?text=Hardware+Engineer&experience=noExperience&work_format=REMOTE&search_field=name&search_field=company_name&search_field=description&ored_clusters=true&enable_snippets=true&hhtmFrom=vacancy_search_list&hhtmFromLabel=drawer_filter&hhtmSource=vacancy_search_list&hhtmSourceLabel=vacancy_search_list",

    # "Hardware Engineer" (Уфа + Казань)
    "https://hh.ru/search/vacancy?text=Hardware+Engineer&experience=noExperience&area=99&area=88&search_field=name&search_field=company_name&search_field=description&ored_clusters=true&enable_snippets=true&hhtmFrom=vacancy_search_list&hhtmFromLabel=drawer_filter&hhtmSource=vacancy_search_list&hhtmSourceLabel=vacancy_search_list",

    # ---- cloud ----
    # "Cloud Engineer" (remote)
    "https://hh.ru/search/vacancy?text=Cloud+Engineer&experience=noExperience&work_format=REMOTE&search_field=name&search_field=company_name&search_field=description&ored_clusters=true&enable_snippets=true&hhtmFrom=vacancy_search_list&hhtmFromLabel=drawer_filter&hhtmSource=vacancy_search_list&hhtmSourceLabel=vacancy_search_list",

    # "Cloud Engineer" (Уфа + Казань)
    "https://hh.ru/search/vacancy?text=Cloud+Engineer&experience=noExperience&area=99&area=88&search_field=name&search_field=company_name&search_field=description&ored_clusters=true&enable_snippets=true&hhtmFrom=vacancy_search_list&hhtmFromLabel=drawer_filter&hhtmSource=vacancy_search_list&hhtmSourceLabel=vacancy_search_list",

    # ---- architecture ----
    # "Software Architect" (remote)
    "https://hh.ru/search/vacancy?text=Software+Architect&experience=noExperience&work_format=REMOTE&search_field=name&search_field=company_name&search_field=description&ored_clusters=true&enable_snippets=true&hhtmFrom=vacancy_search_list&hhtmFromLabel=drawer_filter&hhtmSource=vacancy_search_list&hhtmSourceLabel=vacancy_search_list",

    # "Software Architect" (Уфа + Казань)
    "https://hh.ru/search/vacancy?text=Software+Architect&experience=noExperience&area=99&area=88&search_field=name&search_field=company_name&search_field=description&ored_clusters=true&enable_snippets=true&hhtmFrom=vacancy_search_list&hhtmFromLabel=drawer_filter&hhtmSource=vacancy_search_list&hhtmSourceLabel=vacancy_search_list",

    # ---- business_analyst ----
    # "Системный аналитик" (remote)
    "https://hh.ru/search/vacancy?text=%D0%A1%D0%B8%D1%81%D1%82%D0%B5%D0%BC%D0%BD%D1%8B%D0%B9+%D0%B0%D0%BD%D0%B0%D0%BB%D0%B8%D1%82%D0%B8%D0%BA&experience=noExperience&work_format=REMOTE&search_field=name&search_field=company_name&search_field=description&ored_clusters=true&enable_snippets=true&hhtmFrom=vacancy_search_list&hhtmFromLabel=drawer_filter&hhtmSource=vacancy_search_list&hhtmSourceLabel=vacancy_search_list",

    # "Системный аналитик" (Уфа + Казань)
    "https://hh.ru/search/vacancy?text=%D0%A1%D0%B8%D1%81%D1%82%D0%B5%D0%BC%D0%BD%D1%8B%D0%B9+%D0%B0%D0%BD%D0%B0%D0%BB%D0%B8%D1%82%D0%B8%D0%BA&experience=noExperience&area=99&area=88&search_field=name&search_field=company_name&search_field=description&ored_clusters=true&enable_snippets=true&hhtmFrom=vacancy_search_list&hhtmFromLabel=drawer_filter&hhtmSource=vacancy_search_list&hhtmSourceLabel=vacancy_search_list",

    # ---- it_management ----
    # "IT Project Manager" (remote)
    "https://hh.ru/search/vacancy?text=IT+Project+Manager&experience=noExperience&work_format=REMOTE&search_field=name&search_field=company_name&search_field=description&ored_clusters=true&enable_snippets=true&hhtmFrom=vacancy_search_list&hhtmFromLabel=drawer_filter&hhtmSource=vacancy_search_list&hhtmSourceLabel=vacancy_search_list",

    # "IT Project Manager" (Уфа + Казань)
    "https://hh.ru/search/vacancy?text=IT+Project+Manager&experience=noExperience&area=99&area=88&search_field=name&search_field=company_name&search_field=description&ored_clusters=true&enable_snippets=true&hhtmFrom=vacancy_search_list&hhtmFromLabel=drawer_filter&hhtmSource=vacancy_search_list&hhtmSourceLabel=vacancy_search_list",

    # ---- ux_ui ----
    # "UX/UI дизайнер" (remote)
    "https://hh.ru/search/vacancy?text=UX%2FUI+%D0%B4%D0%B8%D0%B7%D0%B0%D0%B9%D0%BD%D0%B5%D1%80&experience=noExperience&work_format=REMOTE&search_field=name&search_field=company_name&search_field=description&ored_clusters=true&enable_snippets=true&hhtmFrom=vacancy_search_list&hhtmFromLabel=drawer_filter&hhtmSource=vacancy_search_list&hhtmSourceLabel=vacancy_search_list",

    # "UX/UI дизайнер" (Уфа + Казань)
    "https://hh.ru/search/vacancy?text=UX%2FUI+%D0%B4%D0%B8%D0%B7%D0%B0%D0%B9%D0%BD%D0%B5%D1%80&experience=noExperience&area=99&area=88&search_field=name&search_field=company_name&search_field=description&ored_clusters=true&enable_snippets=true&hhtmFrom=vacancy_search_list&hhtmFromLabel=drawer_filter&hhtmSource=vacancy_search_list&hhtmSourceLabel=vacancy_search_list",

    # ---- VibeCoder ----
    # "VibeCoder" (remote)
    "https://hh.ru/search/vacancy?text=VibeCoder&search_field=name&search_field=company_name&search_field=description&experience=noExperience&work_format=REMOTE",

   # "VibeCoder" (Уфа + Казань)
    "https://hh.ru/search/vacancy?text=VibeCoder&experience=noExperience&area=99&area=88&search_field=name&search_field=company_name&search_field=description&ored_clusters=true&enable_snippets=true&hhtmFrom=vacancy_search_list&hhtmFromLabel=drawer_filter&hhtmSource=vacancy_search_list&hhtmSourceLabel=vacancy_search_list",


]

# Сколько карточек максимум ПРОСМОТРЕТЬ
# с одного поискового URL.
#
# Это НЕ число вакансий после fast-filter.
#
MAX_VACANCIES_PER_URL = 2500

# ============================================================
# Лимит APPLY
# ============================================================

MAX_APPLIES_PER_RUN = 250

# ============================================================
# Задержки
# ============================================================

MIN_DELAY_SEC = 8

MAX_DELAY_SEC = 24

LONG_PAUSE_CHANCE = 0.12

LONG_PAUSE_MIN_SEC = 18

LONG_PAUSE_MAX_SEC = 60

# ============================================================
# Ollama
# ============================================================

OLLAMA_URL = (
    "http://127.0.0.1:11434"
)

OLLAMA_MODEL = (
    "qwen2.5:7b"
)

# ============================================================
# Локальные данные
# ============================================================

PROFILE_FILE = (
        BASE_DIR / "profile.txt"
)

PROFILE_FACTS_FILE = (
        BASE_DIR / "profile_facts.json"
)

PREFERENCES_FILE = (
        BASE_DIR / "preferences.txt"
)

DATA_DIR = (
        BASE_DIR / "data"
)

HISTORY_FILE = (
        DATA_DIR / "history.json"
)

# Постоянный список вакансий, на которые реально был отправлен
# отклик (или которые сервер уже показывал как "отклик
# отправлен"). В отличие от HISTORY_FILE, этот файл НЕ предназначен
# для периодической ручной очистки — history.json можно чистить,
# чтобы вернуться к вакансиям, отклонённым раньше (например, после
# смены критериев в PROFILE/PREFERENCES), а вот повторно
# откликаться на уже обработанные вакансии не нужно никогда. См.
# main.py::load_applied_ids / _is_permanently_applied_status.
APPLIED_IDS_FILE = (
        DATA_DIR / "applied_ids.json"
)

RESULTS_CSV_FILE = (
        DATA_DIR / "results.csv"
)

COVER_LETTERS_DIR = (
        DATA_DIR / "cover_letters"
)

# ============================================================
# Логика
# ============================================================

REPROCESS_VACANCIES = True

# Реальные отклики включены — DRY_RUN выключен.
DRY_RUN = False

# ============================================================
# Сопроводительные
# ============================================================

GENERATE_COVER_LETTERS = True

COVER_LETTER_DECISIONS = {
    "APPLY",
}

# ============================================================
# FAST FILTER
# ============================================================
#
# Whitelist-first логика (filters/fast_filter.py):
#     FAST_FILTER_IT_PROTECT_MARKERS  <- DEFAULT_IT_PROTECT_MARKERS
#     FAST_FILTER_HARD_REJECT_MARKERS <- DEFAULT_FORCE_HARD_REJECT_MARKERS
#
# Оба списка импортируются напрямую из filters/fast_filter.py
# (см. импорт в начале файла) — здесь ничего не дублируется и
# не переопределяется. Правь маркеры/whitelist только в
# filters/fast_filter.py.

FAST_FILTER_ENABLED = True

# ============================================================
# Прочие старые Python-фильтры
# ============================================================

STOP_WORDS_IN_TITLE = [
    "call-центра",
    "оператор call",
]

MAX_EXPERIENCE_YEARS_MIN = 2

# ============================================================
# CAPTCHA / блокировка HH — пауза-и-восстановление
# ============================================================
#
# Вместо немедленной остановки прогона при обнаружении CAPTCHA
# (check_blocked() == True) main.py вызывает
# hh.browser.wait_for_unblock(), которая ждёт, пока пользователь
# решит капчу вручную в открытом окне Chrome (HEADLESS = False),
# опрашивая страницу каждые CAPTCHA_POLL_INTERVAL_SEC секунд.
# Если за CAPTCHA_MAX_WAIT_SEC блокировка не снята — прогон
# останавливается, как и раньше.

CAPTCHA_MAX_WAIT_SEC = 600

CAPTCHA_POLL_INTERVAL_SEC = 5

# ------------------------------------------------------------
# CAPTCHA VISION (qwen2.5vl:3b) — первый кусок цепочки
# автоматического решения CAPTCHA: только обнаружение +
# скриншот + анализ изображения, БЕЗ попытки что-либо решать.
#
# Текущий основной анализатор вакансий (qwen2.5:7b) остаётся
# без изменений — vision-модель вызывается ТОЛЬКО по событию
# CAPTCHA (см. hh/browser.py: analyze_captcha_with_vision).
#
# CAPTCHA_SCREENSHOT_X/Y/WIDTH/HEIGHT задают область страницы
# (в пикселях от левого верхнего угла), которую нужно
# заскриншотить. Подгони эти координаты под то место, где
# реально появляется CAPTCHA на HH — без изменений кода.
# ------------------------------------------------------------

CAPTCHA_VISION_ENABLED = True

CAPTCHA_VISION_MODEL = "qwen2.5vl:3b"

CAPTCHA_SCREENSHOT_X = 726

CAPTCHA_SCREENSHOT_Y = 106

CAPTCHA_SCREENSHOT_WIDTH = 485

CAPTCHA_SCREENSHOT_HEIGHT = 632

# ============================================================
# DEBUG
# ============================================================

DEBUG_MODE = True

DEBUG_DUMP_DIR = (
        DATA_DIR / "debug_dumps"
)

# ============================================================
# Подтверждение реальной доставки отклика (ФИКС №5, см.
# hh/apply.py, докстринг модуля) — решение проблемы
# "отклики не доходят".
# ============================================================

VERIFY_INSTANT_APPLY_VIA_RELOAD = True

# КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: строго ограничиваем эндпоинты доменом hh.ru.
# Теперь бот намертво игнорирует top-fwz1.mail.ru и yandex пиксели аналитики.
NETWORK_RESPONSE_URL_MARKERS = [
    "hh.ru/applicant/vacancy_response",
    "hh.ru/v/negotiations",
    "hh.ru/v/response_letter",
    "hh.ru/v/response/popup"
]


# ============================================================
# ХАБР КАРЬЕРА (career.habr.com) — второй источник вакансий
# ============================================================
#
# router.py разводит вызовы по домену URL:
#     hh.ru / *.hh.ru  -> hh/*
#     career.habr.com  -> habr/*
#
# Поэтому habr-ссылки просто складываются в общий SEARCH_URLS
# (склейка в самом конце файла), и main.py их не отличает.
# ============================================================

# Поисковые URL Хабр Карьеры.
#
# Специализации (параметр s[]) взяты из твоих же сохранённых
# фильтров, которые видны в SSR-состоянии страницы выдачи:
#
#   s[]=10  Инженер по автоматизации тестирования
#   s[]=12  Инженер по ручному тестированию
#   s[]=13  Инженер по обеспечению качества
#   s[]=87  UX-тестировщик
#
# qid — грейд: 1 Intern, 3 Junior, 4 Middle, 5 Senior, 6 Lead.
# remote=true — только удалённые.
# type=suitable — подборка "Подходящие" по твоему профилю.
HABR_SEARCH_URLS = [

    # ---- QA, удалённо ----
    "https://career.habr.com/vacancies?type=all&currency=RUR&remote=true&s[]=12&s[]=13&s[]=87&s[]=10&sort=date",

    # ---- QA, без фильтра по формату работы ----
    "https://career.habr.com/vacancies?type=all&currency=RUR&s[]=12&s[]=13&s[]=87&s[]=10&sort=date",

    # ---- Стажировки по всем направлениям, удалённо ----
    "https://career.habr.com/vacancies?type=all&currency=RUR&remote=true&qid=1&sort=date",

    # ---- Джуны по всем направлениям, удалённо ----
    "https://career.habr.com/vacancies?type=all&currency=RUR&remote=true&qid=3&sort=date",

    # ---- Подборка Хабра "Подходящие" ----
    "https://career.habr.com/vacancies?type=suitable&sort=date",
]


# Отдельный лимит просмотра карточек для Хабра.
#
# MAX_VACANCIES_PER_URL = 2500 выставлен под HH, где выдача
# практически бесконечная. У Хабра вся база — порядка 1200
# вакансий, страница фиксирована в 25 карточек (perPage=25).
# 600 — это уже половина всей площадки по одному URL.
HABR_MAX_VACANCIES_PER_URL = 600


# Мягкий режим fast-filter для Хабра.
#
# filters/fast_filter.py писался под HH, где 85-90% выдачи —
# не-IT мусор (по логам прогонов: 2831 HARD_REJECT против
# 233 TARGET, и почти все отказы — "not_in_whitelist").
# Хабр изначально IT-only, там whitelist названий будет резать
# нормальные вакансии.
#
# True:  на Хабре HARD_REJECT по причине not_in_whitelist
#        понижается до REVIEW_BY_AI (уходит к Qwen).
#        Жёсткие чёрные маркеры (force_non_it_title: 'курьер',
#        'кладовщик', 'преподаватель') продолжают резать сразу.
#
# False: Хабр фильтруется ровно так же, как HH.
HABR_SOFT_FAST_FILTER = True


# Отклик на Хабре.
#
# ПО УМОЛЧАНИЮ ВЫКЛЮЧЕН. Причина конкретная: сбор и парсинг
# вакансий написаны по реальному HTML выдачи, а разметки
# страницы самой вакансии и модалки отклика не было, поэтому
# селекторы в habr/apply.py построены на видимом тексте кнопок
# и не проверены на живой странице.
#
# Пока False: конвейер по Хабру отрабатывает целиком — сбор,
# фильтры, Qwen, письмо, валидация, дампы — и на последнем шаге
# возвращает HABR_APPLY_DISABLED вместо клика. Полный прогон
# и все дампы есть, реальных откликов нет.
#
# Переводить в True после прогона inspect_habr.py и сверки
# селекторов по снятой разметке.
HABR_APPLY_ENABLED = True


# Маркеры URL для подтверждения доставки отклика на Хабре.
#
# Тот же приём, что NETWORK_RESPONSE_URL_MARKERS для HH: ловим
# ответ сервера и по HTTP-коду понимаем, дошёл отклик или нет.
# "/api/frontend/quick_responses" взят прямо из атрибута
# quickResponseHref в карточках выдачи Хабра. Точный путь
# обычного (не быстрого) отклика подтвердится после
# inspect_habr.py.
HABR_NETWORK_RESPONSE_URL_MARKERS = [
    "/api/frontend/responses",
    "/api/frontend/quick_responses",
    "vacancy_response",
    "/responses",
]


# ============================================================
# СКЛЕЙКА ИСТОЧНИКОВ
# ============================================================
#
# Хабр идёт ПОСЛЕ HH. Значит, при исчерпании общего
# MAX_APPLIES_PER_RUN до Хабра дело может не дойти.
# Если нужно наоборот — поменяй слагаемые местами:
#
#     SEARCH_URLS = HABR_SEARCH_URLS + SEARCH_URLS
#
SEARCH_URLS = SEARCH_URLS + HABR_SEARCH_URLS