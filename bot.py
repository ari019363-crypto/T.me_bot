# -*- coding: utf-8 -*-
"""
ربات چتر - ربات مدیریت گروه تلگرام با پایتون
نیازمندی‌ها: python-telegram-bot==20.7  (pip install python-telegram-bot==20.7)
اجرا: یک توکن از @BotFather بگیر و در متغیر BOT_TOKEN پایین قرار بده (یا در متغیر محیطی BOT_TOKEN ست کن)
دیتابیس: SQLite (فایل chatr_bot.db به صورت خودکار کنار همین فایل ساخته می‌شه)
"""

import os
import re
import ast
import html
import json
import random
import sqlite3
import logging
import asyncio
import urllib.request
from datetime import datetime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ChatPermissions,
    BotCommand,
    MenuButtonCommands,
)
from telegram.constants import ParseMode, ChatMemberStatus
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ChatMemberHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("chatr_bot")

# ---------------------------------------------------------------------------
# تنظیمات پایه
# ---------------------------------------------------------------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8793539029:AAGBdIZYPBXCs-DZ_E1ZD3rGsSLOO0QQIvg")
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chatr_bot.db")
MAX_WARNINGS = 3          # بعد از این تعداد اخطار، کاربر به صورت خودکار از گروه حذف می‌شه
MESSAGES_TO_KEEP = 2000   # حداکثر تعداد آی‌دی پیام ذخیره شده برای هر گروه (برای قابلیت حذف پیام‌ها)
MAX_SPAM_MUTE_MINUTES = 30  # حداکثر مجاز برای دقیقه‌ی سکوت خودکار ضد اسپم

# آی‌دی عددی مالک اصلی ربات (تو). هر کسی که آی‌دیش اینجا باشه، تو هر گروهی که ربات عضوشه،
# فارغ از اینکه واقعا ادمین/مالک همون گروه باشه یا نه، دسترسی کامل ادمین و مالک داره.
# می‌تونی مستقیم عدد آی‌دیت رو اینجا بنویسی، یا با متغیر محیطی SUPER_ADMIN_IDS (با کاما جدا) ست کنی.
SUPER_ADMIN_IDS = set()
_env_super_admins = os.environ.get("SUPER_ADMIN_IDS", "7430881772")
if _env_super_admins:
    SUPER_ADMIN_IDS |= {int(x.strip()) for x in _env_super_admins.split(",") if x.strip().isdigit()}
# مثال دستی: SUPER_ADMIN_IDS.add(123456789)

# پک‌های دیالوگ (لحن‌ها) که از فایل‌های راو گیت‌هاب خونده می‌شن. هر لحن یه متغیر محیطی جدا داره؛
# اگه متغیرش خالی باشه یعنی هنوز فایلش آماده نیست. چندتا لحن می‌تونن هم‌زمان برای یه گروه فعال باشن.
PACK_DEFINITIONS = {
    "default": {"label": "🗨 عمومی (پیش‌فرض)", "url_env": "https://raw.githubusercontent.com/ari019363-crypto/T.me_bot/refs/heads/main/default_pack.py"},
    "angry": {"label": "😠 عصبانی", "url_env": "https://raw.githubusercontent.com/ari019363-crypto/T.me_bot/refs/heads/main/angry_pack.py"},
    "sad": {"label": "😢 ناراحت", "url_env": "https://raw.githubusercontent.com/ari019363-crypto/T.me_bot/refs/heads/main/sad_pack.py"},
    "happy": {"label": "😄 خوشحال", "url_env": "https://raw.githubusercontent.com/ari019363-crypto/T.me_bot/refs/heads/main/happy_pack.py"},
}
DEFAULT_PACK_REFRESH_SECONDS = 3600  # هر چند وقت یک‌بار خودکار از گیت‌هاب دوباره خونده بشه
_pack_cache = {}  # pack_name -> {"data": {...}, "loaded_at": datetime | None}

# جملات پیش‌فرض «یادآوری غیبت اعضا» - هر چند وقت یک‌بار ربات یکی رو تصادفی تگ می‌کنه و یکی از این جمله‌ها رو می‌گه
ENGAGEMENT_PHRASES = [
    "هی خوشگل، کجایی؟ نیستی کم پیدایی! 🌸",
    "بدون تو گپ کویره، اگه میشه برگرد ☂️",
    "کجا گمی رفیق؟ جات اینجا خالیه!",
    "چقدر وقته پیدات نیست، یه سر بزن ببینیم چه خبر!",
    "دلمون برات تنگ شد، بیا یه گپی بزنیم!",
    "گروه بدون تو رنگ و بو نداره، بیا دیگه!",
    "پس چرا انقدر کم‌پیدایی؟ منتظرتیم!",
    "یه سر بزن حداقل، دلمون تنگ شده!",
    "کجایی که این‌جا سوت و کوره بدون تو!",
    "بیا یه چیزی بگو، جات خالیه اینجا!",
]

# اسم ربات - وقتی جایی تو پیام باشه، ربات یکی از این ۱۰ جواب رو رندوم جواب می‌ده (همیشه فعاله، مستقل از پک‌ها)
BOT_NAME = "کولیبا"
BOT_NAME_REACTIONS = [
    "جونم؟ صدام کردی؟ 😄",
    "بله بله، در خدمتم!",
    "کولیبا حاضره، بفرما!",
    "جانم عزیز، چیزی شده؟",
    "بله؟ اینجام، چیکار داری؟",
    "کولیبا شنیدم، بگو ببینم!",
    "هوی، صدام کردی! چه خبر؟",
    "بله سرورم، در خدمتم! 🫡",
    "جونم رفیق، گوش می‌دم!",
    "کولیبا اینجاست، بگو چی شده!",
]

# پیام‌های خوشامد برای کاربری که قبلاً تو گروه بوده، رفته، و برگشته
WELCOME_BACK_PHRASES = [
    "برگشتی رفیق! خوش اومدی، جات خالی بود.",
    "به‌به، برگشتی! دلمون برات تنگ شده بود.",
    "خوش اومدی، می‌دونستم برمی‌گردی!",
    "برگشتی که! گروه بدون تو یه‌چیزیش کم بود.",
    "سلام دوباره! خوش برگشتی رفیق.",
]

# مراحل مکالمه (ConversationHandler states)
(
    LEARN_WORD_WAIT_TRIGGER,
    LEARN_WORD_WAIT_ANSWER,
    EDIT_WORD_WAIT_ANSWER,
    ADD_TITLE_WAIT_USER,
    ADD_TITLE_WAIT_TEXT,
    WARN_WAIT_USER,
    WARN_WAIT_REASON,
    REMOVE_WARN_WAIT_USER,
    FORBIDDEN_ADD_WAIT_WORD,
    FORBIDDEN_REMOVE_WAIT_WORD,
    DELETE_N_WAIT_NUMBER,
    SPECIAL_ADD_WAIT_USER,
    SPECIAL_TONE_WAIT_TEXT,
    DELETE_WORD_WAIT_CODE,
    SPAM_CFG_WAIT_THRESHOLD,
    SPAM_CFG_WAIT_MUTE,
    ENGAGEMENT_WAIT_HOURS,
) = range(17)


# ---------------------------------------------------------------------------
# لایه دیتابیس
# ---------------------------------------------------------------------------
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS learned_words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            teacher_id INTEGER NOT NULL DEFAULT 0,
            code INTEGER NOT NULL,
            trigger_word TEXT NOT NULL,
            answers TEXT NOT NULL,      -- JSON list of strings
            UNIQUE(chat_id, teacher_id, code)
        );

        CREATE TABLE IF NOT EXISTS admins (
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            PRIMARY KEY (chat_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS warnings (
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            count INTEGER NOT NULL DEFAULT 0,
            reasons TEXT NOT NULL DEFAULT '[]',   -- JSON list of strings
            PRIMARY KEY (chat_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS forbidden_words (
            chat_id INTEGER NOT NULL,
            word TEXT NOT NULL,
            PRIMARY KEY (chat_id, word)
        );

        CREATE TABLE IF NOT EXISTS special_members (
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            custom_tone TEXT,
            PRIMARY KEY (chat_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS group_settings (
            chat_id INTEGER PRIMARY KEY,
            locked INTEGER NOT NULL DEFAULT 0,
            forward_allowed INTEGER NOT NULL DEFAULT 1,
            spam_protection INTEGER NOT NULL DEFAULT 0,
            spam_threshold INTEGER NOT NULL DEFAULT 5,
            spam_mute_minutes INTEGER NOT NULL DEFAULT 5,
            allow_photo INTEGER NOT NULL DEFAULT 1,
            allow_video INTEGER NOT NULL DEFAULT 1,
            allow_sticker_gif INTEGER NOT NULL DEFAULT 1,
            owner_user_id INTEGER
        );

        CREATE TABLE IF NOT EXISTS tracked_messages (
            chat_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (chat_id, message_id)
        );

        CREATE TABLE IF NOT EXISTS user_groups (
            user_id INTEGER NOT NULL,
            chat_id INTEGER NOT NULL,
            title TEXT,
            PRIMARY KEY (user_id, chat_id)
        );

        CREATE TABLE IF NOT EXISTS group_members (
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            first_name TEXT,
            username TEXT,
            updated_at TEXT,
            first_seen TEXT,
            is_present INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (chat_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS active_packs (
            chat_id INTEGER NOT NULL,
            pack_name TEXT NOT NULL,
            PRIMARY KEY (chat_id, pack_name)
        );
        """
    )
    conn.commit()

    # --- مهاجرت امن برای دیتابیس‌های قدیمی‌تر که این ستون‌ها/محدودیت‌ها رو نداشتن ---
    def _column_names(table):
        c.execute(f"PRAGMA table_info({table})")
        return [r[1] for r in c.fetchall()]

    def _add_column_if_missing(table, coldef):
        col_name = coldef.split()[0]
        if col_name not in _column_names(table):
            c.execute(f"ALTER TABLE {table} ADD COLUMN {coldef}")
            conn.commit()

    for coldef in (
        "spam_threshold INTEGER NOT NULL DEFAULT 5",
        "spam_mute_minutes INTEGER NOT NULL DEFAULT 5",
        "allow_photo INTEGER NOT NULL DEFAULT 1",
        "allow_video INTEGER NOT NULL DEFAULT 1",
        "allow_sticker_gif INTEGER NOT NULL DEFAULT 1",
        "owner_user_id INTEGER",
        "use_default_pack INTEGER NOT NULL DEFAULT 0",
        "block_links INTEGER NOT NULL DEFAULT 0",
        "engagement_enabled INTEGER NOT NULL DEFAULT 0",
        "engagement_interval_hours INTEGER NOT NULL DEFAULT 6",
        "last_engagement_at TEXT",
    ):
        _add_column_if_missing("group_settings", coldef)

    for coldef in (
        "first_seen TEXT",
        "is_present INTEGER NOT NULL DEFAULT 1",
    ):
        _add_column_if_missing("group_members", coldef)

    # برای رکوردهای قدیمیِ اعضا که first_seen ندارن، از همون updated_at به عنوان اولین دیدار استفاده می‌کنیم
    c.execute("UPDATE group_members SET first_seen = updated_at WHERE first_seen IS NULL")
    conn.commit()

    # مهاجرت از سیستم قدیمی تک‌پک (use_default_pack) به سیستم چندپکِ جدید (active_packs)
    c.execute("SELECT chat_id FROM group_settings WHERE use_default_pack=1")
    for row in c.fetchall():
        c.execute(
            "INSERT OR IGNORE INTO active_packs (chat_id, pack_name) VALUES (?, 'default')", (row["chat_id"],)
        )
    conn.commit()

    # اگه learned_words قدیمی (بدون teacher_id) باشه، جدولش رو با نگه‌داشتن داده‌ها بازسازی می‌کنیم
    if "teacher_id" not in _column_names("learned_words"):
        c.executescript(
            """
            ALTER TABLE learned_words RENAME TO learned_words_old;
            CREATE TABLE learned_words (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                teacher_id INTEGER NOT NULL DEFAULT 0,
                code INTEGER NOT NULL,
                trigger_word TEXT NOT NULL,
                answers TEXT NOT NULL,
                UNIQUE(chat_id, teacher_id, code)
            );
            INSERT INTO learned_words (id, chat_id, teacher_id, code, trigger_word, answers)
                SELECT id, chat_id, 0, code, trigger_word, answers FROM learned_words_old;
            DROP TABLE learned_words_old;
            """
        )
        conn.commit()

    conn.close()


# ---- گروه‌های شناخته‌شده هر کاربر (برای اینکه بشه تو پیوی هم کلمه یاد داد) --
def record_user_group(user_id: int, chat_id: int, title: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO user_groups (user_id, chat_id, title) VALUES (?, ?, ?) "
        "ON CONFLICT(user_id, chat_id) DO UPDATE SET title=excluded.title",
        (user_id, chat_id, title),
    )
    conn.commit()
    conn.close()


def get_user_groups(user_id: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT chat_id, title FROM user_groups WHERE user_id=?", (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows


def get_settings(chat_id: int) -> sqlite3.Row:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM group_settings WHERE chat_id=?", (chat_id,))
    row = c.fetchone()
    if row is None:
        c.execute("INSERT INTO group_settings (chat_id) VALUES (?)", (chat_id,))
        conn.commit()
        c.execute("SELECT * FROM group_settings WHERE chat_id=?", (chat_id,))
        row = c.fetchone()
    conn.close()
    return row


async def get_group_owner_id(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    """
    آی‌دی مالک واقعی گروه رو برمی‌گردونه (کش‌شده تو دیتابیس). فقط لیست کلمات همین آدم
    تو گروه استفاده می‌شه، تا لیست هر ادمین دیگه‌ای خصوصیِ خودش بمونه.
    """
    s = get_settings(chat_id)
    if s["owner_user_id"]:
        return s["owner_user_id"]
    try:
        admins = await context.bot.get_chat_administrators(chat_id)
        for m in admins:
            if m.status == ChatMemberStatus.OWNER:
                conn = get_conn()
                c = conn.cursor()
                c.execute("UPDATE group_settings SET owner_user_id=? WHERE chat_id=?", (m.user.id, chat_id))
                conn.commit()
                conn.close()
                return m.user.id
    except Exception:
        pass
    return None


# ---- کلمات یاد گرفته شده (هر ادمین لیست خصوصیِ خودش رو داره) ---------------
def add_learned_word(chat_id: int, teacher_id: int, trigger_word: str, answer: str) -> int:
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "SELECT COALESCE(MAX(code), 0) + 1 FROM learned_words WHERE chat_id=? AND teacher_id=?",
        (chat_id, teacher_id),
    )
    new_code = c.fetchone()[0]
    c.execute(
        "INSERT INTO learned_words (chat_id, teacher_id, code, trigger_word, answers) VALUES (?, ?, ?, ?, ?)",
        (chat_id, teacher_id, new_code, trigger_word.strip(), json.dumps([answer.strip()], ensure_ascii=False)),
    )
    conn.commit()
    conn.close()
    return new_code


def list_learned_words(chat_id: int, teacher_id: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "SELECT * FROM learned_words WHERE chat_id=? AND teacher_id=? ORDER BY code",
        (chat_id, teacher_id),
    )
    rows = c.fetchall()
    conn.close()
    return rows


def get_learned_word(chat_id: int, teacher_id: int, code: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "SELECT * FROM learned_words WHERE chat_id=? AND teacher_id=? AND code=?",
        (chat_id, teacher_id, code),
    )
    row = c.fetchone()
    conn.close()
    return row


def set_word_answer(chat_id: int, teacher_id: int, code: int, new_answer: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "UPDATE learned_words SET answers=? WHERE chat_id=? AND teacher_id=? AND code=?",
        (json.dumps([new_answer.strip()], ensure_ascii=False), chat_id, teacher_id, code),
    )
    conn.commit()
    conn.close()


def add_extra_answer(chat_id: int, teacher_id: int, code: int, extra_answer: str):
    row = get_learned_word(chat_id, teacher_id, code)
    if row is None:
        return
    answers = json.loads(row["answers"])
    answers.append(extra_answer.strip())
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "UPDATE learned_words SET answers=? WHERE chat_id=? AND teacher_id=? AND code=?",
        (json.dumps(answers, ensure_ascii=False), chat_id, teacher_id, code),
    )
    conn.commit()
    conn.close()


def delete_learned_word(chat_id: int, teacher_id: int, code: int) -> bool:
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "DELETE FROM learned_words WHERE chat_id=? AND teacher_id=? AND code=?",
        (chat_id, teacher_id, code),
    )
    deleted = c.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def find_matching_word(chat_id: int, teacher_id: int, text: str):
    """
    اگه یکی از کلمات یاد گرفته شده‌ی همون معلم (مثلا مالک گروه) هرجایی داخل متن پیام باشه
    (نه فقط وقتی پیام دقیقاً همون کلمه باشه)، جواب رندوم برمی‌گردونه. اگه چندتا کلمه هم‌زمان
    تو پیام پیدا بشن، اونی که طولانی‌تره (دقیق‌تره) در اولویته.
    """
    text_norm = text.strip()
    if not text_norm:
        return None
    best_row = None
    best_len = -1
    for row in list_learned_words(chat_id, teacher_id):
        trig = row["trigger_word"].strip()
        if trig and trig in text_norm and len(trig) > best_len:
            best_row = row
            best_len = len(trig)
    if best_row:
        answers = json.loads(best_row["answers"])
        if answers:
            return random.choice(answers)
    return None


# ---- سوپرادمین (تو): تو هر گروهی که ربات عضوشه دسترسی کامل داره -------------
def is_super_admin(user_id: int) -> bool:
    return user_id in SUPER_ADMIN_IDS


# ---- مالک گروه (برای اینکه فقط ادمین‌ها بتونن لیست خصوصی کلمه بسازن) --------
async def is_user_owner(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int) -> bool:
    if is_super_admin(user_id):
        return True
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        return member.status == ChatMemberStatus.OWNER
    except Exception:
        return False


# ---- ادمین‌ها -------------------------------------------------------------
async def is_user_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, chat_id: int) -> bool:
    """ادمین یعنی: سوپرادمین ربات، ادمین/مالک واقعی گروه در تلگرام، یا کسی که دستی اضافه شده."""
    if is_super_admin(user_id):
        return True
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        if member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
            return True
    except Exception:
        pass

    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT 1 FROM admins WHERE chat_id=? AND user_id=?", (chat_id, user_id))
    row = c.fetchone()
    conn.close()
    return row is not None


def add_manual_admin(chat_id: int, user_id: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO admins (chat_id, user_id) VALUES (?, ?)", (chat_id, user_id))
    conn.commit()
    conn.close()


# ---- اخطارها ---------------------------------------------------------------
def add_warning(chat_id: int, user_id: int, reason: str) -> int:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT count, reasons FROM warnings WHERE chat_id=? AND user_id=?", (chat_id, user_id))
    row = c.fetchone()
    if row is None:
        count = 1
        reasons = [reason]
        c.execute(
            "INSERT INTO warnings (chat_id, user_id, count, reasons) VALUES (?, ?, ?, ?)",
            (chat_id, user_id, count, json.dumps(reasons, ensure_ascii=False)),
        )
    else:
        count = row["count"] + 1
        reasons = json.loads(row["reasons"])
        reasons.append(reason)
        c.execute(
            "UPDATE warnings SET count=?, reasons=? WHERE chat_id=? AND user_id=?",
            (count, json.dumps(reasons, ensure_ascii=False), chat_id, user_id),
        )
    conn.commit()
    conn.close()
    return count


def remove_all_warnings(chat_id: int, user_id: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM warnings WHERE chat_id=? AND user_id=?", (chat_id, user_id))
    conn.commit()
    conn.close()


def get_warning_reasons(chat_id: int, user_id: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT reasons FROM warnings WHERE chat_id=? AND user_id=?", (chat_id, user_id))
    row = c.fetchone()
    conn.close()
    if row is None:
        return []
    return json.loads(row["reasons"])


# ---- کلمات ممنوعه ----------------------------------------------------------
def add_forbidden_word(chat_id: int, word: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO forbidden_words (chat_id, word) VALUES (?, ?)", (chat_id, word.strip()))
    conn.commit()
    conn.close()


def remove_forbidden_word(chat_id: int, word: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM forbidden_words WHERE chat_id=? AND word=?", (chat_id, word.strip()))
    conn.commit()
    conn.close()


def list_forbidden_words(chat_id: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT word FROM forbidden_words WHERE chat_id=?", (chat_id,))
    rows = [r["word"] for r in c.fetchall()]
    conn.close()
    return rows


def contains_forbidden_word(chat_id: int, text: str):
    text_norm = (text or "").strip()
    if not text_norm:
        return None
    for w in list_forbidden_words(chat_id):
        if w and w in text_norm:
            return w
    return None


# ---- اعضای ویژه -------------------------------------------------------------
def add_special_member(chat_id: int, user_id: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO special_members (chat_id, user_id) VALUES (?, ?)", (chat_id, user_id))
    conn.commit()
    conn.close()


def list_special_members(chat_id: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT user_id, custom_tone FROM special_members WHERE chat_id=?", (chat_id,))
    rows = c.fetchall()
    conn.close()
    return rows


def is_special_member(chat_id: int, user_id: int) -> bool:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT 1 FROM special_members WHERE chat_id=? AND user_id=?", (chat_id, user_id))
    row = c.fetchone()
    conn.close()
    return row is not None


def set_special_tone(chat_id: int, user_id: int, tone_text: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "UPDATE special_members SET custom_tone=? WHERE chat_id=? AND user_id=?",
        (tone_text, chat_id, user_id),
    )
    conn.commit()
    conn.close()


# ---- ردیابی پیام‌ها (برای قابلیت حذف پیام‌ها) -------------------------------
def track_message(chat_id: int, message_id: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT OR IGNORE INTO tracked_messages (chat_id, message_id, created_at) VALUES (?, ?, ?)",
        (chat_id, message_id, datetime.utcnow().isoformat()),
    )
    conn.commit()
    # حفظ حجم دیتابیس: فقط آخرین MESSAGES_TO_KEEP پیام هر گروه نگه داشته می‌شه
    c.execute(
        """
        DELETE FROM tracked_messages
        WHERE chat_id=? AND message_id NOT IN (
            SELECT message_id FROM tracked_messages WHERE chat_id=?
            ORDER BY message_id DESC LIMIT ?
        )
        """,
        (chat_id, chat_id, MESSAGES_TO_KEEP),
    )
    conn.commit()
    conn.close()


def get_tracked_messages(chat_id: int, limit: int = None):
    conn = get_conn()
    c = conn.cursor()
    if limit:
        c.execute(
            "SELECT message_id FROM tracked_messages WHERE chat_id=? ORDER BY message_id DESC LIMIT ?",
            (chat_id, limit),
        )
    else:
        c.execute("SELECT message_id FROM tracked_messages WHERE chat_id=? ORDER BY message_id DESC", (chat_id,))
    rows = [r["message_id"] for r in c.fetchall()]
    conn.close()
    return rows


def clear_tracked_messages(chat_id: int, message_ids):
    conn = get_conn()
    c = conn.cursor()
    c.executemany(
        "DELETE FROM tracked_messages WHERE chat_id=? AND message_id=?",
        [(chat_id, mid) for mid in message_ids],
    )
    conn.commit()
    conn.close()


# ---- ارسال پیام + ردیابی خودکار (تا «حذف پیام‌ها» پیام‌های خودِ ربات رو هم پاک کنه) ---
async def send_tracked(bot, chat_id: int, text: str, **kwargs):
    sent = await bot.send_message(chat_id, text, **kwargs)
    track_message(chat_id, sent.message_id)
    return sent


async def reply_tracked(message, text: str, **kwargs):
    sent = await message.reply_text(text, **kwargs)
    track_message(message.chat_id, sent.message_id)
    return sent


# ---- اعضای شناخته‌شده‌ی هر گروه (برای تگ همگانی، یادآوری غیبت، و شناخت کاربر برگشتی) ----
def upsert_group_member(chat_id: int, user):
    if user is None or user.is_bot:
        return
    now = datetime.utcnow().isoformat()
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT first_seen FROM group_members WHERE chat_id=? AND user_id=?", (chat_id, user.id))
    row = c.fetchone()
    if row is None:
        c.execute(
            "INSERT INTO group_members (chat_id, user_id, first_name, username, updated_at, first_seen, is_present) "
            "VALUES (?, ?, ?, ?, ?, ?, 1)",
            (chat_id, user.id, user.first_name or "کاربر", user.username, now, now),
        )
    else:
        c.execute(
            "UPDATE group_members SET first_name=?, username=?, updated_at=?, is_present=1 "
            "WHERE chat_id=? AND user_id=?",
            (user.first_name or "کاربر", user.username, now, chat_id, user.id),
        )
    conn.commit()
    conn.close()


def get_group_members(chat_id: int):
    """فقط اعضایی که الان تو گروه حضور دارن (برای تگ همگانی و یادآوری غیبت)."""
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "SELECT user_id, first_name, username FROM group_members WHERE chat_id=? AND is_present=1", (chat_id,)
    )
    rows = c.fetchall()
    conn.close()
    return rows


def get_member_record(chat_id: int, user_id: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM group_members WHERE chat_id=? AND user_id=?", (chat_id, user_id))
    row = c.fetchone()
    conn.close()
    return row


def mark_member_left(chat_id: int, user_id: int):
    """به‌جای حذف کامل، فقط علامت می‌زنیم که رفته - تا اگه برگشت، بشناسیمش."""
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "UPDATE group_members SET is_present=0, updated_at=? WHERE chat_id=? AND user_id=?",
        (datetime.utcnow().isoformat(), chat_id, user_id),
    )
    conn.commit()
    conn.close()


def remove_group_member(chat_id: int, user_id: int):
    """حذف کامل از دیتابیس (برای پاک‌سازی دستی؛ رفتار عادی رفتن از گروه از mark_member_left استفاده می‌کنه)."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM group_members WHERE chat_id=? AND user_id=?", (chat_id, user_id))
    conn.commit()
    conn.close()


# ---- پک‌های دیالوگ (لحن‌ها) - از فایل‌هایی روی گیت‌هاب خونده می‌شن، نه هاردکد تو کد ربات -----
async def _fetch_url_text(url: str) -> str:
    def _blocking():
        with urllib.request.urlopen(url, timeout=15) as resp:
            return resp.read().decode("utf-8")
    return await asyncio.to_thread(_blocking)


async def get_pack(pack_name: str, force_refresh: bool = False) -> dict:
    """
    یه پک (لحن) رو از آدرس گیت‌هابش می‌خونه و کش می‌کنه. فایل باید یه فایل پایتونی باشه که
    یه دیکشنری (رشته -> لیست رشته) توش تعریف شده - اسم متغیر مهم نیست. با ast.literal_eval
    خونده می‌شه، یعنی هیچ کدی از اون فایل اجرا نمی‌شه (امن در برابر کد مخرب).
    """
    info = PACK_DEFINITIONS.get(pack_name)
    if not info:
        return {}
    url = os.environ.get(info["url_env"], "")
    if not url:
        return {}
    cache = _pack_cache.setdefault(pack_name, {"data": {}, "loaded_at": None})
    now = datetime.utcnow()
    if not force_refresh and cache["loaded_at"] is not None:
        if (now - cache["loaded_at"]).total_seconds() < DEFAULT_PACK_REFRESH_SECONDS:
            return cache["data"]
    try:
        text = await _fetch_url_text(url)
        tree = ast.parse(text, mode="exec")
        pack = None
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
                try:
                    candidate = ast.literal_eval(node.value)
                except Exception:
                    continue
                if isinstance(candidate, dict):
                    pack = candidate
                    break
        if not isinstance(pack, dict):
            raise ValueError("هیچ دیکشنری معتبری تو فایل پیدا نشد.")
        cache["data"] = pack
        cache["loaded_at"] = now
    except Exception as e:
        logger.warning(f"خطا در گرفتن پک «{pack_name}» از گیت‌هاب: {e}")
        # اگه قبلاً یه نسخه‌ی موفق کش شده باشه، همون برمی‌گرده؛ وگرنه دیکشنری خالی
    return cache["data"]


def find_best_match_across_packs(packs_data: list, text: str):
    """
    چندتا پک هم‌زمان فعال می‌تونن باشن؛ این تابع تو همه‌شون دنبال طولانی‌ترین (دقیق‌ترینِ) کلمه‌ای
    می‌گرده که تو متن پیام باشه. اگه چندتا پک هم‌زمان همون کلمه رو داشته باشن، یکی‌شون رندوم انتخاب می‌شه.
    """
    text_norm = text.strip()
    if not text_norm:
        return None
    best_len = -1
    candidates = []
    for pack in packs_data:
        if not pack:
            continue
        for trig, answers in pack.items():
            trig_s = trig.strip() if isinstance(trig, str) else ""
            if trig_s and trig_s in text_norm:
                if len(trig_s) > best_len:
                    best_len = len(trig_s)
                    candidates = [answers]
                elif len(trig_s) == best_len:
                    candidates.append(answers)
    if not candidates:
        return None
    chosen = random.choice(candidates)
    if chosen:
        return random.choice(chosen)
    return None


# ---- اعضای فعال (تنظیمات پک‌های فعال هر گروه) --------------------------------
def get_active_packs(chat_id: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT pack_name FROM active_packs WHERE chat_id=?", (chat_id,))
    rows = [r["pack_name"] for r in c.fetchall()]
    conn.close()
    return rows


def toggle_active_pack(chat_id: int, pack_name: str) -> bool:
    """پک رو روشن/خاموش می‌کنه و برمی‌گردونه که الان روشنه (True) یا خاموش (False)."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT 1 FROM active_packs WHERE chat_id=? AND pack_name=?", (chat_id, pack_name))
    exists = c.fetchone() is not None
    if exists:
        c.execute("DELETE FROM active_packs WHERE chat_id=? AND pack_name=?", (chat_id, pack_name))
    else:
        c.execute("INSERT INTO active_packs (chat_id, pack_name) VALUES (?, ?)", (chat_id, pack_name))
    conn.commit()
    conn.close()
    return not exists


# ---------------------------------------------------------------------------
# کیبوردها
# ---------------------------------------------------------------------------
def admin_menu_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔒 قفل کردن گروه", callback_data="adm_lock"),
             InlineKeyboardButton("🔓 باز کردن گروه", callback_data="adm_unlock")],
            [InlineKeyboardButton("🏷 دادن لقب به عضو", callback_data="adm_title")],
            [InlineKeyboardButton("⚠️ ثبت اخطار", callback_data="adm_warn_add"),
             InlineKeyboardButton("✅ حذف اخطار", callback_data="adm_warn_remove")],
            [InlineKeyboardButton("🚫 کلمات ممنوعه", callback_data="adm_forbidden")],
            [InlineKeyboardButton("🗑 حذف پیام‌ها", callback_data="adm_delete_msgs")],
            [InlineKeyboardButton("🌟 افراد ویژه", callback_data="adm_special")],
            [InlineKeyboardButton("⚙️ تنظیمات گروه", callback_data="adm_settings")],
            [InlineKeyboardButton("🗨 کلمه‌های آماده", callback_data="adm_ready_words")],
            [InlineKeyboardButton("👥 تعداد اعضا", callback_data="adm_member_count"),
             InlineKeyboardButton("🔗 لینک دعوت", callback_data="adm_invite_link")],
            [InlineKeyboardButton("❌ بستن پنل", callback_data="adm_close_panel")],
        ]
    )


def back_to_admin_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ بازگشت به پنل ادمین", callback_data="adm_back")]])


def main_menu_keyboard_for(bot_username: str):
    """کیبورد شیشه‌ای کامل - همچنان داخل گروه استفاده می‌شه، بدون تغییر."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ افزودن به گروه", url=f"https://t.me/{bot_username}?startgroup=true")],
            [InlineKeyboardButton("📚 یاد دادن کلمه", callback_data="learn_word")],
            [InlineKeyboardButton("📋 دیدن کلمات ساخته شده", callback_data="view_words")],
        ]
    )


def private_menu_keyboard(bot_username: str):
    """تو پیوی فقط دکمه افزودن به گروه نگه داشته می‌شه؛ بقیه از منوی ☰ خود ربات در دسترسه."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("➕ افزودن به گروه", url=f"https://t.me/{bot_username}?startgroup=true")]]
    )


# ---------------------------------------------------------------------------
# کمکی: پیدا کردن گروهی که باید کلمات روش ثبت/چک بشه
# ---------------------------------------------------------------------------
async def resolve_manage_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    اگه داخل گروه هستیم، همون گروه هدفه (رفتار قبلی، بدون تغییر).
    اگه تو پیویم، باید بفهمیم منظور کدوم گروهه:
      - اگه قبلا برای همین کاربر مشخص شده، همونو برمی‌گردونه.
      - اگه کاربر فقط تو یه گروه شناخته شده (پیام داده/ادمینه)، همونو خودکار انتخاب می‌کنه.
      - اگه صفر یا بیشتر از یکی بود، None برمی‌گردونه و extra اطلاعات لازم برای تصمیم‌گیری رو می‌ده.
    """
    chat = update.effective_chat
    if chat.type in ("group", "supergroup"):
        context.user_data["manage_chat_id"] = chat.id
        return chat.id, None

    if "manage_chat_id" in context.user_data:
        return context.user_data["manage_chat_id"], None

    groups = get_user_groups(update.effective_user.id)
    if not groups:
        return None, "no_groups"
    if len(groups) == 1:
        context.user_data["manage_chat_id"] = groups[0]["chat_id"]
        return groups[0]["chat_id"], None
    return None, groups


def active_chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """چت هدفی که باید کلمه توش ثبت/ویرایش بشه - برای گروه همون گروه، برای پیوی همونی که قبلا resolve شده."""
    chat = update.effective_chat
    if chat.type in ("group", "supergroup"):
        return chat.id
    return context.user_data.get("manage_chat_id", chat.id)


async def _reply(update: Update, text: str, reply_markup=None):
    """به روزرسانی/ارسال پیام، چه از طریق دکمه شیشه‌ای و چه از طریق دستور متنی."""
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup)


# ---------------------------------------------------------------------------
# دستور /start و منوی اصلی
# ---------------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    bot_username = (await context.bot.get_me()).username
    if chat.type in ("group", "supergroup"):
        record_user_group(update.effective_user.id, chat.id, chat.title)
        keyboard = main_menu_keyboard_for(bot_username)
        text = (
            "هی سلام! 👋 من ربات چتر هستم.\n"
            "از منوی زیر می‌تونی یکی از قابلیت‌ها رو انتخاب کنی:"
        )
    else:
        keyboard = private_menu_keyboard(bot_username)
        text = (
            "هی سلام! 👋 من ربات چتر هستم.\n"
            "می‌تونی منو به گروهت اضافه کنی تا یه خاطره‌ی خوش با هم داشته باشیم 🌸\n\n"
            "برای یاد دادن کلمه یا دیدن کلمات ساخته‌شده، از دکمه‌ی منو (☰) کنار پیام استفاده کن."
        )
    if update.message:
        await update.message.reply_text(text, reply_markup=keyboard)
    elif update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=keyboard)


async def back_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    bot_username = (await context.bot.get_me()).username
    chat = update.effective_chat
    if chat.type in ("group", "supergroup"):
        await query.edit_message_text(
            "منوی اصلی 🌸\nاز گزینه‌های زیر یکی رو انتخاب کن:",
            reply_markup=main_menu_keyboard_for(bot_username),
        )
    else:
        await query.edit_message_text(
            "منوی اصلی 🌸\nبرای یاد دادن کلمه یا دیدن کلمات، از دکمه‌ی منو (☰) استفاده کن.",
            reply_markup=private_menu_keyboard(bot_username),
        )


# ---------------------------------------------------------------------------
# قابلیت: یاد دادن کلمه (مکالمه ۲ مرحله‌ای) - هم با دکمه شیشه‌ای، هم با دستور /addword
# هر ادمین لیست خصوصیِ خودش رو می‌سازه؛ تو گروه فقط لیست خودِ مالک واقعی گروه اجرا می‌شه.
# ---------------------------------------------------------------------------
async def learn_word_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
    chat_id, extra = await resolve_manage_chat(update, context)
    if chat_id is None:
        if extra == "no_groups":
            await _reply(
                update,
                "اول باید ربات رو به یه گروه اضافه کنی و اونجا یه پیام (مثلا /start) بفرستی، "
                "بعد از همینجا می‌تونی براش کلمه یاد بدی.",
            )
        else:
            buttons = [
                [InlineKeyboardButton(g["title"] or str(g["chat_id"]), callback_data=f"selgrp_{g['chat_id']}_learn")]
                for g in extra
            ]
            await _reply(update, "برای کدوم گروه می‌خوای کلمه یاد بدی؟", InlineKeyboardMarkup(buttons))
        return ConversationHandler.END

    if not await is_user_admin(update, context, update.effective_user.id, chat_id):
        await _reply(update, "⛔ یاد دادن کلمه فقط برای ادمین‌های گروه ممکنه.")
        return ConversationHandler.END

    await _reply(
        update,
        "اون کلمه‌ای که می‌خوای وقتی مردم گفتن ربات جواب بده رو بفرست.\nمثلا: سلام\n\n"
        "توجه: این لیستِ خصوصیِ خودته. تو گروه فقط لیستِ مالکِ واقعیِ گروه اجرا می‌شه.",
    )
    return LEARN_WORD_WAIT_TRIGGER


async def learn_word_got_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_trigger"] = update.message.text
    await update.message.reply_text(
        f"باشه، حالا اون جوابی که می‌خوای من به «{update.message.text}» بدم رو بفرست."
    )
    return LEARN_WORD_WAIT_ANSWER


async def learn_word_got_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    trigger = context.user_data.pop("new_trigger", None)
    if not trigger:
        await update.message.reply_text("یه مشکلی پیش اومد، دوباره از منو شروع کن.")
        return ConversationHandler.END
    chat_id = active_chat_id(update, context)
    teacher_id = update.effective_user.id
    code = add_learned_word(chat_id, teacher_id, trigger, update.message.text)
    await update.message.reply_text(
        f"✅ ثبت شد (تو لیست خصوصی خودت)!\nکد: {code}\nکلمه: {trigger}\nجواب: {update.message.text}"
    )
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# قابلیت: دیدن کلمات ساخته شده - هم با دکمه شیشه‌ای، هم با دستور /mywords
# هر کسی فقط لیست خودش رو می‌بینه؛ لیست بقیه (حتی لیست مالک) براش قابل دیدن نیست.
# ---------------------------------------------------------------------------
def build_words_list_text(chat_id: int, teacher_id: int) -> str:
    rows = list_learned_words(chat_id, teacher_id)
    if not rows:
        return "هنوز هیچ کلمه‌ای تو لیست خصوصی تو یاد داده نشده."
    lines = ["لیست کلمات یاد گرفته شده‌ی تو:\n"]
    for r in rows:
        answers = json.loads(r["answers"])
        answer_display = answers[0] if len(answers) == 1 else " | ".join(answers)
        lines.append(f"کد: {r['code']}\nکلمه: {r['trigger_word']}\nجواب: {answer_display}\n")
    return "\n".join(lines)


def words_list_keyboard(chat_id: int, teacher_id: int):
    rows = list_learned_words(chat_id, teacher_id)
    buttons = []
    row_buf = []
    for r in rows:
        row_buf.append(InlineKeyboardButton(f"✏️ کد {r['code']}", callback_data=f"word_edit_{r['code']}"))
        if len(row_buf) == 3:
            buttons.append(row_buf)
            row_buf = []
    if row_buf:
        buttons.append(row_buf)
    buttons.append([InlineKeyboardButton("➕ اضافه کردن جدید", callback_data="learn_word")])
    if rows:
        buttons.append([InlineKeyboardButton("🗑 حذف یه کلمه", callback_data="worddel_start")])
    buttons.append([InlineKeyboardButton("⬅️ بازگشت", callback_data="back_main")])
    return InlineKeyboardMarkup(buttons)


async def view_words(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
    chat_id, extra = await resolve_manage_chat(update, context)
    if chat_id is None:
        if extra == "no_groups":
            await _reply(
                update,
                "اول باید ربات رو به یه گروه اضافه کنی و اونجا یه پیام (مثلا /start) بفرستی، "
                "بعد از همینجا می‌تونی کلمات خودت رو ببینی.",
            )
        else:
            buttons = [
                [InlineKeyboardButton(g["title"] or str(g["chat_id"]), callback_data=f"selgrp_{g['chat_id']}_view")]
                for g in extra
            ]
            await _reply(update, "کلمات کدوم گروه رو می‌خوای ببینی؟", InlineKeyboardMarkup(buttons))
        return
    teacher_id = update.effective_user.id
    await _reply(update, build_words_list_text(chat_id, teacher_id), words_list_keyboard(chat_id, teacher_id))


async def select_group_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """کاربر تو پیوی گروه هدف رو از لیست انتخاب کرده. callback_data شکل selgrp_<chat_id>_<action> است."""
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    chat_id = int(parts[1])
    action = parts[2]
    context.user_data["manage_chat_id"] = chat_id
    if action == "learn":
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("✅ ادامه: یاد دادن کلمه", callback_data="learn_word")]])
        await query.edit_message_text("گروه انتخاب شد. برای ادامه دکمه زیر رو بزن:", reply_markup=keyboard)
    else:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("✅ ادامه: دیدن کلمات", callback_data="view_words")]])
        await query.edit_message_text("گروه انتخاب شد. برای ادامه دکمه زیر رو بزن:", reply_markup=keyboard)


async def word_edit_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    code = int(query.data.split("_")[-1])
    context.user_data["edit_code"] = code
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔁 تغییر جواب", callback_data="wact_change")],
            [InlineKeyboardButton("➕ اضافه کردن جواب دیگر (رندوم)", callback_data="wact_add_extra")],
            [InlineKeyboardButton("⬅️ بازگشت", callback_data="view_words")],
        ]
    )
    await query.edit_message_text(f"حالتت رو انتخاب کن (کد {code}):", reply_markup=keyboard)


async def word_action_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = active_chat_id(update, context)
    if not await is_user_admin(update, context, update.effective_user.id, chat_id):
        await query.answer("⛔ ویرایش کلمه‌ها فقط برای ادمین‌ها ممکنه.", show_alert=True)
        return ConversationHandler.END
    await query.answer()
    context.user_data["edit_mode"] = "change"
    await query.edit_message_text("جواب جدید رو بفرست تا جایگزین جواب قبلی بشه.")
    return EDIT_WORD_WAIT_ANSWER


async def word_action_add_extra(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = active_chat_id(update, context)
    if not await is_user_admin(update, context, update.effective_user.id, chat_id):
        await query.answer("⛔ ویرایش کلمه‌ها فقط برای ادمین‌ها ممکنه.", show_alert=True)
        return ConversationHandler.END
    await query.answer()
    context.user_data["edit_mode"] = "extra"
    await query.edit_message_text(
        "جواب اضافه رو بفرست. از این به بعد ربات به صورت رندوم یکی از جواب‌ها رو انتخاب می‌کنه."
    )
    return EDIT_WORD_WAIT_ANSWER


async def word_edit_got_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = context.user_data.pop("edit_code", None)
    mode = context.user_data.pop("edit_mode", None)
    chat_id = active_chat_id(update, context)
    teacher_id = update.effective_user.id
    if code is None:
        await update.message.reply_text("یه مشکلی پیش اومد، دوباره امتحان کن.")
        return ConversationHandler.END
    if mode == "change":
        set_word_answer(chat_id, teacher_id, code, update.message.text)
        await update.message.reply_text(f"✅ جواب کد {code} عوض شد.")
    else:
        add_extra_answer(chat_id, teacher_id, code, update.message.text)
        await update.message.reply_text(f"✅ جواب جدید به کد {code} اضافه شد.")
    return ConversationHandler.END


# ---- حذف کامل یه کلمه با کد -------------------------------------------------
async def worddel_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = active_chat_id(update, context)
    if not await is_user_admin(update, context, update.effective_user.id, chat_id):
        await query.answer("⛔ حذف کلمه فقط برای ادمین‌ها ممکنه.", show_alert=True)
        return ConversationHandler.END
    await query.answer()
    await query.edit_message_text("کد کلمه‌ای که می‌خوای کامل حذف بشه رو بفرست.")
    return DELETE_WORD_WAIT_CODE


async def worddel_got_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        code = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("لطفا فقط عدد کدِ کلمه رو بفرست.")
        return DELETE_WORD_WAIT_CODE
    chat_id = active_chat_id(update, context)
    teacher_id = update.effective_user.id
    if delete_learned_word(chat_id, teacher_id, code):
        await update.message.reply_text(f"✅ کلمه با کد {code} کامل حذف شد.")
    else:
        await update.message.reply_text(f"کلمه‌ای با کد {code} تو لیست خودت پیدا نکردم.")
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# پنل ادمین: ورود
# ---------------------------------------------------------------------------
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("این دستور فقط داخل گروه کار می‌کنه.")
        return
    if not await is_user_admin(update, context, user.id, chat.id):
        await update.message.reply_text("⛔ این بخش فقط برای ادمین‌های گروه است.")
        return
    record_user_group(user.id, chat.id, chat.title)
    await get_group_owner_id(context, chat.id)  # کش مالک گروه رو تازه/آماده نگه می‌داره
    await update.message.reply_text("پنل مدیریت گروه 🛠", reply_markup=admin_menu_keyboard())


async def admin_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("پنل مدیریت گروه 🛠", reply_markup=admin_menu_keyboard())


async def adm_close_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _guard_admin_callback(update, context):
        return
    try:
        await update.callback_query.message.delete()
    except Exception:
        await update.callback_query.edit_message_text("پنل بسته شد. ✅")


async def _guard_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """چک می‌کنه که آیا کاربری که روی دکمه ادمین کلیک کرده واقعا ادمینه یا نه."""
    query = update.callback_query
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not await is_user_admin(update, context, user_id, chat_id):
        await query.answer("⛔ این گزینه برای شما نیست.", show_alert=True)
        return False
    await query.answer()
    return True


# ---- قفل / باز کردن گروه ----------------------------------------------------
async def adm_lock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _guard_admin_callback(update, context):
        return
    chat_id = update.effective_chat.id
    try:
        await context.bot.set_chat_permissions(
            chat_id, ChatPermissions(can_send_messages=False)
        )
        conn = get_conn()
        c = conn.cursor()
        c.execute(
            "INSERT INTO group_settings (chat_id, locked) VALUES (?, 1) "
            "ON CONFLICT(chat_id) DO UPDATE SET locked=1",
            (chat_id,),
        )
        conn.commit()
        conn.close()
        await update.callback_query.edit_message_text("🔒 گروه قفل شد.", reply_markup=back_to_admin_keyboard())
    except Exception as e:
        await update.callback_query.edit_message_text(
            f"خطا در قفل کردن گروه (باید ربات ادمین با دسترسی مدیریت گروه باشه): {e}",
            reply_markup=back_to_admin_keyboard(),
        )


async def adm_unlock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _guard_admin_callback(update, context):
        return
    chat_id = update.effective_chat.id
    try:
        await context.bot.set_chat_permissions(
            chat_id,
            ChatPermissions(
                can_send_messages=True,
                can_send_audios=True,
                can_send_documents=True,
                can_send_photos=True,
                can_send_videos=True,
                can_send_video_notes=True,
                can_send_voice_notes=True,
                can_send_polls=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
            ),
        )
        conn = get_conn()
        c = conn.cursor()
        c.execute(
            "INSERT INTO group_settings (chat_id, locked) VALUES (?, 0) "
            "ON CONFLICT(chat_id) DO UPDATE SET locked=0",
            (chat_id,),
        )
        conn.commit()
        conn.close()
        await update.callback_query.edit_message_text("🔓 گروه باز شد.", reply_markup=back_to_admin_keyboard())
    except Exception as e:
        await update.callback_query.edit_message_text(
            f"خطا در باز کردن گروه: {e}", reply_markup=back_to_admin_keyboard()
        )


# ---- دادن لقب به عضو --------------------------------------------------------
async def adm_title_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _guard_admin_callback(update, context):
        return ConversationHandler.END
    await update.callback_query.edit_message_text(
        "روی پیام همون عضو ریپلای کن و لقب مورد نظر رو به عنوان جواب بفرست.\n"
        "(باید روی یک پیام از عضو مورد نظر در گروه ریپلای کنی)"
    )
    return ADD_TITLE_WAIT_TEXT


async def adm_title_got_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("باید روی پیام همون عضو ریپلای کنی. دوباره امتحان کن.")
        return ADD_TITLE_WAIT_TEXT
    target = update.message.reply_to_message.from_user
    if target is None:
        await update.message.reply_text("نتونستم فرستنده‌ی این پیام رو شناسایی کنم.")
        return ConversationHandler.END
    chat_id = update.effective_chat.id
    title_text = update.message.text[:16]  # تلگرام حداکثر ۱۶ کاراکتر برای لقب اجازه می‌ده
    try:
        # تلگرام فقط به کسی که از قبل «ادمین» گروهه اجازه‌ی داشتن لقب می‌ده؛ اگه عضو عادیه،
        # اول با حداقل اختیار (فقط برای داشتن لقب، بدون هیچ دسترسی واقعی) ادمینش می‌کنیم.
        member = await context.bot.get_chat_member(chat_id, target.id)
        if member.status not in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
            await context.bot.promote_chat_member(
                chat_id,
                target.id,
                can_manage_chat=False,
                can_delete_messages=False,
                can_manage_video_chats=False,
                can_restrict_members=False,
                can_promote_members=False,
                can_change_info=False,
                can_invite_users=False,
                can_post_messages=False,
                can_edit_messages=False,
                can_pin_messages=False,
            )
        await context.bot.set_chat_administrator_custom_title(chat_id, target.id, title_text)
        await update.message.reply_text(f"✅ لقب «{title_text}» به {target.first_name} داده شد.")
    except Exception as e:
        await update.message.reply_text(
            f"نشد لقب رو ثبت کنم (باید ربات دسترسی 'افزودن ادمین جدید' داشته باشه): {e}"
        )
    return ConversationHandler.END


# ---- ثبت / حذف اخطار --------------------------------------------------------
async def perform_warn(context: ContextTypes.DEFAULT_TYPE, chat_id: int, target, reason: str, reply_target_message=None):
    """منطق مشترک ثبت اخطار: هم پنل ادمین (مکالمه‌ای) و هم دستور سریع «اخطار» از این استفاده می‌کنن."""
    count = add_warning(chat_id, target.id, reason)
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("👁 مشاهده پیام", callback_data=f"warnview_{target.id}")],
            [InlineKeyboardButton("✅ حذف اخطار", callback_data=f"warnremove_{target.id}")],
        ]
    )
    text = f"⚠️ {target.first_name} شما {count} اخطار از {MAX_WARNINGS} اخطار رو گرفتید.\nدلیل: {reason}"
    if reply_target_message is not None:
        await reply_tracked(reply_target_message, text, reply_markup=keyboard)
    else:
        await send_tracked(context.bot, chat_id, text, reply_markup=keyboard)
    if count >= MAX_WARNINGS:
        try:
            await context.bot.ban_chat_member(chat_id, target.id)
            await send_tracked(
                context.bot, chat_id, f"🚫 {target.first_name} به دلیل رسیدن به {MAX_WARNINGS} اخطار از گروه حذف شد."
            )
            remove_all_warnings(chat_id, target.id)
        except Exception as e:
            await send_tracked(context.bot, chat_id, f"نتونستم کاربر رو حذف کنم: {e}")


# ---- اخطار خودکار مشترک برای هر چیزی که تو گروه ممنوع اعلام شده (کلمه ممنوعه/رسانه/فوروارد/لینک) ----
async def warn_and_maybe_ban(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user, violation_text: str):
    count = add_warning(chat_id, user.id, violation_text)
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("👁 مشاهده پیام", callback_data=f"warnview_{user.id}")],
            [InlineKeyboardButton("✅ حذف اخطار", callback_data=f"warnremove_{user.id}")],
        ]
    )
    await send_tracked(
        context.bot,
        chat_id,
        f"{user.first_name} اینجا {violation_text} ممنوعه، این کارو نکن! ({count} اخطار از {MAX_WARNINGS})",
        reply_markup=keyboard,
    )
    if count >= MAX_WARNINGS:
        try:
            await context.bot.ban_chat_member(chat_id, user.id)
            await send_tracked(
                context.bot, chat_id, f"🚫 {user.first_name} به دلیل رسیدن به {MAX_WARNINGS} اخطار حذف شد."
            )
            remove_all_warnings(chat_id, user.id)
        except Exception:
            pass


URL_PATTERN = re.compile(r"(https?://|t\.me/|www\.)\S+", re.IGNORECASE)


async def adm_warn_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _guard_admin_callback(update, context):
        return ConversationHandler.END
    await update.callback_query.edit_message_text(
        "روی پیام عضو مورد نظر ریپلای کن و دلیل اخطار رو بنویس."
    )
    return WARN_WAIT_REASON


async def adm_warn_add_got_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("باید روی پیام همون عضو ریپلای کنی. دوباره امتحان کن.")
        return WARN_WAIT_REASON
    target = update.message.reply_to_message.from_user
    chat_id = update.effective_chat.id
    reason = update.message.text
    await perform_warn(context, chat_id, target, reason, reply_target_message=update.message)
    return ConversationHandler.END


async def adm_warn_remove_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _guard_admin_callback(update, context):
        return ConversationHandler.END
    await update.callback_query.edit_message_text(
        "روی پیام عضوی که می‌خوای اخطارش پاک بشه ریپلای کن و هر متنی بفرست."
    )
    return REMOVE_WARN_WAIT_USER


async def adm_warn_remove_got_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("باید روی پیام همون عضو ریپلای کنی. دوباره امتحان کن.")
        return REMOVE_WARN_WAIT_USER
    target = update.message.reply_to_message.from_user
    chat_id = update.effective_chat.id
    remove_all_warnings(chat_id, target.id)
    await update.message.reply_text(f"✅ اخطارهای {target.first_name} پاک شد.")
    return ConversationHandler.END


async def warn_view_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = int(query.data.split("_")[-1])
    chat_id = update.effective_chat.id
    reasons = get_warning_reasons(chat_id, user_id)
    if not reasons:
        await query.message.reply_text("اخطاری برای این کاربر ثبت نشده (یا قبلا پاک شده).")
        return
    text = "دلایل اخطار:\n" + "\n".join(f"- {r}" for r in reasons)
    await query.message.reply_text(text)


async def warn_remove_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not await is_user_admin(update, context, user_id, chat_id):
        await query.answer("⛔ حذف اخطار فقط برای ادمین‌هاست.", show_alert=True)
        return
    await query.answer()
    target_id = int(query.data.split("_")[-1])
    remove_all_warnings(chat_id, target_id)
    await query.message.reply_text("✅ اخطار این کاربر پاک شد.")


# ---- کلمات ممنوعه ------------------------------------------------------------
async def adm_forbidden_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _guard_admin_callback(update, context):
        return
    chat_id = update.effective_chat.id
    words = list_forbidden_words(chat_id)
    text = "کلمات ممنوعه فعلی:\n" + (", ".join(words) if words else "هیچ کلمه‌ای ثبت نشده")
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ اضافه کردن کلمه", callback_data="forb_add")],
            [InlineKeyboardButton("➖ حذف کلمه", callback_data="forb_remove")],
            [InlineKeyboardButton("⬅️ بازگشت", callback_data="adm_back")],
        ]
    )
    await update.callback_query.edit_message_text(text, reply_markup=keyboard)


async def forb_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _guard_admin_callback(update, context):
        return ConversationHandler.END
    await update.callback_query.edit_message_text("کلمه‌ای که می‌خوای ممنوع بشه رو بفرست.")
    return FORBIDDEN_ADD_WAIT_WORD


async def forb_add_got_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    add_forbidden_word(update.effective_chat.id, update.message.text)
    await update.message.reply_text(f"✅ «{update.message.text}» به لیست کلمات ممنوعه اضافه شد.")
    return ConversationHandler.END


async def forb_remove_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _guard_admin_callback(update, context):
        return ConversationHandler.END
    await update.callback_query.edit_message_text("کلمه‌ای که می‌خوای از لیست ممنوعه حذف بشه رو بفرست.")
    return FORBIDDEN_REMOVE_WAIT_WORD


async def forb_remove_got_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remove_forbidden_word(update.effective_chat.id, update.message.text)
    await update.message.reply_text(f"✅ «{update.message.text}» از لیست کلمات ممنوعه حذف شد.")
    return ConversationHandler.END


# ---- حذف پیام‌ها --------------------------------------------------------------
async def adm_delete_msgs_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _guard_admin_callback(update, context):
        return
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🗑 حذف کل پیام‌های ردیابی‌شده گروه", callback_data="del_all")],
            [InlineKeyboardButton("🔢 حذف با عدد دلخواه", callback_data="del_n")],
            [InlineKeyboardButton("⬅️ بازگشت", callback_data="adm_back")],
        ]
    )
    await update.callback_query.edit_message_text("از گزینه‌های زیر استفاده کن:", reply_markup=keyboard)


async def del_all_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _guard_admin_callback(update, context):
        return
    chat_id = update.effective_chat.id
    message_ids = get_tracked_messages(chat_id)
    deleted = 0
    for mid in message_ids:
        try:
            await context.bot.delete_message(chat_id, mid)
            deleted += 1
        except Exception:
            pass
    clear_tracked_messages(chat_id, message_ids)
    await update.callback_query.edit_message_text(
        f"✅ {deleted} پیام حذف شد (فقط پیام‌هایی که ربات از زمان اضافه شدنش دیده بود قابل حذف هستن).",
        reply_markup=back_to_admin_keyboard(),
    )


async def del_n_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _guard_admin_callback(update, context):
        return ConversationHandler.END
    await update.callback_query.edit_message_text("می‌خوای چند تا پیام پاک بشه؟ یه عدد بفرست.")
    return DELETE_N_WAIT_NUMBER


async def del_n_got_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        n = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("لطفا فقط یه عدد بفرست.")
        return DELETE_N_WAIT_NUMBER
    chat_id = update.effective_chat.id
    message_ids = get_tracked_messages(chat_id, limit=n)
    deleted = 0
    for mid in message_ids:
        try:
            await context.bot.delete_message(chat_id, mid)
            deleted += 1
        except Exception:
            pass
    clear_tracked_messages(chat_id, message_ids)
    await update.message.reply_text(f"✅ {deleted} پیام پاک شد.")
    return ConversationHandler.END


# ---- افراد ویژه ---------------------------------------------------------------
async def adm_special_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _guard_admin_callback(update, context):
        return
    chat_id = update.effective_chat.id
    members = list_special_members(chat_id)
    if not members:
        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("➕ می‌خوام کسی رو عضو ویژه کنم", callback_data="special_add")],
                [InlineKeyboardButton("⬅️ بازگشت", callback_data="adm_back")],
            ]
        )
        await update.callback_query.edit_message_text(
            "در حال حاضر عضو ویژه‌ای ثبت نشده.\nمی‌خوای کسی رو عضو ویژه کنی؟", reply_markup=keyboard
        )
        return
    lines = ["اعضای ویژه:"]
    for m in members:
        lines.append(f"- {m['user_id']}" + (f" (لحن: {m['custom_tone']})" if m["custom_tone"] else ""))
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ اضافه کردن عضو ویژه دیگر", callback_data="special_add")],
            [InlineKeyboardButton("⬅️ بازگشت", callback_data="adm_back")],
        ]
    )
    await update.callback_query.edit_message_text("\n".join(lines), reply_markup=keyboard)


async def special_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _guard_admin_callback(update, context):
        return ConversationHandler.END
    await update.callback_query.edit_message_text(
        "روی پیام عضوی که می‌خوای ویژه بشه ریپلای کن و هر متنی بفرست."
    )
    return SPECIAL_ADD_WAIT_USER


async def special_add_got_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("باید روی پیام همون عضو ریپلای کنی. دوباره امتحان کن.")
        return SPECIAL_ADD_WAIT_USER
    target = update.message.reply_to_message.from_user
    chat_id = update.effective_chat.id
    add_special_member(chat_id, target.id)
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🎨 لحن جدا براش درست کن", callback_data=f"special_tone_{target.id}")]]
    )
    await update.message.reply_text(
        f"✅ {target.first_name} عضو ویژه شد و از حذف پیام به‌خاطر کلمات ممنوعه معاف می‌شه.\n"
        "می‌خوای برای این فرد لحن جدا هم درست کنی؟",
        reply_markup=keyboard,
    )
    return ConversationHandler.END


async def special_tone_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await _guard_admin_callback(update, context):
        return ConversationHandler.END
    user_id = int(query.data.split("_")[-1])
    context.user_data["special_tone_user"] = user_id
    await query.edit_message_text("متن لحن مخصوص این عضو رو بفرست (این متن فقط برای یادداشت شماست).")
    return SPECIAL_TONE_WAIT_TEXT


async def special_tone_got_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = context.user_data.pop("special_tone_user", None)
    if user_id is None:
        await update.message.reply_text("مشکلی پیش اومد، دوباره امتحان کن.")
        return ConversationHandler.END
    set_special_tone(update.effective_chat.id, user_id, update.message.text)
    await update.message.reply_text("✅ لحن ثبت شد.")
    return ConversationHandler.END


# ---- تنظیمات گروه ---------------------------------------------------------------
def _toggle_col(s, col_name: str) -> str:
    return "✅ مجاز" if s[col_name] else "❌ ممنوع"


async def adm_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _guard_admin_callback(update, context):
        return
    chat_id = update.effective_chat.id
    s = get_settings(chat_id)
    link_status = "❌ ممنوع" if s["block_links"] else "✅ مجاز"
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(f"فوروارد پیام: {_toggle_col(s, 'forward_allowed')}", callback_data="set_toggle_forward")],
            [InlineKeyboardButton(f"عکس: {_toggle_col(s, 'allow_photo')}", callback_data="set_toggle_photo")],
            [InlineKeyboardButton(f"فیلم: {_toggle_col(s, 'allow_video')}", callback_data="set_toggle_video")],
            [InlineKeyboardButton(f"استیکر و گیف: {_toggle_col(s, 'allow_sticker_gif')}", callback_data="set_toggle_sticker")],
            [InlineKeyboardButton(f"لینک (اعضای عادی): {link_status}", callback_data="set_toggle_links")],
            [InlineKeyboardButton("🚨 اسپم", callback_data="set_spam_menu")],
            [InlineKeyboardButton("💌 یادآوری غیبت اعضا", callback_data="eng_menu")],
            [InlineKeyboardButton("⬅️ بازگشت", callback_data="adm_back")],
        ]
    )
    await update.callback_query.edit_message_text("تنظیمات گروه، هر مورد رو می‌تونی روشن/خاموش یا تنظیم کنی:", reply_markup=keyboard)


async def _toggle_setting_and_refresh(update, context, column: str):
    if not await _guard_admin_callback(update, context):
        return
    chat_id = update.effective_chat.id
    s = get_settings(chat_id)
    new_val = 0 if s[column] else 1
    conn = get_conn()
    c = conn.cursor()
    c.execute(f"UPDATE group_settings SET {column}=? WHERE chat_id=?", (new_val, chat_id))
    conn.commit()
    conn.close()
    await adm_settings_menu(update, context)


async def set_toggle_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _toggle_setting_and_refresh(update, context, "forward_allowed")


async def set_toggle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _toggle_setting_and_refresh(update, context, "allow_photo")


async def set_toggle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _toggle_setting_and_refresh(update, context, "allow_video")


async def set_toggle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _toggle_setting_and_refresh(update, context, "allow_sticker_gif")


async def set_toggle_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _toggle_setting_and_refresh(update, context, "block_links")


# ---- زیرمنوی اسپم: روشن/خاموش + تنظیمات (چند پیام پشت سرهم / چند دقیقه سکوت) ----
async def set_spam_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _guard_admin_callback(update, context):
        return
    chat_id = update.effective_chat.id
    s = get_settings(chat_id)
    status = "✅ روشن" if s["spam_protection"] else "❌ خاموش"
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(f"وضعیت: {status}", callback_data="set_toggle_spam")],
            [InlineKeyboardButton(
                f"⚙️ تنظیمات (فعلا: {s['spam_threshold']} پیام ← {s['spam_mute_minutes']} دقیقه سکوت)",
                callback_data="set_spam_config_start",
            )],
            [InlineKeyboardButton("⬅️ بازگشت", callback_data="adm_settings")],
        ]
    )
    await update.callback_query.edit_message_text("حالتت رو انتخاب کن:", reply_markup=keyboard)


async def set_toggle_spam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _guard_admin_callback(update, context):
        return
    chat_id = update.effective_chat.id
    s = get_settings(chat_id)
    new_val = 0 if s["spam_protection"] else 1
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE group_settings SET spam_protection=? WHERE chat_id=?", (new_val, chat_id))
    conn.commit()
    conn.close()
    await set_spam_menu(update, context)


async def set_spam_config_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _guard_admin_callback(update, context):
        return ConversationHandler.END
    await update.callback_query.edit_message_text(
        "چند تا پیام پشت سر هم از یه کاربر ارسال بشه تا براش سکوت بزنم؟ یه عدد بفرست."
    )
    return SPAM_CFG_WAIT_THRESHOLD


async def set_spam_config_got_threshold(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        n = int(update.message.text.strip())
        if n < 1:
            raise ValueError
    except ValueError:
        await update.message.reply_text("لطفا یه عدد صحیح بزرگ‌تر از صفر بفرست.")
        return SPAM_CFG_WAIT_THRESHOLD
    context.user_data["spam_cfg_threshold"] = n
    await update.message.reply_text(f"باشه. حالا چند دقیقه سکوت بدم؟ (حداکثر {MAX_SPAM_MUTE_MINUTES} دقیقه)")
    return SPAM_CFG_WAIT_MUTE


async def set_spam_config_got_mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        minutes = int(update.message.text.strip())
        if minutes < 1:
            raise ValueError
    except ValueError:
        await update.message.reply_text("لطفا یه عدد صحیح بزرگ‌تر از صفر بفرست.")
        return SPAM_CFG_WAIT_MUTE
    minutes = min(minutes, MAX_SPAM_MUTE_MINUTES)
    threshold = context.user_data.pop("spam_cfg_threshold", 5)
    chat_id = update.effective_chat.id
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "UPDATE group_settings SET spam_threshold=?, spam_mute_minutes=? WHERE chat_id=?",
        (threshold, minutes, chat_id),
    )
    conn.commit()
    conn.close()
    await update.message.reply_text(
        f"✅ تنظیم شد: بعد از {threshold} پیام پشت‌سرهم از یه کاربر، {minutes} دقیقه سکوت می‌شه."
    )
    return ConversationHandler.END


# ---- زیرمنوی یادآوری غیبت اعضا: هر چند ساعت یک‌بار یکی رو تصادفی تگ می‌کنه ----
async def eng_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _guard_admin_callback(update, context):
        return
    chat_id = update.effective_chat.id
    s = get_settings(chat_id)
    status = "✅ روشن" if s["engagement_enabled"] else "❌ خاموش"
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(f"وضعیت: {status}", callback_data="eng_toggle")],
            [InlineKeyboardButton(
                f"⚙️ فاصله زمانی (فعلا هر {s['engagement_interval_hours']} ساعت)", callback_data="eng_interval_start"
            )],
            [InlineKeyboardButton("⬅️ بازگشت", callback_data="adm_settings")],
        ]
    )
    await update.callback_query.edit_message_text(
        "هر چند وقت یک‌بار یه عضو رو تصادفی تگ می‌کنم و یه جمله‌ی باحال بهش می‌گم تا گروه رو زنده نگه داره:",
        reply_markup=keyboard,
    )


async def eng_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _guard_admin_callback(update, context):
        return
    chat_id = update.effective_chat.id
    s = get_settings(chat_id)
    new_val = 0 if s["engagement_enabled"] else 1
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE group_settings SET engagement_enabled=? WHERE chat_id=?", (new_val, chat_id))
    conn.commit()
    conn.close()
    await eng_menu(update, context)


async def eng_interval_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _guard_admin_callback(update, context):
        return ConversationHandler.END
    await update.callback_query.edit_message_text("هر چند ساعت یک‌بار این پیام‌ها رو بفرستم؟ یه عدد بفرست.")
    return ENGAGEMENT_WAIT_HOURS


async def eng_interval_got(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        hours = int(update.message.text.strip())
        if hours < 1:
            raise ValueError
    except ValueError:
        await update.message.reply_text("لطفا یه عدد صحیح بزرگ‌تر از صفر بفرست.")
        return ENGAGEMENT_WAIT_HOURS
    chat_id = update.effective_chat.id
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE group_settings SET engagement_interval_hours=? WHERE chat_id=?", (hours, chat_id))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"✅ تنظیم شد: هر {hours} ساعت یک‌بار.")
    return ConversationHandler.END


# ---- تعداد اعضا و لینک دعوت ------------------------------------------------------
async def adm_member_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _guard_admin_callback(update, context):
        return
    chat_id = update.effective_chat.id
    try:
        count = await context.bot.get_chat_member_count(chat_id)
        await update.callback_query.edit_message_text(
            f"👥 تعداد اعضای گروه: {count}", reply_markup=back_to_admin_keyboard()
        )
    except Exception as e:
        await update.callback_query.edit_message_text(f"نشد تعداد اعضا رو بگیرم: {e}", reply_markup=back_to_admin_keyboard())


async def adm_invite_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _guard_admin_callback(update, context):
        return
    chat_id = update.effective_chat.id
    try:
        link = await context.bot.export_chat_invite_link(chat_id)
        await update.callback_query.edit_message_text(
            f"🔗 لینک دعوت گروه:\n{link}", reply_markup=back_to_admin_keyboard()
        )
    except Exception as e:
        await update.callback_query.edit_message_text(
            f"نشد لینک دعوت رو بگیرم (باید ربات دسترسی 'دعوت با لینک' داشته باشه): {e}",
            reply_markup=back_to_admin_keyboard(),
        )


# ---- کلمه‌های آماده (چند لحن که هم‌زمان قابل فعال‌سازی‌ان، از گیت‌هاب خونده می‌شن) ------------
async def adm_ready_words_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _guard_admin_callback(update, context):
        return
    chat_id = update.effective_chat.id
    active = set(get_active_packs(chat_id))
    buttons = []
    for name, info in PACK_DEFINITIONS.items():
        configured = bool(os.environ.get(info["url_env"], ""))
        status = "✅" if name in active else "❌"
        note = "" if configured else " (تنظیم نشده)"
        buttons.append([InlineKeyboardButton(f"{status} {info['label']}{note}", callback_data=f"pack_toggle_{name}")])
    buttons.append([InlineKeyboardButton("🔄 بروزرسانی همه‌ی پک‌ها", callback_data="refresh_all_packs")])
    buttons.append([InlineKeyboardButton("⬅️ بازگشت", callback_data="adm_back")])
    await update.callback_query.edit_message_text(
        "لحن خود را انتخاب کن (می‌تونی چندتا رو هم‌زمان روشن کنی، مثلاً هم عصبانی هم ناراحت):",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def pack_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _guard_admin_callback(update, context):
        return
    chat_id = update.effective_chat.id
    pack_name = update.callback_query.data[len("pack_toggle_"):]
    info = PACK_DEFINITIONS.get(pack_name)
    if info is None:
        return
    if not os.environ.get(info["url_env"], ""):
        await update.callback_query.edit_message_text(
            f"لحن «{info['label']}» هنوز آماده نیست: اول باید آدرس فایلش رو تو متغیر {info['url_env']} تنظیم کنی.",
            reply_markup=back_to_admin_keyboard(),
        )
        return
    now_active = toggle_active_pack(chat_id, pack_name)
    if now_active:
        await get_pack(pack_name)  # کش رو گرم می‌کنیم
    await adm_ready_words_menu(update, context)


async def refresh_all_packs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _guard_admin_callback(update, context):
        return
    total_words = 0
    refreshed = 0
    for name, info in PACK_DEFINITIONS.items():
        if not os.environ.get(info["url_env"], ""):
            continue
        pack = await get_pack(name, force_refresh=True)
        total_words += len(pack)
        refreshed += 1
    await update.callback_query.edit_message_text(
        f"✅ {refreshed} تا لحن بروزرسانی شد (مجموعاً {total_words} کلمه).",
        reply_markup=back_to_admin_keyboard(),
    )


# ---------------------------------------------------------------------------
# هندلر عمومی پیام‌های گروه: چک کلمات ممنوعه، جواب کلمات یاد گرفته شده، ردیابی پیام، فوروارد
# ---------------------------------------------------------------------------
async def group_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if msg is None or msg.text is None:
        return
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        return
    chat_id = chat.id
    user = update.effective_user

    # این کاربر رو به عنوان کسی که تو این گروه فعاله ثبت می‌کنیم (برای اینکه بشه تو پیوی هم روی این گروه کار کرد)
    record_user_group(user.id, chat_id, chat.title)
    upsert_group_member(chat_id, user)  # برای قابلیت تگ همگانی

    # ردیابی آی‌دی پیام برای قابلیت حذف پیام‌ها
    track_message(chat_id, msg.message_id)

    text_stripped = msg.text.strip()

    # ---- دستورهای سریع بدون نیاز به ریپلای ----

    # لینک گروه - فقط مالک - "لینک"
    if text_stripped == "لینک" and await is_user_owner(context, chat_id, user.id):
        try:
            link = await context.bot.export_chat_invite_link(chat_id)
            await reply_tracked(msg, f"🔗 لینک گروه:\n{link}")
        except Exception as e:
            await reply_tracked(msg, f"نتونستم لینک رو بگیرم: {e}")
        return

    # تگ همگانی - فقط مالک، باید ریپلای روی یه پیام باشه - "تگ همگانی"
    if text_stripped == "تگ همگانی" and await is_user_owner(context, chat_id, user.id):
        if not msg.reply_to_message:
            await reply_tracked(msg, "برای تگ همگانی باید روی یه پیام ریپلای کنی.")
            return
        members = get_group_members(chat_id)
        if not members:
            await reply_tracked(
                msg,
                "هنوز هیچ عضوی رو نشناختم؛ اعضا باید حداقل یه پیام تو گروه بفرستن تا بشناسمشون.",
            )
            return
        target_message_id = msg.reply_to_message.message_id
        CHUNK = 8
        for i in range(0, len(members), CHUNK):
            chunk = members[i : i + CHUNK]
            mentions = " ".join(
                f'<a href="tg://user?id={m["user_id"]}">{html.escape(m["first_name"] or "کاربر")}</a>'
                for m in chunk
            )
            try:
                sent = await context.bot.send_message(
                    chat_id, mentions, parse_mode=ParseMode.HTML, reply_to_message_id=target_message_id
                )
                track_message(chat_id, sent.message_id)
            except Exception:
                pass
        return

    # ---- دستورهای سریع ادمین (فقط وقتی ریپلای روی پیام یه عضو باشه و فرستنده ادمین باشه) ----
    if msg.reply_to_message and await is_user_admin(update, context, user.id, chat_id):
        target = msg.reply_to_message.from_user
        if target is None:
            # پیام ریپلای‌شده از طرف یه ادمین ناشناس یا کانال بوده، نمی‌تونیم کاربر مشخصی رو هدف بگیریم
            if text_stripped in ("بن", "صیکتیر", "اخطار", "آزاد") or text_stripped.startswith("اخطار ") or text_stripped == "سکوت" or re.match(r"^سکوت\s+\d+$", text_stripped):
                await reply_tracked(msg, "نتونستم فرستنده‌ی این پیام رو شناسایی کنم (احتمالاً پیام از طرف ادمین ناشناس یا کانال بوده).")
                return
            target = None  # بذار بقیه‌ی دستورها (مثل پین/آنپین که نیازی به target ندارن) ادامه پیدا کنن

        # بن سریع - "بن" یا "صیکتیر"
        if target is not None and text_stripped in ("بن", "صیکتیر"):
            try:
                await context.bot.ban_chat_member(chat_id, target.id)
                await reply_tracked(msg, f"🚫 {target.first_name} از گروه حذف شد.")
            except Exception as e:
                await reply_tracked(msg, f"نتونستم حذفش کنم: {e}")
            return

        # اخطار سریع - "اخطار" یا "اخطار <دلیل>"
        if target is not None and (text_stripped == "اخطار" or text_stripped.startswith("اخطار ")):
            reason = text_stripped[len("اخطار "):].strip() if text_stripped.startswith("اخطار ") else "اخطار سریع"
            await perform_warn(context, chat_id, target, reason, reply_target_message=msg)
            return

        # سکوت سریع - "سکوت" (نامحدود) یا "سکوت <عدد به دقیقه>" (موقت)
        if target is not None and (text_stripped == "سکوت" or re.match(r"^سکوت\s+\d+$", text_stripped)):
            mute_match = re.match(r"^سکوت\s+(\d+)$", text_stripped)
            try:
                if mute_match:
                    minutes = int(mute_match.group(1))
                    until = int(datetime.utcnow().timestamp() + minutes * 60)
                    await context.bot.restrict_chat_member(
                        chat_id, target.id, permissions=ChatPermissions(can_send_messages=False), until_date=until
                    )
                    await reply_tracked(msg, f"🔇 {target.first_name} به مدت {minutes} دقیقه سکوت شد.")
                else:
                    # بدون عدد = سکوت نامحدود (تا وقتی خودمون با «آزاد» بازش کنیم)
                    await context.bot.restrict_chat_member(
                        chat_id, target.id, permissions=ChatPermissions(can_send_messages=False)
                    )
                    await reply_tracked(msg, f"🔇 {target.first_name} سکوت شد (تا وقتی که با «آزاد» درش بیاری).")
            except Exception as e:
                await reply_tracked(msg, f"نتونستم سکوتش کنم: {e}")
            return

        # آزاد کردن از سکوت - "آزاد"
        if target is not None and text_stripped == "آزاد":
            full_permissions = ChatPermissions(
                can_send_messages=True,
                can_send_audios=True,
                can_send_documents=True,
                can_send_photos=True,
                can_send_videos=True,
                can_send_video_notes=True,
                can_send_voice_notes=True,
                can_send_polls=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
                can_change_info=False,
                can_invite_users=True,
                can_pin_messages=False,
            )
            try:
                await context.bot.restrict_chat_member(chat_id, target.id, permissions=full_permissions)
                await reply_tracked(msg, f"🔊 {target.first_name} از سکوت در اومد.")
            except Exception:
                # اگه ست‌کردن همه‌ی مجوزها یه‌جا خطا داد (مثلا به‌خاطر تنظیمات خودِ گروه)، با کمترین
                # مجوز لازم (فقط اجازه‌ی ارسال پیام) دوباره امتحان می‌کنیم تا حداقل صداش دربیاد
                try:
                    await context.bot.restrict_chat_member(
                        chat_id, target.id, permissions=ChatPermissions(can_send_messages=True)
                    )
                    await reply_tracked(msg, f"🔊 {target.first_name} از سکوت در اومد.")
                except Exception as e2:
                    await reply_tracked(msg, f"نتونستم آزادش کنم: {e2}")
            return

        # پین سریع - "پین"
        if text_stripped == "پین":
            try:
                await context.bot.pin_chat_message(chat_id, msg.reply_to_message.message_id)
                await reply_tracked(msg, "📌 پیام پین شد.")
            except Exception as e:
                await reply_tracked(msg, f"نتونستم پینش کنم: {e}")
            return

        # آنپین سریع - "آنپین"
        if text_stripped == "آنپین":
            try:
                await context.bot.unpin_chat_message(chat_id, msg.reply_to_message.message_id)
                await reply_tracked(msg, "📌 پین پیام برداشته شد.")
            except Exception as e:
                await reply_tracked(msg, f"نتونستم آنپینش کنم: {e}")
            return

    # تنظیم فوروارد: اگه فوروارد ممنوع باشه و پیام فوروارد شده باشه، حذف + اخطار
    settings = get_settings(chat_id)
    is_admin_user = await is_user_admin(update, context, user.id, chat_id)
    is_special_user = is_special_member(chat_id, user.id)
    if msg.forward_origin is not None and not settings["forward_allowed"] and not is_admin_user and not is_special_user:
        try:
            await msg.delete()
        except Exception:
            pass
        await warn_and_maybe_ban(context, chat_id, user, "فوروارد پیام")
        return

    # لینک: اگه ارسال لینک ممنوع باشه، حذف + اخطار
    if settings["block_links"] and not is_admin_user and not is_special_user and URL_PATTERN.search(msg.text):
        try:
            await msg.delete()
        except Exception:
            pass
        await warn_and_maybe_ban(context, chat_id, user, "ارسال لینک")
        return

    # محافظت اسپم: اگه فعال باشه و کاربر (غیر ادمین/غیر ویژه) پشت سر هم پیام بده، سکوتش می‌کنیم
    if settings["spam_protection"] and not is_admin_user and not is_special_user:
        spam_key = f"spam_{chat_id}"
        state = context.chat_data.get(spam_key, {"user_id": None, "count": 0})
        if state["user_id"] == user.id:
            state["count"] += 1
        else:
            state = {"user_id": user.id, "count": 1}
        context.chat_data[spam_key] = state
        if state["count"] >= settings["spam_threshold"]:
            minutes = min(settings["spam_mute_minutes"], MAX_SPAM_MUTE_MINUTES)
            try:
                until = datetime.utcnow().timestamp() + minutes * 60
                await context.bot.restrict_chat_member(
                    chat_id, user.id, permissions=ChatPermissions(can_send_messages=False), until_date=int(until)
                )
                await send_tracked(
                    context.bot,
                    chat_id,
                    f"🔇 {user.first_name} به خاطر ارسال پشت‌سرهم پیام (اسپم)، {minutes} دقیقه سکوت شد.",
                )
            except Exception:
                pass
            context.chat_data[spam_key] = {"user_id": None, "count": 0}
            return

    # کلمات ممنوعه (اعضای ویژه معاف هستن)
    if not is_special_user:
        bad_word = contains_forbidden_word(chat_id, msg.text)
        if bad_word:
            try:
                await msg.delete()
            except Exception:
                pass
            await warn_and_maybe_ban(context, chat_id, user, f"استفاده از کلمه ممنوعه ({bad_word})")
            return

    # جواب به کلمات یاد گرفته شده - اول لیستِ مالکِ واقعیِ گروه، بعد واکنش به اسم ربات، بعد پک‌های فعال
    owner_id = await get_group_owner_id(context, chat_id)
    answer = None
    if owner_id:
        answer = find_matching_word(chat_id, owner_id, msg.text)
    if not answer and BOT_NAME in msg.text:
        answer = random.choice(BOT_NAME_REACTIONS)
    if not answer:
        active_pack_names = get_active_packs(chat_id)
        if active_pack_names:
            packs_data = [await get_pack(name) for name in active_pack_names]
            answer = find_best_match_across_packs(packs_data, msg.text)
    if answer:
        await reply_tracked(msg, answer)


async def group_member_update_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """با ورود/خروج اعضا (از روی پیام سرویس)، لیست اعضا رو به‌روز نگه می‌داره. (chat_member_status_handler
    روش اصلی و مطمئن‌تره؛ این فقط یه پشتیبان اضافیه.)"""
    msg = update.message
    if msg is None:
        return
    chat_id = update.effective_chat.id
    if msg.new_chat_members:
        for member in msg.new_chat_members:
            upsert_group_member(chat_id, member)
    if msg.left_chat_member:
        mark_member_left(chat_id, msg.left_chat_member.id)


async def chat_member_status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    هر تغییر وضعیت عضویت (جوین/لفت/بن/ارتقا) رو از طریق chat_member آپدیت می‌گیره - این روش
    مستقل از پیام‌های سرویسِ «فلان کاربر اضافه شد» کار می‌کنه، پس قابل‌اعتمادتره.
    اگه کسی که قبلاً می‌شناختیم (رفته بود) دوباره برگرده، یه پیام خوشامد می‌فرستیم.
    """
    cmu = update.chat_member
    if cmu is None:
        return
    chat_id = cmu.chat.id
    old_status = cmu.old_chat_member.status
    new_status = cmu.new_chat_member.status
    member_user = cmu.new_chat_member.user

    if new_status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED):
        mark_member_left(chat_id, member_user.id)
        return

    if new_status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR):
        prior = get_member_record(chat_id, member_user.id)
        was_gone = prior is not None and prior["is_present"] == 0
        upsert_group_member(chat_id, member_user)
        if was_gone and old_status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED) and not member_user.is_bot:
            try:
                phrase = random.choice(WELCOME_BACK_PHRASES)
                sent = await context.bot.send_message(chat_id, f"👋 {member_user.first_name} {phrase}")
                track_message(chat_id, sent.message_id)
            except Exception:
                pass


async def my_chat_member_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    وقتی ربات به یه گروه اضافه می‌شه، فوراً لیست ادمین‌های اون لحظه رو ثبت می‌کنه (بیشترین کاری
    که تلگرام به یه ربات اجازه می‌ده - گرفتن لیست کامل اعضای عادی از قبل، از طریق Bot API ممکن نیست).
    """
    cmu = update.my_chat_member
    if cmu is None:
        return
    chat = cmu.chat
    if chat.type not in ("group", "supergroup"):
        return
    new_status = cmu.new_chat_member.status
    if new_status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR):
        try:
            admins = await context.bot.get_chat_administrators(chat.id)
            for m in admins:
                upsert_group_member(chat.id, m.user)
        except Exception:
            pass


async def group_catch_all_tracker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    از لحظه‌ای که ربات تو گروهه، هر پیامی (از هر نوعی - سند/صدا/لوکیشن/نظرسنجی/...، از هر کسی
    حتی ادمین‌ها و ربات‌های دیگه) رو برای قابلیت «حذف پیام‌ها» ردیابی می‌کنه. توجه: تلگرام به هیچ
    رباتی اجازه دسترسی به پیام‌های قبل از اضافه شدنش رو نمی‌ده؛ این فقط از همین لحظه به بعد کار می‌کنه.
    """
    msg = update.message
    if msg is None:
        return
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        return
    track_message(chat.id, msg.message_id)


async def engagement_job(context: ContextTypes.DEFAULT_TYPE):
    """هر بار که اجرا می‌شه، برای گروه‌هایی که این قابلیت روشنه و زمانش رسیده، یه عضو تصادفی رو تگ می‌کنه."""
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "SELECT chat_id, engagement_interval_hours, last_engagement_at FROM group_settings WHERE engagement_enabled=1"
    )
    rows = c.fetchall()
    conn.close()

    now = datetime.utcnow()
    for row in rows:
        chat_id = row["chat_id"]
        interval_hours = row["engagement_interval_hours"] or 6
        last_at = row["last_engagement_at"]
        due = True
        if last_at:
            try:
                due = (now - datetime.fromisoformat(last_at)).total_seconds() >= interval_hours * 3600
            except Exception:
                due = True
        if not due:
            continue

        members = get_group_members(chat_id)
        if not members:
            continue
        member = random.choice(members)
        phrase = random.choice(ENGAGEMENT_PHRASES)
        mention = f'<a href="tg://user?id={member["user_id"]}">{html.escape(member["first_name"] or "کاربر")}</a>'
        try:
            sent = await context.bot.send_message(chat_id, f"{mention} {phrase}", parse_mode=ParseMode.HTML)
            track_message(chat_id, sent.message_id)
        except Exception:
            continue

        conn2 = get_conn()
        c2 = conn2.cursor()
        c2.execute("UPDATE group_settings SET last_engagement_at=? WHERE chat_id=?", (now.isoformat(), chat_id))
        conn2.commit()
        conn2.close()


async def group_media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """چک می‌کنه که آیا عکس/فیلم/استیکر/گیف تو این گروه مجازه یا نه (تنظیمات گروه)."""
    msg = update.message
    if msg is None:
        return
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        return
    chat_id = chat.id
    user = update.effective_user
    upsert_group_member(chat_id, user)  # برای قابلیت تگ همگانی
    settings = get_settings(chat_id)
    is_admin_user = await is_user_admin(update, context, user.id, chat_id)
    is_special_user = is_special_member(chat_id, user.id)
    exempt = is_admin_user or is_special_user

    blocked_reason = None
    if msg.photo and not settings["allow_photo"] and not exempt:
        blocked_reason = "ارسال عکس"
    elif msg.video and not settings["allow_video"] and not exempt:
        blocked_reason = "ارسال فیلم"
    elif (msg.sticker or msg.animation) and not settings["allow_sticker_gif"] and not exempt:
        blocked_reason = "ارسال استیکر/گیف"

    if blocked_reason:
        try:
            await msg.delete()
        except Exception:
            pass
        await warn_and_maybe_ban(context, chat_id, user, blocked_reason)
        return

    track_message(chat_id, msg.message_id)


async def non_admin_click_guard_no_op(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """برای دکمه‌هایی که فقط پیام اطلاع رسانی می‌دن (مثل زمانی که کاربر عادی روی دکمه ادمین بزنه)."""
    query = update.callback_query
    await query.answer("این گزینه فقط برای مدیر گروه است.", show_alert=True)


async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("لغو شد.")
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# راه‌اندازی برنامه و ثبت هندلرها
# ---------------------------------------------------------------------------
def build_application() -> Application:
    app = Application.builder().token(BOT_TOKEN).build()

    # /start
    app.add_handler(CommandHandler("start", start))
    # /admin - ورود به پنل ادمین داخل گروه
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("cancel", cancel_conversation))

    # مکالمه: یاد دادن کلمه جدید (هم از دکمه شیشه‌ای، هم از دستور /addword که تو منوی ☰ ربات هست)
    learn_word_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(learn_word_start, pattern="^learn_word$"),
            CommandHandler("addword", learn_word_start),
        ],
        states={
            LEARN_WORD_WAIT_TRIGGER: [MessageHandler(filters.TEXT & ~filters.COMMAND, learn_word_got_trigger)],
            LEARN_WORD_WAIT_ANSWER: [MessageHandler(filters.TEXT & ~filters.COMMAND, learn_word_got_answer)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation)],
        per_message=False,
    )
    app.add_handler(learn_word_conv)
    # /mywords - معادل دکمه «دیدن کلمات ساخته شده»، از منوی ☰ ربات در پیوی در دسترسه
    app.add_handler(CommandHandler("mywords", view_words))
    # انتخاب گروه هدف وقتی کاربر تو پیوی چند گروه داره
    app.add_handler(CallbackQueryHandler(select_group_callback, pattern="^selgrp_"))

    # مکالمه: ویرایش کلمه (تغییر جواب / اضافه کردن جواب رندوم)
    edit_word_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(word_action_change, pattern="^wact_change$"),
            CallbackQueryHandler(word_action_add_extra, pattern="^wact_add_extra$"),
        ],
        states={
            EDIT_WORD_WAIT_ANSWER: [MessageHandler(filters.TEXT & ~filters.COMMAND, word_edit_got_answer)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation)],
        per_message=False,
    )
    app.add_handler(edit_word_conv)

    # کالبک‌های مربوط به دیدن/ویرایش کلمات و منوی اصلی
    app.add_handler(CallbackQueryHandler(view_words, pattern="^view_words$"))
    app.add_handler(CallbackQueryHandler(word_edit_menu, pattern="^word_edit_\\d+$"))
    app.add_handler(CallbackQueryHandler(back_to_main_menu, pattern="^back_main$"))

    # مکالمه: حذف کامل یه کلمه با کد
    app.add_handler(
        ConversationHandler(
            entry_points=[CallbackQueryHandler(worddel_start, pattern="^worddel_start$")],
            states={DELETE_WORD_WAIT_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, worddel_got_code)]},
            fallbacks=[CommandHandler("cancel", cancel_conversation)],
            per_message=False,
        )
    )

    # پنل ادمین: منوی اصلی و بازگشت
    app.add_handler(CallbackQueryHandler(admin_back, pattern="^adm_back$"))
    app.add_handler(CallbackQueryHandler(adm_lock, pattern="^adm_lock$"))
    app.add_handler(CallbackQueryHandler(adm_unlock, pattern="^adm_unlock$"))
    app.add_handler(CallbackQueryHandler(adm_forbidden_menu, pattern="^adm_forbidden$"))
    app.add_handler(CallbackQueryHandler(adm_delete_msgs_menu, pattern="^adm_delete_msgs$"))
    app.add_handler(CallbackQueryHandler(adm_special_menu, pattern="^adm_special$"))
    app.add_handler(CallbackQueryHandler(adm_settings_menu, pattern="^adm_settings$"))
    app.add_handler(CallbackQueryHandler(adm_member_count, pattern="^adm_member_count$"))
    app.add_handler(CallbackQueryHandler(adm_invite_link, pattern="^adm_invite_link$"))
    app.add_handler(CallbackQueryHandler(adm_ready_words_menu, pattern="^adm_ready_words$"))
    app.add_handler(CallbackQueryHandler(pack_toggle_callback, pattern="^pack_toggle_\\w+$"))
    app.add_handler(CallbackQueryHandler(refresh_all_packs, pattern="^refresh_all_packs$"))
    app.add_handler(CallbackQueryHandler(set_toggle_forward, pattern="^set_toggle_forward$"))
    app.add_handler(CallbackQueryHandler(set_toggle_photo, pattern="^set_toggle_photo$"))
    app.add_handler(CallbackQueryHandler(set_toggle_video, pattern="^set_toggle_video$"))
    app.add_handler(CallbackQueryHandler(set_toggle_sticker, pattern="^set_toggle_sticker$"))
    app.add_handler(CallbackQueryHandler(set_toggle_links, pattern="^set_toggle_links$"))
    app.add_handler(CallbackQueryHandler(set_spam_menu, pattern="^set_spam_menu$"))
    app.add_handler(CallbackQueryHandler(set_toggle_spam, pattern="^set_toggle_spam$"))
    app.add_handler(CallbackQueryHandler(eng_menu, pattern="^eng_menu$"))
    app.add_handler(CallbackQueryHandler(eng_toggle, pattern="^eng_toggle$"))
    app.add_handler(CallbackQueryHandler(adm_close_panel, pattern="^adm_close_panel$"))
    app.add_handler(CallbackQueryHandler(del_all_callback, pattern="^del_all$"))
    app.add_handler(CallbackQueryHandler(warn_view_callback, pattern="^warnview_\\d+$"))
    app.add_handler(CallbackQueryHandler(warn_remove_callback, pattern="^warnremove_\\d+$"))

    # مکالمه: تنظیمات یادآوری غیبت اعضا (فاصله زمانی به ساعت)
    app.add_handler(
        ConversationHandler(
            entry_points=[CallbackQueryHandler(eng_interval_start, pattern="^eng_interval_start$")],
            states={ENGAGEMENT_WAIT_HOURS: [MessageHandler(filters.TEXT & ~filters.COMMAND, eng_interval_got)]},
            fallbacks=[CommandHandler("cancel", cancel_conversation)],
            per_message=False,
        )
    )

    # مکالمه: تنظیمات اسپم (چند پیام پشت سرهم / چند دقیقه سکوت)
    app.add_handler(
        ConversationHandler(
            entry_points=[CallbackQueryHandler(set_spam_config_start, pattern="^set_spam_config_start$")],
            states={
                SPAM_CFG_WAIT_THRESHOLD: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_spam_config_got_threshold)],
                SPAM_CFG_WAIT_MUTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_spam_config_got_mute)],
            },
            fallbacks=[CommandHandler("cancel", cancel_conversation)],
            per_message=False,
        )
    )

    # مکالمه: دادن لقب
    app.add_handler(
        ConversationHandler(
            entry_points=[CallbackQueryHandler(adm_title_start, pattern="^adm_title$")],
            states={ADD_TITLE_WAIT_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_title_got_text)]},
            fallbacks=[CommandHandler("cancel", cancel_conversation)],
            per_message=False,
        )
    )

    # مکالمه: ثبت اخطار
    app.add_handler(
        ConversationHandler(
            entry_points=[CallbackQueryHandler(adm_warn_add_start, pattern="^adm_warn_add$")],
            states={WARN_WAIT_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_warn_add_got_reason)]},
            fallbacks=[CommandHandler("cancel", cancel_conversation)],
            per_message=False,
        )
    )

    # مکالمه: حذف اخطار (از منوی ادمین)
    app.add_handler(
        ConversationHandler(
            entry_points=[CallbackQueryHandler(adm_warn_remove_start, pattern="^adm_warn_remove$")],
            states={REMOVE_WARN_WAIT_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_warn_remove_got_user)]},
            fallbacks=[CommandHandler("cancel", cancel_conversation)],
            per_message=False,
        )
    )

    # مکالمه: اضافه کردن کلمه ممنوعه
    app.add_handler(
        ConversationHandler(
            entry_points=[CallbackQueryHandler(forb_add_start, pattern="^forb_add$")],
            states={FORBIDDEN_ADD_WAIT_WORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, forb_add_got_word)]},
            fallbacks=[CommandHandler("cancel", cancel_conversation)],
            per_message=False,
        )
    )

    # مکالمه: حذف کلمه ممنوعه
    app.add_handler(
        ConversationHandler(
            entry_points=[CallbackQueryHandler(forb_remove_start, pattern="^forb_remove$")],
            states={FORBIDDEN_REMOVE_WAIT_WORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, forb_remove_got_word)]},
            fallbacks=[CommandHandler("cancel", cancel_conversation)],
            per_message=False,
        )
    )

    # مکالمه: حذف N پیام
    app.add_handler(
        ConversationHandler(
            entry_points=[CallbackQueryHandler(del_n_start, pattern="^del_n$")],
            states={DELETE_N_WAIT_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, del_n_got_number)]},
            fallbacks=[CommandHandler("cancel", cancel_conversation)],
            per_message=False,
        )
    )

    # مکالمه: اضافه کردن عضو ویژه + لحن مخصوص
    app.add_handler(
        ConversationHandler(
            entry_points=[CallbackQueryHandler(special_add_start, pattern="^special_add$")],
            states={SPECIAL_ADD_WAIT_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, special_add_got_user)]},
            fallbacks=[CommandHandler("cancel", cancel_conversation)],
            per_message=False,
        )
    )
    app.add_handler(
        ConversationHandler(
            entry_points=[CallbackQueryHandler(special_tone_start, pattern="^special_tone_\\d+$")],
            states={SPECIAL_TONE_WAIT_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, special_tone_got_text)]},
            fallbacks=[CommandHandler("cancel", cancel_conversation)],
            per_message=False,
        )
    )

    # هندلر عمومی پیام‌های متنی گروه (باید بعد از همه ConversationHandler ها ثبت بشه)
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS & ~filters.COMMAND, group_message_handler))

    # هندلر رسانه‌های گروه: عکس/فیلم/استیکر/گیف (طبق تنظیمات گروه مجاز یا حذف می‌شن)
    app.add_handler(
        MessageHandler(
            (filters.PHOTO | filters.VIDEO | filters.Sticker.ALL | filters.ANIMATION) & filters.ChatType.GROUPS,
            group_media_handler,
        )
    )

    # هندلر ورود/خروج اعضا (برای به‌روز نگه‌داشتن لیستِ تگ همگانی)
    app.add_handler(
        MessageHandler(
            (filters.StatusUpdate.NEW_CHAT_MEMBERS | filters.StatusUpdate.LEFT_CHAT_MEMBER) & filters.ChatType.GROUPS,
            group_member_update_handler,
        )
    )

    # هندلر chat_member (روش مطمئن‌تر برای ردیابی جوین/لفت/بن اعضا - برای تگ همگانی)
    app.add_handler(ChatMemberHandler(chat_member_status_handler, ChatMemberHandler.CHAT_MEMBER))

    # هندلر my_chat_member (وقتی ربات به یه گروه اضافه می‌شه، فوراً ادمین‌های اون گروه رو ثبت می‌کنه)
    app.add_handler(ChatMemberHandler(my_chat_member_handler, ChatMemberHandler.MY_CHAT_MEMBER))

    # ردیاب عمومی: هر نوع پیامی تو گروه (سند/صدا/لوکیشن/نظرسنجی/...) رو برای «حذف پیام‌ها» ثبت می‌کنه.
    # تو گروه جدا (group=1) ثبت شده تا مستقل از هندلرهای بالا (که ممکنه پیام رو حذف کرده باشن) اجرا بشه.
    app.add_handler(MessageHandler(filters.ChatType.GROUPS, group_catch_all_tracker), group=1)

    app.post_init = setup_bot_menu
    return app


async def setup_bot_menu(app: Application):
    """به جای دکمه‌های شیشه‌ای، تو پیوی از منوی رسمی (☰) خود ربات استفاده می‌کنیم."""
    await app.bot.set_my_commands(
        [
            BotCommand("start", "شروع / منوی اصلی"),
            BotCommand("addword", "یاد دادن کلمه جدید"),
            BotCommand("mywords", "دیدن کلمات ساخته شده"),
            BotCommand("admin", "پنل مدیریت گروه (فقط داخل گروه)"),
            BotCommand("cancel", "لغو عملیات جاری"),
        ]
    )
    await app.bot.set_chat_menu_button(menu_button=MenuButtonCommands())


def main():
    if BOT_TOKEN == "PUT-YOUR-TOKEN-HERE":
        print("⚠️  لطفا اول توکن ربات رو در متغیر BOT_TOKEN یا متغیر محیطی BOT_TOKEN قرار بده.")
        return
    init_db()
    app = build_application()
    if app.job_queue is not None:
        # هر ۳۰ دقیقه چک می‌کنه ببینه کدوم گروه‌ها وقتِ «یادآوری غیبت اعضا»شونه
        app.job_queue.run_repeating(engagement_job, interval=1800, first=60)
    else:
        logger.warning(
            "JobQueue فعال نیست؛ برای قابلیت «یادآوری غیبت اعضا» این پکیج رو نصب کن: "
            "pip install \"python-telegram-bot[job-queue]==20.7\""
        )
    logger.info("ربات چتر در حال اجراست...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
