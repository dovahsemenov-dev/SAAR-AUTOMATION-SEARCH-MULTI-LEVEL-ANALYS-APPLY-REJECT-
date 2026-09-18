
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
OUTPUT_FILE = PROJECT_DIR / "all_project_code.txt"

INCLUDE_EXTENSIONS = {".py", ".json"}

EXCLUDE_DIRS = {
    ".venv",
    "venv",
    "__pycache__",
    ".git",
    ".idea",
    "node_modules",
}

EXCLUDE_FILES = {
    OUTPUT_FILE.name,
}


def should_skip(path: Path) -> bool:
    if path.name in EXCLUDE_FILES:
        return True

    for part in path.parts:
        if part in EXCLUDE_DIRS:
            return True

    return False


def main():
    files = []

    for path in PROJECT_DIR.rglob("*"):
        if not path.is_file():
            continue

        if should_skip(path):
            continue

        if path.suffix.lower() not in INCLUDE_EXTENSIONS:
            continue

        files.append(path)

    files.sort(key=lambda p: str(p.relative_to(PROJECT_DIR)).lower())

    with OUTPUT_FILE.open("w", encoding="utf-8") as out:
        out.write("=" * 100 + "\n")
        out.write("AI AUTO PROJECT DUMP\n")
        out.write("=" * 100 + "\n\n")

        for path in files:
            relative_path = path.relative_to(PROJECT_DIR)

            out.write("\n")
            out.write("=" * 100 + "\n")
            out.write(f"FILE: {relative_path}\n")
            out.write("=" * 100 + "\n\n")

            try:
                content = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                try:
                    content = path.read_text(encoding="utf-8-sig")
                except Exception as e:
                    content = f"[ERROR READING FILE: {e}]"

            out.write(content)

            if not content.endswith("\n"):
                out.write("\n")

    print(f"Готово.")
    print(f"Собрано файлов: {len(files)}")
    print(f"Результат: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()

