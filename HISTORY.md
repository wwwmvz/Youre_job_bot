# Youre Job Bot — Історія розробки

## Загальний опис проєкту

Telegram-бот для пошуку роботи в Україні. Агрегує вакансії з кількох джерел, підтримує персональні профілі, фільтри по місту та автоматичні сповіщення.

**Репозиторій:** https://github.com/wwwmvz/Youre_job_bot  
**Деплой:** Railway (auto-deploy з main гілки)  
**Railway project ID:** `fd3158ca-a74f-4af6-9d4a-67585aca7b19`  
**Railway service ID:** `d2771380-e06a-40ad-92bf-794c68ec3860`  
**Робоча директорія:** `/tmp/job_bot/` (клон репозиторію, Documents заблокований macOS TCC)

---

## Сесія 1 — Базова структура + Djinni, DOU, Jobs.ua

Початкова версія бота вже мала:
- Пошук по DOU.ua
- Пошук по Djinni
- Пошук по Jobs.ua
- Профіль користувача (місто, сфера, досвід, зарплата, розклад)
- Автоматичні сповіщення по розкладу
- Таблиці `users` і `sent_jobs` в PostgreSQL/SQLite

---

## Сесія 2 — Work.ua RSS + Robota.ua API

### Проблеми та рішення

**Work.ua** повертав 403 на Railway датацентрі при HTML-скрапінгу.  
→ Перейшли на RSS-фід: `https://www.work.ua/jobs/rss/?search={keyword}`

**Robota.ua** блокував запити через Cloudflare.  
→ Перейшли на прямий API: `POST https://api.robota.ua/vacancy/search`

**Robota.ua 404 на посиланнях** — три ітерації:
1. `robota.ua/vacancy/{id}` — 404
2. `robota.ua/ua/company/{notebookId}/vacancies/{vacancyId}` — 404 (Angular SPA strips `/ua/`)
3. Проаналізували Angular bundle `main.7e1e0dbb96abffb0.js`, знайшли custom router matcher з regex `/^company\d+$/` + `/^vacancy\d+$/`  
   → Правильний формат: `https://robota.ua/company{notebookId}/vacancy{vacancyId}` ✅

**PERSONAL_BOT_TOKEN не знаходив** — Railway має змінну `TELEGRAM_TOKEN`, а код читав `PERSONAL_BOT_TOKEN`.  
→ Додали fallback: `os.environ.get("PERSONAL_BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN")`

### Додані функції

```python
async def fetch_workua_rss(keyword: str) -> list:
    # GET https://www.work.ua/jobs/rss/?search={keyword}
    # Парсить XML, витягує pubDate через email.utils.parsedate_to_datetime
    # job_id = f"workua_rss_{parts[-2]}"
    # source = "Work.ua"

async def fetch_robotaua(keyword: str) -> list:
    # POST https://api.robota.ua/vacancy/search
    # json={"keyWords": keyword, "ukrainian": True, "page": 0, "count": 20}
    # url = f"https://robota.ua/company{notebookId}/vacancy{vacancyId}"
    # source = "Robota.ua"
```

### Оновлення `_search_all_sources`
```python
dou_r, djinni_r, jobsua_r, workua_r, robota_r, tg_r, tgp_r = await asyncio.gather(...)
_SOURCE_ORDER = ["DOU.ua", "Djinni", "Work.ua", "Robota.ua", "Jobs.ua", "TG канали", "TG (приватний)"]
```

---

## Сесія 3 — Трекінг показаних вакансій + персистентність

### Проблема
При повторному пошуку по тому самому ключовому слову бот показував ті самі вакансії.

### Рішення
**Write-through cache**: in-memory словник + PostgreSQL/SQLite для збереження між перезапусками.

### Нова таблиця в БД
```sql
CREATE TABLE IF NOT EXISTS keyword_shown (
    user_id BIGINT,  -- або INTEGER для SQLite
    keyword TEXT,
    job_ids TEXT DEFAULT '[]',
    updated_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (user_id, keyword)
)
```

### Нові функції
```python
_keyword_shown: dict = {}  # {user_id: {kw_key: set[job_ids]}}

def load_keyword_shown(user_id: int, keyword: str) -> set:
    # SELECT job_ids FROM keyword_shown WHERE user_id=? AND keyword=?

def save_keyword_shown(user_id: int, keyword: str, job_ids: set):
    # INSERT OR REPLACE / ON CONFLICT DO UPDATE

def _get_shown(uid, kw_key) -> set:
    # Читає з кешу, при miss — з БД

def _set_shown(uid, kw_key, ids):
    # Пише в кеш + БД одночасно
```

### Логіка при пошуку
1. Отримуємо всі вакансії з джерел
2. Фільтруємо ті, що вже були показані (`_get_shown`)
3. Якщо є нові — показуємо + зберігаємо в shown
4. Якщо нових немає → `_offer_repeat_search`: кнопки "🔄 Показати попередні" / "🔙 Назад до меню"

---

## Сесія 4 — Фільтр по місту

### Запит
"Якщо я вказав місто Одеса, то на кожен запит пропонувати кнопки: 'З міста Одеси' / 'З іншого міста' / 'По всій Україні'"

### Реалізація

**Нова клавіатура:**
```python
def city_search_kb(profile_city: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton(f"🏙️ {profile_city}"), KeyboardButton("🌍 Інше місто")],
         [KeyboardButton("🌐 По всій Україні")]],
        resize_keyboard=True, one_time_keyboard=True
    )
```

**Фільтр вакансій по місту:**
```python
def _filter_by_city(jobs: list, city: str) -> list:
    # Пропускає вакансії якщо:
    # - місто збігається
    # - місто порожнє / "Україна"
    # - вакансія Remote/Дистанційна
```

**Оновлена `keyword_search`:**
```python
async def keyword_search(update, ctx, keyword, period="📅 Всі вакансії", city=None):
    # city_label = f" в {city}" if city else ""
    # kw_key = f"{keyword.strip().lower()}|{city or ''}"  # місто включено в ключ кешу
```

**Стейт-машина `handle_message` (нові кроки):**
- `if not step:` → якщо є місто в профілі → `search_city` → показує `city_search_kb`
- `search_city` → обробляє вибір міста
- `search_city_other` → показує повну `city_kb()`, зберігає місто → `search_period`
- `search_period` → передає `city` в `keyword_search`

**Виправлення `_offer_repeat_search`:**
```python
async def _offer_repeat_search(update, uid, keyword, period,
                               city, cached, period_label, city_label=""):
    user_state[uid] = {"step": "repeat_search_choice", "keyword": keyword,
                       "period": period, "city": city, "cached_jobs": cached}
```

---

## Сесія 5 — Прямі вакансії (Варіант А)

### Запит
"Роботодавець пише інфо → я публікую → вона приходить всім юзерам"

### Реалізація

**Нова env змінна:**
```
ADMIN_ID = <твій Telegram user ID>
```
(отримати через `@userinfobot`)

**Нова таблиця в БД:**
```sql
CREATE TABLE IF NOT EXISTS direct_vacancies (
    id SERIAL PRIMARY KEY,  -- INTEGER AUTOINCREMENT для SQLite
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    city TEXT DEFAULT '',
    salary TEXT DEFAULT '',
    description TEXT DEFAULT '',
    contact TEXT DEFAULT '',
    url TEXT DEFAULT '',
    keywords TEXT DEFAULT '',
    posted_at TIMESTAMP DEFAULT NOW(),
    active BOOLEAN DEFAULT TRUE
)
```

**Команда `/post` (тільки для адміна):**
8-крокова форма:
1. Назва вакансії
2. Назва компанії
3. Місто (або «Віддалено»)
4. Зарплата (або «-»)
5. Короткий опис (або «-»)
6. Контакт для зв'язку
7. Посилання (або «-»)
8. Ключові слова через кому

Після заповнення → вакансія зберігається в БД → **автоматична розсилка** всім активним юзерам чиї ключові слова в профілі збігаються.

**Інтеграція в пошук:**
```python
_SOURCE_ORDER = ["📌 Пряма вакансія", "DOU.ua", "Djinni", ...]
# Прямі вакансії йдуть першими в результатах
direct = get_direct_vacancies(keyword)
all_jobs = direct + dou_filtered + ...
```

---

## Поточна архітектура бота

### Джерела вакансій
| Джерело | Метод | Примітки |
|---------|-------|----------|
| 📌 Пряма вакансія | БД | Додається через `/post` |
| DOU.ua | HTML scraping | Фільтр по ключовому слову |
| Djinni | HTML scraping | |
| Work.ua | RSS XML | `work.ua/jobs/rss/?search=...` |
| Robota.ua | POST API | `api.robota.ua/vacancy/search` |
| Jobs.ua | HTML scraping | |
| TG канали | t.me/s/ scraping | Публічні канали |
| TG (приватний) | Telethon | Потребує TG_API_ID/HASH/SESSION |

### Environment Variables (Railway)
| Змінна | Опис |
|--------|------|
| `TELEGRAM_TOKEN` | Токен бота |
| `ADMIN_ID` | Telegram ID адміна (для /post) |
| `DATABASE_URL` | PostgreSQL URL (якщо не вказано — SQLite) |
| `TG_API_ID` | Telethon API ID (для приватних каналів) |
| `TG_API_HASH` | Telethon API Hash |
| `TG_SESSION` | Telethon StringSession |

### Команди бота
| Команда | Опис |
|---------|------|
| `/start` | Реєстрація + заповнення профілю |
| `/post` | Розмістити пряму вакансію (тільки адмін) |
| `/jobs` | Отримати вакансії за профілем зараз |
| `/settings` | Оновити профіль |
| `/stop` | Зупинити сповіщення |
| `/help` | Довідка |

### Стейт-машина пошуку
```
Текст → [є місто в профілі?]
  Так → search_city (вибір міста)
    "🏙️ {місто}" → search_period
    "🌍 Інше місто" → search_city_other → city_kb → search_period
    "🌐 По всій Україні" → search_period (city=None)
  Ні → search_period (вибір періоду)
    → keyword_search(keyword, period, city)
```

### БД таблиці
- `users` — профілі користувачів
- `sent_jobs` — надіслані вакансії по профілю (дедуплікація автосповіщень)
- `keyword_shown` — показані вакансії по ключовому слову (дедуплікація ручного пошуку)
- `direct_vacancies` — прямі вакансії від роботодавців

---

## Важливі технічні деталі

- **macOS TCC блокує Documents** → всі зміни робляться в `/tmp/job_bot/`
- **Деплой:** `git push origin main` → Railway auto-deploy
- **DB fallback:** якщо `DATABASE_URL` не встановлено → SQLite (дані губляться при редеплої)
- **`keyword_shown` ключ:** `"{keyword}|{city}"` — місто включене щоб не плутати запити по різних містах
- **Robota.ua URL формат:** `robota.ua/company{notebookId}/vacancy{vacancyId}` (без `/ua/`)

---

## Відомі обмеження / TODO

- [ ] Підключити PostgreSQL `DATABASE_URL` в Railway для справжньої персистентності `keyword_shown`
- [ ] Встановити `ADMIN_ID` в Railway Variables
- [ ] Команда `/vacancies` для перегляду і деактивації прямих вакансій (адмін)
- [ ] Статистика по прямих вакансіях (скільки переглядів, переходів)
- [ ] Оплата від роботодавців (LiqPay/Stripe) — варіант Б на майбутнє
