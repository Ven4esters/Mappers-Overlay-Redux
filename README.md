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
  ui/main_window.py      # главное окно (пока каркас)
  ui/region_overlay.py   # оверлей выбора области
  discord_client.py      # вебхук: multipart, ретраи 429/5xx, маппинг кодов ошибок
  albums.py              # сервис альбомов: создание/привязка/имена файлов
  oauth.py               # OAuth2 webhook.incoming: PKCE, локальный колбэк, обмен кода
  transfer.py            # экспорт/импорт резервной копии (config+history)
  workers.py             # QThread-конвейеры: отправка, подключение Discord
  cache.py               # локальный кэш отправленных скриншотов (blake2b, дедуп)
assets/i18n/             # языковые пакеты (RU+EN, ключи синхронны)
tests/                   # pytest (80 тестов, respx-моки для HTTP)
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
| 9 | BB-код публикации (XenForo) + кэш скриншотов + catbox | ⏳ |
| 10 | start.bat, README-финализация, смоук-тесты | ⏳ |

## Подключить Discord (OAuth2) / Connect Discord

Кнопка **«🔗 Подключить Discord…»** (Настройки → Профили) создаёт вебхук сама: вы выбираете сервер и канал прямо в интерфейсе Discord, приложение получает URL вебхука и предлагает сохранить профиль. Токен доступа нигде не сохраняется — из ответа берётся только `webhook.url`.

The **“Connect Discord…”** button (Settings → Profiles) creates the webhook itself: you pick a server and channel in Discord's own UI, the app receives the webhook URL and offers to save it as a profile. The access token is never stored — only `webhook.url` is kept.

**Одноразовая настройка (один раз на установку) / One-time setup (once per installation):**

1. https://discord.com/developers/applications → **New Application**
2. **OAuth2 → Redirects** → добавьте `http://localhost:8321/callback` (ровно так, порт = `redirect_port`)
3. Скопируйте **Client ID** и **Client Secret**
4. Создайте рядом с `main.py` файл `oauth.client.json` (шаблон: `oauth.client.example.json`):
   ```json
   { "client_id": "…", "redirect_port": 8321, "client_secret": "…" }
   ```
   `oauth.client.json` в `.gitignore` и никогда не коммитится.
5. Нажмите «Подключить Discord» снова. Откроется браузер; после выбора канала вкладку можно закрыть.

Без этого файла кнопка покажет инструкцию, а отправка по обычному вебхуку (вставка URL вручную) работает как раньше. / Without the file, the button shows this help; manual webhook URLs keep working.

Приложение проекта по умолчанию публичное (`client_id 1572688177242574918` в репозитории). Вы можете зарегистрировать **собственное** приложение Discord — тогда `client_id` в `oauth.client.json` переопределит встроенный.

## Безопасность / Security
- `config.json` (URL вебхуков), `oauth.client.json` (client secret), `cache/` — в `.gitignore`.
- Токены OAuth нигде не хранятся: из ответа берётся только `webhook.url`/`channel_id`.
- Webhook URL — фактически пароль на отправку в канал: храните `config.json` как секрет.

## Лицензия / License
MIT (see LICENSE when added) / MIT (см. LICENSE, когда добавим).
