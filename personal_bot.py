import os, logging, asyncio, httpx, re, json
from dotenv import load_dotenv
load_dotenv()
from datetime import datetime, timedelta
from urllib.parse import quote_plus
from bs4 import BeautifulSoup
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.error import RetryAfter
import nest_asyncio

nest_asyncio.apply()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

PERSONAL_BOT_TOKEN = os.environ.get("PERSONAL_BOT_TOKEN")
MAIN_CHANNEL       = os.environ.get("MAIN_CHANNEL", "https://t.me/+YNCaw9gBllI5NzU0")
DATABASE_URL       = os.environ.get("DATABASE_URL",        "")

logger.info(f"DATABASE_URL present: {bool(DATABASE_URL)}")
logger.info(f"TOKEN present: {bool(PERSONAL_BOT_TOKEN)}")


PHOTO_IDS = {
    "💻 IT / Програмування": [0,1,2,3,4], "📊 Аналітика / BI": [20,21,22,23,24],
    "🎨 Дизайн / UX": [40,41,42,43,44], "📢 Маркетинг / SMM": [60,61,62,63,64],
    "💰 Продажі / Sales": [80,81,82,83,84], "🔧 Технічна підтримка": [100,101,102,103,104],
    "📦 Логістика / Склад": [120,121,122,123,124], "👷 Будівництво": [140,141,142,143,144],
    "🏥 Медицина": [160,161,162,163,164], "🍽️ HoReCa / Ресторан": [180,181,182,183,184],
    "🛒 Рітейл / Торгівля": [200,201,202,203,204], "📚 Освіта": [220,221,222,223,224],
    "🏦 Фінанси / Бухгалтерія": [240,241,242,243,244], "⚖️ Юриспруденція": [260,261,262,263,264],
    "🧹 Прибирання / Клінінг": [280,281,282,283,284], "🚗 Водій": [300,301,302,303,304],
    "🌾 Сільське господарство": [320,321,322,323,324], "🔨 Виробництво": [340,341,342,343,344],
    "📞 Кол-центр / Оператор": [360,361,362,363,364], "🎯 HR / Рекрутинг": [380,381,382,383,384],
    "🔍 Інше": [400,401,402,403,404],
}

def get_photo_url(prof_label, job_id):
    import hashlib
    keywords = {
        "💻 IT / Програмування": "coding,programming,developer",
        "📊 Аналітика / BI": "analytics,data,charts",
        "🎨 Дизайн / UX": "design,creative,sketch",
        "📢 Маркетинг / SMM": "marketing,social,advertising",
        "💰 Продажі / Sales": "sales,business,handshake",
        "🔧 Технічна підтримка": "technology,support,computer",
        "📦 Логістика / Склад": "warehouse,logistics,delivery",
        "👷 Будівництво": "construction,building,architect",
        "🏥 Медицина": "medicine,hospital,doctor",
        "🍽️ HoReCa / Ресторан": "restaurant,cooking,chef",
        "🛒 Рітейл / Торгівля": "retail,shop,store",
        "📚 Освіта": "education,teaching,classroom",
        "🏦 Фінанси / Бухгалтерія": "finance,money,accounting",
        "⚖️ Юриспруденція": "law,justice,legal",
        "🧹 Прибирання / Клінінг": "cleaning,housekeeping",
        "🚗 Водій": "driving,car,transport",
        "🌾 Сільське господарство": "agriculture,farm,nature",
        "🔨 Виробництво": "factory,manufacturing,industry",
        "📞 Кол-центр / Оператор": "callcenter,headset,operator",
        "🎯 HR / Рекрутинг": "recruitment,hr,teamwork",
        "🔍 Інше": "office,work,business",
    }
    seed = int(hashlib.md5(job_id.encode()).hexdigest()[:8], 16) % 1000
    return f"https://picsum.photos/seed/{seed}/600/400"

def get_db():
    if DATABASE_URL:
        try:
            import psycopg2
            conn = psycopg2.connect(DATABASE_URL, sslmode="require")
            return conn, "pg"
        except Exception as e:
            logger.error(f"PostgreSQL connection failed: {e}")
    import sqlite3
    conn = sqlite3.connect("personal_bot.db")
    return conn, "sqlite"

def init_db():
    conn, mode = get_db()
    logger.info(f"DB mode: {mode}")
    cur = conn.cursor()
    if mode == "pg":
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                city TEXT, profession TEXT, profession_label TEXT,
                experience TEXT, salary INTEGER, schedule TEXT,
                first_name TEXT, last_name TEXT, username TEXT, language_code TEXT,
                active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sent_jobs (
                user_id BIGINT, job_id TEXT,
                sent_at TIMESTAMP DEFAULT NOW(),
                PRIMARY KEY (user_id, job_id)
            )
        """)
    else:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                city TEXT, profession TEXT, profession_label TEXT,
                experience TEXT, salary INTEGER, schedule TEXT,
                first_name TEXT, last_name TEXT, username TEXT, language_code TEXT,
                active INTEGER DEFAULT 1,
                created_at TEXT, updated_at TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sent_jobs (
                user_id INTEGER, job_id TEXT,
                sent_at TEXT, PRIMARY KEY (user_id, job_id)
            )
        """)
    conn.commit()
    conn.close()
    # Add new columns if they don't exist (for existing tables)
    try:
        conn2, mode2 = get_db()
        cur2 = conn2.cursor()
        if mode2 == "pg":
            for col in ["first_name", "last_name", "username", "language_code"]:
                try:
                    cur2.execute(f"ALTER TABLE users ADD COLUMN {col} TEXT DEFAULT ''")
                    conn2.commit()
                except Exception:
                    conn2.rollback()
        conn2.close()
    except Exception as e:
        logger.warning(f"ALTER TABLE skipped: {e}")
    logger.info("DB initialized successfully")

def save_user(user_id, city, profession, profession_label, experience, salary, schedule, first_name="", last_name="", username="", language_code=""):
    conn, mode = get_db()
    cur = conn.cursor()
    now = datetime.utcnow().isoformat()
    if mode == "pg":
        cur.execute("""
            INSERT INTO users (user_id,city,profession,profession_label,experience,salary,schedule,first_name,last_name,username,language_code,updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
            ON CONFLICT (user_id) DO UPDATE SET
                city=EXCLUDED.city, profession=EXCLUDED.profession,
                profession_label=EXCLUDED.profession_label,
                experience=EXCLUDED.experience, salary=EXCLUDED.salary,
                schedule=EXCLUDED.schedule, first_name=EXCLUDED.first_name, last_name=EXCLUDED.last_name, username=EXCLUDED.username, language_code=EXCLUDED.language_code, active=TRUE, updated_at=NOW()
        """, (user_id, city, profession, profession_label, experience, salary, schedule, first_name, last_name, username, language_code))
    else:
        cur.execute("""
            INSERT OR REPLACE INTO users
            (user_id,city,profession,profession_label,experience,salary,schedule,first_name,last_name,username,language_code,active,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,1,?,?)
        """, (user_id, city, profession, profession_label, experience, salary, schedule, first_name, last_name, username, language_code, now, now))
    conn.commit()
    conn.close()
    logger.info(f"Saved user {user_id} to {mode}")

def get_user(user_id):
    conn, mode = get_db()
    cur = conn.cursor()
    if mode == "pg":
        cur.execute("SELECT * FROM users WHERE user_id=%s", (user_id,))
    else:
        cur.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    cols = ["user_id","city","profession","profession_label","experience","salary","schedule","first_name","last_name","username","language_code","active","created_at","updated_at"]
    return dict(zip(cols, row))

def mark_sent(user_id, job_id):
    conn, mode = get_db()
    cur = conn.cursor()
    now = datetime.utcnow().isoformat()
    try:
        if mode == "pg":
            cur.execute("INSERT INTO sent_jobs (user_id,job_id) VALUES (%s,%s) ON CONFLICT DO NOTHING", (user_id, job_id))
        else:
            cur.execute("INSERT OR IGNORE INTO sent_jobs (user_id,job_id,sent_at) VALUES (?,?,?)", (user_id, job_id, now))
        conn.commit()
    except Exception as e:
        logger.error(f"mark_sent error: {e}")
    conn.close()

def is_sent(user_id, job_id):
    conn, mode = get_db()
    cur = conn.cursor()
    if mode == "pg":
        cur.execute("SELECT 1 FROM sent_jobs WHERE user_id=%s AND job_id=%s", (user_id, job_id))
    else:
        cur.execute("SELECT 1 FROM sent_jobs WHERE user_id=? AND job_id=?", (user_id, job_id))
    res = cur.fetchone()
    conn.close()
    return res is not None

def get_all_active_users():
    conn, mode = get_db()
    cur = conn.cursor()
    if mode == "pg":
        cur.execute("SELECT * FROM users WHERE active=TRUE")
    else:
        cur.execute("SELECT * FROM users WHERE active=1")
    rows = cur.fetchall()
    conn.close()
    cols = ["user_id","city","profession","profession_label","experience","salary","schedule","first_name","last_name","username","language_code","active","created_at","updated_at"]
    return [dict(zip(cols, r)) for r in rows]

def deactivate_user(user_id):
    conn, mode = get_db()
    cur = conn.cursor()
    if mode == "pg":
        cur.execute("UPDATE users SET active=FALSE WHERE user_id=%s", (user_id,))
    else:
        cur.execute("UPDATE users SET active=0 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

# ── State & UI ────────────────────────────────────────────────────────────────
user_state = {}

CITIES = [
    "Київ","Львів","Харків","Одеса","Дніпро","Запоріжжя","Вінниця",
    "Чернівці","Ужгород","Івано-Франківськ","Тернопіль","Луцьк",
    "Рівне","Хмельницький","Житомир","Черкаси","Кропивницький",
    "Суми","Полтава","Миколаїв","Херсон","Ірпінь","Буча","Віддалено"
]

PROFESSIONS = [
    ("💻 IT / Програмування",    "python javascript розробник developer програміст backend frontend fullstack"),
    ("📊 Аналітика / BI",        "аналітик analyst data bi excel sql звіт"),
    ("🎨 Дизайн / UX",           "дизайнер designer ux ui figma графік"),
    ("📢 Маркетинг / SMM",       "маркетолог smm таргет реклама контент просування"),
    ("💰 Продажі / Sales",       "менеджер продажів sales account b2b crm"),
    ("🔧 Технічна підтримка",    "підтримка support helpdesk технік адміністратор"),
    ("📦 Логістика / Склад",     "логіст склад комірник водій кур'єр доставка"),
    ("👷 Будівництво",           "будівництво прораб інженер архітектор монтаж"),
    ("🏥 Медицина",              "лікар медсестра фармацевт стоматолог медицина"),
    ("🍽️ HoReCa / Ресторан",    "кухар офіціант бармен ресторан готель кафе"),
    ("🛒 Рітейл / Торгівля",     "продавець касир магазин рітейл торгівля"),
    ("📚 Освіта",                "вчитель викладач репетитор тренер освіта"),
    ("🏦 Фінанси / Бухгалтерія", "бухгалтер фінансист аудитор банк фінанси"),
    ("⚖️ Юриспруденція",         "юрист адвокат правник нотаріус право"),
    ("🧹 Прибирання / Клінінг",  "прибиральник клінінг прибирання господарська"),
    ("🚗 Водій",                 "водій driver таксі кур'єр категорія"),
    ("🌾 Сільське господарство", "агроном агро ферма тваринництво рослинництво"),
    ("🔨 Виробництво",           "оператор виробництво завод технолог зварювальник"),
    ("📞 Кол-центр / Оператор",  "оператор кол-центр call диспетчер"),
    ("🎯 HR / Рекрутинг",        "hr рекрутер кадри персонал"),
    ("🔍 Інше",                  ""),
]

EXPERIENCES = ["Без досвіду","До 1 року","1-2 роки","2-5 років","5+ років"]
SALARIES    = [10000,15000,20000,25000,30000,35000,40000,50000,60000,70000,80000,100000]
SCHEDULES   = ["Кожну нову вакансію","Кожну годину","Кожні 3 години","Кожні 6 годин","Раз на день"]

MAIN_KB = ReplyKeyboardMarkup(
    [[KeyboardButton("🔍 Знайти вакансії"), KeyboardButton("⚙️ Налаштування")],
     [KeyboardButton("⛔ Зупинити"),         KeyboardButton("📊 Мій профіль")]],
    resize_keyboard=True
)

def city_kb():
    btns = [[KeyboardButton(CITIES[i]), KeyboardButton(CITIES[i+1])] for i in range(0,len(CITIES)-1,2)]
    if len(CITIES)%2: btns.append([KeyboardButton(CITIES[-1])])
    return ReplyKeyboardMarkup(btns, resize_keyboard=True)

def profession_kb():
    labels = [p[0] for p in PROFESSIONS]
    btns = [[KeyboardButton(labels[i]), KeyboardButton(labels[i+1])] for i in range(0,len(labels)-1,2)]
    if len(labels)%2: btns.append([KeyboardButton(labels[-1])])
    return ReplyKeyboardMarkup(btns, resize_keyboard=True)

def experience_kb():
    return ReplyKeyboardMarkup([[KeyboardButton(e)] for e in EXPERIENCES], resize_keyboard=True)

def salary_kb():
    rows = []
    for i in range(0, len(SALARIES), 3):
        rows.append([KeyboardButton(f"{s:,} грн".replace(",","_")) for s in SALARIES[i:i+3]])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

def schedule_kb():
    return ReplyKeyboardMarkup([[KeyboardButton(s)] for s in SCHEDULES], resize_keyboard=True)

# ── Handlers ──────────────────────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user_state[uid] = {"step": "city"}
    await update.message.reply_text(
        f"👋 Привіт! Я допоможу знайти роботу саме для тебе.\n\n"
        f"Підписуйся на основний канал: {MAIN_CHANNEL}\n\n"
        f"Крок 1/5 — Оберіть місто:",
        reply_markup=city_kb()
    )

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    text = update.message.text.strip()

    if text == "🔍 Знайти вакансії":
        await send_jobs_now(update, ctx); return
    if text == "⚙️ Налаштування":
        user_state[uid] = {"step": "city"}
        await update.message.reply_text("Оновлення профілю. Крок 1/5 — Місто:", reply_markup=city_kb()); return
    if text == "⛔ Зупинити":
        deactivate_user(uid)
        await update.message.reply_text("⛔ Сповіщення зупинено. /start щоб відновити."); return
    if text == "📊 Мій профіль":
        u = get_user(uid)
        if u:
            await update.message.reply_text(
                f"📊 Твій профіль:\n🏙️ Місто: {u['city']}\n💼 Професія: {u['profession_label']}\n"
                f"🎓 Досвід: {u['experience']}\n💰 Зарплата: {u['salary']:,} грн\n🔔 Розклад: {u['schedule']}",
                reply_markup=MAIN_KB)
        else:
            await update.message.reply_text("Профіль не знайдено. Напишіть /start")
        return

    state = user_state.get(uid, {})
    step  = state.get("step")

    if not step:
        await keyword_search(update, ctx, text)
        return

    if step == "city":
        if text not in CITIES:
            await update.message.reply_text("Оберіть місто з кнопок 👇", reply_markup=city_kb()); return
        state["city"] = text; state["step"] = "profession"; user_state[uid] = state
        await update.message.reply_text("Крок 2/5 — Оберіть сферу роботи:", reply_markup=profession_kb())

    elif step == "profession":
        match = next((p for p in PROFESSIONS if p[0] == text), None)
        if not match:
            await update.message.reply_text("Оберіть сферу з кнопок 👇", reply_markup=profession_kb()); return
        state["profession_label"] = match[0]; state["profession"] = match[1]
        state["step"] = "experience"; user_state[uid] = state
        await update.message.reply_text("Крок 3/5 — Ваш досвід роботи:", reply_markup=experience_kb())

    elif step == "experience":
        if text not in EXPERIENCES:
            await update.message.reply_text("Оберіть досвід з кнопок 👇", reply_markup=experience_kb()); return
        state["experience"] = text; state["step"] = "salary"; user_state[uid] = state
        await update.message.reply_text("Крок 4/5 — Бажана зарплата (±20% від обраної):", reply_markup=salary_kb())

    elif step == "salary":
        num_str = re.sub(r"[^\d]","",text)
        if not num_str:
            await update.message.reply_text("Оберіть зарплату з кнопок 👇", reply_markup=salary_kb()); return
        state["salary"] = int(num_str); state["step"] = "schedule"; user_state[uid] = state
        await update.message.reply_text("Крок 5/5 — Як часто отримувати вакансії?", reply_markup=schedule_kb())

    elif step == "schedule":
        if text not in SCHEDULES:
            await update.message.reply_text("Оберіть варіант з кнопок 👇", reply_markup=schedule_kb()); return
        state["schedule"] = text
        tg_user = update.effective_user
        save_user(uid, state["city"], state["profession"], state["profession_label"],
                  state["experience"], state["salary"], state["schedule"],
                  first_name=tg_user.first_name or "",
                  last_name=tg_user.last_name or "",
                  username=tg_user.username or "",
                  language_code=tg_user.language_code or "")
        user_state.pop(uid, None)
        await update.message.reply_text(
            f"✅ Профіль збережено!\n\n"
            f"🏙️ Місто: {state['city']}\n💼 Сфера: {state['profession_label']}\n"
            f"🎓 Досвід: {state['experience']}\n💰 Зарплата: ~{state['salary']:,} грн\n"
            f"🔔 Сповіщення: {state['schedule']}\n\nВикористовуй кнопки нижче 👇",
            reply_markup=MAIN_KB
        )

# ── Jobs ──────────────────────────────────────────────────────────────────────
PHOTO_URLS = {
    "💻 IT / Програмування":    "https://images.unsplash.com/photo-1555066931-4365d14bab8c?w=600",
    "📊 Аналітика / BI":        "https://images.unsplash.com/photo-1551288049-bebda4e38f71?w=600",
    "🎨 Дизайн / UX":           "https://images.unsplash.com/photo-1561070791-2526d30994b5?w=600",
    "📢 Маркетинг / SMM":       "https://images.unsplash.com/photo-1460925895917-afdab827c52f?w=600",
    "💰 Продажі / Sales":       "https://images.unsplash.com/photo-1521791136064-7986c2920216?w=600",
    "🔧 Технічна підтримка":    "https://images.unsplash.com/photo-1516321318423-f06f85e504b3?w=600",
    "📦 Логістика / Склад":     "https://images.unsplash.com/photo-1586528116311-ad8dd3c8310d?w=600",
    "👷 Будівництво":           "https://images.unsplash.com/photo-1504307651254-35680f356dfd?w=600",
    "🏥 Медицина":              "https://images.unsplash.com/photo-1559757148-5c350d0d3c56?w=600",
    "🍽️ HoReCa / Ресторан":    "https://images.unsplash.com/photo-1414235077428-338989a2e8c0?w=600",
    "🛒 Рітейл / Торгівля":     "https://images.unsplash.com/photo-1441986300917-64674bd600d8?w=600",
    "📚 Освіта":                "https://images.unsplash.com/photo-1503676260728-1c00da094a0b?w=600",
    "🏦 Фінанси / Бухгалтерія": "https://images.unsplash.com/photo-1554224155-6726b3ff858f?w=600",
    "⚖️ Юриспруденція":         "https://images.unsplash.com/photo-1589829545856-d10d557cf95f?w=600",
    "🧹 Прибирання / Клінінг":  "https://images.unsplash.com/photo-1581578731548-c64695cc6952?w=600",
    "🚗 Водій":                 "https://images.unsplash.com/photo-1449965408869-eaa3f722e40d?w=600",
    "🌾 Сільське господарство": "https://images.unsplash.com/photo-1500382017468-9049fed747ef?w=600",
    "🔨 Виробництво":           "https://images.unsplash.com/photo-1565793979853-c7c98049571f?w=600",
    "📞 Кол-центр / Оператор":  "https://images.unsplash.com/photo-1534536281715-e28d76689b4d?w=600",
    "🎯 HR / Рекрутинг":        "https://images.unsplash.com/photo-1521737604893-d14cc237f11d?w=600",
    "🔍 Інше":                  "https://images.unsplash.com/photo-1486312338219-ce68d2c6f44d?w=600",
}

CITY_SLUGS = {
    "Київ":"kyiv","Львів":"lviv","Харків":"kharkiv","Одеса":"odessa",
    "Дніпро":"dnipro","Запоріжжя":"zaporizhzhia","Вінниця":"vinnytsia",
    "Чернівці":"chernivtsi","Ужгород":"uzhhorod","Івано-Франківськ":"ivano-frankivsk",
    "Тернопіль":"ternopil","Луцьк":"lutsk","Рівне":"rivne",
    "Хмельницький":"khmelnytskyi","Житомир":"zhytomyr","Черкаси":"cherkasy",
    "Кропивницький":"kropyvnytskyi","Суми":"sumy","Полтава":"poltava",
    "Миколаїв":"mykolaiv","Херсон":"kherson","Ірпінь":"irpin","Буча":"bucha",
}

async def fetch_workua(city, keywords):
    jobs = []
    city_slug = CITY_SLUGS.get(city, "")
    if city == "Віддалено":
        url = "https://www.work.ua/jobs/?employment=74"
    elif city_slug:
        url = f"https://www.work.ua/jobs-{city_slug}/"
    else:
        url = "https://www.work.ua/jobs/"
    headers = {"User-Agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
    try:
        async with httpx.AsyncClient(headers=headers, timeout=15, follow_redirects=True) as client:
            r = await client.get(url)
            if r.status_code != 200: return jobs
            soup = BeautifulSoup(r.text, "lxml")
            for card in soup.select("div.card.card-hover.job-link")[:20]:
                title_tag = card.select_one("h2 a")
                if not title_tag: continue
                title   = title_tag.get_text(strip=True)
                link    = "https://www.work.ua" + title_tag["href"]
                company = card.select_one(".add-top-xs")
                company = company.get_text(strip=True) if company else "Компанія"
                sal_tag = card.select_one(".h5.strong-600")
                salary  = sal_tag.get_text(strip=True) if sal_tag else ""
                desc_tag = card.select_one("p.overflow.cut-bottom")
                desc    = desc_tag.get_text(strip=True)[:200] if desc_tag else ""
                job_id  = f"workua_{link.split('/')[-2]}"
                jobs.append({"id":job_id,"title":title,"company":company,"salary":salary,
                             "city":city,"desc":desc,"url":link,"source":"Work.ua"})
    except Exception as e:
        logger.error(f"Work.ua error: {e}")
    return jobs

async def fetch_dou(keywords):
    jobs = []
    headers = {"User-Agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
    try:
        async with httpx.AsyncClient(headers=headers, timeout=15, follow_redirects=True) as client:
            r = await client.get("https://jobs.dou.ua/vacancies/")
            if r.status_code != 200: return jobs
            soup = BeautifulSoup(r.text, "lxml")
            for li in soup.select("li.l-vacancy")[:20]:
                a = li.select_one("a.vt")
                if not a: continue
                title   = a.get_text(strip=True)
                link    = a["href"]
                company = li.select_one(".company")
                company = company.get_text(strip=True) if company else "Компанія"
                city_tag = li.select_one(".cities")
                city    = city_tag.get_text(strip=True) if city_tag else "Україна"
                sal_tag = li.select_one(".salary")
                salary  = sal_tag.get_text(strip=True) if sal_tag else ""
                desc_tag = li.select_one(".sh-info")
                desc    = desc_tag.get_text(strip=True)[:200] if desc_tag else ""
                job_id  = f"dou_{link.split('/')[-2]}"
                jobs.append({"id":job_id,"title":title,"company":company,"salary":salary,
                             "city":city,"desc":desc,"url":link,"source":"DOU.ua"})
    except Exception as e:
        logger.error(f"DOU error: {e}")
    return jobs


async def fetch_job_desc(url: str, source: str) -> str:
    """Fetch job duties/responsibilities from vacancy page."""
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
    # Keywords that signal duties section
    DUTY_KEYWORDS = [
        "обов'язки", "обовязки", "що потрібно робити", "функції", "задачі", "завдання",
        "responsibilities", "duties", "what you'll do", "your role",
        "вимоги", "що ми шукаємо", "requirements", "що потрібно"
    ]
    try:
        async with httpx.AsyncClient(headers=headers, timeout=10, follow_redirects=True) as client:
            r = await client.get(url)
            if r.status_code != 200:
                return ""
            soup = BeautifulSoup(r.text, "lxml")

            if source == "Work.ua":
                block = soup.select_one("#job-description")
                if not block:
                    return ""
                # Try to find duties section by heading
                for tag in block.find_all(["h2","h3","h4","strong","b"]):
                    heading = tag.get_text(strip=True).lower()
                    if any(kw in heading for kw in DUTY_KEYWORDS):
                        # Collect text after this heading
                        parts = []
                        for sib in tag.find_next_siblings():
                            if sib.name in ["h2","h3","h4"] and sib != tag:
                                break
                            parts.append(sib.get_text(separator=" ", strip=True))
                        text = " ".join(parts).strip()
                        if text:
                            return text[:300]
                # Fallback: return first 300 chars skipping company intro
                full = block.get_text(separator=" ", strip=True)
                # Skip first sentence if it looks like company description
                sentences = full.split(". ")
                if len(sentences) > 2:
                    full = ". ".join(sentences[1:])
                return full[:300]

            elif source == "DOU.ua":
                # DOU has sections with headers
                sections = soup.select(".b-typo.vacancy-section")
                for section in sections:
                    header = section.select_one("h2, h3, strong")
                    if header:
                        heading = header.get_text(strip=True).lower()
                        if any(kw in heading for kw in DUTY_KEYWORDS):
                            text = section.get_text(separator=" ", strip=True)
                            # Remove the heading itself
                            text = text.replace(header.get_text(strip=True), "").strip()
                            return text[:300]
                # Fallback: second section (first is usually about company)
                if len(sections) >= 2:
                    text = sections[1].get_text(separator=" ", strip=True)
                    return text[:300]
                elif sections:
                    full = sections[0].get_text(separator=" ", strip=True)
                    sentences = full.split(". ")
                    if len(sentences) > 2:
                        full = ". ".join(sentences[1:])
                    return full[:300]
    except Exception as e:
        logger.error(f"fetch_job_desc error: {e}")
    return ""


async def fetch_duties_ai(url: str) -> str:
    """Use Claude to extract job duties from vacancy page."""
    try:
        async with httpx.AsyncClient(headers={"User-Agent":"Mozilla/5.0"}, timeout=8, follow_redirects=True) as dc:
            dr = await dc.get(url)
            if dr.status_code != 200:
                return ""
            from bs4 import BeautifulSoup as BS
            soup = BS(dr.text, "lxml")
            # Remove scripts and styles
            for tag in soup(["script","style","nav","header","footer"]):
                tag.decompose()
            text = soup.get_text(separator=" ", strip=True)[:3000]
        
        response = await httpx.AsyncClient(timeout=10).post(
            "https://api.anthropic.com/v1/messages",
            headers={"Content-Type": "application/json", "x-api-key": os.environ.get("ANTHROPIC_API_KEY",""), "anthropic-version": "2023-06-01"},
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 200,
                "messages": [{
                    "role": "user",
                    "content": f"З тексту вакансії витягни ТІЛЬКИ обов\'язки та що треба робити. Відповідь максимум 2-3 речення українською. Якщо обов\'язків немає — напиши порожньо.\n\n{text}"
                }]
            }
        )
        data = response.json()
        result = data.get("content", [{}])[0].get("text", "").strip()
        return result if len(result) > 20 else ""
    except Exception as e:
        logger.error(f"AI fetch error: {e}")
        return ""

def salary_match(job_salary_str, user_salary):
    if not job_salary_str or not user_salary: return True
    nums = re.findall(r"\d[\d\s]*\d|\d+", job_salary_str.replace(" ",""))
    nums = [int(n.replace(" ","")) for n in nums if len(n.replace(" ",""))>=4]
    if not nums: return True
    lo = user_salary*0.8; hi = user_salary*1.2
    return not (max(nums)<lo or min(nums)>hi)

async def send_jobs_to_user(bot, user):
    city      = user["city"]
    keywords  = user.get("profession","")
    u_salary  = user.get("salary",0)
    prof      = user.get("profession_label","🔍 Інше")
    # photo_url set per job below
    jobs = await fetch_workua(city, keywords)
    jobs += await fetch_dou(keywords)
    sent = 0
    for job in jobs:
        if is_sent(user["user_id"], job["id"]): continue
        if not salary_match(job.get("salary",""), u_salary): continue
        city_d = job.get("city","") or city
        if any(w in city_d.lower() for w in ["дистанц","remote","home","віддал"]):
            city_d = "Віддалено"
        sal_d = job.get("salary","") or "не вказана"
        desc_text = ""
        if job.get("url"):
            try:
                async with httpx.AsyncClient(headers={"User-Agent":"Mozilla/5.0"}, timeout=5, follow_redirects=True) as dc:
                    dr = await dc.get(job["url"])
                    if dr.status_code == 200:
                        from bs4 import BeautifulSoup as BS
                        ds = BS(dr.text, "lxml")
                        DUTY_KW = ["обов","функці","завдан","відповідальност","зона","що потрібно","що ти будеш","твої задачі","responsibilities","duties","what you","your role","you will"]
                        for tag in ds.find_all(["h2","h3","strong","b"]):
                            if any(k in tag.get_text().lower() for k in DUTY_KW):
                                # Try siblings of parent element
                                parent = tag.parent
                                siblings = list(parent.find_next_siblings())
                                parts = []
                                for s in siblings:
                                    if s.name in ["h2","h3"]: break
                                    t = s.get_text(" ", strip=True)
                                    if t: parts.append(t)
                                if not parts:
                                    # Try direct siblings
                                    for s in tag.find_next_siblings():
                                        if s.name in ["h2","h3"]: break
                                        t = s.get_text(" ", strip=True)
                                        if t: parts.append(t)
                                desc_text = " ".join(parts)[:400]
                                if desc_text: break
            except: pass
        if not desc_text:
            desc_text = job.get("desc","")
        photo = get_photo_url(prof, job["id"])
        caption = f"🆕 {job['title']}\n\n🏢 {job['company']}\n💰 {sal_d}\n📍 {city_d}\n"
        if desc_text:
            caption += f"\n📝 {desc_text[:280]}\n"
        caption += f"\n🔗 {job['url']}\n📌 {job['source']}"
        if len(caption)>4096: caption=caption[:4090]+"..."
        text = f"🆕 <b>{job['title']}</b>\n\n🏢 {job['company']}\n💰 {sal_d}\n📍 {city_d}\n"
        if desc_text:
            text += f"\n📋 <b>Обов'язки:</b>\n{desc_text[:400]}\n"
        text += f"\n🔗 <a href=\"{job['url']}\">Переглянути вакансію</a>\n📌 {job['source']}"
        if len(text)>4096: text=text[:4090]+"..."
        try:
            await bot.send_message(chat_id=user["user_id"], text=text, parse_mode="HTML", disable_web_page_preview=False)
            mark_sent(user["user_id"], job["id"])
            sent += 1
            await asyncio.sleep(0.5)
            if sent>=5: break
        except Exception as e:
            logger.error(f"Send error {user['user_id']}: {e}"); break
    logger.info(f"Надіслано {sent} вакансій юзеру {user['user_id']}")
    return sent

async def fetch_djinni_search(keyword: str) -> list:
    jobs = []
    kw_lower = keyword.lower()
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
               "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
               "Accept-Language": "uk-UA,uk;q=0.9,en;q=0.7"}
    try:
        async with httpx.AsyncClient(headers=headers, timeout=15, follow_redirects=True) as client:
            for page in range(1, 3):
                url = f"https://djinni.co/jobs/?q={quote_plus(keyword)}" if page == 1 else f"https://djinni.co/jobs/?q={quote_plus(keyword)}&page={page}"
                r = await client.get(url)
                if r.status_code != 200:
                    break
                soup = BeautifulSoup(r.text, "html.parser")
                scripts = soup.find_all("script", type="application/ld+json")
                found = False
                for s in scripts:
                    try:
                        data = json.loads(s.string or "")
                    except Exception:
                        continue
                    if not isinstance(data, list):
                        continue
                    for item in data:
                        if item.get("@type") != "JobPosting":
                            continue
                        found = True
                        title = item.get("title", "")
                        desc_raw = item.get("description", "")
                        if kw_lower not in title.lower() and kw_lower not in desc_raw.lower():
                            continue
                        url_job = item.get("url", "")
                        org = item.get("hiringOrganization") or {}
                        company = org.get("name", "Компанія") if isinstance(org, dict) else "Компанія"
                        is_remote = item.get("jobLocationType") == "TELECOMMUTE"
                        city = "Віддалено" if is_remote else "Україна"
                        sal_data = item.get("baseSalary") or {}
                        salary = ""
                        if isinstance(sal_data, dict):
                            val = sal_data.get("value") or {}
                            if isinstance(val, dict):
                                mn, mx, cur = val.get("minValue"), val.get("maxValue"), sal_data.get("currency", "USD")
                                if mn and mx:
                                    salary = f"{mn}–{mx} {cur}"
                                elif mn or mx:
                                    salary = f"{mn or mx} {cur}"
                        job_id = "djinni_" + url_job.rstrip("/").split("/")[-1]
                        jobs.append({"id": job_id, "title": title, "company": company,
                                     "salary": salary, "city": city, "desc": desc_raw[:200],
                                     "url": url_job, "source": "Djinni"})
                if not found:
                    break
    except Exception as e:
        logger.error(f"Djinni search error: {e}")
    return jobs


async def fetch_jobs_ua_search(keyword: str) -> list:
    jobs = []
    kw_lower = keyword.lower()
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
               "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
    try:
        async with httpx.AsyncClient(headers=headers, timeout=15, follow_redirects=True) as client:
            r = await client.get(f"https://jobs.ua/ukr/vacancy/?search_phrase={quote_plus(keyword)}")
            if r.status_code != 200:
                return jobs
            soup = BeautifulSoup(r.text, "html.parser")
            for card in soup.select("li.b-vacancy__item"):
                a = card.select_one("a.b-vacancy__top__title")
                if not a:
                    continue
                title = a.get_text(strip=True)
                if kw_lower not in title.lower():
                    continue
                href = a.get("href", "")
                uid_part = href.rstrip("/").split("-")[-1]
                sal_el = card.select_one("span.b-vacancy__top__pay")
                salary = re.sub(r"\s+", " ", sal_el.get_text(strip=True)) if sal_el else ""
                tech = card.select("span.b-vacancy__tech__item")
                company = tech[0].get_text(strip=True) if tech else "Компанія"
                location = ""
                for item in tech[1:]:
                    if item.select_one("i.fa-map-marker"):
                        loc_a = item.select_one("a")
                        location = loc_a.get_text(strip=True) if loc_a else ""
                        break
                jobs.append({"id": f"jobs_{uid_part}", "title": title, "company": company,
                             "salary": salary, "city": location or "Україна",
                             "desc": "", "url": href, "source": "Jobs.ua"})
    except Exception as e:
        logger.error(f"Jobs.ua search error: {e}")
    return jobs


async def keyword_search(update: Update, ctx: ContextTypes.DEFAULT_TYPE, keyword: str):
    await update.message.reply_text(f"🔍 Шукаю «{keyword}»...", reply_markup=MAIN_KB)
    kw_lower = keyword.lower()

    dou_results = await fetch_dou(keyword)
    dou_filtered = [j for j in dou_results if kw_lower in j["title"].lower()]
    djinni_results = await fetch_djinni_search(keyword)
    jobsua_results = await fetch_jobs_ua_search(keyword)

    all_jobs = dou_filtered + djinni_results + jobsua_results

    seen = set()
    unique = []
    for job in all_jobs:
        key = re.sub(r"[^\w]", "", job["title"].lower())
        if key not in seen:
            seen.add(key)
            unique.append(job)

    if not unique:
        await update.message.reply_text(
            f"😔 Нічого не знайдено по запиту «{keyword}».\nСпробуйте інше ключове слово.",
            reply_markup=MAIN_KB
        )
        return

    await update.message.reply_text(f"✅ Знайдено {len(unique[:10])} вакансій по запиту «{keyword}»:")
    for i, job in enumerate(unique[:10], 1):
        city_d = job.get("city", "Україна")
        loc = "🌐 Віддалено" if any(w in city_d.lower() for w in ["дистанц","remote","віддал"]) else f"📍 {city_d}"
        lines = [f"<b>{i}. {job['title']}</b>", f"🏢 {job['company']}", loc]
        if job.get("salary"):
            lines.append(f"💰 {job['salary']}")
        if job.get("desc"):
            desc = job['desc'][:180] + "…" if len(job.get('desc','')) > 180 else job.get('desc','')
            if desc:
                lines.append(f"\n📝 {desc}")
        lines.append(f"\n🔗 <a href='{job['url']}'>Переглянути ({job['source']})</a>")
        text = "\n".join(lines)
        try:
            await update.message.reply_text(text, parse_mode="HTML", disable_web_page_preview=True)
            await asyncio.sleep(0.5)
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
            await update.message.reply_text(text, parse_mode="HTML", disable_web_page_preview=True)
        except Exception as e:
            logger.error(f"Search send error: {e}")


async def send_jobs_now(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    user = get_user(uid)
    if not user:
        await update.message.reply_text("Спочатку налаштуй профіль — натисни /start"); return
    await update.message.reply_text("🔍 Шукаю вакансії для тебе...", reply_markup=MAIN_KB)
    sent = await send_jobs_to_user(ctx.bot, user)
    if sent==0:
        await update.message.reply_text("Нових вакансій поки немає. Спробуй пізніше!", reply_markup=MAIN_KB)

async def scheduled_sender(ctx: ContextTypes.DEFAULT_TYPE):
    users = get_all_active_users()
    now   = datetime.utcnow()
    schedule_hours = {
        "Кожну годину": 1, "Кожні 3 години": 3,
        "Кожні 6 годин": 6, "Раз на день": 24
    }
    for user in users:
        sched = user.get("schedule","")
        hours = schedule_hours.get(sched)
        if hours:
            updated_at = user.get("updated_at")
            if isinstance(updated_at, str):
                try: updated_at = datetime.fromisoformat(updated_at)
                except: updated_at = now - timedelta(hours=hours+1)
            elif updated_at is None:
                updated_at = now - timedelta(hours=hours+1)
            if (now - updated_at).total_seconds() < hours*3600: continue
        elif sched != "Кожну нову вакансію":
            continue
        await send_jobs_to_user(ctx.bot, user)

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    init_db()
    app = Application.builder().token(PERSONAL_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",    start))
    app.add_handler(CommandHandler("jobs",     send_jobs_now))
    app.add_handler(CommandHandler("settings", lambda u,c: handle_settings(u,c)))
    app.add_handler(CommandHandler("stop",     lambda u,c: handle_stop(u,c)))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    if app.job_queue:
        app.job_queue.run_repeating(scheduled_sender, interval=3600, first=60)
        logger.info("Job queue enabled")
    else:
        logger.warning("Job queue not available - install python-telegram-bot[job-queue]")
    logger.info("Персональний бот запущено")
    app.run_polling(drop_pending_updates=True)

async def handle_settings(update, ctx):
    uid = update.effective_user.id
    user_state[uid] = {"step":"city"}
    await update.message.reply_text("Крок 1/5 — Місто:", reply_markup=city_kb())

async def handle_stop(update, ctx):
    deactivate_user(update.effective_user.id)
    await update.message.reply_text("⛔ Сповіщення зупинено. /start щоб відновити.")

if __name__ == "__main__":
    main()
