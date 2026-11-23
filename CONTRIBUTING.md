# Как мы работаем над Mapper's Overlay Redux

Документ фиксирует правила из `docs/instruction-code-style-and-checks.md` применительно
к этому проекту: что именно проверяется автоматически и что считается «готово».

## Definition of Done

Задача закрыта, только если:

- `ruff format --check .` и `ruff check .` чистые;
- `mypy` чистый (strict, Python 3.12);
- `bandit -q -c pyproject.toml -r map_overlay tools` без замечаний, `detect-secrets-hook`
  по `git ls-files` — без находок, `pip-audit` — без уязвимостей,
  `python -m tools.check_licenses` — без сильного копилефта;
- `pytest` зелёный, покрытие `map_overlay` не ниже 80 %, критичные модули
  (`domain/movement.py`, `domain/formatting.py`, `application/writer.py`,
  `application/session.py`) — 100 % по ветвям, насколько это достижимо;
- на каждый исправленный баг добавлен регрессионный тест;
- обновлены `CHANGELOG.md` и README, если изменилось поведение для пользователя;
- значимое решение описано в `docs/adr/`;
- новая ошибка/тупик занесены в `docs/LESSONS.md`;
- нет мёртвого кода, закомментированных блоков, `TODO` без тикета, магических чисел.

## Коммиты и ветки

- Conventional Commits: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`, `perf:`.
  Ломающее изменение — `feat!:` с объяснением в теле.
- В сообщении — смысл изменения и причина, а не перечисление файлов.
- История не переписывается (`force-push` в общие ветки запрещён).

## Перед каждой версией

1. Прогнать все проверки из Definition of Done.
2. Перечитать `docs/LESSONS.md` и сверить код: не повторяем ли уже пройденный тупик.
3. Проверить, что документация соответствует коду (README, ADR, CHANGELOG).
4. Собрать `LSP...zip`/архив релиза, распаковать в чистую папку, запустить `--check-only`
   и тесты — только потом коммит и тег.

## CI

`.github/workflows/ci.yml` на Python 3.12: формат, линтер, типы, тесты с покрытием,
`bandit`, `pip-audit`, проверка лицензий (`tools/check_licenses.py`), поиск секретов
(`detect-secrets-hook` по `git ls-files`), сборка колеса пакета. PR без зелёного CI не мержится. Шаблон PR — `.github/pull_request_template.md`
(что, зачем, как проверено, риски, откат).

## Документация

- `README.md` — для пользователя: что умеет, как запустить, как откалибровать.
- `docs/adr/` — решения с контекстом и последствиями.
- `docs/LESSONS.md` — памятка: ошибка → причина → как не повторить.
- `CHANGELOG.md` — только пользовательские изменения, SemVer.
- `docs/instruction-code-style-and-checks.md` — исходная инструкция, менять её нельзя.
