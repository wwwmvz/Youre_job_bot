import asyncio
import sqlite3
import logging
import os
import re
from datetime import datetime
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup
from telegram import (
    Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, filters, ContextTypes
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler("personal_bot.log"), logging.StreamHandler()]
)
log = logging.getLogger(__name__)

# ─── НАЛАШТУВАННЯ ────────────────────────────────────────────────────────────
PERSONAL_BOT_TOKEN = os.getenv("PERSONAL_BOT_TOKEN", "8018911506:AAFPS_Jdw8MCYJ34M3UGnKvGoEV8PN7yRSQ")
MAIN_CHANNEL = os.getenv("MAIN_CHANNEL", "https://t.me/+YNCaw9gBllI5NzU0")  # посилання на основний канал
DB_FILE = "personal_bot.db"
# ─────────────────────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

# ─── СТАНИ РОЗМОВИ ───────────────────────────────────────────────────────────
(
    ASK_CITY, ASK_PROFESSION, ASK_EXPERIENCE,
    ASK_SALARY, ASK_SCHEDULE, DONE
) = range(6)

# ─── МІСТА ───────────────────────────────────────────────────────────────────
CITIES = [
    "Київ", "Львів", "Одеса", "Харків", "Дніпро", "Запоріжжя",
    "Вінниця", "Полтава", "Черкаси", "Чернігів", "Суми", "Житомир",
    "Рівне", "Луцьк", "Тернопіль", "Івано-Франківськ", "Ужгород",
    "Чернівці", "Хмельницький", "Кропивницький", "Миколаїв", "Херсон",
    "Запоріжжя", "Віддалено / Remote"
]

EXPERIENCE_OPTIONS = [
    "Без досвіду", "До 1 року", "1-2 роки", "2-5 років", "5+ років"
]

SALARY_OPTIONS = [
    "10 000", "15 000", "20 000", "25 000", "30 000",
    "35 000", "40 000", "50 000", "60 000", "70 000",
    "80 000", "100 000+", "Не важливо"
]

SCHEDULE_OPTIONS = [
    "⚡ Одразу як з'являється", "🕐 Раз на годину",
    "🕒 Раз на 3 години", "🕕 Раз на 6 годин", "📅 Раз на день"
]

PROFESSIONS = [
    "💻 IT / Програмування", "📊 Аналітика / Data",
    "🎨 Дизайн / UX", "📱 Мобільна розробка",
    "⚙️ DevOps / Адміністрування", "🧪 QA / Тестування",
    "📢 Маркетинг / SMM", "💰 Продажі / Менеджмент",
    "📞 Підтримка / Сервіс", "🏦 Бухгалтерія / Фінанси",
    "⚖️ Юриспруденція", "👥 HR / Рекрутинг",
    "🚗 Водій / Кур'єр", "📦 Склад / Логістика",
    "🏗️ Будівництво / Монтаж", "🍽️ HoReCa / Кухар",
    "🛒 Торгівля / Касир", "🏥 Медицина / Фармація",
    "📚 Освіта / Викладання", "🔒 Охорона / Безпека",
    "🌐 Інше"
]

PROFESSION_KEYWORDS = {
    "💻 IT / Програмування": ["python", "javascript", "java", "php", "програміст", "розробник", "developer"],
    "📊 Аналітика / Data": ["аналітик", "analyst", "data", "bi", "tableau", "excel"],
    "🎨 Дизайн / UX": ["дизайнер", "designer", "ui", "ux", "figma", "photoshop"],
    "📱 Мобільна розробка": ["ios", "android", "swift", "kotlin", "mobile"],
    "⚙️ DevOps / Адміністрування": ["devops", "docker", "linux", "адмін", "сисадмін", "aws"],
    "🧪 QA / Тестування": ["qa", "тестувальник", "testing", "автоматизація"],
    "📢 Маркетинг / SMM": ["маркетолог", "smm", "seo", "контент", "реклама", "таргет"],
    "💰 Продажі / Менеджмент": ["менеджер", "продажі", "sales", "manager", "продавець-консультант"],
    "📞 Підтримка / Сервіс": ["підтримка", "support", "оператор", "колцентр", "сервіс"],
    "🏦 Бухгалтерія / Фінанси": ["бухгалтер", "фінансист", "accountant", "економіст"],
    "⚖️ Юриспруденція": ["юрист", "lawyer", "legal", "адвокат"],
    "👥 HR / Рекрутинг": ["hr", "рекрутер", "recruiter", "кадри"],
    "🚗 Водій / Кур'єр": ["водій", "кур'єр", "driver", "courier", "доставка"],
    "📦 Склад / Логістика": ["склад", "вантажник", "комплектувальник", "логіст", "warehouse"],
    "🏗️ Будівництво / Монтаж": ["будівельник", "монтажник", "електрик", "зварювальник", "ремонт"],
    "🍽️ HoReCa / Кухар": ["кухар", "офіціант", "бармен", "повар", "ресторан"],
    "🛒 Торгівля / Касир": ["касир", "продавець", "консультант", "магазин"],
    "🏥 Медицина / Фармація": ["лікар", "медсестра", "фармацевт", "медичний"],
    "📚 Освіта / Викладання": ["вчитель", "викладач", "репетитор", "teacher"],
    "🔒 Охорона / Безпека": ["охоронець", "охорона", "security", "безпека"],
    "🌐 Інше": [],
}

PROFESSION_PHOTOS = {
    "💻 IT / Програмування": "https://images.unsplash.com/photo-1461749280684-dccba630e2f6?w=800&fit=crop",
    "📊 Аналітика / Data": "https://images.unsplash.com/photo-1551288049-bebda4e38f71?w=800&fit=crop",
    "🎨 Дизайн / UX": "https://images.unsplash.com/photo-1561070791-2526d30994b5?w=800&fit=crop",
    "📱 Мобільна розробка": "https://images.unsplash.com/photo-1526498460520-4c246339dccb?w=800&fit=crop",
    "⚙️ DevOps / Адміністрування": "https://images.unsplash.com/photo-1558494949-ef010cbdcc31?w=800&fit=crop",
    "🧪 QA / Тестування": "https://images.unsplash.com/photo-1518770660439-4636190af475?w=800&fit=crop",
    "📢 Маркетинг / SMM": "https://images.unsplash.com/photo-1611162617213-7d7a39e9b1d7?w=800&fit=crop",
    "💰 Продажі / Менеджмент": "https://images.unsplash.com/photo-1552664730-d307ca884978?w=800&fit=crop",
    "📞 Підтримка / Сервіс": "https://images.unsplash.com/photo-1521791136064-7986c2920216?w=800&fit=crop",
    "🏦 Бухгалтерія / Фінанси": "https://images.unsplash.com/photo-1554224155-6726b3ff858f?w=800&fit=crop",
    "⚖️ Юриспруденція": "https://images.unsplash.com/photo-1589829545856-d10d557cf95f?w=800&fit=crop",
    "👥 HR / Рекрутинг": "https://images.unsplash.com/photo-1573497019940-1c28c88b4f3e?w=800&fit=crop",
    "🚗 Водій / Кур'єр": "https://images.unsplash.com/photo-1449965408869-eaa3f722e40d?w=800&fit=crop",
    "📦 Склад / Логістика": "https://images.unsplash.com/photo-1586528116311-ad8dd3c8310d?w=800&fit=crop",
    "🏗️ Будівництво / Монтаж": "https://images.unsplash.com/photo-1504307651254-35680f356dfd?w=800&fit=crop",
    "🍽️ HoReCa / Кухар": "https://images.unsplash.com/photo-1556909114-f6e7ad7d3136?w=800&fit=crop",
    "🛒 Торгівля / Касир": "https://images.unsplash.com/photo-1601598851547-4302969d0614?w=800&fit=crop",
    "🏥 Медицина / Фармація": "https://images.unsplash.com/photo-1576091160550-2173dba999ef?w=800&fit=crop",
    "📚 Освіта / Викладання": "https://images.unsplash.com/photo-1523580494863-6f3031224c94?w=800&fit=crop",
    "🔒 Охорона / Безпека": "https://images.unsplash.com/photo-1582139329536-e7284fece509?w=800&fit=crop",
    "🌐 Інше": "https://images.unsplash.com/photo-1521737711867-e3b97375f902?w=800&fit=crop",
}

SCHEDULE_INTERVALS = {
    "⚡ Одразу як з'являється": 0,
    "🕐 Раз на годину": 60,
    "🕒 Раз на 3 години": 180,
    "🕕 Раз на 6 годин": 360,
    "📅 Раз на день": 1440,
}

# ─── БАЗА ДАНИХ ──────────────────────────────────────────────────────────────
def init_db():
    con = sqlite3.connect(DB_FILE)
    con.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            city TEXT,
            profession TEXT,
            experience TEXT,
            salary TEXT,
            schedule TEXT,
            schedule_minutes INTEGER DEFAULT 60,
            active INTEGER DEFAULT 1,
            created_at TEXT,
            last_sent TEXT
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS sent_jobs (
            user_id INTEGER,
            job_uid TEXT,
            sent_at TEXT,
            PRIMARY KEY (user_id, job_uid)
        )
    """)
    con.commit()
    return con


def save_user(con, user_id, data: dict):
    schedule = data.get("schedule", "🕐 Раз на годину")
    minutes = SCHEDULE_INTERVALS.get(schedule, 60)
    # Створюємо таблицю з profession_label якщо ще немає
    con.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            city TEXT,
            profession TEXT,
            profession_label TEXT,
            experience TEXT,
            salary TEXT,
            schedule TEXT,
            schedule_minutes INTEGER DEFAULT 60,
            active INTEGER DEFAULT 1,
            created_at TEXT,
            last_sent TEXT
        )
    """)
    # Додаємо колонку якщо не існує
    try:
        con.execute("ALTER TABLE users ADD COLUMN profession_label TEXT")
    except Exception:
        pass
    con.execute("""
        INSERT OR REPLACE INTO users
        (user_id, city, profession, profession_label, experience, salary, schedule, schedule_minutes, active, created_at, last_sent)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
    """, (
        user_id,
        data.get("city", ""),
        data.get("profession", ""),
        data.get("profession_label", data.get("profession", "")),
        data.get("experience", ""),
        data.get("salary", ""),
        schedule,
        minutes,
        datetime.utcnow().isoformat(),
        None
    ))
    con.commit()


def get_user(con, user_id):
    row = con.execute("SELECT * FROM users WHERE user_id=? AND active=1", (user_id,)).fetchone()
    if not row:
        return None
    cursor = con.execute("PRAGMA table_info(users)")
    cols = [r[1] for r in cursor.fetchall()]
    return dict(zip(cols, row))


def get_all_users(con):
    rows = con.execute("SELECT * FROM users WHERE active=1").fetchall()
    # Отримуємо назви колонок динамічно
    cursor = con.execute("PRAGMA table_info(users)")
    cols = [row[1] for row in cursor.fetchall()]
    return [dict(zip(cols, r)) for r in rows]


def is_job_sent(con, user_id, job_uid):
    return con.execute(
        "SELECT 1 FROM sent_jobs WHERE user_id=? AND job_uid=?", (user_id, job_uid)
    ).fetchone() is not None


def mark_job_sent(con, user_id, job_uid):
    con.execute(
        "INSERT OR IGNORE INTO sent_jobs VALUES (?, ?, ?)",
        (user_id, job_uid, datetime.utcnow().isoformat())
    )
    con.commit()


def update_last_sent(con, user_id):
    con.execute("UPDATE users SET last_sent=? WHERE user_id=?",
                (datetime.utcnow().isoformat(), user_id))
    con.commit()


# ─── ПАРСЕРИ ─────────────────────────────────────────────────────────────────
@dataclass
class Job:
    uid: str
    title: str
    company: str
    salary: str
    location: str
    experience: str
    url: str
    source: str
    description: str = ""


async def fetch(client: httpx.AsyncClient, url: str):
    try:
        r = await client.get(url, headers=HEADERS, timeout=20, follow_redirects=True)
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        log.warning(f"Помилка {url}: {e}")
        return None


async def parse_work_ua(client: httpx.AsyncClient) -> list:
    jobs = []
    for page in range(1, 4):
        soup = await fetch(client, f"https://www.work.ua/jobs/?page={page}")
        if not soup:
            break
        for card in soup.select("div.job-link"):
            a = card.select_one("h2 a")
            if not a:
                continue
            href = a["href"]
            uid = "work_" + href.split("/")[-2]
            title = a.get_text(strip=True)
            loc_el = card.select_one("span.glyphicon-map-marker")
            location = ""
            if loc_el:
                sib = loc_el.find_next_sibling(string=True)
                location = sib.strip() if sib else ""

            job_url = "https://www.work.ua" + href
            soup2 = await fetch(client, job_url)
            salary, experience, description = "", "", ""
            if soup2:
                for el in soup2.select("span, b, strong"):
                    text = el.get_text(strip=True)
                    if re.search(r'\d[\d\s]*грн|usd|\$', text, re.IGNORECASE) and len(text) < 60:
                        salary = text
                        break
                for dt in soup2.select("dt"):
                    label = dt.get_text(strip=True).lower()
                    dd = dt.find_next_sibling("dd")
                    if not dd:
                        continue
                    val = dd.get_text(strip=True)
                    if "місто" in label:
                        location = location or val
                    elif "досвід" in label:
                        experience = val
                desc_el = soup2.select_one("div#job-description")
                if desc_el:
                    text = desc_el.get_text(separator=" ", strip=True)
                    description = text[:300] + "…" if len(text) > 300 else text

            jobs.append(Job(uid, title, "—", salary, location or "Україна", experience, job_url, "Work.ua", description))
            await asyncio.sleep(0.7)
    return jobs


async def parse_dou(client: httpx.AsyncClient) -> list:
    jobs = []
    soup = await fetch(client, "https://jobs.dou.ua/vacancies/")
    if not soup:
        return jobs
    for li in soup.select("li.l-vacancy")[:60]:
        a = li.select_one("a.vt")
        if not a:
            continue
        href = a["href"]
        uid = "dou_" + href.split("/")[-2]
        title = a.get_text(strip=True)
        company_el = li.select_one("a.company")
        company = company_el.get_text(strip=True) if company_el else "—"
        salary_el = li.select_one("span.salary")
        salary = salary_el.get_text(strip=True) if salary_el else ""
        loc_el = li.select_one("span.cities")
        location = loc_el.get_text(strip=True) if loc_el else "Україна"
        soup2 = await fetch(client, href)
        experience, description = "", ""
        if soup2:
            info = soup2.select_one("div.sh-info")
            if info:
                for span in info.select("span"):
                    t = span.get_text(strip=True).lower()
                    if any(w in t for w in ["рік", "років", "без досвід", "year"]):
                        experience = span.get_text(strip=True)
                        break
            desc_el = soup2.select_one("div.vacancy-section")
            if desc_el:
                text = desc_el.get_text(separator=" ", strip=True)
                description = text[:300] + "…" if len(text) > 300 else text
        jobs.append(Job(uid, title, company, salary, location, experience, href, "DOU.ua", description))
        await asyncio.sleep(0.7)
    return jobs


async def collect_jobs(client: httpx.AsyncClient) -> list:
    results = await asyncio.gather(
        parse_work_ua(client),
        parse_dou(client),
        return_exceptions=True
    )
    jobs = []
    for r in results:
        if isinstance(r, list):
            jobs.extend(r)
    return jobs


# ─── ФІЛЬТРАЦІЯ ──────────────────────────────────────────────────────────────
def job_matches_user(job: Job, user: dict) -> bool:
    text = (job.title + " " + job.description).lower()
    location = job.location.lower()

    # Фільтр міста
    city = user.get("city", "").lower()
    if "віддалено" in city or "remote" in city:
        city_ok = any(w in location for w in ["дистанційно", "remote", "віддалено", "віддалена"])
    else:
        city_ok = city in location or "україна" in location or any(
            w in location for w in ["дистанційно", "remote", "віддалено"]
        )
    if not city_ok:
        return False

    # Фільтр професії/навичок
    profession = user.get("profession", "").lower()
    if profession and len(profession) > 2:
        keywords = [w.strip() for w in re.split(r'[,\s]+', profession) if len(w.strip()) > 2]
        if keywords and not any(kw in text for kw in keywords):
            return False

    # Фільтр зарплати ±20%
    salary_pref = user.get("salary", "")
    if salary_pref and salary_pref != "Не важливо" and job.salary:
        # Бажана зарплата юзера
        pref_nums = re.findall(r'\d+', re.sub(r'(\d)\s+(\d)', r'\1\2', salary_pref))
        if pref_nums:
            desired = int(pref_nums[0])
            min_salary = desired * 0.8
            max_salary = desired * 1.2

            # Зарплата у вакансії
            job_nums = re.findall(r'\d+', re.sub(r'(\d)\s+(\d)', r'\1\2', job.salary))
            if job_nums:
                job_salary = int(job_nums[0])
                if job_salary < min_salary or job_salary > max_salary:
                    return False

    return True


def format_job(job: Job, short: bool = False) -> str:
    lines = [f"🆕 <b>{job.title}</b>"]
    if job.company and job.company != "—":
        lines.append(f"🏢 {job.company}")
    lines.append(f"💰 {job.salary if job.salary else 'Зарплата не вказана'}")
    lines.append(f"📍 {job.location}")
    if job.experience:
        lines.append(f"🎓 Досвід: {job.experience}")
    # Завжди показуємо опис якщо є (коротший для фото через ліміт підпису)
    if job.description:
        desc = job.description[:180] + "…" if len(job.description) > 180 else job.description
        lines.append(f"\n📝 {desc}")
    lines.append(f"\n🔗 <a href='{job.url}'>Переглянути вакансію</a>")
    lines.append(f"<i>Джерело: {job.source}</i>")
    return "\n".join(lines)


# ─── ОБРОБНИКИ КОМАНД ────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    # По 2 міста в рядок
    keyboard = [CITIES[i:i+2] for i in range(0, len(CITIES), 2)]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text(
        f"👋 Привіт, {user.first_name}!\n\n"
        f"Я допоможу знайти роботу саме для тебе.\n"
        f"Підписуйся також на наш основний канал: {MAIN_CHANNEL}\n\n"
        f"Давай налаштуємо твій профіль!\n\n"
        f"🏙️ <b>Крок 1/5:</b> Обери місто або вкажи своє:",
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup
    )
    return ASK_CITY


async def ask_city(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["city"] = update.message.text
    keyboard = [PROFESSIONS[i:i+2] for i in range(0, len(PROFESSIONS), 2)]
    await update.message.reply_text(
        f"✅ Місто: <b>{update.message.text}</b>\n\n"
        f"💼 <b>Крок 2/5:</b> Обери свою професію або сферу:",
        parse_mode=ParseMode.HTML,
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    )
    return ASK_PROFESSION


async def ask_profession(update: Update, context: ContextTypes.DEFAULT_TYPE):
    profession_label = update.message.text
    # Зберігаємо і назву і ключові слова для пошуку
    keywords = PROFESSION_KEYWORDS.get(profession_label, [])
    context.user_data["profession"] = " ".join(keywords) if keywords else profession_label
    context.user_data["profession_label"] = profession_label
    keyboard = [[exp] for exp in EXPERIENCE_OPTIONS]
    await update.message.reply_text(
        f"✅ Професія: <b>{profession_label}</b>\n\n"
        f"🎓 <b>Крок 3/5:</b> Який у тебе досвід роботи?",
        parse_mode=ParseMode.HTML,
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    )
    return ASK_EXPERIENCE


async def ask_experience(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["experience"] = update.message.text
    keyboard = [SALARY_OPTIONS[i:i+3] for i in range(0, len(SALARY_OPTIONS), 3)]
    await update.message.reply_text(
        f"✅ Досвід: <b>{update.message.text}</b>\n\n"
        f"💰 <b>Крок 4/5:</b> Яка бажана зарплата? (грн)\n"
        f"<i>Бот шукатиме вакансії ±20% від вказаної суми</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    )
    return ASK_SALARY


async def ask_salary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["salary"] = update.message.text
    keyboard = [[s] for s in SCHEDULE_OPTIONS]
    await update.message.reply_text(
        f"✅ Зарплата: <b>{update.message.text}</b>\n\n"
        f"🔔 <b>Крок 5/5:</b> Як часто надсилати нові вакансії?",
        parse_mode=ParseMode.HTML,
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    )
    return ASK_SCHEDULE


async def ask_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["schedule"] = update.message.text
    user_id = update.effective_user.id
    data = context.user_data

    con = sqlite3.connect(DB_FILE)
    save_user(con, user_id, data)
    con.close()

    await update.message.reply_text(
        f"🎉 <b>Профіль збережено!</b>\n\n"
        f"🏙️ Місто: {data['city']}\n"
        f"💼 Професія: {data.get('profession_label', data['profession'])}\n"
        f"🎓 Досвід: {data['experience']}\n"
        f"💰 Зарплата: {data['salary']}\n"
        f"🔔 Сповіщення: {data['schedule']}\n\n"
        f"Я починаю шукати вакансії для тебе! 🚀\n\n"
        f"Команди:\n"
        f"/вакансії — отримати вакансії зараз\n"
        f"/налаштування — змінити профіль\n"
        f"/стоп — зупинити сповіщення",
        parse_mode=ParseMode.HTML,
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END


MAIN_KEYBOARD = ReplyKeyboardMarkup([
    ["🔍 Знайти вакансії", "⚙️ Налаштування"],
    ["⛔ Зупинити", "📊 Мій профіль"],
], resize_keyboard=True)


async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🔍 Знайти вакансії":
        await cmd_jobs(update, context)
    elif text == "⚙️ Налаштування":
        await cmd_settings(update, context)
    elif text == "⛔ Зупинити":
        await cmd_stop(update, context)
    elif text == "📊 Мій профіль":
        await cmd_profile(update, context)


async def cmd_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    con = sqlite3.connect(DB_FILE)
    user = get_user(con, user_id)
    con.close()
    if not user:
        await update.message.reply_text("❌ Профіль не знайдено. Натисни /start", reply_markup=MAIN_KEYBOARD)
        return
    await update.message.reply_text(
        f"📊 <b>Твій профіль:</b>\n\n"
        f"🏙️ Місто: {user['city']}\n"
        f"💼 Професія: {user.get('profession_label', user['profession'])}\n"
        f"🎓 Досвід: {user['experience']}\n"
        f"💰 Зарплата: {user['salary']} грн\n"
        f"🔔 Сповіщення: {user['schedule']}\n\n"
        f"Щоб змінити — натисни ⚙️ Налаштування",
        parse_mode=ParseMode.HTML,
        reply_markup=MAIN_KEYBOARD
    )


async def cmd_jobs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    con = sqlite3.connect(DB_FILE)
    user = get_user(con, user_id)

    if not user:
        await update.message.reply_text(
            "❌ Спочатку налаштуй профіль командою /start"
        )
        con.close()
        return

    await update.message.reply_text("🔍 Шукаю вакансії для тебе...")

    async with httpx.AsyncClient() as client:
        jobs = await collect_jobs(client)

    matched = [j for j in jobs if job_matches_user(j, user) and not is_job_sent(con, user_id, j.uid)]

    if not matched:
        await update.message.reply_text(
            "😔 Нових підходящих вакансій поки немає.\n"
            "Спробуй пізніше або зміни налаштування",
            reply_markup=MAIN_KEYBOARD
        )
        con.close()
        return

    await update.message.reply_text(f"✅ Знайдено {len(matched)} нових вакансій!", reply_markup=MAIN_KEYBOARD)

    profession_label = user.get("profession_label", "🌐 Інше")
    photo_url = PROFESSION_PHOTOS.get(profession_label, PROFESSION_PHOTOS["🌐 Інше"])

    for job in matched[:10]:
        try:
            await context.bot.send_photo(
                chat_id=user_id,
                photo=photo_url,
                caption=format_job(job, short=True),
                parse_mode=ParseMode.HTML,
            )
            mark_job_sent(con, user_id, job.uid)
            await asyncio.sleep(1)
        except Exception as e:
            log.error(f"Помилка надсилання: {e}")

    update_last_sent(con, user_id)
    con.close()


async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚙️ Щоб змінити налаштування — натисни /start і пройди заново.",
        reply_markup=MAIN_KEYBOARD
    )


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    con = sqlite3.connect(DB_FILE)
    con.execute("UPDATE users SET active=0 WHERE user_id=?", (user_id,))
    con.commit()
    con.close()
    await update.message.reply_text(
        "⛔ Сповіщення зупинено.\n"
        "Щоб відновити — натисни /start"
    )


# ─── АВТОМАТИЧНЕ НАДСИЛАННЯ ──────────────────────────────────────────────────
async def auto_send_jobs(app):
    """Фоновий процес який надсилає вакансії по розкладу."""
    while True:
        try:
            con = sqlite3.connect(DB_FILE)
            users = get_all_users(con)
            con.close()

            if not users:
                await asyncio.sleep(60)
                continue

            async with httpx.AsyncClient() as client:
                jobs = await collect_jobs(client)

            now = datetime.utcnow()

            for user in users:
                try:
                    schedule_min = user.get("schedule_minutes", 60)
                    last_sent = user.get("last_sent")

                    # Перевіряємо чи прийшов час
                    if schedule_min > 0 and last_sent:
                        last_dt = datetime.fromisoformat(last_sent)
                        diff = (now - last_dt).total_seconds() / 60
                        if diff < schedule_min:
                            continue

                    con = sqlite3.connect(DB_FILE)
                    matched = [
                        j for j in jobs
                        if job_matches_user(j, user) and not is_job_sent(con, user["user_id"], j.uid)
                    ]

                    if not matched:
                        con.close()
                        continue

                    # Якщо "одразу" — надсилаємо по одній
                    send_limit = 1 if schedule_min == 0 else 10

                    profession_label = user.get("profession_label", "🌐 Інше")
                    photo_url = PROFESSION_PHOTOS.get(profession_label, PROFESSION_PHOTOS["🌐 Інше"])

                    for job in matched[:send_limit]:
                        try:
                            await app.bot.send_photo(
                                chat_id=user["user_id"],
                                photo=photo_url,
                                caption=format_job(job, short=True),
                                parse_mode=ParseMode.HTML,
                            )
                        except Exception:
                            await app.bot.send_message(
                                chat_id=user["user_id"],
                                text=format_job(job),
                                parse_mode=ParseMode.HTML,
                                disable_web_page_preview=True
                            )
                        mark_job_sent(con, user["user_id"], job.uid)
                        await asyncio.sleep(1)

                    update_last_sent(con, user["user_id"])
                    con.close()
                    log.info(f"Надіслано {len(matched[:send_limit])} вакансій юзеру {user['user_id']}")

                except Exception as e:
                    log.error(f"Помилка для юзера {user.get('user_id')}: {e}")

        except Exception as e:
            log.error(f"Помилка auto_send: {e}")

        await asyncio.sleep(60)  # перевіряємо кожну хвилину


# ─── ЗАПУСК ──────────────────────────────────────────────────────────────────
async def main():
    init_db()

    app = Application.builder().token(PERSONAL_BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_CITY:       [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_city)],
            ASK_PROFESSION: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_profession)],
            ASK_EXPERIENCE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_experience)],
            ASK_SALARY:     [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_salary)],
            ASK_SCHEDULE:   [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_schedule)],
        },
        fallbacks=[CommandHandler("start", start)],
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("jobs", cmd_jobs))
    app.add_handler(CommandHandler("settings", cmd_settings))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_buttons))

    log.info("Персональний бот запущено!")
    
    async with app:
        await app.start()
        # Запускаємо фоновий процес
        asyncio.ensure_future(auto_send_jobs(app))
        await app.updater.start_polling(drop_pending_updates=True)
        await asyncio.Event().wait()  # чекаємо вічно


if __name__ == "__main__":
    import nest_asyncio
    try:
        import nest_asyncio
        nest_asyncio.apply()
    except ImportError:
        pass
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(main())
    finally:
        loop.close()