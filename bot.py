import os
import random
import re
import sqlite3
import time
import json
import telebot
from telebot import types
from telebot.types import ChatPermissions

# ================= ================= =================
# تنظیمات اولیه ربات و متغیرهای محیطی Railway
# ================= ================= =================
TOKEN = os.environ.get("BOT_TOKEN", "8793539029:AAFv2XHBLW695nET_eCqu3Bj42jxdAJYc74")
BOT_USERNAME = os.environ.get("BOT_USERNAME", "GapYar128_bot")

# آیدی عددی مالکان اصلی ربات (سودو ادمین‌ها)
sudo_raw = os.environ.get("SUDO_ADMINS", "7430881772,8632617239")
SUDO_ADMINS = [
    int(x.strip()) for x in sudo_raw.split(",") if x.strip().isdigit()
]

bot = telebot.TeleBot(TOKEN)
user_states = {}  # مدیریت وضعیت ورودی‌های کاربران

# ================= ================= =================
# مجوزهای سکوت و لغو سکوت (Mute / Unmute)
# ================= ================= =================
MUTE_PERMISSIONS = ChatPermissions(
    can_send_messages=False,
    can_send_media_messages=False,
    can_send_other_messages=False,
    can_add_web_page_previews=False,
)

UNMUTE_PERMISSIONS = ChatPermissions(
    can_send_messages=True,
    can_send_media_messages=True,
    can_send_other_messages=True,
    can_add_web_page_previews=True,
    can_send_polls=True,
    can_invite_users=True,
)


# ================= ================= =================
# مدیریت دیتابیس SQLite (ذخیره جامع داده‌ها)
# ================= ================= =================
def init_db():
    conn = sqlite3.connect("chatar_bot.db")
    cursor = conn.cursor()

    # جدول کلمات یاد گرفته شده
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS learned_words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            word TEXT,
            response TEXT
        )
    """)

    # جدول اخطارهای کاربران در گروه‌ها
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS warnings (
            chat_id INTEGER,
            user_id INTEGER,
            count INTEGER,
            PRIMARY KEY (chat_id, user_id)
        )
    """)

    # جدول سطوح مجازات (استریک)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS strikes (
            chat_id INTEGER,
            user_id INTEGER,
            count INTEGER DEFAULT 0,
            PRIMARY KEY (chat_id, user_id)
        )
    """)

    # جدول کلمات ممنوعه گروه‌ها
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS banned_words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            word TEXT
        )
    """)

    # جدول اعضای ویژه (VIP)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS vip_users (
            chat_id INTEGER,
            user_id INTEGER,
            PRIMARY KEY (chat_id, user_id)
        )
    """)

    # جدول تنظیمات پیشرفته گروه‌ها
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS group_settings (
            chat_id INTEGER PRIMARY KEY,
            anti_forward INTEGER DEFAULT 0,
            anti_link INTEGER DEFAULT 0,
            anti_spam INTEGER DEFAULT 0,
            anti_bot INTEGER DEFAULT 0,
            default_dialog INTEGER DEFAULT 0
        )
    """)

    # جدول القاب اعضا
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_titles (
            chat_id INTEGER,
            user_id INTEGER,
            title TEXT,
            PRIMARY KEY (chat_id, user_id)
        )
    """)

    # جدول دیالوگ‌های پیش‌فرض / پک دیالوگ عمومی
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS default_dialogs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT,
            response TEXT
        )
    """)

    # اضافه کردن ستون default_dialog در صورت ارتقای دیتابیس‌های قدیمی
    try:
        cursor.execute("ALTER TABLE group_settings ADD COLUMN default_dialog INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    conn.commit()
    conn.close()


init_db()


def db_query(query, params=(), fetchone=False, fetchall=False, commit=False):
    conn = sqlite3.connect("chatar_bot.db")
    cursor = conn.cursor()
    cursor.execute(query, params)
    data = None
    if fetchone:
        data = cursor.fetchone()
    elif fetchall:
        data = cursor.fetchall()
    if commit:
        conn.commit()
    conn.close()
    return data


# ================= ================= =================
# توابع کمکی و مجازات پلکانی
# ================= ================= =================
def convert_fa_numbers(text: str) -> str:
    """تبدیل اعداد فارسی و عربی به انگلیسی"""
    fa_digits = "۰۱۲۳۴۵۶۷۸۹"
    ar_digits = "٠١٢٣٤٥٦٧٨٩"
    en_digits = "0123456789"
    for f, a, e in zip(fa_digits, ar_digits, en_digits):
        text = text.replace(f, e).replace(a, e)
    return text


def apply_progressive_punishment(chat_id, user_id):
    """اعمال مجازات پلکانی بر اساس تعداد دفعات ۳ اخطاره شدن (استریک)"""
    strike_row = db_query(
        "SELECT count FROM strikes WHERE chat_id = ? AND user_id = ?",
        (chat_id, user_id),
        fetchone=True,
    )
    current_strikes = (strike_row[0] + 1) if strike_row else 1

    # افزایش سطح استریک و صفر کردن اخطارهای خرد
    db_query(
        "INSERT OR REPLACE INTO strikes (chat_id, user_id, count) VALUES (?, ?, ?)",
        (chat_id, user_id, current_strikes),
        commit=True,
    )
    db_query(
        "UPDATE warnings SET count = 0 WHERE chat_id = ? AND user_id = ?",
        (chat_id, user_id),
        commit=True,
    )

    now = int(time.time())

    if current_strikes == 1:
        until = now + 3600  # ۱ ساعت
        bot.restrict_chat_member(
            chat_id, user_id, until_date=until, permissions=MUTE_PERMISSIONS
        )
        return (
            f"⏳ کاربر به دلیل دریافت ۳ اخطار، **۱ ساعت** سکوت شد. (سطح جریمه: {current_strikes})"
        )
    elif current_strikes == 2:
        until = now + (12 * 3600)  # ۱۲ ساعت
        bot.restrict_chat_member(
            chat_id, user_id, until_date=until, permissions=MUTE_PERMISSIONS
        )
        return (
            f"⏳ کاربر به دلیل تکرار تخلف (بار دوم)، **۱۲ ساعت** سکوت شد. (سطح جریمه: {current_strikes})"
        )
    elif current_strikes == 3:
        until = now + (24 * 3600)  # ۲۴ ساعت
        bot.restrict_chat_member(
            chat_id, user_id, until_date=until, permissions=MUTE_PERMISSIONS
        )
        return (
            f"⏳ کاربر به دلیل تکرار تخلف (بار سوم)، **۲۴ ساعت** سکوت شد. (سطح جریمه: {current_strikes})"
        )
    else:
        bot.ban_chat_member(chat_id, user_id)
        return "🚫 کاربر به دلیل بی‌توجهی به اخطارها (بار چهارم)، از گروه **اخراج (Ban)** شد!"


def is_admin(chat_id, user_id):
    if user_id in SUDO_ADMINS:
        return True
    try:
        member = bot.get_chat_member(chat_id, user_id)
        return member.status in ["administrator", "creator"]
    except Exception:
        return False


def get_group_owner_id(chat_id):
    try:
        admins = bot.get_chat_administrators(chat_id)
        for admin in admins:
            if admin.status == "creator":
                return admin.user.id
    except Exception:
        pass
    return None


def get_settings(chat_id):
    row = db_query(
        "SELECT anti_forward, anti_link, anti_spam, anti_bot, default_dialog FROM group_settings WHERE chat_id = ?",
        (chat_id,),
        fetchone=True,
    )
    if not row:
        db_query(
            "INSERT INTO group_settings (chat_id, anti_forward, anti_link, anti_spam, anti_bot, default_dialog) VALUES (?, 0, 0, 0, 0, 0)",
            (chat_id,),
            commit=True,
        )
        return {"anti_forward": 0, "anti_link": 0, "anti_spam": 0, "anti_bot": 0, "default_dialog": 0}
    
    def_diag = row[4] if len(row) > 4 and row[4] is not None else 0
    return {
        "anti_forward": row[0],
        "anti_link": row[1],
        "anti_spam": row[2],
        "anti_bot": row[3],
        "default_dialog": def_diag,
    }


def get_user_distinct_words(user_id):
    rows = db_query(
        "SELECT DISTINCT word FROM learned_words WHERE user_id = ?",
        (user_id,),
        fetchall=True,
    )
    return [r[0] for r in rows] if rows else []


# ================= ================= =================
# 1. پیوی و استارت (شامل ۴ گزینه اصلی)
# ================= ================= =================
@bot.message_handler(commands=["start"], chat_types=["private"])
def start_private(message):
    welcome_text = (
        "هی سلام من ربات چتر هستم ☂️\n"
        "می‌تونی منو به گروهت اضافه کنی تا یه خاطره خوشی رو با هم داشته باشیم!"
    )

    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_add = types.InlineKeyboardButton(
        "➕ افزودن به گروه",
        url=f"https://t.me/{BOT_USERNAME}?startgroup=true",
    )
    btn_teach = types.InlineKeyboardButton(
        "🎓 یاد دادن کلمه", callback_data="teach_word"
    )
    btn_list = types.InlineKeyboardButton(
        "📜 دیدن کلمات ساخته شده", callback_data="list_words"
    )
    btn_help = types.InlineKeyboardButton(
        "📖 لیست دستورات و قابلیت‌ها", callback_data="help_commands"
    )

    markup.add(btn_add)
    markup.add(btn_teach, btn_list)
    markup.add(btn_help)

    bot.reply_to(message, welcome_text, reply_markup=markup)


@bot.callback_query_handler(
    func=lambda call: call.data
    in [
        "teach_word",
        "list_words",
        "select_mode",
        "delete_word_menu",
        "help_commands",
    ]
)
def handle_private_callbacks(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id

    if call.data == "teach_word":
        user_states[user_id] = {"step": "wait_word"}
        bot.send_message(chat_id, "اون کلمه‌ای که می‌خوای وقتی مردم گفتن رو بگو:")

    elif call.data == "list_words":
        show_words_list(chat_id, user_id)

    elif call.data == "select_mode":
        markup = types.InlineKeyboardMarkup(row_width=1)
        btn_multi = types.InlineKeyboardButton(
            "🔄 اضافه کردن جواب دیگری (پاسخ رندوم)", callback_data="teach_word"
        )
        btn_del = types.InlineKeyboardButton(
            "🗑️ حذف کلمه یا جواب", callback_data="delete_word_menu"
        )
        btn_new = types.InlineKeyboardButton(
            "➕ اضافه کردن کلمه جدید", callback_data="teach_word"
        )
        markup.add(btn_multi, btn_del, btn_new)
        bot.send_message(
            chat_id, "حالت مورد نظر خود را انتخاب کنید:", reply_markup=markup
        )

    elif call.data == "delete_word_menu":
        words = get_user_distinct_words(user_id)
        if not words:
            bot.send_message(chat_id, "شما هنوز هیچ کلمه‌ای ثبت نکرده‌اید!")
            return
        user_states[user_id] = {"step": "wait_delete_code"}
        bot.send_message(
            chat_id, "کد کلمه‌ای که می‌خواهی حذف کنی را بفرست (مثلاً عدد 1):"
        )

    elif call.data == "help_commands":
        help_text = (
            "📖 **راهنمای کامل دستورات و قابلیت‌های ربات چتر:**\n\n"
            "☂️ **۱. بخش چت‌بات شخصی:**\n"
            "• با دکمه «یاد دادن کلمه» در پیوی، کلمات دلخواهتان را ذخیره کنید.\n"
            "• ربات در هر گروهی که **مالک (Creator)** آن باشید، از لیست کلمات اختصاصی شما پاسخ می‌دهد.\n\n"
            "⚙️ **۲. دستورات فارسی و انگلیسی گروه (مخصوص مدیران با ریپلای):**\n"
            "• `اخطار` یا `/warn` : ثبت اخطار (با رسیدن به ۳، جریمه پلکانی ۱س/۱۲س/۲۴س/بن اعمال می‌شود)\n"
            "• `حذف اخطار` یا `/unwarn` : پاک کردن ۱ اخطار کاربر\n"
            "• `صفر کردن` : پاکسازی کامل اخطارها و سطح جریمه کاربر\n"
            "• `سکوت 10` : سکوت زمان‌دار کاربر به دقیقه دلخواه\n"
            "• `رفع سکوت` : لغو وضعیت سکوت کاربر\n"
            "• `بن` : اخراج کاربر از گروه\n"
            "• `/title [لقب]` : دادن لقب به عضو\n"
            "• `/vip` و `/unvip` : مدیریت اعضای ویژه\n"
            "• `/panel` : باز کردن پنل تنظیمات گروه\n\n"
            "📦 **۳. سیستم بکاپ و پک دیالوگ (مالک ربات):**\n"
            "• `/backup` : دریافت فایل کامل دیتابیس\n"
            "• `/restore` : بازیابی کامل اطلاعات با ریپلای روی فایل `.db`\n"
            "• `/import_dialog` : وارد کردن پک دیالوگ با ریپلای روی فایل `.json`"
        )
        bot.send_message(chat_id, help_text, parse_mode="Markdown")


def show_words_list(chat_id, user_id):
    words = get_user_distinct_words(user_id)
    if not words:
        bot.send_message(
            chat_id, "شما هنوز هیچ کلمه‌ای در لیست اختصاصی خود ثبت نکرده‌اید!"
        )
        return

    text = "📜 **لیست کلمات یاد گرفته شده:**\n\n"
    for idx, w in enumerate(words, 1):
        responses_rows = db_query(
            "SELECT response FROM learned_words WHERE user_id = ? AND word = ?",
            (user_id, w),
            fetchall=True,
        )
        res_list = [r[0] for r in responses_rows]
        res_str = " / ".join(res_list)
        text += f"کد:{idx}\nکلمه: {w}\nجواب: {res_str}\n------------------\n"

    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_add = types.InlineKeyboardButton(
        "➕ اضافه کردن جدید", callback_data="teach_word"
    )
    btn_change = types.InlineKeyboardButton(
        "✏️ تغییر / حذف کلمات", callback_data="select_mode"
    )
    markup.add(btn_add, btn_change)

    bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=markup)


# ورودی‌های متنی پیوی (ثبت/حذف کلمات)
@bot.message_handler(
    func=lambda msg: msg.chat.type == "private"
    and msg.from_user.id in user_states
)
def process_private_inputs(message):
    user_id = message.from_user.id
    state = user_states[user_id].get("step")

    if state == "wait_word":
        user_states[user_id] = {
            "step": "wait_response",
            "word": message.text.strip(),
        }
        bot.reply_to(message, "اون جوابی که می‌خوای من بهش بدم رو بگو:")

    elif state == "wait_response":
        word = user_states[user_id]["word"]
        response = message.text.strip()
        db_query(
            "INSERT INTO learned_words (user_id, word, response) VALUES (?, ?, ?)",
            (user_id, word, response),
            commit=True,
        )
        del user_states[user_id]
        bot.reply_to(message, "✅ کلمه و جواب با موفقیت در لیست شما ثبت شد!")

    elif state == "wait_delete_code":
        if message.text.isdigit():
            code = int(message.text.strip())
            words = get_user_distinct_words(user_id)
            if 1 <= code <= len(words):
                target_word = words[code - 1]
                del user_states[user_id]

                markup = types.InlineKeyboardMarkup(row_width=1)
                markup.add(
                    types.InlineKeyboardButton(
                        "🗑️ حذف خود کلمه (کل جواب‌ها)", callback_data=f"del_all_{code}"
                    ),
                    types.InlineKeyboardButton(
                        "💬 حذف یک جواب خاص", callback_data=f"del_resp_pick_{code}"
                    ),
                )
                bot.send_message(
                    message.chat.id,
                    f"کلمه انتخاب شده: **{target_word}**\nکدام بخش را می‌خواهی پاک کنی؟",
                    parse_mode="Markdown",
                    reply_markup=markup,
                )
            else:
                bot.reply_to(message, "❌ کد وارد شده معتبر نیست!")
        else:
            bot.reply_to(message, "لطفاً فقط عدد کد کلمه را بفرستید!")


# کالبک‌های حذف کلمه و جواب
@bot.callback_query_handler(
    func=lambda call: call.data.startswith((
        "del_all_",
        "del_resp_pick_",
        "confirm_delword_",
        "del_single_resp_",
        "confirm_delresp_",
        "cancel_del",
    ))
)
def handle_deletion_flow(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    data = call.data

    if data.startswith("del_all_"):
        code = int(data.split("_")[2])
        words = get_user_distinct_words(user_id)
        if code <= len(words):
            target_word = words[code - 1]
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton(
                    "✅ بله", callback_data=f"confirm_delword_{code}"
                ),
                types.InlineKeyboardButton("❌ خیر", callback_data="cancel_del"),
            )
            bot.send_message(
                chat_id,
                f"آیا مطمئنی می‌خواهی کلمه **{target_word}** و تمامی پاسخ‌های آن را حذف کنی؟",
                parse_mode="Markdown",
                reply_markup=markup,
            )

    elif data.startswith("confirm_delword_"):
        code = int(data.split("_")[2])
        words = get_user_distinct_words(user_id)
        if code <= len(words):
            target_word = words[code - 1]
            db_query(
                "DELETE FROM learned_words WHERE user_id = ? AND word = ?",
                (user_id, target_word),
                commit=True,
            )
            bot.edit_message_text(
                f"✅ کلمه **{target_word}** با موفقیت حذف شد.",
                chat_id,
                call.message.message_id,
                parse_mode="Markdown",
            )

    elif data.startswith("del_resp_pick_"):
        code = int(data.split("_")[3])
        words = get_user_distinct_words(user_id)
        if code <= len(words):
            target_word = words[code - 1]
            responses = db_query(
                "SELECT id, response FROM learned_words WHERE user_id = ? AND word = ?",
                (user_id, target_word),
                fetchall=True,
            )

            markup = types.InlineKeyboardMarkup(row_width=1)
            for r_id, r_text in responses:
                markup.add(
                    types.InlineKeyboardButton(
                        f"💬 {r_text[:30]}", callback_data=f"del_single_resp_{r_id}"
                    )
                )

            bot.send_message(
                chat_id,
                f"یکی از پاسخ‌های کلمه **{target_word}** را برای حذف انتخاب کن:",
                parse_mode="Markdown",
                reply_markup=markup,
            )

    elif data.startswith("del_single_resp_"):
        resp_id = int(data.split("_")[3])
        resp_data = db_query(
            "SELECT response FROM learned_words WHERE id = ? AND user_id = ?",
            (resp_id, user_id),
            fetchone=True,
        )
        if resp_data:
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton(
                    "✅ بله", callback_data=f"confirm_delresp_{resp_id}"
                ),
                types.InlineKeyboardButton("❌ خیر", callback_data="cancel_del"),
            )
            bot.send_message(
                chat_id,
                f"آیا مطمئنی می‌خواهی پاسخ «**{resp_data[0]}**» را حذف کنی؟",
                parse_mode="Markdown",
                reply_markup=markup,
            )

    elif data.startswith("confirm_delresp_"):
        resp_id = int(data.split("_")[2])
        db_query(
            "DELETE FROM learned_words WHERE id = ? AND user_id = ?",
            (resp_id, user_id),
            commit=True,
        )
        bot.edit_message_text(
            "✅ پاسخ مورد نظر با موفقیت حذف شد.", chat_id, call.message.message_id
        )

    elif data == "cancel_del":
        bot.edit_message_text(
            "❌ عملیات حذف لغو شد.", chat_id, call.message.message_id
        )


# ================= ================= =================
# 2. پنل مدیریت گروه
# ================= ================= =================
@bot.message_handler(commands=["panel"], chat_types=["group", "supergroup"])
def admin_panel(message):
    if not is_admin(message.chat.id, message.from_user.id):
        return

    text = "⚙️ **پنل مدیریت گروه چتر:**"
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🔒 قفل گروه", callback_data="panel_lock"),
        types.InlineKeyboardButton(
            "🔓 باز کردن گروه", callback_data="panel_unlock"
        ),
        types.InlineKeyboardButton(
            "🏷️ راهنمای لقب", callback_data="panel_title_info"
        ),
        types.InlineKeyboardButton(
            "⚠️ ثبت اخطار", callback_data="panel_warn_info"
        ),
        types.InlineKeyboardButton(
            "🟢 حذف اخطار", callback_data="panel_unwarn_info"
        ),
        types.InlineKeyboardButton(
            "🚫 کلمات ممنوعه", callback_data="panel_banned_menu"
        ),
        types.InlineKeyboardButton(
            "🗑️ حذف پیام‌ها", callback_data="panel_purge"
        ),
        types.InlineKeyboardButton("⭐ افراد ویژه", callback_data="panel_vip"),
        types.InlineKeyboardButton(
            "🛠️ تنظیمات گروه", callback_data="panel_settings"
        ),
    )
    bot.reply_to(message, text, parse_mode="Markdown", reply_markup=markup)


def get_settings_keyboard(chat_id):
    st = get_settings(chat_id)
    markup = types.InlineKeyboardMarkup(row_width=2)

    btn_fwd = types.InlineKeyboardButton(
        f"فوروارد: {'🟢 روشن' if st['anti_forward'] else '🔴 خاموش'}",
        callback_data="toggle_anti_forward",
    )
    btn_link = types.InlineKeyboardButton(
        f"لینک: {'🟢 روشن' if st['anti_link'] else '🔴 خاموش'}",
        callback_data="toggle_anti_link",
    )
    btn_spam = types.InlineKeyboardButton(
        f"اسپم: {'🟢 روشن' if st['anti_spam'] else '🔴 خاموش'}",
        callback_data="toggle_anti_spam",
    )
    btn_bot = types.InlineKeyboardButton(
        f"ضد ربات: {'🟢 روشن' if st['anti_bot'] else '🔴 خاموش'}",
        callback_data="toggle_anti_bot",
    )
    btn_dialog = types.InlineKeyboardButton(
        f"دیالوگ پیش‌فرض: {'🟢 روشن' if st['default_dialog'] else '🔴 خاموش'}",
        callback_data="toggle_default_dialog",
    )

    markup.add(btn_fwd, btn_link, btn_spam, btn_bot)
    markup.add(btn_dialog)
    return markup


@bot.callback_query_handler(
    func=lambda call: call.data.startswith(("panel_", "toggle_", "banned_"))
)
def handle_panel_and_settings(call):
    chat_id = call.message.chat.id
    user_id = call.from_user.id

    if not is_admin(chat_id, user_id):
        bot.answer_callback_query(
            call.id, "❌ شما دسترسی مدیر ندارید!", show_alert=True
        )
        return

    data = call.data

    if data == "panel_lock":
        bot.set_chat_permissions(
            chat_id, types.ChatPermissions(can_send_messages=False)
        )
        bot.send_message(chat_id, "🔒 گروه با موفقیت قفل شد.")

    elif data == "panel_unlock":
        bot.set_chat_permissions(
            chat_id, types.ChatPermissions(can_send_messages=True)
        )
        bot.send_message(chat_id, "🔓 گروه باز شد.")

    elif data == "panel_title_info":
        bot.send_message(
            chat_id,
            "🏷️ برای دادن لقب به یک عضو، روی پیام او ریپلای کنید و بنویسید:\n`/title [لقب مورد نظر]`",
            parse_mode="Markdown",
        )

    elif data == "panel_warn_info":
        bot.send_message(
            chat_id,
            "⚠️ برای ثبت اخطار دستی، روی پیام کاربر ریپلای کنید و عبارت `اخطار` یا `/warn` را بفرستید.",
        )

    elif data == "panel_unwarn_info":
        bot.send_message(
            chat_id,
            "🟢 برای حذف اخطار کاربر، روی پیام او ریپلای کنید و عبارت `حذف اخطار` یا `/unwarn` را بفرستید.",
        )

    elif data == "panel_banned_menu":
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton(
                "➕ افزودن کلمه ممنوعه", callback_data="banned_add"
            ),
            types.InlineKeyboardButton(
                "📜 لیست و حذف کلمات ممنوعه", callback_data="banned_list"
            ),
        )
        bot.send_message(
            chat_id,
            "🚫 **مدیریت کلمات ممنوعه گروه:**",
            parse_mode="Markdown",
            reply_markup=markup,
        )

    elif data == "banned_add":
        user_states[user_id] = {"step": "wait_banned_word", "chat_id": chat_id}
        bot.send_message(
            chat_id, "کلمه‌ای که می‌خواهی در این گروه ممنوع شود را بفرست:"
        )

    elif data == "banned_list":
        words = db_query(
            "SELECT id, word FROM banned_words WHERE chat_id = ?",
            (chat_id,),
            fetchall=True,
        )
        if not words:
            bot.send_message(
                chat_id, "هیچ کلمه ممنوعه‌ای برای این گروه ثبت نشده است."
            )
            return

        markup = types.InlineKeyboardMarkup(row_width=1)
        for b_id, b_word in words:
            markup.add(
                types.InlineKeyboardButton(
                    f"❌ حذف «{b_word}»", callback_data=f"banned_del_{b_id}"
                )
            )

        bot.send_message(
            chat_id,
            "📜 **لیست کلمات ممنوعه گروه:**\nروی هر کدام بزنید تا پاک شود.",
            parse_mode="Markdown",
            reply_markup=markup,
        )

    elif data.startswith("banned_del_"):
        b_id = int(data.split("_")[2])
        db_query(
            "DELETE FROM banned_words WHERE id = ? AND chat_id = ?",
            (b_id, chat_id),
            commit=True,
        )
        bot.edit_message_text(
            "✅ کلمه ممنوعه با موفقیت از لیست گروه حذف شد.",
            chat_id,
            call.message.message_id,
        )

    elif data == "panel_settings":
        bot.send_message(
            chat_id,
            "🛠️ **تنظیمات پیشرفته گروه:**\nبرای تغییر وضعیت هر بخش روی دکمه آن کلیک کنید:",
            parse_mode="Markdown",
            reply_markup=get_settings_keyboard(chat_id),
        )

    elif data.startswith("toggle_"):
        st = get_settings(chat_id)
        field = data.replace("toggle_", "")
        new_val = 1 if st[field] == 0 else 0

        db_query(
            f"UPDATE group_settings SET {field} = ? WHERE chat_id = ?",
            (new_val, chat_id),
            commit=True,
        )
        bot.edit_message_reply_markup(
            chat_id,
            call.message.message_id,
            reply_markup=get_settings_keyboard(chat_id),
        )

    elif data == "panel_vip":
        vips = db_query(
            "SELECT user_id FROM vip_users WHERE chat_id = ?",
            (chat_id,),
            fetchall=True,
        )
        text = f"⭐ **اعضای ویژه گروه:** {len(vips)} نفر\n\n"
        text += (
            "💡 برای ویژه کردن یک عضو یا لغو آن، روی پیام او ریپلای کنید و عبارت `/vip` یا `/unvip` را ارسال کنید."
        )
        bot.send_message(chat_id, text, parse_mode="Markdown")

    elif data == "panel_purge":
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton(
                "💥 حذف کل پیام‌های اخیر (تا ۱۰۰ پیام)", callback_data="purge_all"
            ),
            types.InlineKeyboardButton(
                "🔢 حذف پیام با عدد دلخواه", callback_data="purge_custom"
            ),
        )
        bot.send_message(
            chat_id, "از گزینه‌های زیر برای پاکسازی استفاده کن:", reply_markup=markup
        )


# دریافت کلمه ممنوعه جدید
@bot.message_handler(
    func=lambda msg: msg.from_user.id in user_states
    and user_states[msg.from_user.id].get("step") == "wait_banned_word"
)
def process_banned_word_input(message):
    user_id = message.from_user.id
    chat_id = user_states[user_id]["chat_id"]
    b_word = message.text.strip()

    db_query(
        "INSERT INTO banned_words (chat_id, word) VALUES (?, ?)",
        (chat_id, b_word),
        commit=True,
    )
    del user_states[user_id]
    bot.reply_to(
        message, f"✅ کلمه «{b_word}» به لیست کلمات ممنوعه این گروه اضافه شد."
    )


# ================= ================= =================
# 3. پردازش پاکسازی پیام‌ها (Purge Logic)
# ================= ================= =================
@bot.callback_query_handler(
    func=lambda call: call.data in ["purge_all", "purge_custom"]
)
def handle_purge_actions(call):
    chat_id = call.message.chat.id
    user_id = call.from_user.id

    if not is_admin(chat_id, user_id):
        return

    if call.data == "purge_custom":
        user_states[user_id] = {"step": "wait_purge_num", "chat_id": chat_id}
        bot.send_message(chat_id, "می‌خوای چندتا پیام پاک بشه؟ (یک عدد وارد کن):")

    elif call.data == "purge_all":
        start_id = call.message.message_id
        deleted = 0
        for m_id in range(start_id, max(1, start_id - 100), -1):
            try:
                bot.delete_message(chat_id, m_id)
                deleted += 1
            except Exception:
                pass
        bot.send_message(chat_id, f"💥 تعداد {deleted} پیام با موفقیت پاکسازی شد.")


@bot.message_handler(
    func=lambda msg: msg.from_user.id in user_states
    and user_states[msg.from_user.id].get("step") == "wait_purge_num"
)
def process_purge_number(message):
    user_id = message.from_user.id
    chat_id = user_states[user_id]["chat_id"]

    if message.text.isdigit():
        count = int(message.text)
        start_id = message.message_id
        deleted = 0
        for m_id in range(start_id, max(1, start_id - count - 1), -1):
            try:
                bot.delete_message(chat_id, m_id)
                deleted += 1
            except Exception:
                pass
        del user_states[user_id]
        bot.send_message(chat_id, f"✅ تعداد {deleted} پیام پاک شد.")
    else:
        bot.reply_to(message, "لطفاً فقط عدد بفرستید!")


# ================= ================= =================
# 4. پردازش دستورات فارسی و انگلیسی ادمین (با ریپلای)
# ================= ================= =================
@bot.message_handler(
    func=lambda msg: msg.chat.type in ["group", "supergroup"]
    and msg.reply_to_message is not None
)
def handle_persian_and_english_reply_commands(message):
    chat_id = message.chat.id
    user_id = message.from_user.id

    if not is_admin(chat_id, user_id):
        return

    raw_text = message.text or ""
    text = convert_fa_numbers(raw_text.strip().lower())
    target_user = message.reply_to_message.from_user

    # جلوگیری از اعمال دستور روی ادمین‌ها یا ربات
    if is_admin(chat_id, target_user.id) or target_user.is_bot:
        if (
            text
            in [
                "اخطار",
                "بن",
                "صفر کردن",
                "پاکسازی اخطار",
                "بخشش",
                "حذف اخطار",
                "کم کردن اخطار",
                "رفع سکوت",
                "آزاد",
                "ازاد",
            ]
            or text.startswith("سکوت")
            or text.startswith(("/warn", "/unwarn", "/vip", "/unvip"))
        ):
            bot.reply_to(
                message,
                "❌ امکان اعمال دستورات مدیریتی روی ادمین‌ها یا ربات‌ها وجود ندارد.",
            )
            return

    # ۱. دستور اخطار (فارسی و انگلیسی)
    if text in ["اخطار", "/warn"]:
        warn_data = db_query(
            "SELECT count FROM warnings WHERE chat_id = ? AND user_id = ?",
            (chat_id, target_user.id),
            fetchone=True,
        )
        current = (warn_data[0] + 1) if warn_data else 1

        if current >= 3:
            punish_msg = apply_progressive_punishment(chat_id, target_user.id)
            bot.reply_to(
                message,
                f"⚠️ کاربر [{target_user.first_name}](tg://user?id={target_user.id}) به ۳ اخطار رسید!\n\n{punish_msg}",
                parse_mode="Markdown",
            )
        else:
            db_query(
                "INSERT OR REPLACE INTO warnings (chat_id, user_id, count) VALUES (?, ?, ?)",
                (chat_id, target_user.id, current),
                commit=True,
            )
            bot.reply_to(
                message,
                f"⚠️ یک اخطار به [{target_user.first_name}](tg://user?id={target_user.id}) داده شد.\nتعداد اخطارها: **{current}/3**",
                parse_mode="Markdown",
            )

    # ۲. دستور حذف اخطار (فارسی و انگلیسی)
    elif text in ["حذف اخطار", "کم کردن اخطار", "/unwarn"]:
        warn_data = db_query(
            "SELECT count FROM warnings WHERE chat_id = ? AND user_id = ?",
            (chat_id, target_user.id),
            fetchone=True,
        )
        if warn_data and warn_data[0] > 0:
            new_count = warn_data[0] - 1
            db_query(
                "UPDATE warnings SET count = ? WHERE chat_id = ? AND user_id = ?",
                (new_count, chat_id, target_user.id),
                commit=True,
            )
            bot.reply_to(
                message,
                f"🟢 یک اخطار از [{target_user.first_name}](tg://user?id={target_user.id}) کسر شد. اخطارهای باقی‌مانده: **{new_count}**",
                parse_mode="Markdown",
            )
        else:
            bot.reply_to(
                message,
                f"ℹ️ کاربر [{target_user.first_name}](tg://user?id={target_user.id}) هیچ اخطاری ندارد.",
                parse_mode="Markdown",
            )

    # ۳. صفر کردن کامل اخطارها و سطح جریمه (استریک)
    elif text in ["صفر کردن", "پاکسازی اخطار", "بخشش"]:
        db_query(
            "UPDATE warnings SET count = 0 WHERE chat_id = ? AND user_id = ?",
            (chat_id, target_user.id),
            commit=True,
        )
        db_query(
            "UPDATE strikes SET count = 0 WHERE chat_id = ? AND user_id = ?",
            (chat_id, target_user.id),
            commit=True,
        )
        bot.reply_to(
            message,
            f"🔄 تمامی اخطارها و سطح جریمه کاربر [{target_user.first_name}](tg://user?id={target_user.id}) صفر شد.",
            parse_mode="Markdown",
        )

    # ۴. رفع سکوت (Unmute)
    elif text in ["رفع سکوت", "حذف سکوت", "ازاد", "آزاد"]:
        try:
            bot.restrict_chat_member(
                chat_id, target_user.id, permissions=UNMUTE_PERMISSIONS
            )
            bot.reply_to(
                message,
                f"🔊 وضعیت سکوت کاربر [{target_user.first_name}](tg://user?id={target_user.id}) لغو شد.",
                parse_mode="Markdown",
            )
        except Exception:
            bot.reply_to(message, "❌ خطایی در رفع سکوت کاربر رخ داد.")

    # ۵. اخراج کاربر (Ban)
    elif text in ["بن", "/ban"]:
        try:
            bot.ban_chat_member(chat_id, target_user.id)
            bot.reply_to(
                message,
                f"🚫 کاربر [{target_user.first_name}](tg://user?id={target_user.id}) از گروه اخراج شد.",
                parse_mode="Markdown",
            )
        except Exception:
            bot.reply_to(message, "❌ خطایی در بن کردن کاربر رخ داد.")

    # ۶. سکوت زمان‌دار (مثلاً: سکوت 10 یا سکوت ۵)
    elif text.startswith("سکوت"):
        parts = text.split()
        if len(parts) >= 2 and parts[1].isdigit():
            minutes = int(parts[1])
            until_time = int(time.time()) + (minutes * 60)
            try:
                bot.restrict_chat_member(
                    chat_id,
                    target_user.id,
                    until_date=until_time,
                    permissions=MUTE_PERMISSIONS,
                )
                bot.reply_to(
                    message,
                    f"🔇 کاربر [{target_user.first_name}](tg://user?id={target_user.id}) به مدت **{minutes} دقیقه** سکوت شد.",
                    parse_mode="Markdown",
                )
            except Exception:
                bot.reply_to(message, "❌ خطایی در سکوت کردن کاربر رخ داد.")

    # ۷. عضو ویژه (VIP)
    elif text in ["/vip", "ویژه"]:
        db_query(
            "INSERT OR REPLACE INTO vip_users (chat_id, user_id) VALUES (?, ?)",
            (chat_id, target_user.id),
            commit=True,
        )
        bot.reply_to(
            message,
            f"⭐ کاربر [{target_user.first_name}](tg://user?id={target_user.id}) به اعضای ویژه (VIP) اضافه شد.",
            parse_mode="Markdown",
        )

    # ۸. لغو عضو ویژه (UnVIP)
    elif text in ["/unvip", "حذف ویژه"]:
        db_query(
            "DELETE FROM vip_users WHERE chat_id = ? AND user_id = ?",
            (chat_id, target_user.id),
            commit=True,
        )
        bot.reply_to(
            message,
            f"❌ کاربر [{target_user.first_name}](tg://user?id={target_user.id}) از اعضای ویژه حذف شد.",
            parse_mode="Markdown",
        )

    # ۹. اعطای لقب (/title)
    elif text.startswith("/title") or text.startswith("لقب"):
        parts = message.text.split(maxsplit=1)
        if len(parts) > 1:
            title_text = parts[1].strip()
            db_query(
                "INSERT OR REPLACE INTO user_titles (chat_id, user_id, title) VALUES (?, ?, ?)",
                (chat_id, target_user.id, title_text),
                commit=True,
            )
            bot.reply_to(
                message,
                f"🏷️ لقب «{title_text}» برای کاربر [{target_user.first_name}](tg://user?id={target_user.id}) ثبت شد.",
                parse_mode="Markdown",
            )
        else:
            bot.reply_to(
                message,
                "لطفاً لقب را هم بنویسید. مثال: `/title سلطان`",
                parse_mode="Markdown",
            )


# ================= ================= =================
# 5. دستورات بکاپ، بازیابی و اپلود پک دیالوگ (مخصوص سودو)
# ================= ================= =================
@bot.message_handler(commands=["backup"], chat_types=["private"])
def send_db_backup(message):
    if message.from_user.id in SUDO_ADMINS:
        if os.path.exists("chatar_bot.db"):
            try:
                with open("chatar_bot.db", "rb") as doc:
                    bot.send_document(
                        message.chat.id,
                        doc,
                        caption=(
                            "📦 **فایل بکاپ کامل و جامع دیتابیس ربات چتر**\n\nشامل تمامی"
                            " کلمات، تنظیمات، اخطارها و داده‌های همه کاربران.\n\nبرای"
                            " بازیابی، این فایل را ریپلای کرده و دستور `/restore` را"
                            " ارسال کنید."
                        ),
                        parse_mode="Markdown",
                    )
            except Exception as e:
                bot.reply_to(message, f"❌ خطا در ارسال بکاپ: {e}")
        else:
            bot.reply_to(message, "❌ فایل دیتابیس یافت نشد!")


@bot.message_handler(commands=["restore"], chat_types=["private"])
def restore_db_backup(message):
    if message.from_user.id not in SUDO_ADMINS:
        return

    if not message.reply_to_message or not message.reply_to_message.document:
        bot.reply_to(
            message,
            "❌ لطفاً این دستور را روی فایل بکاپ ارسال‌شده (`chatar_bot.db`) ریپلای کنید!",
        )
        return

    doc = message.reply_to_message.document
    if not doc.file_name.endswith(".db"):
        bot.reply_to(
            message, "❌ فایل ارسالی باید یک فایل دیتابیس با پسوند `.db` باشد!"
        )
        return

    try:
        file_info = bot.get_file(doc.file_id)
        downloaded_file = bot.download_file(file_info.file_path)

        with open("chatar_bot.db", "wb") as new_db:
            new_db.write(downloaded_file)

        bot.reply_to(
            message,
            "✅ **دیتابیس با موفقیت و کامل بازیابی شد!**\nتمامی داده‌های ربات مجدداً فعال شدند.",
        )
    except Exception as e:
        bot.reply_to(message, f"❌ خطا در بازیابی دیتابیس: {e}")


@bot.message_handler(commands=["import_dialog"], chat_types=["private"])
def import_dialog_pack(message):
    """دستور ورود پک دیالوگ با فایل JSON"""
    if message.from_user.id not in SUDO_ADMINS:
        return

    if not message.reply_to_message or not message.reply_to_message.document:
        bot.reply_to(
            message,
            "❌ لطفاً این دستور را روی فایل JSON پک دیالوگ ریپلای کنید!",
        )
        return

    doc = message.reply_to_message.document
    if not doc.file_name.endswith((".json", ".txt")):
        bot.reply_to(
            message, "❌ فایل ارسالی باید دارای پسوند `.json` یا `.txt` باشد!"
        )
        return

    try:
        file_info = bot.get_file(doc.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        data = json.loads(downloaded_file.decode("utf-8"))

        count = 0
        if isinstance(data, dict):
            for word, resp in data.items():
                if isinstance(resp, list):
                    for r in resp:
                        db_query(
                            "INSERT INTO default_dialogs (word, response) VALUES (?, ?)",
                            (word.strip().lower(), str(r)),
                            commit=True,
                        )
                        count += 1
                else:
                    db_query(
                        "INSERT INTO default_dialogs (word, response) VALUES (?, ?)",
                        (word.strip().lower(), str(resp)),
                        commit=True,
                    )
                    count += 1
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    w = item.get("word") or item.get("k")
                    r = item.get("response") or item.get("v")
                    if w and r:
                        db_query(
                            "INSERT INTO default_dialogs (word, response) VALUES (?, ?)",
                            (str(w).strip().lower(), str(r)),
                            commit=True,
                        )
                        count += 1

        bot.reply_to(
            message,
            f"✅ **پک دیالوگ با موفقیت وارد دیتابیس شد!**\nتعداد **{count}** دیالوگ به حافظه پیش‌فرض اضافه گردید.",
            parse_mode="Markdown",
        )
    except Exception as e:
        bot.reply_to(message, f"❌ خطا در پردازش فایل پک دیالوگ: {e}")


# ================= ================= =================
# 6. پردازش پیام‌های گروه (فیلترها + چت‌بات)
# ================= ================= =================
@bot.message_handler(
    func=lambda msg: msg.chat.type in ["group", "supergroup"],
    content_types=["text", "forward_date", "new_chat_members"],
)
def group_messages_processor(message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    text = message.text or ""

    # ضد ربات
    st = get_settings(chat_id)
    if st["anti_bot"] and message.new_chat_members:
        for new_mem in message.new_chat_members:
            if new_mem.is_bot and not is_admin(chat_id, user_id):
                try:
                    bot.ban_chat_member(chat_id, new_mem.id)
                    bot.send_message(
                        chat_id, "🚫 ربات اضافه شده توسط کاربر غیرمجاز اخراج شد."
                    )
                except Exception:
                    pass
        return

    is_vip = db_query(
        "SELECT 1 FROM vip_users WHERE chat_id = ? AND user_id = ?",
        (chat_id, user_id),
        fetchone=True,
    )
    if is_vip or is_admin(chat_id, user_id):
        process_chatbot_response(message)
        return

    # ضد فوروارد
    if st["anti_forward"] and (
        message.forward_date
        or message.forward_from
        or message.forward_from_chat
    ):
        try:
            bot.delete_message(chat_id, message.message_id)
        except Exception:
            pass
        return

    # ضد لینک
    if st["anti_link"]:
        link_pattern = r"(https?://\S+|t\.me/\S+|@[a-zA-Z0-9_]+)"
        if re.search(link_pattern, text):
            try:
                bot.delete_message(chat_id, message.message_id)
            except Exception:
                pass
            return

    # کلمات ممنوعه
    banned_list = db_query(
        "SELECT word FROM banned_words WHERE chat_id = ?", (chat_id,), fetchall=True
    )
    for b_word in banned_list:
        if b_word[0].lower() in text.lower():
            try:
                bot.delete_message(chat_id, message.message_id)
            except Exception:
                pass

            warn_data = db_query(
                "SELECT count FROM warnings WHERE chat_id = ? AND user_id = ?",
                (chat_id, user_id),
                fetchone=True,
            )
            current_warns = (warn_data[0] + 1) if warn_data else 1

            if current_warns >= 3:
                punish_msg = apply_progressive_punishment(chat_id, user_id)
                bot.send_message(
                    chat_id,
                    f"⚠️ کاربر [{message.from_user.first_name}](tg://user?id={user_id})"
                    " به دلیل استفاده از کلمه ممنوعه به ۳ اخطار رسید!\n\n"
                    f"{punish_msg}",
                    parse_mode="Markdown",
                )
            else:
                db_query(
                    "INSERT OR REPLACE INTO warnings (chat_id, user_id, count) VALUES (?, ?, ?)",
                    (chat_id, user_id, current_warns),
                    commit=True,
                )

                markup = types.InlineKeyboardMarkup(row_width=2)
                btn_show = types.InlineKeyboardButton(
                    "👁️ مشاهده پیام", callback_data=f"view_msg_{user_id}"
                )
                btn_del_warn = types.InlineKeyboardButton(
                    "❌ حذف اخطار", callback_data=f"remove_warn_{user_id}"
                )
                markup.add(btn_show, btn_del_warn)

                bot.send_message(
                    chat_id,
                    f"کاربر [{message.from_user.first_name}](tg://user?id={user_id})"
                    f" شما از کلمه ممنوعه استفاده کردید و {current_warns} اخطار از 3 اخطار را گرفتید!",
                    parse_mode="Markdown",
                    reply_markup=markup,
                )
            return

    process_chatbot_response(message)


def process_chatbot_response(message):
    chat_id = message.chat.id
    text = (message.text or "").strip().lower()
    owner_id = get_group_owner_id(chat_id)

    # 1. اولویت اول: کلمات یاد داده‌شده اختصاصی مالک گروه
    if owner_id:
        responses = db_query(
            "SELECT response FROM learned_words WHERE user_id = ? AND LOWER(word) = ?",
            (owner_id, text),
            fetchall=True,
        )
        if responses:
            chosen_response = random.choice(responses)[0]
            bot.reply_to(message, chosen_response)
            return

    # 2. اولویت دوم: دیالوگ‌های پک پیش‌فرض (در صورت روشن بودن تنظیمات در گروه)
    st = get_settings(chat_id)
    if st.get("default_dialog", 0) == 1:
        default_responses = db_query(
            "SELECT response FROM default_dialogs WHERE LOWER(word) = ?",
            (text,),
            fetchall=True,
        )
        if default_responses:
            chosen_response = random.choice(default_responses)[0]
            bot.reply_to(message, chosen_response)


# کالبک‌های دکمه اخطار
@bot.callback_query_handler(
    func=lambda call: call.data.startswith(("view_msg_", "remove_warn_"))
)
def handle_warn_callback_buttons(call):
    chat_id = call.message.chat.id
    clicker_id = call.from_user.id

    if call.data.startswith("remove_warn_"):
        if not is_admin(chat_id, clicker_id):
            bot.answer_callback_query(
                call.id, "این گزینه برای شما نیست!", show_alert=True
            )
            return

        target_user = int(call.data.split("_")[2])
        warn_data = db_query(
            "SELECT count FROM warnings WHERE chat_id = ? AND user_id = ?",
            (chat_id, target_user),
            fetchone=True,
        )
        if warn_data and warn_data[0] > 0:
            new_count = warn_data[0] - 1
            db_query(
                "UPDATE warnings SET count = ? WHERE chat_id = ? AND user_id = ?",
                (new_count, chat_id, target_user),
                commit=True,
            )
            bot.answer_callback_query(
                call.id, f"✅ اخطار کاربر به {new_count} کاهش یافت.", show_alert=True
            )
        else:
            bot.answer_callback_query(
                call.id, "کاربر هیچ اخطاری ندارد.", show_alert=True
            )

    elif call.data.startswith("view_msg_"):
        bot.answer_callback_query(
            call.id,
            "این پیام به دلیل استفاده از کلمات ممنوعه توسط ربات پاک شده است.",
            show_alert=True,
        )


# ================= ================= =================
# اجرای ربات
# ================= ================= =================
if __name__ == "__main__":
    print("Bot Umbrella (Full Final Version) is running...")
    bot.infinity_polling(skip_pending=True)
