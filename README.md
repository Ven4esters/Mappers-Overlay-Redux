# Screensaver into Discord / Скриншот → Discord

> **RU.** Десктоп-приложение (Python 3.12 + PySide6): снимает экран/окно/область и публикует скриншоты в темы Discord-форума («Альбомы») через **вебхуки** — без отдельного бота и без хостинга. Доставка: обычный вебхук по URL (всегда работает) либо кнопка «Подключить Discord» (OAuth2 `webhook.incoming` + PKCE; токен не хранится). Двуязычный интерфейс RU/EN. Поддержка «Название | N.ext»-именования, секций (`**Заголовок**` + скриншоты одним сообщением), BB-кода публикации для XenForo-форумов (спойлеры + медиа-ссылки).
>
> **EN.** Desktop app (Python 3.12 + PySide6): capture full screen / active window / region and post screenshots into Discord forum threads ("Albums") via **webhooks** — no bot, no hosting required. Delivery: plain webhook URL (works out of the box) or a "Connect Discord" button (OAuth2 `webhook.incoming` + PKCE; the token is never stored). Bilingual RU/EN UI. Supports `Name | N.ext` file naming, sections (`**Heading**` + shots in one message), and XenForo BB-code export for forum publishing (spoilers + media links).

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
  hotkeys.py             # глобальные хоткеи Windows (Ctrl+Shift+S/R)
  ui/main_window.py      # главное окно (очередь, секции, отправка)
  ui/region_overlay.py   # оверлей выбора области
  discord_client.py      # вебхук: multipart, ретраи 429/5xx, маппинг кодов ошибок
  albums.py              # сервис альбомов: создание/привязка/имена файлов
  oauth.py               # OAuth2 webhook.incoming: PKCE, локальный колбэк, обмен кода
  transfer.py            # экспорт/импорт резервной копии (config+history)
  workers.py             # QThread-конвейеры: отправка, подключение Discord
  cache.py               # локальный кэш отправленных скриншотов (blake2b, дедуп)
  bbcode.py              # сборщик BB-кода XenForo (заголовок, секции, спойлеры)
  catbox.py              # анонимная загрузка на catbox.moe (постоянные ссылки)
assets/i18n/             # языковые пакеты (RU+EN, ключи синхронны)
tests/                   # pytest (107 тестов: 106 ✓ + 1 GUI-skip, respx-моки)
oauth.client.example.json  # шаблон oauth.client.json (сам файл НЕ коммитится)
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
| 8 | OAuth2 (PKCE) «Подключить Discord» | ✅ |
| 9 | BB-код публикации (XenForo) + кэш скриншотов + catbox | ✅ |
| 10 | start.bat, README-финализация, смоук-тесты | ✅ |

## Подключить Discord (OAuth2) / Connect Discord

Кнопка **«🔗 Подключить Discord…»** (Настройки → Профили) создаёт вебхук сама: вы выбираете сервер и канал прямо в интерфейсе Discord, приложение получает URL вебхука и предлагает сохранить профиль. Токен доступа нигде не сохраняется — из ответа берётся только `webhook.url`.

The **“Connect Discord…”** button (Settings → Profiles) creates the webhook itself: you pick a server and channel in Discord's own UI, the app receives the webhook URL and offers to save it as a profile. The access token is never stored — only `webhook.url` is kept.

**Одноразовая настройка прямо в приложении (один раз на установку):**

1. **Настройки → Профили → «Подключение Discord (OAuth2)»** → нажмите **«Открыть Developer Portal…»** и создайте приложение: https://discord.com/developers/applications → **New Application** → **OAuth2**.
2. **OAuth2 → Redirects** → добавьте Redirect URI (кнопка **«Копировать Redirect URI»** даёт `http://localhost:8321/callback`).
3. Скопируйте **Client ID** и **Client Secret** в поля ниже и нажмите **«Сохранить и записать oauth.client.json»** — приложение само создаст `oauth.client.json` рядом с `main.py` (права только для владельца, `chmod 600` на POSIX). Создавать или редактировать файлы руками **не нужно**.
4. Нажмите **«🔗 Подключить Discord…»**: откроется браузер; после выбора сервера и канала вкладку можно закрыть — приложение получит webhook URL и само подставит его в новый профиль; останется указать имя и нажать «Добавить».

`oauth.client.json` в `.gitignore` и никогда не коммитится; удалить его можно кнопкой **«Удалить ключи»**. Файл `oauth.client.example.json` — необязательный шаблон для ручной правки (в обычной настройке не нужен).

> **Важно.** Client ID и Client Secret должны быть от **одного и того же** приложения, и именно на нём в **OAuth2 → Redirects** должен быть зарегистрирован Redirect URI — точное совпадение, включая `http`, `localhost`, порт и путь (`/callback`). Если Discord отвечает «Некорректный OAuth2 redirect_uri»: (а) убедитесь, что в поле Client ID вписан ID именно того приложения, где вы добавили Redirect (встроенный Client ID из репозитория принадлежит приложению автора и заработает только с его секретом); (б) проверьте, что URI зарегистрирован **до** первого «Подключить» и совпадает символ в символ; (в) если меняли порт — зарегистрируйте `http://localhost:ВАШ_ПОРТ/callback`.

> **Важно про форумы.** В окне OAuth2 (scope `webhook.incoming`) Discord **не показывает форум-каналы** — можно выбрать только текстовые/объявления/голосовые. Это ограничение Discord, а не приложения. Для альбомов в форуме создайте вебхук вручную внутри форум-канала (правый клик по каналу → Настройки → Интеграции → Вебхуки → Новый вебхук → Копировать URL) и вставьте его в «URL вебхука»; OAuth для форума не нужен. Кнопка «Подключить Discord…» подходит, когда хотите отправлять обычными сообщениями в текстовый канал.

**One-time in-app setup (once per installation):**

1. **Settings → Profiles → “Connect Discord (OAuth2)”** → press **“Open Developer Portal…”** and create an app: https://discord.com/developers/applications → **New Application** → **OAuth2**.
2. **OAuth2 → Redirects** → add the Redirect URI (the **“Copy Redirect URI”** button provides `http://localhost:8321/callback`).
3. Paste **Client ID** and **Client Secret** into the fields and press **“Save and write oauth.client.json”** — the app creates `oauth.client.json` next to `main.py` itself (owner-only permissions, `chmod 600` on POSIX). No hand-editing of files is needed.
4. Press **“Connect Discord…”**: a browser opens; after you pick the server and channel the tab can be closed — the app receives the webhook URL and pre-fills a new profile; name it and press “Add”.

`oauth.client.json` is `.gitignore`d and never committed; the **“Remove credentials”** button deletes it. `oauth.client.example.json` is an optional template for manual setup (not needed in the usual flow).

> **Important.** Client ID and Client Secret must come from the **same** app, and that exact app must have the Redirect URI registered (**OAuth2 → Redirects**) — exact match, including `http`, `localhost`, port and path (`/callback`). If Discord answers “Invalid OAuth2 redirect_uri”: (a) make sure the Client ID field holds the ID of the app where you registered the URI (the built-in Client ID in the repo belongs to the author's app and only works with its secret); (b) register the URI **before** pressing Connect, exactly as shown; (c) if you changed the port, register `http://localhost:YOUR_PORT/callback`.

> **About forums.** In the OAuth2 dialog (scope `webhook.incoming`) Discord **does not list forum channels** — only text/announcement/voice channels can be picked. That is a Discord limitation, not the app's. For album threads in a forum, create the webhook inside the forum channel itself (right-click the channel → Settings → Integrations → Webhooks → New Webhook → Copy URL) and paste it into “Webhook URL” — no OAuth needed for forums. The “Connect Discord…” button is the right path when you want plain messages in a text channel.

Если вебхука у вас ещё нет — кнопка выше создаст его сама. Если вебхук уже есть, OAuth вообще не нужен: вставьте его URL в поле «URL вебхука» (глазик покажет/спрячет его) и нажмите «Проверить вебхук». / If you already have a webhook, no OAuth is needed at all: paste its URL (the eye toggle reveals/hides it) and press “Test webhook”. Without saved keys the button shows a hint; manual webhook URLs keep working regardless.

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

Готовы и запушены все 10 модулей: каркас → конфигурация → захват → Discord-клиент → альбомы → главное окно → настройки → OAuth2 → BB-код → релизная обвязка. Приложение запускается двойным кликом по `start.bat` (само развернёт `.venv` и зависимости) или `python main.py`.

All 10 modules are done and pushed: scaffold → config → capture → Discord client → albums → main window → settings → OAuth2 → BB-code → release packaging. Double-click `start.bat` (it self-provisions `.venv` + deps) or run `python main.py`.

**Что нужно знать / Known limitations:**
- GUI проверен автоматическими тестами логики (QT-free) и headless-компиляцией; первый живой прогон интерфейса — на Windows (Qt там работает из коробки, Linux нужны `libgl1`, `libegl1`, `libxkbcommon`). / GUI logic is covered by QT-free tests; the first live UI run happens on Windows (Linux needs the GL libs).
- «Подключить Discord» требует одноразового ввода Client ID / Client Secret в настройках — приложение само запишет `oauth.client.json` (см. раздел про OAuth2 выше); без них ручной вебхук работает как раньше. / The Connect button needs a one-time entry of Client ID / Client Secret in the settings — the app writes `oauth.client.json` itself (see OAuth2 section); manual webhooks work regardless.
- Ссылки Discord CDN живут ≈24 ч (ограничение Discord); для постоянных медиа-ссылок в BB-коде используйте источник catbox.moe. / Discord CDN links expire after ≈24 h; use catbox.moe for permanent BB-code media links.
- URL вебхука = пароль на отправку в канал: храните `config.json` в секрете (он в `.gitignore`). / A webhook URL is a posting password: keep `config.json` secret (it is gitignored).

## Безопасность / Security
- `config.json` (URL вебхуков), `oauth.client.json` (client secret), `cache/` — в `.gitignore`.
- Токены OAuth нигде не хранятся: из ответа берётся только `webhook.url`/`channel_id`.
- Webhook URL — фактически пароль на отправку в канал: храните `config.json` как секрет.

## Лицензия / License
MIT (see LICENSE when added) / MIT (см. LICENSE, когда добавим).
