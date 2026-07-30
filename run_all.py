# -*- coding: utf-8 -*-
"""
اجرای هم‌زمانِ ربات + پنل وب تو یه پروسه‌ی واحد.
======================================================
چرا این فایل لازمه؟
پلتفرم‌هایی مثل Railway معمولاً برای هر «سرویس» فقط یه پروسه اجرا می‌کنن و هر سرویس
دیسکِ جدا و ایزوله‌ی خودش رو داره. اگه ربات و پنل رو دو سرویسِ جدا بالا بیاری، هرکدوم
یه فایلِ chatr_bot.db جدا برای خودش می‌سازن و اصلاً همدیگه رو نمی‌بینن!

راه‌حل: همینجا هردوشون رو تو یه سرویسِ واحد (یه پروسه) روشن می‌کنیم - پنل تو یه ترد
پس‌زمینه، ربات تو ترد اصلی - و چون تو یه پروسه‌ن، دقیقاً از یه فایل دیتابیس مشترک
استفاده می‌کنن.

روی Railway کافیه Start Command رو این بذاری:
    python run_all.py
"""
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "panel"))

import bot as bot_module


def _run_panel():
    import app as panel_app  # همون panel/app.py
    port = int(os.environ.get("PORT", os.environ.get("PANEL_PORT", "8080")))
    panel_app.app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    panel_thread = threading.Thread(target=_run_panel, daemon=True)
    panel_thread.start()
    bot_module.main()
