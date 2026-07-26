# -*- coding: utf-8 -*-
"""
دوز (تیک-تاک-تو) - ماژول مستقل بازی برای ربات چتر
=====================================================
این فایل کاملاً جداست تا مدیریتش راحت باشه؛ فقط کافیه تو bot.py این‌طور صداش بزنی:

    import dooz_game
    ...
    dooz_game.register(app)   # داخل build_application(), قبل از برگردوندن app

طراحی رابط کاربری: کل بازی روی یه پیامِ واحد انجام می‌شه (فقط ادیت می‌شه، نه پیام جدید)،
پس گپ همیشه تمیز می‌مونه - نیازی به تایپ عدد و پاک کردن پیام نیست.

قابلیت‌ها:
- "دوز" یا /dooz -> انتخاب حالت: بازی با ربات / بازی با کاربر
- بازی با ربات: ۴ درجه سختی (آسون تا وحشتناک، آخری غیرقابل شکسته)
- بازی با کاربر: روی پیام طرف ریپلای بزن و بنویس «بازی»
- بعد از باخت/برد/مساوی، دکمه‌ی «دوباره بازی» با جابه‌جاییِ نفرِ اول (منصفانه‌تر)
"""

import os
import json
import random
import sqlite3
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ---------------------------------------------------------------------------
# دیتابیس (همون فایل chatr_bot.db که کنار bot.py هست، یه جدول جدا برای بازی‌ها)
# ---------------------------------------------------------------------------
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chatr_bot.db")
BOT_SENTINEL = -1  # آی‌دی قراردادی برای «ربات» به‌عنوان بازیکن (آی‌دی واقعی تلگرام هیچ‌وقت منفی نیست)

WIN_LINES = (
    (0, 1, 2), (3, 4, 5), (6, 7, 8),
    (0, 3, 6), (1, 4, 7), (2, 5, 8),
    (0, 4, 8), (2, 4, 6),
)

DIFFICULTY_LABELS = {
    "easy": "آسون",
    "normal": "معمولی",
    "hard": "سخت",
    "impossible": "وحشتناک",
}

MARK_X = "❌"
MARK_O = "⭕"
MARK_EMPTY = "・"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_schema():
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS dooz_games (
            game_id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            message_id INTEGER,
            player_x_id INTEGER NOT NULL,
            player_x_name TEXT,
            player_o_id INTEGER,
            player_o_name TEXT,
            vs_bot INTEGER NOT NULL DEFAULT 0,
            difficulty TEXT,
            board TEXT NOT NULL,
            turn TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT
        )
        """
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS dooz_player_stats (
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            first_seen TEXT,
            total_games INTEGER NOT NULL DEFAULT 0,
            wins INTEGER NOT NULL DEFAULT 0,
            losses INTEGER NOT NULL DEFAULT 0,
            draws INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS dooz_head_to_head (
            user_a_id INTEGER NOT NULL,
            user_b_id INTEGER NOT NULL,
            user_a_name TEXT,
            user_b_name TEXT,
            wins_a INTEGER NOT NULL DEFAULT 0,
            wins_b INTEGER NOT NULL DEFAULT 0,
            draws INTEGER NOT NULL DEFAULT 0,
            total INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_a_id, user_b_id)
        )
        """
    )
    conn.commit()
    conn.close()


_ensure_schema()


# ---------------------------------------------------------------------------
# لایه دیتابیس بازی
# ---------------------------------------------------------------------------
def create_game(chat_id, player_x_id, player_x_name, player_o_id, player_o_name, vs_bot, difficulty, board, turn):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO dooz_games "
        "(chat_id, player_x_id, player_x_name, player_o_id, player_o_name, vs_bot, difficulty, board, turn, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)",
        (
            chat_id, player_x_id, player_x_name, player_o_id, player_o_name,
            int(vs_bot), difficulty, json.dumps(board), turn, datetime.utcnow().isoformat(),
        ),
    )
    conn.commit()
    game_id = c.lastrowid
    conn.close()
    return game_id


def get_game(game_id: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM dooz_games WHERE game_id=?", (game_id,))
    row = c.fetchone()
    conn.close()
    return row


def set_message_id(game_id: int, message_id: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE dooz_games SET message_id=? WHERE game_id=?", (message_id, game_id))
    conn.commit()
    conn.close()


def update_game(game_id: int, board: list, turn: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE dooz_games SET board=?, turn=? WHERE game_id=?", (json.dumps(board), turn, game_id))
    conn.commit()
    conn.close()


def finish_game(game_id: int, board: list):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE dooz_games SET board=?, status='finished' WHERE game_id=?", (json.dumps(board), game_id))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# آمار بازیکن‌ها (پروفایل) و رکورد رودررو بین دو نفر
# ---------------------------------------------------------------------------
def record_result_for_user(user_id: int, name: str, result: str):
    """result: 'win' | 'loss' | 'draw'"""
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT user_id FROM dooz_player_stats WHERE user_id=?", (user_id,))
    if c.fetchone() is None:
        c.execute(
            "INSERT INTO dooz_player_stats (user_id, name, first_seen, total_games, wins, losses, draws) "
            "VALUES (?, ?, ?, 0, 0, 0, 0)",
            (user_id, name, datetime.utcnow().isoformat()),
        )
    col = {"win": "wins", "loss": "losses", "draw": "draws"}[result]
    c.execute(
        f"UPDATE dooz_player_stats SET name=?, total_games=total_games+1, {col}={col}+1 WHERE user_id=?",
        (name, user_id),
    )
    conn.commit()
    conn.close()


def get_player_stats(user_id: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM dooz_player_stats WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row


def record_head_to_head(user_a_id, user_a_name, user_b_id, user_b_name, winner_id):
    """winner_id: آی‌دی برنده یا None برای مساوی. ترتیب a/b خودکار نرمال (کوچیک‌تر اول) می‌شه."""
    if user_a_id > user_b_id:
        user_a_id, user_b_id = user_b_id, user_a_id
        user_a_name, user_b_name = user_b_name, user_a_name

    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM dooz_head_to_head WHERE user_a_id=? AND user_b_id=?", (user_a_id, user_b_id))
    if c.fetchone() is None:
        c.execute(
            "INSERT INTO dooz_head_to_head (user_a_id, user_b_id, user_a_name, user_b_name, wins_a, wins_b, draws, total) "
            "VALUES (?, ?, ?, ?, 0, 0, 0, 0)",
            (user_a_id, user_b_id, user_a_name, user_b_name),
        )
    if winner_id is None:
        c.execute(
            "UPDATE dooz_head_to_head SET user_a_name=?, user_b_name=?, draws=draws+1, total=total+1 "
            "WHERE user_a_id=? AND user_b_id=?",
            (user_a_name, user_b_name, user_a_id, user_b_id),
        )
    elif winner_id == user_a_id:
        c.execute(
            "UPDATE dooz_head_to_head SET user_a_name=?, user_b_name=?, wins_a=wins_a+1, total=total+1 "
            "WHERE user_a_id=? AND user_b_id=?",
            (user_a_name, user_b_name, user_a_id, user_b_id),
        )
    else:
        c.execute(
            "UPDATE dooz_head_to_head SET user_a_name=?, user_b_name=?, wins_b=wins_b+1, total=total+1 "
            "WHERE user_a_id=? AND user_b_id=?",
            (user_a_name, user_b_name, user_a_id, user_b_id),
        )
    conn.commit()
    c.execute("SELECT * FROM dooz_head_to_head WHERE user_a_id=? AND user_b_id=?", (user_a_id, user_b_id))
    row = c.fetchone()
    conn.close()
    return row


def get_opponents_list(user_id: int):
    """لیست همه‌ی افرادی که این کاربر باهاشون بازیِ دونفره داشته، با آمار هرکدوم."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM dooz_head_to_head WHERE user_a_id=? OR user_b_id=?", (user_id, user_id))
    rows = c.fetchall()
    conn.close()
    result = []
    for r in rows:
        if r["user_a_id"] == user_id:
            opp_name, wins, losses = r["user_b_name"], r["wins_a"], r["wins_b"]
        else:
            opp_name, wins, losses = r["user_a_name"], r["wins_b"], r["wins_a"]
        result.append({"name": opp_name, "wins": wins, "losses": losses, "draws": r["draws"], "total": r["total"]})
    result.sort(key=lambda x: x["total"], reverse=True)
    return result


def build_head_to_head_text(h2h_row) -> str:
    lines = ["", "📊 آمار رودررو:", f"کل بازی‌ها: {h2h_row['total']} بار",
             f"{h2h_row['user_a_name']}: {h2h_row['wins_a']} بار برد",
             f"{h2h_row['user_b_name']}: {h2h_row['wins_b']} بار برد"]
    if h2h_row["draws"]:
        lines.append(f"مساوی: {h2h_row['draws']} بار")
    return "\n".join(lines)


def finalize_game(game, board: list, winner: str) -> str:
    """بازی رو تموم‌شده علامت می‌زنه، آمار رو به‌روز می‌کنه، و متنِ آمارِ قابل‌نمایش رو برمی‌گردونه."""
    finish_game(game["game_id"], board)
    if game["vs_bot"]:
        uid, uname = game["player_x_id"], game["player_x_name"]
        if winner == "DRAW":
            record_result_for_user(uid, uname, "draw")
        elif winner == "X":
            record_result_for_user(uid, uname, "win")
        else:
            record_result_for_user(uid, uname, "loss")
        return ""

    x_id, x_name = game["player_x_id"], game["player_x_name"]
    o_id, o_name = game["player_o_id"], game["player_o_name"]
    if winner == "DRAW":
        record_result_for_user(x_id, x_name, "draw")
        record_result_for_user(o_id, o_name, "draw")
        h2h = record_head_to_head(x_id, x_name, o_id, o_name, winner_id=None)
    elif winner == "X":
        record_result_for_user(x_id, x_name, "win")
        record_result_for_user(o_id, o_name, "loss")
        h2h = record_head_to_head(x_id, x_name, o_id, o_name, winner_id=x_id)
    else:
        record_result_for_user(o_id, o_name, "win")
        record_result_for_user(x_id, x_name, "loss")
        h2h = record_head_to_head(x_id, x_name, o_id, o_name, winner_id=o_id)
    return "\n" + build_head_to_head_text(h2h)


# ---------------------------------------------------------------------------
# منطق بازی
# ---------------------------------------------------------------------------
def check_winner(board: list):
    """برگردوندن 'X'، 'O'، 'DRAW' یا None."""
    for a, b, c_ in WIN_LINES:
        if board[a] and board[a] == board[b] == board[c_]:
            return board[a]
    if all(cell for cell in board):
        return "DRAW"
    return None


def minimax(board: list, player: str, bot_mark: str, human_mark: str, depth: int = 0):
    """مینی‌مکس کامل (بدون هرس) - برای دوز به این کوچیکی خیلی سریع اجرا می‌شه."""
    winner = check_winner(board)
    if winner == bot_mark:
        return 10 - depth, None
    if winner == human_mark:
        return depth - 10, None
    if winner == "DRAW":
        return 0, None

    best_score = float("-inf") if player == bot_mark else float("inf")
    best_move = None
    for i in range(9):
        if board[i] == "":
            board[i] = player
            score, _ = minimax(board, human_mark if player == bot_mark else bot_mark, bot_mark, human_mark, depth + 1)
            board[i] = ""
            if player == bot_mark and score > best_score:
                best_score, best_move = score, i
            elif player != bot_mark and score < best_score:
                best_score, best_move = score, i
    return best_score, best_move


def bot_move(board: list, difficulty: str, bot_mark: str, human_mark: str):
    empty = [i for i, v in enumerate(board) if v == ""]
    if not empty:
        return None

    if difficulty == "easy":
        return random.choice(empty)

    if difficulty == "normal":
        # اگه یه حرکت برای بردن هست، بزن
        for i in empty:
            board[i] = bot_mark
            if check_winner(board) == bot_mark:
                board[i] = ""
                return i
            board[i] = ""
        # اگه حریف داره می‌بره، جلوشو بگیر
        for i in empty:
            board[i] = human_mark
            if check_winner(board) == human_mark:
                board[i] = ""
                return i
            board[i] = ""
        # وگرنه اولویت با وسط، بعد گوشه‌ها، بعد رندوم
        for pref in (4, 0, 2, 6, 8):
            if pref in empty:
                return pref
        return random.choice(empty)

    if difficulty == "hard":
        # ۲۵٪ مواقع یه حرکت غیربهینه می‌زنه تا قابل‌شکست باشه، ولی بازم قویه
        if random.random() < 0.25:
            return random.choice(empty)
        _, move = minimax(board[:], bot_mark, bot_mark, human_mark)
        return move if move is not None else random.choice(empty)

    # impossible: همیشه بهینه، حداکثر نتیجه‌ی حریف مساویه
    _, move = minimax(board[:], bot_mark, bot_mark, human_mark)
    return move if move is not None else random.choice(empty)


# ---------------------------------------------------------------------------
# رندر پیام بازی (متن + کیبورد شیشه‌ای)
# ---------------------------------------------------------------------------
def _player_labels(game):
    x_label = f"{MARK_X} {game['player_x_name'] or 'بازیکن ۱'}"
    if game["vs_bot"]:
        diff_fa = DIFFICULTY_LABELS.get(game["difficulty"], "")
        o_label = f"{MARK_O} ربات ({diff_fa})"
    else:
        o_label = f"{MARK_O} {game['player_o_name'] or 'بازیکن ۲'}"
    return x_label, o_label


def build_game_view(game_id: int, board_override=None, winner=None):
    game = get_game(game_id)
    board = board_override if board_override is not None else json.loads(game["board"])
    x_label, o_label = _player_labels(game)

    lines = ["🎮 دوز", f"{x_label}   در مقابل   {o_label}", ""]
    if winner:
        if winner == "DRAW":
            lines.append("🤝 مساوی شد! بازی خوبی بود.")
        elif winner == "X":
            lines.append(f"🎉 برد با {x_label}!")
        else:
            lines.append(f"🎉 برد با {o_label}!")
    else:
        turn_label = x_label if game["turn"] == "X" else o_label
        lines.append(f"نوبت: {turn_label}")
    text = "\n".join(lines)

    buttons = []
    for r in range(3):
        row = []
        for col in range(3):
            i = r * 3 + col
            cell = board[i]
            cell_text = MARK_X if cell == "X" else MARK_O if cell == "O" else MARK_EMPTY
            row.append(InlineKeyboardButton(cell_text, callback_data=f"dooz_move_{game_id}_{i}"))
        buttons.append(row)
    if winner:
        buttons.append([InlineKeyboardButton("🔁 دوباره بازی", callback_data=f"dooz_rematch_{game_id}")])
        buttons.append([InlineKeyboardButton("🗑 بستن بازی", callback_data=f"dooz_close_{game_id}")])
    return text, InlineKeyboardMarkup(buttons)


# ---------------------------------------------------------------------------
# هندلرها
# ---------------------------------------------------------------------------
async def dooz_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🤖 بازی با ربات", callback_data="dooz_mode_bot")],
            [InlineKeyboardButton("👥 بازی با کاربر", callback_data="dooz_mode_user")],
            [InlineKeyboardButton("👤 پروفایل", callback_data="dooz_profile")],
        ]
    )
    await update.message.reply_text("🎮 دوز! حالتت رو انتخاب کن:", reply_markup=keyboard)


async def dooz_mode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    mode = query.data.split("_")[-1]
    if mode == "bot":
        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("😌 آسون", callback_data="dooz_diff_easy"),
                 InlineKeyboardButton("🙂 معمولی", callback_data="dooz_diff_normal")],
                [InlineKeyboardButton("😈 سخت", callback_data="dooz_diff_hard"),
                 InlineKeyboardButton("💀 وحشتناک", callback_data="dooz_diff_impossible")],
            ]
        )
        await query.edit_message_text("درجه سختی رو انتخاب کن:", reply_markup=keyboard)
    else:
        await query.edit_message_text(
            "با اون کسی که می‌خوای باهاش بازی کنی، روی یکی از پیام‌هاش ریپلای بزن و بنویس «بازی»."
        )


async def dooz_diff_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    difficulty = query.data.split("_")[-1]
    user = update.effective_user
    board = [""] * 9
    game_id = create_game(
        chat_id=update.effective_chat.id,
        player_x_id=user.id,
        player_x_name=user.first_name or "بازیکن",
        player_o_id=BOT_SENTINEL,
        player_o_name="ربات",
        vs_bot=True,
        difficulty=difficulty,
        board=board,
        turn="X",
    )
    text, keyboard = build_game_view(game_id)
    await query.edit_message_text(text, reply_markup=keyboard)
    set_message_id(game_id, query.message.message_id)


async def dooz_challenge_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """وقتی کسی روی پیام یکی دیگه ریپلای بزنه و فقط بنویسه «بازی»."""
    msg = update.message
    challenger = update.effective_user
    opponent = msg.reply_to_message.from_user if msg.reply_to_message else None
    if opponent is None:
        await msg.reply_text("باید روی پیامِ همون کسی که می‌خوای باهاش بازی کنی ریپلای بزنی.")
        return
    if opponent.is_bot:
        await msg.reply_text("نمی‌تونم بین تو و یه ربات دیگه بازی راه بندازم؛ یه آدم واقعی رو ریپلای بزن.")
        return
    if opponent.id == challenger.id:
        await msg.reply_text("نمی‌تونی با خودت بازی کنی! روی پیام یکی دیگه ریپلای بزن.")
        return

    board = [""] * 9
    game_id = create_game(
        chat_id=update.effective_chat.id,
        player_x_id=challenger.id,
        player_x_name=challenger.first_name or "بازیکن ۱",
        player_o_id=opponent.id,
        player_o_name=opponent.first_name or "بازیکن ۲",
        vs_bot=False,
        difficulty=None,
        board=board,
        turn="X",
    )
    text, keyboard = build_game_view(game_id)
    sent = await msg.reply_text(text, reply_markup=keyboard)
    set_message_id(game_id, sent.message_id)


async def dooz_move_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    parts = query.data.split("_")
    game_id = int(parts[2])
    idx = int(parts[3])

    game = get_game(game_id)
    if game is None or game["status"] != "active":
        await query.answer("این بازی تموم شده. اگه می‌خوای، دکمه‌ی «دوباره بازی» رو بزن.", show_alert=True)
        return

    board = json.loads(game["board"])
    user = update.effective_user
    current_mark = game["turn"]
    current_player_id = game["player_x_id"] if current_mark == "X" else game["player_o_id"]

    if user.id != current_player_id:
        await query.answer("الان نوبت تو نیست!", show_alert=True)
        return
    if board[idx] != "":
        await query.answer("این خونه پره!", show_alert=True)
        return

    await query.answer()
    board[idx] = current_mark
    winner = check_winner(board)
    if winner:
        stats_text = finalize_game(game, board, winner)
        text, keyboard = build_game_view(game_id, board_override=board, winner=winner)
        await query.edit_message_text(text + stats_text, reply_markup=keyboard)
        return

    next_mark = "O" if current_mark == "X" else "X"
    update_game(game_id, board, next_mark)

    # اگه بازی با رباته و نوبت به ربات (O) رسید، همین‌جا حرکتشو می‌زنه - بدون معطلی
    if game["vs_bot"] and next_mark == "O":
        move_idx = bot_move(board[:], game["difficulty"], bot_mark="O", human_mark="X")
        if move_idx is not None:
            board[move_idx] = "O"
        winner2 = check_winner(board)
        if winner2:
            stats_text = finalize_game(game, board, winner2)
            text, keyboard = build_game_view(game_id, board_override=board, winner=winner2)
            await query.edit_message_text(text + stats_text, reply_markup=keyboard)
            return
        update_game(game_id, board, "X")

    text, keyboard = build_game_view(game_id, board_override=board)
    await query.edit_message_text(text, reply_markup=keyboard)


async def dooz_rematch_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    old_game_id = int(query.data.split("_")[-1])
    old = get_game(old_game_id)
    if old is None:
        await query.answer("بازی قبلی پیدا نشد.", show_alert=True)
        return
    await query.answer()

    board = [""] * 9
    if old["vs_bot"]:
        new_id = create_game(
            chat_id=old["chat_id"],
            player_x_id=old["player_x_id"],
            player_x_name=old["player_x_name"],
            player_o_id=BOT_SENTINEL,
            player_o_name="ربات",
            vs_bot=True,
            difficulty=old["difficulty"],
            board=board,
            turn="X",
        )
    else:
        # نفر اولِ دفعه‌ی قبل، این‌بار دومی می‌شه - منصفانه‌تره
        new_id = create_game(
            chat_id=old["chat_id"],
            player_x_id=old["player_o_id"],
            player_x_name=old["player_o_name"],
            player_o_id=old["player_x_id"],
            player_o_name=old["player_x_name"],
            vs_bot=False,
            difficulty=None,
            board=board,
            turn="X",
        )
    text, keyboard = build_game_view(new_id)
    await query.edit_message_text(text, reply_markup=keyboard)
    set_message_id(new_id, query.message.message_id)


async def dooz_close_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بستن (حذف) پیامِ بازی - چون پیام مشترکه، حذفش برای هر دو طرف یکسان اعمال می‌شه."""
    query = update.callback_query
    game_id = int(query.data.split("_")[-1])
    game = get_game(game_id)
    user_id = update.effective_user.id
    if game is not None:
        participant_ids = {game["player_x_id"], game["player_o_id"]}
        if user_id not in participant_ids:
            await query.answer("این بازی مال تو نیست، فقط بازیکن‌ها می‌تونن ببندنش.", show_alert=True)
            return
    await query.answer()
    try:
        await query.message.delete()
    except Exception:
        await query.edit_message_text("بازی بسته شد. ✅")


async def dooz_profile_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    stats = get_player_stats(user.id)
    lines = [f"👤 پروفایل {user.first_name or 'بازیکن'}", ""]
    if stats is None:
        lines.append("هنوز هیچ بازی دوزی نکردی! یه بازی شروع کن ببین چند تا می‌بری 😉")
    else:
        first_seen = (stats["first_seen"] or "")[:10]
        lines.append(f"تاریخ عضویت (اولین بازی): {first_seen}")
        lines.append(f"جمع کل بازی‌ها: {stats['total_games']}")
        lines.append(f"جمع کل بردها: {stats['wins']}")
        lines.append(f"جمع کل باخت‌ها: {stats['losses']}")
        if stats["draws"]:
            lines.append(f"مساوی‌ها: {stats['draws']}")
        lines.append("")
        opponents = get_opponents_list(user.id)
        if opponents:
            lines.append("👥 کسایی که باهاشون بازی کردی:")
            for opp in opponents:
                extra = f"، {opp['draws']} مساوی" if opp["draws"] else ""
                lines.append(f"- {opp['name']}: {opp['total']} بازی ({opp['wins']} برد، {opp['losses']} باخت{extra})")
        else:
            lines.append("هنوز با کسی بازیِ دونفره نداشتی.")
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ بازگشت", callback_data="dooz_back_main")]])
    await query.edit_message_text("\n".join(lines), reply_markup=keyboard)


async def dooz_back_main_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🤖 بازی با ربات", callback_data="dooz_mode_bot")],
            [InlineKeyboardButton("👥 بازی با کاربر", callback_data="dooz_mode_user")],
            [InlineKeyboardButton("👤 پروفایل", callback_data="dooz_profile")],
        ]
    )
    await query.edit_message_text("🎮 دوز! حالتت رو انتخاب کن:", reply_markup=keyboard)


# ---------------------------------------------------------------------------
# ثبت هندلرها - این تابع رو از bot.py صدا بزن: dooz_game.register(app)
# ---------------------------------------------------------------------------
def register(app: Application):
    # گروه ۲: مستقل از هندلر عمومی متنیِ گروه (group=0) اجرا می‌شه، پس با هم تداخل ندارن
    app.add_handler(CommandHandler("dooz", dooz_entry), group=2)
    app.add_handler(
        MessageHandler(filters.Regex(r"^دوز$") & (filters.ChatType.GROUPS | filters.ChatType.PRIVATE), dooz_entry),
        group=2,
    )
    app.add_handler(
        MessageHandler(filters.Regex(r"^بازی$") & filters.REPLY, dooz_challenge_trigger),
        group=2,
    )
    app.add_handler(CallbackQueryHandler(dooz_mode_callback, pattern="^dooz_mode_"))
    app.add_handler(CallbackQueryHandler(dooz_diff_callback, pattern="^dooz_diff_"))
    app.add_handler(CallbackQueryHandler(dooz_move_callback, pattern="^dooz_move_"))
    app.add_handler(CallbackQueryHandler(dooz_rematch_callback, pattern="^dooz_rematch_"))
    app.add_handler(CallbackQueryHandler(dooz_close_callback, pattern="^dooz_close_"))
    app.add_handler(CallbackQueryHandler(dooz_profile_callback, pattern="^dooz_profile$"))
    app.add_handler(CallbackQueryHandler(dooz_back_main_callback, pattern="^dooz_back_main$"))
