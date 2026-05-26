import asyncio
import sqlite3
import logging
import os
import re
from datetime import datetime, timezone
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

import httpx
from bs4 import BeautifulSoup
from telegram import Bot
from telegram.constants import ParseMode

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
            location_preview = ""
            if loc_el:
                sib = loc_el.find_next_sibling(string=True)
                location_preview = sib.strip() if sib else ""
            if location_preview and not is_allowed_location(location_preview):
                continue
            job_url = "https://www.work.ua" + href
            job = await fetch_work_ua_detail(client, job_url, uid, title)
            if not is_allowed_location(job.location):
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
        if not is_allowed_location(location):
            continue
        job = await fetch_dou_detail(client, href, uid, title, company, salary, location)
        jobs.append(job)
        await asyncio.sleep(0.7)
    return jobs


async def collect_all_jobs(client: httpx.AsyncClient) -> list:
    results = await asyncio.gather(
        parse_work_ua(client),
        parse_dou(client),
        return_exceptions=True
    )
    all_jobs = {"work": [], "dou": [], "robota": [], "djinni": []}
    for name, r in zip(["work", "dou", "robota", "djinni"], results):
        if isinstance(r, list):
            all_jobs[name] = r
        else:
            log.error(f"Помилка {name}: {r}")

    # Чергуємо по 5 з кожного джерела
    interleaved = []
    batch = 5
    sources = [all_jobs["work"], all_jobs["dou"], all_jobs["robota"], all_jobs["djinni"]]
    indices = [0, 0, 0, 0]
    while any(indices[i] < len(sources[i]) for i in range(4)):
        for i in range(4):
            chunk = sources[i][indices[i]:indices[i] + batch]
            interleaved.extend(chunk)
            indices[i] += batch
    return interleaved


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


# ─── ГОЛОВНИЙ ЦИКЛ ───────────────────────────────────────────────────────────
async def run():
    bot = Bot(token=TELEGRAM_TOKEN)
    con = init_db()
    me = await bot.get_me()
    log.info(f"Бот запущено: @{me.username}")

    async with httpx.AsyncClient() as client:
        while True:
            log.info("Починаємо збір вакансій…")
            jobs = await collect_all_jobs(client)
            new_count = 0
            for job in jobs:
                if is_sent(con, job.uid):
                    continue
                try:
                    await bot.send_message(
                        chat_id=CHANNEL_ID,
                        text=format_job(job),
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True,
                    )
                    mark_sent(con, job.uid)
                    new_count += 1
                    await asyncio.sleep(2)
                except Exception as e:
                    log.error(f"Помилка відправки {job.uid}: {e}")
            log.info(f"Відправлено: {new_count}. Наступна перевірка через {CHECK_INTERVAL//60} хв.")
            await asyncio.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    asyncio.run(run())
