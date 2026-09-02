import sqlite3
import datetime
import calendar
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from apscheduler.schedulers.background import BackgroundScheduler

# --- خادم الويب (Render) ---
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive!")

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), SimpleHandler)
    server.serve_forever()

# --- إدارة قاعدة البيانات (محسنة وسريعة) ---
def get_db_connection():
    return sqlite3.connect('property_manager.db')

def init_db():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tenants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                property TEXT,
                rent REAL,
                debt REAL
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER,
                amount REAL,
                date TEXT,
                FOREIGN KEY(tenant_id) REFERENCES tenants(id)
            )
        ''')

init_db()

# --- دالة حساب عدد أيام الخميس للشهر الحالي ---
def get_thursdays_count():
    now = datetime.datetime.now()
    year, month = now.year, now.month
    cal = calendar.monthcalendar(year, month)
    # رقم 3 يمثل يوم الخميس في البرمجة (يبدأ الأسبوع من الاثنين=0)
    thursdays = sum(1 for week in cal if week[3] != 0)
    return thursdays, month, year

# --- القائمة الرئيسية ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    keyboard = [
        [InlineKeyboardButton("📋 عرض جميع المستأجرين", callback_data="list_all")],
        [InlineKeyboardButton("👤 كشف حساب", callback_data="menu_details"), InlineKeyboardButton("💰 تسجيل دفعة", callback_data="menu_pay")],
        [InlineKeyboardButton("📈 حساب صافي الأرباح", callback_data="menu_profit")],
        [InlineKeyboardButton("➕ إضافة مستأجر", callback_data="menu_add"), InlineKeyboardButton("❌ حذف مستأجر", callback_data="menu_delete")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "🏠 **نظام إدارة العقارات والأملاك**\nاختر العملية التي تريدها:"
    
    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    elif update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=reply_markup, parse_mode="Markdown")

# --- معالجة الأزرار ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    back_btn = [[InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")]]

    if data == "main_menu":
        await start(update, context)

    elif data == "menu_profit":
        # 1. حساب عدد أيام الخميس والتاريخ
        thursdays, month, year = get_thursdays_count()
        
        # 2. حساب المصروفات
        expenses = (thursdays * 145) + 120
        
        # 3. حساب الدخل الكلي باستثناء المستأجر فؤاد
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT SUM(rent) FROM tenants WHERE name NOT LIKE '%فؤاد%'")
            result = cursor.fetchone()
            total_income = result[0] if result[0] else 0
            
        # 4. استخراج الصافي
        net_profit = total_income - expenses
        
        response = (
            f"📈 **تقرير الأرباح - شهر {month}/{year}:**\n\n"
            f"📅 أيام الخميس هذا الشهر: **{thursdays}** أيام\n"
            f"💸 المصاريف `({thursdays} × 145) + 120` = **{expenses} د.أ**\n"
            f"💰 إجمالي الإيجارات (باستثناء فؤاد): **{total_income} د.أ**\n"
            "─────────────────\n"
            f"💵 **صافي الربح الكلي:** **{net_profit} د.أ**"
        )
        await query.message.edit_text(response, reply_markup=InlineKeyboardMarkup(back_btn), parse_mode="Markdown")

    elif data == "list_all":
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, property, rent, debt FROM tenants")
            rows = cursor.fetchall()

        if not rows:
            await query.message.edit_text("لا يوجد مستأجرين مسجلين حالياً.", reply_markup=InlineKeyboardMarkup(back_btn))
            return

        response = "📋 **قائمة المستأجرين والعقارات:**\n\n"
        total_rent = 0
        total_debt = 0

        for row in rows:
            response += f"👤 {row[1]} | 🏠 {row[2]}\n💰 الإيجار: {row[3]} | ⚠️ الدين: {row[4]}\n---\n"
            total_rent += row[3]
            total_debt += row[4]
        
        response += f"\n📊 **إجمالي الإيجارات:** {total_rent} د.أ\n📊 **إجمالي الديون:** {total_debt} د.أ"
        await query.message.edit_text(response, reply_markup=InlineKeyboardMarkup(back_btn), parse_mode="Markdown")

    elif data in ["menu_details", "menu_pay", "menu_delete"]:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, property FROM tenants")
            tenants = cursor.fetchall()

        if not tenants:
            await query.message.edit_text("لا يوجد مستأجرين مسجلين.", reply_markup=InlineKeyboardMarkup(back_btn))
            return

        keyboard = []
        prefix = "det_" if data == "menu_details" else ("pay_" if data == "menu_pay" else "del_")
        # ترتيب المستأجرين في أزرار ثنائية بجانب بعضها
        for i in range(0, len(tenants), 2):
            row = [InlineKeyboardButton(f"👤 {tenants[i][1]}", callback_data=f"{prefix}{tenants[i][0]}")]
            if i + 1 < len(tenants):
                row.append(InlineKeyboardButton(f"👤 {tenants[i+1][1]}", callback_data=f"{prefix}{tenants[i+1][0]}"))
            keyboard.append(row)

        keyboard.append([InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")])
        title = "اختر المستأجر:"
        await query.message.edit_text(title, reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("det_"):
        tenant_id = int(data.split("_")[1])
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name, property, rent, debt FROM tenants WHERE id = ?", (tenant_id,))
            tenant = cursor.fetchone()
            # جلب آخر 5 دفعات فقط
            cursor.execute("SELECT amount, date FROM payments WHERE tenant_id = ? ORDER BY id DESC LIMIT 5", (tenant_id,))
            payments = cursor.fetchall()
        
        response = (f"👤 الاسم: {tenant[0]}\n🏠 العقار: {tenant[1]}\n"
                    f"💰 الإيجار: {tenant[2]} د.أ\n⚠️ الدين الحالي: **{tenant[3]} د.أ**\n\n📜 **آخر الدفعات:**\n")
        if not payments:
            response += "لا توجد دفعات."
        else:
            for p in payments:
                response += f"• `{p[1]}` ⟵ **{p[0]} د.أ**\n"
                
        await query.message.edit_text(response, reply_markup=InlineKeyboardMarkup(back_btn), parse_mode="Markdown")

    elif data.startswith("del_"):
        tenant_id = int(data.split("_")[1])
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM tenants WHERE id = ?", (tenant_id,))
            cursor.execute("DELETE FROM payments WHERE tenant_id = ?", (tenant_id,))
        
        await query.message.edit_text("✅ تم الحذف بنجاح.", reply_markup=InlineKeyboardMarkup(back_btn))

    elif data.startswith("pay_"):
        tenant_id = int(data.split("_")[1])
        context.user_data['step'] = 'waiting_payment'
        context.user_data['tenant_id'] = tenant_id
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name, debt FROM tenants WHERE id = ?", (tenant_id,))
            t_info = cursor.fetchone()

        await query.message.edit_text(
            f"💰 **{t_info[0]}** (الدين: {t_info[1]} د.أ)\nأرسل **المبلغ المدفوع** كرقم فقط (مثال: 50):",
            reply_markup=InlineKeyboardMarkup(back_btn), parse_mode="Markdown"
        )

    elif data == "menu_add":
        context.user_data['step'] = 'waiting_add'
        await query.message.edit_text(
            "➕ أرسل بيانات المستأجر الجديد هكذا:\n`الاسم | العقار | الإيجار | الدين`\nمثال: `أحمد | شقة 2 | 150 | 0`",
            reply_markup=InlineKeyboardMarkup(back_btn), parse_mode="Markdown"
        )

# --- معالجة النصوص للمدخلات ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get('step')
    back_btn = [[InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")]]

    if step == 'waiting_payment':
        try:
            amount = float(update.message.text.strip())
            tenant_id = context.user_data['tenant_id']
            
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT debt, name FROM tenants WHERE id = ?", (tenant_id,))
                current_debt, name = cursor.fetchone()
                
                new_debt = max(0, current_debt - amount)
                cursor.execute("UPDATE tenants SET debt = ? WHERE id = ?", (new_debt, tenant_id))
                
                payment_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
                cursor.execute("INSERT INTO payments (tenant_id, amount, date) VALUES (?, ?, ?)", (tenant_id, amount, payment_date))
                
            context.user_data.clear()
            await update.message.reply_text(
                f"✅ تم الدفع: **{amount} د.أ** لـ **{name}**.\n⚠️ الدين المتبقي: **{new_debt} د.أ**",
                reply_markup=InlineKeyboardMarkup(back_btn), parse_mode="Markdown"
            )
        except Exception:
            await update.message.reply_text("الرجاء إرسال رقم صحيح فقط (مثال: 50).")

    elif step == 'waiting_add':
        try:
            text = update.message.text.strip()
            name, prop, rent, debt = [x.strip() for x in text.split('|')]
            
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("INSERT INTO tenants (name, property, rent, debt) VALUES (?, ?, ?, ?)", (name, prop, float(rent), float(debt)))
            
            context.user_data.clear()
            await update.message.reply_text(f"✅ تمت إضافة **{name}** بنجاح!", reply_markup=InlineKeyboardMarkup(back_btn), parse_mode="Markdown")
        except Exception:
            await update.message.reply_text("خطأ! الصيغة الصحيحة:\nالاسم | العقار | الإيجار | الدين")
    else:
        await update.message.reply_text("استخدم الأزرار لإدارة النظام. أرسل /start لعرض القائمة.")

# --- التحديث الشهري للديون ---
def monthly_rent_update():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE tenants SET debt = debt + rent")

if __name__ == '__main__':
    server_thread = threading.Thread(target=run_web_server, daemon=True)
    server_thread.start()

    TOKEN = "8602954639:AAF3pr8tk4ns8WogFsAlDCITQrtcl7BQAL4"
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    scheduler = BackgroundScheduler()
    scheduler.add_job(monthly_rent_update, 'cron', day=1, hour=0, minute=0)
    scheduler.start()

    app.run_polling(drop_pending_updates=True)
