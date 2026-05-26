import asyncio
import sqlite3
import logging
import os
import re
from datetime import datetime, timezone
from dataclasses import dataclass
from urllib.parse import quote_plus
from dotenv import load_dotenv

load_dotenv()

import httpx
from bs4 import BeautifulSoup
from telegram import Update
from telegram.constants import ParseMode
from telegram.error import RetryAfter
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ─── НАЛАШТУВАННЯ ────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHANNEL_ID     = os.getenv("CHANNEL_ID", "-1003931372029")
CHECK_INTERVAL = 60 * 30
DB_FILE        = "jobs.db"
# ─────────────────────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}

# ─── МІСТА ───────────────────────────────────────────────────────────────────
CITY_TAGS = {
    "львів": "#Львів", "lviv": "#Львів",
    "івано-франківськ": "#ІваноФранківськ",
    "тернопіль": "#Тернопіль",
    "луцьк": "#Луцьк",
    "рівне": "#Рівне",
    "ужгород": "#Ужгород",
    "чернівці": "#Чернівці",
    "хмельницький": "#Хмельницький",
    "київ": "#Київ", "kyiv": "#Київ",
    "вінниця": "#Вінниця",
    "черкаси": "#Черкаси",
    "житомир": "#Житомир",
    "кропивницький": "#Кропивницький",
    "полтава": "#Полтава",
    "суми": "#Суми",
    "чернігів": "#Чернігів",
    "одеса": "#Одеса", "odesa": "#Одеса",
    "миколаїв": "#Миколаїв",
    "херсон": "#Херсон",
    "запоріжжя": "#Запоріжжя",
    "дніпро": "#Дніпро",
    "харків": "#Харків",
}

REMOTE_KEYWORDS = {
    "дистанційно", "дистанційна", "дистанційна робота", "дистанційний",
    "remote", "remotely", "віддалено", "віддалена", "віддалена робота",
    "home office", "робота вдома", "з дому",
}

ALLOWED_CITIES = set(CITY_TAGS.keys()) | REMOTE_KEYWORDS | {"україна", "ukraine"}

# ─── КАТЕГОРІЇ ───────────────────────────────────────────────────────────────
CATEGORY_TAGS = [
    (["python", "django", "flask"],                                    "#Python"),
    (["javascript", "js", "react", "vue", "angular", "node"],         "#JavaScript"),
    (["java", "spring"],                                               "#Java"),
    (["php", "laravel", "symfony"],                                    "#PHP"),
    (["c++", "c#", ".net", "unity"],                                   "#CSharp"),
    (["ios", "swift"],                                                 "#iOS"),
    (["android", "kotlin"],                                            "#Android"),
    (["devops", "docker", "kubernetes", "aws", "cloud"],               "#DevOps"),
    (["qa", "тестувальник", "тестировщик", "testing", "automation"],  "#QA"),
    (["аналітик", "analyst", "bi", "tableau", "data"],                "#Analytics"),
    (["ml", "machine learning", "deep learning", "штучний інтелект"], "#ML_AI"),
    (["дизайнер", "designer", "ui", "ux", "figma"],                   "#Design"),
    (["маркетолог", "marketing", "smm", "seo", "контент"],            "#Marketing"),
    (["бухгалтер", "accountant", "фінансист"],                        "#Бухгалтерія"),
    (["менеджер", "manager", "продажі", "sales"],                     "#Менеджмент"),
    (["водій", "driver", "кур'єр", "courier"],                        "#Водій"),
    (["склад", "warehouse", "вантажник", "комплектувальник"],         "#Склад"),
    (["будівельник", "монтажник", "електрик", "зварювальник"],        "#Будівництво"),
    (["медсестра", "лікар", "фармацевт", "медичний"],                 "#Медицина"),
    (["вчитель", "викладач", "репетитор", "teacher"],                 "#Освіта"),
    (["юрист", "lawyer", "legal"],                                    "#Юриспруденція"),
    (["hr", "рекрутер", "recruiter"],                                 "#HR"),
    (["охоронець", "охорона", "security"],                            "#Охорона"),
    (["кухар", "офіціант", "бармен", "повар"],                        "#HoReCa"),
    (["касир", "продавець", "консультант"],                           "#Торгівля"),
]


def get_category_hashtags(title: str, description: str) -> list:
    text = (title + " " + description).lower()
    tags = []
    for keywords, tag in CATEGORY_TAGS:
        if any(kw in text for kw in keywords):
            tags.append(tag)
    return tags[:3]


# ─── ЗАРПЛАТА ────────────────────────────────────────────────────────────────
def parse_salary_amount(salary_str: str) -> int:
    if not salary_str:
        return 0
    cleaned = re.sub(r'(\d)\s+(\d)', r'\1\2', salary_str)
    numbers = re.findall(r'\d+', cleaned)
    return int(numbers[0]) if numbers else 0


def get_salary_hashtag(salary_str: str) -> str:
    amount = parse_salary_amount(salary_str)
    if amount <= 0:       return ""
    if amount < 20000:    return "#до_20к"
    elif amount < 30000:  return "#20к_30к"
    elif amount < 40000:  return "#30к_40к"
    elif amount < 50000:  return "#40к_50к"
    elif amount < 100000: return "#50к_плюс"
    else:                 return "#100к_плюс"


# ─── ЛОКАЦІЯ ─────────────────────────────────────────────────────────────────
def normalize_location(location: str):
    if not location:
        return "Не вказано", "", False
    loc_lower = location.lower()
    for kw in REMOTE_KEYWORDS:
        if kw in loc_lower:
            return "Віддалено", "#Віддалено", True
    for key, tag in CITY_TAGS.items():
        if key in loc_lower:
            return location.split(",")[0].strip(), tag, False
    return location.split(",")[0].strip(), "", False


def is_allowed_location(location: str) -> bool:
    if not location:
        return True
    loc_lower = location.lower()
    return any(city in loc_lower for city in ALLOWED_CITIES)


# ─── БАЗА ДАНИХ ──────────────────────────────────────────────────────────────
def init_db():
    con = sqlite3.connect(DB_FILE)
    con.execute("""
        CREATE TABLE IF NOT EXISTS sent_jobs (
            uid TEXT PRIMARY KEY,
            sent_at TEXT
        )
    """)
    con.commit()
    return con


def is_sent(con, uid: str) -> bool:
    return con.execute("SELECT 1 FROM sent_jobs WHERE uid=?", (uid,)).fetchone() is not None


def mark_sent(con, uid: str):
    con.execute("INSERT OR IGNORE INTO sent_jobs VALUES (?, ?)",
                (uid, datetime.now(timezone.utc).isoformat()))
    con.commit()


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


# ─── HTTPX ПАРСЕРИ ───────────────────────────────────────────────────────────
async def fetch(client: httpx.AsyncClient, url: str):
    try:
        r = await client.get(url, headers=HEADERS, timeout=20, follow_redirects=True)
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        log.warning(f"Помилка завантаження {url}: {e}")
        return None


async def fetch_work_ua_detail(client, url, uid, title) -> Job:
    soup = await fetch(client, url)
    if not soup:
        return Job(uid, title, "—", "", "Україна", "", url, "Work.ua")
    company_el = soup.select_one("a[href*='/company/']") or soup.select_one("div.job-details--title a")
    company = company_el.get_text(strip=True) if company_el else "—"
    salary = ""
    for el in soup.select("span, b, strong"):
        text = el.get_text(strip=True)
        if re.search(r'\d[\d\s]*грн|usd|\$', text, re.IGNORECASE) and len(text) < 60:
            salary = text
            break
    location = ""
    experience = ""
    for dt in soup.select("dt"):
        label = dt.get_text(strip=True).lower()
        dd = dt.find_next_sibling("dd")
        if not dd:
            continue
        val = dd.get_text(strip=True)
        if "місто" in label or "місце" in label:
            location = val
        elif "досвід" in label:
            experience = val
    desc_el = soup.select_one("div#job-description")
    description = ""
    if desc_el:
        text = desc_el.get_text(separator=" ", strip=True)
        description = text[:280] + "…" if len(text) > 280 else text
    return Job(uid, title, company, salary, location or "Україна", experience, url, "Work.ua", description)


async def parse_work_ua(client: httpx.AsyncClient, keyword: str = None) -> list:
    jobs = []
    for page in range(1, 4):
        if keyword:
            url = f"https://www.work.ua/jobs/?q={quote_plus(keyword)}&page={page}"
        else:
            url = f"https://www.work.ua/jobs/?page={page}"
        soup = await fetch(client, url)
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
            location_preview = ""
            if loc_el:
                sib = loc_el.find_next_sibling(string=True)
                location_preview = sib.strip() if sib else ""
            if not keyword and location_preview and not is_allowed_location(location_preview):
                continue
            job_url = "https://www.work.ua" + href
            job = await fetch_work_ua_detail(client, job_url, uid, title)
            if not keyword and not is_allowed_location(job.location):
                continue
            jobs.append(job)
            await asyncio.sleep(0.7)
    return jobs


async def fetch_dou_detail(client, url, uid, title, company, salary, location) -> Job:
    soup = await fetch(client, url)
    if not soup:
        return Job(uid, title, company, salary, location, "", url, "DOU.ua")
    experience = ""
    info_block = soup.select_one("div.sh-info")
    if info_block:
        for span in info_block.select("span"):
            text = span.get_text(strip=True).lower()
            if any(w in text for w in ["рік", "років", "без досвід", "year"]):
                experience = span.get_text(strip=True)
                break
    desc_el = soup.select_one("div.vacancy-section")
    description = ""
    if desc_el:
        text = desc_el.get_text(separator=" ", strip=True)
        description = text[:280] + "…" if len(text) > 280 else text
    return Job(uid, title, company, salary, location, experience, url, "DOU.ua", description)


async def parse_dou(client: httpx.AsyncClient, keyword: str = None) -> list:
    jobs = []
    if keyword:
        url = f"https://jobs.dou.ua/vacancies/?search={quote_plus(keyword)}"
    else:
        url = "https://jobs.dou.ua/vacancies/"
    soup = await fetch(client, url)
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
        if not keyword and not is_allowed_location(location):
            continue
        job = await fetch_dou_detail(client, href, uid, title, company, salary, location)
        jobs.append(job)
        await asyncio.sleep(0.7)
    return jobs


async def parse_djinni(client: httpx.AsyncClient, keyword: str = None) -> list:
    import json as _json
    jobs = []
    for page in range(1, 4):
        if keyword:
            base = f"https://djinni.co/jobs/?q={quote_plus(keyword)}"
            url = base if page == 1 else f"{base}&page={page}"
        else:
            url = f"https://djinni.co/jobs/?page={page}" if page > 1 else "https://djinni.co/jobs/"
        soup = await fetch(client, url)
        if not soup:
            break
        scripts = soup.find_all("script", type="application/ld+json")
        found = False
        for s in scripts:
            try:
                data = _json.loads(s.string or "")
            except Exception:
                continue
            if not isinstance(data, list):
                continue
            for item in data:
                if item.get("@type") != "JobPosting":
                    continue
                found = True
                url_job = item.get("url", "")
                uid = "djinni_" + url_job.rstrip("/").split("/")[-1]
                title = item.get("title", "")
                org = item.get("hiringOrganization") or {}
                company = org.get("name", "—") if isinstance(org, dict) else "—"
                is_remote = item.get("jobLocationType") == "TELECOMMUTE"
                location = "Дистанційно" if is_remote else "Україна"
                exp_req = item.get("experienceRequirements") or {}
                months = exp_req.get("monthsOfExperience") if isinstance(exp_req, dict) else None
                experience = f"{int(months // 12)} р." if months and months >= 12 else ("без досвіду" if months == 0 else "")
                salary_data = item.get("baseSalary") or {}
                salary = ""
                if isinstance(salary_data, dict):
                    val = salary_data.get("value") or {}
                    if isinstance(val, dict):
                        mn = val.get("minValue")
                        mx = val.get("maxValue")
                        currency = salary_data.get("currency", "USD")
                        if mn and mx:
                            salary = f"{mn}–{mx} {currency}"
                        elif mn or mx:
                            salary = f"{mn or mx} {currency}"
                desc_raw = item.get("description", "")
                description = desc_raw[:280] + "…" if len(desc_raw) > 280 else desc_raw
                jobs.append(Job(uid, title, company, salary, location, experience, url_job, "Djinni", description))
                await asyncio.sleep(0.3)
        if not found:
            break
    return jobs


async def parse_jobs_ua(client: httpx.AsyncClient, keyword: str = None) -> list:
    jobs = []
    if keyword:
        pages = [(1, f"https://jobs.ua/ukr/vacancy/?search_phrase={quote_plus(keyword)}")]
    else:
        pages = [(p, f"https://jobs.ua/ukr/vacancy/page-{p}" if p > 1 else "https://jobs.ua/ukr/vacancy/")
                 for p in range(1, 4)]
    for _, url in pages:
        soup = await fetch(client, url)
        if not soup:
            break
        cards = soup.select("li.b-vacancy__item")
        if not cards:
            break
        for card in cards:
            a = card.select_one("a.b-vacancy__top__title")
            if not a:
                continue
            href = a.get("href", "")
            uid_part = href.rstrip("/").split("-")[-1]
            uid = "jobs_" + uid_part
            title = a.get_text(strip=True)
            salary_el = card.select_one("span.b-vacancy__top__pay")
            salary = re.sub(r"\s+", " ", salary_el.get_text(strip=True)).replace("грн.", "грн") if salary_el else ""
            tech_items = card.select("span.b-vacancy__tech__item")
            company = tech_items[0].get_text(strip=True) if tech_items else "—"
            location = ""
            for item in tech_items[1:]:
                if item.select_one("i.fa-map-marker"):
                    loc_a = item.select_one("a")
                    location = loc_a.get_text(strip=True) if loc_a else item.get_text(strip=True)
                    break
            if not keyword and location and not is_allowed_location(location):
                continue
            jobs.append(Job(uid, title, company, salary, location or "Україна", "", href, "Jobs.ua"))
            await asyncio.sleep(0.3)
    return jobs


def _title_key(title: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", title.lower())).strip()


async def collect_all_jobs(client: httpx.AsyncClient) -> list:
    source_names = ["work", "dou", "djinni", "jobs"]
    results = await asyncio.gather(
        parse_work_ua(client),
        parse_dou(client),
        parse_djinni(client),
        parse_jobs_ua(client),
        return_exceptions=True,
    )
    all_jobs = {}
    for name, r in zip(source_names, results):
        if isinstance(r, list):
            all_jobs[name] = r
            log.info(f"{name}: знайдено {len(r)} вакансій")
        else:
            log.error(f"Помилка {name}: {r}")
            all_jobs[name] = []

    interleaved = []
    batch = 5
    sources = [all_jobs[n] for n in source_names]
    indices = [0] * len(sources)
    while any(indices[i] < len(sources[i]) for i in range(len(sources))):
        for i in range(len(sources)):
            chunk = sources[i][indices[i]:indices[i] + batch]
            interleaved.extend(chunk)
            indices[i] += batch

    seen_keys: set[str] = set()
    unique = []
    for job in interleaved:
        key = _title_key(job.title)
        if key not in seen_keys:
            seen_keys.add(key)
            unique.append(job)
    return unique


async def search_jobs(client: httpx.AsyncClient, keyword: str) -> list:
    results = await asyncio.gather(
        parse_dou(client, keyword=keyword),
        parse_djinni(client, keyword=keyword),
        parse_jobs_ua(client, keyword=keyword),
        return_exceptions=True,
    )
    kw_lower = keyword.lower()
    all_jobs = []
    for r in results:
        if isinstance(r, list):
            for job in r:
                if kw_lower in job.title.lower() or kw_lower in job.description.lower():
                    all_jobs.append(job)
    seen_keys: set[str] = set()
    unique = []
    for job in all_jobs:
        key = _title_key(job.title)
        if key not in seen_keys:
            seen_keys.add(key)
            unique.append(job)
    return unique[:15]


# ─── ФОРМАТУВАННЯ ────────────────────────────────────────────────────────────
def format_job(job: Job) -> str:
    location_display, city_tag, is_remote = normalize_location(job.location)
    lines = [f"🆕 <b>{job.title}</b>"]
    if job.company and job.company != "—":
        lines.append(f"🏢 {job.company}")
    lines.append(f"💰 {job.salary if job.salary else 'Зарплата не вказана'}")
    if is_remote:
        lines.append("🌐 Віддалено")
    else:
        lines.append(f"📍 {location_display}")
    if job.experience:
        lines.append(f"🎓 Досвід: {job.experience}")
    if job.description:
        lines.append(f"\n📝 {job.description}")
    lines.append(f"\n🔗 <a href='{job.url}'>Переглянути вакансію</a>")
    lines.append(f"<i>Джерело: {job.source}</i>")

    hashtags = []
    if is_remote:
        hashtags.append("#Віддалено")
        hashtags.append("#Remote")
    elif city_tag:
        hashtags.append(city_tag)
    salary_tag = get_salary_hashtag(job.salary)
    if salary_tag:
        hashtags.append(salary_tag)
    hashtags.extend(get_category_hashtags(job.title, job.description))
    if hashtags:
        lines.append("\n" + " ".join(hashtags))
    return "\n".join(lines)


def format_job_search(job: Job, index: int) -> str:
    """Компактний формат для результатів пошуку."""
    _, _, is_remote = normalize_location(job.location)
    loc = "🌐 Віддалено" if is_remote else f"📍 {job.location.split(',')[0].strip()}"
    salary = f"💰 {job.salary}" if job.salary else ""
    parts = [f"<b>{index}. {job.title}</b>"]
    if job.company and job.company != "—":
        parts.append(f"🏢 {job.company}")
    parts.append(loc)
    if salary:
        parts.append(salary)
    parts.append(f"🔗 <a href='{job.url}'>{job.source}</a>")
    return "\n".join(parts)


# ─── TELEGRAM HANDLERS ───────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 Привіт! Я бот пошуку вакансій по Україні.\n\n"
        "🔍 <b>Як шукати:</b>\n"
        "Просто напишіть ключове слово або фразу, наприклад:\n"
        "  • <code>python developer</code>\n"
        "  • <code>бухгалтер</code>\n"
        "  • <code>водій Київ</code>\n\n"
        "📢 Або підпишіться на канал — нові вакансії публікуються автоматично кожні 30 хв.\n\n"
        "Джерела: DOU.ua • Djinni.co • Jobs.ua"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyword = " ".join(context.args).strip() if context.args else ""
    if not keyword:
        await update.message.reply_text("Вкажіть ключове слово: /search python")
        return
    await _do_search(update, context, keyword)


async def msg_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyword = (update.message.text or "").strip()
    if not keyword:
        return
    await _do_search(update, context, keyword)


async def _do_search(update: Update, context: ContextTypes.DEFAULT_TYPE, keyword: str):
    client: httpx.AsyncClient = context.bot_data["client"]
    msg = await update.message.reply_text(f"🔍 Шукаю «{keyword}»...")
    jobs = await search_jobs(client, keyword)
    if not jobs:
        await msg.edit_text(f"😔 Нічого не знайдено по запиту «{keyword}».\nСпробуйте інше ключове слово.")
        return
    await msg.edit_text(f"✅ Знайдено {len(jobs)} вакансій по запиту «{keyword}»:")
    for i, job in enumerate(jobs, 1):
        try:
            await update.message.reply_text(
                format_job_search(job, i),
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
            await asyncio.sleep(0.5)
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
            await update.message.reply_text(
                format_job_search(job, i),
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except Exception as e:
            log.error(f"Помилка відправки пошукового результату: {e}")


# ─── ФОНОВИЙ ПОСТИНГ ─────────────────────────────────────────────────────────
async def post_auto_jobs(context: ContextTypes.DEFAULT_TYPE):
    client: httpx.AsyncClient = context.bot_data["client"]
    con = context.bot_data["con"]
    log.info("Починаємо збір вакансій…")
    jobs = await collect_all_jobs(client)
    new_count = 0
    for job in jobs:
        if is_sent(con, job.uid):
            continue
        for attempt in range(2):
            try:
                await context.bot.send_message(
                    chat_id=CHANNEL_ID,
                    text=format_job(job),
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
                mark_sent(con, job.uid)
                new_count += 1
                await asyncio.sleep(3)
                break
            except RetryAfter as e:
                wait = e.retry_after + 2
                log.warning(f"Flood control, чекаємо {wait}s")
                await asyncio.sleep(wait)
            except Exception as e:
                log.error(f"Помилка відправки {job.uid}: {e}")
                break
    log.info(f"Відправлено: {new_count}. Наступна перевірка через {CHECK_INTERVAL // 60} хв.")


# ─── ІНІЦІАЛІЗАЦІЯ ───────────────────────────────────────────────────────────
async def post_init(application: Application):
    application.bot_data["con"] = init_db()
    application.bot_data["client"] = httpx.AsyncClient()
    me = await application.bot.get_me()
    log.info(f"Бот запущено: @{me.username}")


async def post_shutdown(application: Application):
    await application.bot_data["client"].aclose()


def main():
    app = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("search", cmd_search))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg_search))
    app.job_queue.run_repeating(post_auto_jobs, interval=CHECK_INTERVAL, first=30)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
