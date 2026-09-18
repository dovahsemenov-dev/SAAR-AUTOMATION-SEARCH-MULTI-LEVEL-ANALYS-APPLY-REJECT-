# AI Vacancy Analyzer

AI-assisted vacancy search and multi-level analysis tool.

## What it does

- Searches vacancies using configured sources.
- Applies fast filtering and decision rules.
- Analyzes vacancy requirements with AI.
- Matches requirements against a structured candidate profile.
- Supports application/review/reject workflows.
- Integrates with external APIs and browser automation.

## Tech stack

- Python
- Playwright
- Requests
- Local/remote LLM integration used by the project

## Local setup

```bash
pip install -r requirements.txt
playwright install
```

Before running the application, configure your own vacancy search URLs and local profile data.

**Do not commit personal resume IDs, private URLs, browser profiles, credentials, or local vacancy history.**

## Project structure

- `ai/` — AI analysis and profile matching
- `filters/` — filtering and decision logic
- `hh/` — HeadHunter integration
- `habr/` — Habr integration
- `main.py` — main application entry point
- `config.py` — local configuration
