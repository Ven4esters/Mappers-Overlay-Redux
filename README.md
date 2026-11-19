# Screensaver into Discord / Скриншот → Discord

> **RU.** Десктоп-приложение (Python 3.12 + PySide6): снимает экран/окно/область (глобальный хоткей снимка с оверлеем выбора режима; по умолчанию PrtSc, но Windows часто забирает его себе — клавишу можно переназначить в Настройки → Приложение → Горячие клавиши) и публикует скриншоты в темы Discord-форума («Альбомы») через **вебхуки** — без отдельного сервера-посредника и без хостинга. Авторизация только через вебхук по URL: приложение не хранит и не запрашивает у Discord никаких токенов. Двуязычный интерфейс RU/EN. Поддержка «Название | N.ext»-именования, секций (`**Заголовок**` + скриншоты одним сообщением), импорта существующих публикаций форума по ссылкам (без бота) и BB-кода публикации для XenForo-форумов (спойлеры + медиа-ссылки).
>
> **EN.** Desktop app (Python 3.12 + PySide6): capture full screen / active window / region (global screenshot hotkey with a mode picker overlay; defaults to PrtSc but Windows usually claims it — rebind it in Settings → App → Hotkeys) and post screenshots into Discord forum threads ("Albums") via **webhooks** — no middleman server, no hosting. Webhooks are the only auth path: the app stores and requests no Discord tokens. Bilingual RU/EN UI. Supports `Name | N.ext` file naming, sections (`**Heading**` + shots in one message), import of existing forum posts via links (no bot needed), and XenForo BB-code export for forum publishing (spoilers + media links).

## Быстрый старт / Quick start

### Windows (рекомендуется / recommended)
```bat
start.bat
```
`start.bat` → создаёт `.venv` → ставит зависимости → запускает приложение. Нужен Python 3.12.

### Вручную / Manually
```bash
py -3.12 -m venv .venv          # or python3.12 -m venv .venv
.venv/Scripts/activate          # Linux/macOS: source .venv/bin/activate
python -m pip install -r requirements.txt
python main.py
```

> Linux note: Qt needs system GL libraries (`libgl1`, `libegl1`, `libxkbcommon`). Windows works out of the box.

## Состав репозитория / Project layout
```
main.py                  # точка входа / entry point
app/
  paths.py               # портативные пути (config.json, cache/)
  i18n.py                # мини-i18n RU/EN (assets/i18n/*.json)
  theme.py               # тёмная синяя UIX-палитра (Fusion + QSS)
  models.py              # dataclasses: AppSettings / WebhookProfile / Album / HistoryItem
  store.py               # config.json + history.json, атомарная запись, .bak-recovery
  webhook_url.py         # валидация/разбор URL вебхука
  capture.py             # захват: весь экран / активное окно / область (Qt-free, тестируемо)
  hotkeys.py             # глобальные хоткеи Windows (настраиваемый снимок, Ctrl+Shift+S/R)
  hotkey_parse.py        # чистая нормализация/разбор хоткеев (без Qt)
  ui/hotkey_qt.py        # QKeySequence из канонической комбинации (лениво, с фоллбэками)
  logging_setup.py       # журнал: ротация screensaver.log + маскировка секретов
  ui/main_window.py      # главное окно (очередь, секции, отправка)
  ui/capture_overlay.py  # PrtSc-оверлей выбора режима захвата
  ui/import_threads_dialog.py  # импорт существующих публикаций по ссылкам
  ui/region_overlay.py   # оверлей выбора области
  discord_client.py      # вебхук: multipart, ретраи 429/5xx, маппинг кодов ошибок
  albums.py              # сервис альбомов: создание/привязка/импорт/имена файлов
  transfer.py            # экспорт/импорт резервной копии (config+history)
  workers.py             # QThread-конвейеры: отправка batch'ей
  cache.py               # локальный кэш отправленных скриншотов (blake2b, дедуп)
  bbcode.py              # сборщик BB-кода XenForo (заголовок, секции, спойлеры)
  catbox.py              # анонимная загрузка на catbox.moe (постоянные ссылки)
assets/i18n/             # языковые пакеты (RU+EN, ключи синхронны)
tests/                   # pytest (respx-моки, QT-free)
```

## Статус модулей / Module status
| # | Модуль | Статус |
|---|--------|--------|
| 1 | Каркас: пути, i18n, тема, входная точка, UI-скелет | ✅ |
| 2 | Конфигурация: профили вебхуков, реестр альбомов, история | ✅ |
| 3 | Захват экрана (mss + overlay области) + горячие клавиши | ✅ |
| 4 | Discord-клиент (webhook, multipart, 429/2200xx, потоковая отправка) | ✅ |
| 5 | Альбомы: создание/привязка/сквозная нумерация имён | ✅ |
| 6 | Главное окно: очередь, секции, отправка (QThread) | ✅ |
| 7 | Настройки, профили, очистка кэша, экспорт/импорт | ✅ |
| 8 | BB-код публикации (XenForo) + кэш скриншотов + catbox | ✅ |
| 9 | Принтскрин-оверлей, импорт существующих публикаций по ссылкам | ✅ |
| 10 | start.bat, README-финализация, смоук-тесты | ✅ |

## Вебхук: как получить URL / Webhook: how to get the URL

Приложение использует вебхук как единственный канал отправки. Создание занимает минуту и делается внутри Discord; никаких ключей приложения создавать не нужно.

The app uses a webhook URL as its only delivery channel. Creating one takes about a minute and happens entirely inside Discord; no developer-application keys are needed.

**RU.**
1. Правый клик по каналу (или по форум-каналу) → **Настройки канала → Интеграции → Вебхуки → Новый вебхук**.
2. Задайте имя и аватар бота-вебхука, скопируйте **URL вебхука**.
3. В приложении: **Настройки → Профили** → вставьте URL в поле «URL вебхука», нажмите **«Проверить вебхук»**, затем «Добавить».
4. Для альбомов в форуме вебхук создаётся **внутри форум-канала** — все темы форума будут поститься через него.
5. URL вебхука = пароль на отправку в канал: храните `config.json` в секрете (он в `.gitignore`).

**EN.**
1. Right-click the channel (or forum channel) → **Channel settings → Integrations → Webhooks → New Webhook**.
2. Set the bot-webhook name/avatar and copy the **Webhook URL**.
3. In the app: **Settings → Profiles** → paste the URL into “Webhook URL”, press **“Test webhook”**, then “Add”.
4. For album posts in a forum, create the webhook **inside the forum channel** — all of the forum's threads are posted through it.
5. A webhook URL is a posting password: keep `config.json` secret (it is gitignored).

## Импорт существующих публикаций / Importing existing posts

**Дисклеймер.** Вебхук Discord принципиально не умеет перечислять темы форума — это ограничение REST API. Поэтому «волшебной кнопки поиска» без бота не существует: существующие публикации подключаются **по ссылкам**.

**RU.** В сайдбаре есть **«📥 Импорт по ссылкам»**. Как получить ссылки: в Discord ПКМ по посту → «Копировать ссылку»; вставьте их в диалог по одной на строку. Приложение зарегистрирует каждую как альбом. Если пост создан через это приложение, название восстановится само из стартовой карточки (вебхук может читать собственные сообщения — больше ничего недоступно). Если пост создан вручную, он получит имя «Thread &lt;id&gt;» — поправьте через ПКМ по альбому → «Переименовать…». Дуббликаты пропускаются, счётчик «Начать нумерацию с» можно задать общий.

**EN.** The sidebar has **“Import via links”**. In Discord, right-click a post → “Copy Link”, then paste the links into the dialog, one per line. Each becomes an album. Posts created by this app recover their name from the starter card (a webhook can only read its own messages — nothing more is available). Manually-created posts get the placeholder “Thread &lt;id&gt;” — fix it via right-click → “Rename…”. Duplicates are skipped, and a shared “start numbering at” counter can be set.

**Почему без бота.** Полноценное обнаружение (список активных/архивных тем) требует бота как единственный способ в REST API — приложение его не запрашивает и не хранит. / **Why no bot.** Full discovery (listing active/archived threads) is only possible via a bot in the Discord REST API; the app does not request and never stores one.

## BB-код для XenForo / BB-code export

В контекстном меню альбома — **«BB-код публикации…»**. Диалог собирает пост из истории отправок выбранного альбома:

Right-click an album → **“BB-code to publish…”**. The dialog builds the post from the album's send history:

```
[B][SIZE=6][COLOR=#FFD34D]Название альбома[/COLOR][/SIZE][/B]

[B]Название секции[/B]
[spoiler]
[IMG]https://…/1.png[/IMG]
[IMG]https://…/2.png[/IMG]
[/spoiler]
```

- **Источник ссылок**: Discord CDN (по умолчанию, ≈24 ч) или **catbox.moe** (постоянные; файлы загружаются из локального кэша один раз, повторный экспорт не перезаливает).
- **Медиа-тег**: `IMG` (по умолчанию), `MEDIA` или собственный (`CUSTOM`).
- Заголовок: жёлтый жирный шаблон `#FFD34D` (настраивается ключом `bb_heading_template` в config.json).
- Локальный кэш скриншотов включён по умолчанию (нужен для catbox); «Настройки → Приложение → Очистить кэш» удаляет его содержимое.

- **Link source**: Discord CDN (default, ≈24 h) or **catbox.moe** (permanent; files upload from the local cache once, re-exports never re-upload).
- **Media tag**: `IMG` (default), `MEDIA` or a custom tag.
- Heading: yellow bold template `#FFD34D` (configurable via `bb_heading_template` in config.json).
- Local screenshot cache is on by default (needed for catbox); clear it in Settings → App → Clear cache.

## Финал / Final

Приложение запускается двойным кликом по `start.bat` (само развернёт `.venv` и зависимости) или `python main.py`. Глобальный хоткей снимка (по умолчанию PrtSc — Windows его часто перехватывает, поэтому переназначается в **Настройки → Приложение → Горячие клавиши**, например на F9) открывает overlay выбора режима; последний использованный режим подсвечивается и выбирается по Enter. Внутри окна та же комбинация работает всегда.

Launch by double-clicking `start.bat` (it self-provisions `.venv` + deps) or `python main.py`. The global screenshot hotkey (PrtSc by default — but Windows usually claims it, so it can be rebound in **Settings → App → Hotkeys**, e.g. to F9) opens the mode-picker overlay; the last used mode is pre-highlighted and confirmed with Enter. The same combo always works inside the window.

**Логи / Logs.** Журнал — `screensaver.log` рядом с `main.py` (ротация, 2 файла по 512 КБ, путь также в Настройках → Приложение → «О программе»). Без секретного: URL вебхуков и ключи маскируются форматтером до записи. Туда попадают запуск (версия, Python, платформа), регистрация глобальных хоткеев, результаты отправки (счётчики, без содержимого), решения импорта, восстановление из .bak. / The journal lives at `screensaver.log` next to `main.py` (rotating, 2×512 KB, path also shown in Settings → App → About). Secrets never persist: webhook URLs and keys are redacted by the formatter. It records startup (version, Python, platform), global-hotkey registration, send counts (no content), import results and .bak recovery.

**Что нужно знать / Known limitations:**
- GUI проверен автоматическими тестами логики (QT-free) и headless-компиляцией; первый живой прогон интерфейса — на Windows (Qt там работает из коробки, Linux нужны `libgl1`, `libegl1`, `libxkbcommon`). / GUI logic is covered by QT-free tests; the first live UI run happens on Windows (Linux needs the GL libs).
- Импорт существующих публикаций работает только по ссылкам (вебхук не перечисляет темы); имена восстанавливаются лишь для постов, созданных этим приложением. / Importing existing posts works by links only (webhooks cannot list threads); names are recovered only for posts created by this app.
- Ссылки Discord CDN живут ≈24 ч (ограничение Discord); для постоянных медиа-ссылок в BB-коде используйте источник catbox.moe. / Discord CDN links expire after ≈24 h; use catbox.moe for permanent BB-code media links.
- URL вебхука = пароль на отправку в канал: храните `config.json` в секрете (он в `.gitignore`). / A webhook URL is a posting password: keep `config.json` secret (it is gitignored).

## Безопасность / Security
- `config.json` (URL вебхуков), `cache/` — в `.gitignore`.
- Webhook URL — фактически пароль на отправку в канал: храните `config.json` как секрет.

## Лицензия / License
MIT (see LICENSE when added) / MIT (см. LICENSE, когда добавим).
