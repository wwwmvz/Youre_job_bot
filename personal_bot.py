import os, logging, asyncio, httpx, re
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import nest_asyncio

nest_asyncio.apply()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

PERSONAL_BOT_TOKEN = os.environ.get("PERSONAL_BOT_TOKEN", "8018911506:AAFPS_Jdw8MCYJ34M3UGnKvGoEV8PN7yRSQ")
MAIN_CHANNEL       = os.environ.get("MAIN_CHANNEL",        "https://t.me/+YNCaw9gBllI5NzU0")
DATABASE_URL       = os.environ.get("DATABASE_URL",        "")

logger.info(f"DATABASE_URL present: {bool(DATABASE_URL)}")
logger.info(f"TOKEN present: {bool(PERSONAL_BOT_TOKEN)}")

# ── DB ────────────────────────────────────────────────────────────────────────
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
                if keywords:
                    kws = keywords.lower().split()
                    if not any(k in (title+" "+desc).lower() for k in kws): continue
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
                if keywords:
                    kws = keywords.lower().split()
                    if not any(k in (title+" "+desc).lower() for k in kws): continue
                jobs.append({"id":job_id,"title":title,"company":company,"salary":salary,
                             "city":city,"desc":desc,"url":link,"source":"DOU.ua"})
    except Exception as e:
        logger.error(f"DOU error: {e}")
    return jobs

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
    photo_url = PHOTO_URLS.get(prof, PHOTO_URLS["🔍 Інше"])
    jobs = await fetch_workua(city, keywords)
    jobs += await fetch_dou(keywords)
    sent = 0
    for job in jobs:
        if is_sent(user["user_id"], job["id"]): continue
        if not salary_match(job.get("salary",""), u_salary): continue
        city_d = job.get("city","") or city
        if any(w in city_d.lower() for w in ["дистанц","remote","home","віддал"]):
            city_d = "🌐 Віддалено"
        sal_d = job.get("salary","") or "не вказана"
        caption = f"🆕 {job['title']}\n\n🏢 {job['company']}\n💰 {sal_d}\n📍 {city_d}\n"
        if job.get("desc"):
            caption += f"\n📝 {job['desc'][:200]}\n"
        caption += f"\n🔗 {job['url']}\nДжерело: {job['source']}"
        if len(caption)>1024: caption=caption[:1020]+"..."
        try:
            await bot.send_photo(chat_id=user["user_id"], photo=photo_url, caption=caption)
            mark_sent(user["user_id"], job["id"])
            sent += 1
            await asyncio.sleep(0.5)
            if sent>=5: break
        except Exception as e:
            logger.error(f"Send error {user['user_id']}: {e}"); break
    logger.info(f"Надіслано {sent} вакансій юзеру {user['user_id']}")
    return sent

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