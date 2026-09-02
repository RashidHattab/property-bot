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

def get_thursdays_count():
    now = datetime.datetime.now()
    year, month = now.year, now.month
    cal = calendar.monthcalendar(year, month)
    thursdays = sum(1 for week in cal if week[3] != 0)
    return thursdays, month, year

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    keyboard = [
        [InlineKeyboardButton("📋 عرض جميع المستأجرين", callback_data="list_all")],
        [InlineKeyboardButton("👤 كشف حساب", callback_data="menu_details"), InlineKeyboardButton("💰 تسجيل دفعة", callback_data="menu_pay")],
        [InlineKeyboardButton("📈 حساب صافي الأرباح", callback_data="menu_profit")],
        [InlineKeyboardButton("➕ إضافة مستأجر", callback_data="menu_add"), InlineKeyboardButton("❌ حذف مستأجر", callback_data="menu_delete")],
        [InlineKeyboardButton("✏️ تعديل بيانات مستأجر", callback_data="menu_edit")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "🏠 **نظام إدارة العقارات والأملاك**\nاختر العملية التي تريدها:"
    
    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    elif update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=reply_markup, parse_mode="Markdown")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    back_btn = [[InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")]]

    if data == "main_menu":
        await start(update, context)

    elif data == "menu_profit":
        thursdays, month, year = get_thursdays_count()
        expenses = (thursdays * 145) + 120
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT SUM(rent) FROM tenants WHERE name NOT LIKE '%فؤاد%'")
            result = cursor.fetchone()
            total_income = result[0] if result[0] else 0
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

        for row in rows:
            bal = row[4]
            status = "🟢 له رصيد" if bal > 0 else ("🔴 عليه إيجار" if bal < 0 else "⚪ مصفر")
            response += f"👤 {row[1]} | 🏠 {row[2]}\n💰 الإيجار: {row[3]} | 💳 الرصيد: **{bal}** ({status})\n---\n"
            total_rent += row[3]
        
        response += f"\n📊 **إجمالي الإيجارات الشهرية المتوقعة:** {total_rent} د.أ\n"
        await query.message.edit_text(response, reply_markup=InlineKeyboardMarkup(back_btn), parse_mode="Markdown")

    elif data in ["menu_details", "menu_pay", "menu_delete", "menu_edit"]:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, property FROM tenants")
            tenants = cursor.fetchall()

        if not tenants:
            await query.message.edit_text("لا يوجد مستأجرين مسجلين.", reply_markup=InlineKeyboardMarkup(back_btn))
            return

        keyboard = []
        if data == "menu_details": prefix = "det_"
        elif data == "menu_pay": prefix = "pay_"
        elif data == "menu_delete": prefix = "del_"
        else: prefix = "edit_"
        
        for i in range(0, len(tenants), 2):
            row = [InlineKeyboardButton(f"👤 {tenants[i][1]}", callback_data=f"{prefix}{tenants[i][0]}")]
            if i + 1 < len(tenants):
                row.append(InlineKeyboardButton(f"👤 {tenants[i+1][1]}", callback_data=f"{prefix}{tenants[i+1][0]}"))
            keyboard.append(row)

        keyboard.append([InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")])
        titles = {
            "menu_details": "اختر المستأجر لعرض كشف الحساب:",
            "menu_pay": "اختر المستأجر لتسجيل الدفعة:",
            "menu_delete": "اختر المستأجر لحذفه:",
            "menu_edit": "اختر المستأجر لتعديل بياناته:"
        }
        await query.message.edit_text(titles[data], reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("det_"):
        tenant_id = int(data.split("_")[1])
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name, property, rent, debt FROM tenants WHERE id = ?", (tenant_id,))
            tenant = cursor.fetchone()
            cursor.execute("SELECT amount, date FROM payments WHERE tenant_id = ? ORDER BY id DESC LIMIT 5", (tenant_id,))
            payments = cursor.fetchall()
        
        bal = tenant[3]
        status = "🟢 رصيد إضافي لصالحه" if bal > 0 else ("🔴 مديون" if bal < 0 else "⚪ رصيده صفر")
        response = (f"👤 الاسم: {tenant[0]}\n🏠 العقار: {tenant[1]}\n"
                    f"💰 الإيجار الشهري: {tenant[2]} د.أ\n"
                    f"💳 الرصيد الحالي: **{bal} د.أ** ({status})\n\n📜 **آخر الدفعات:**\n")
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

    # --- التحديث الجديد: أزرار التعديل ---
    elif data.startswith("edit_"):
        tenant_id = int(data.split("_")[1])
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name, property, rent, debt FROM tenants WHERE id = ?", (tenant_id,))
            t = cursor.fetchone()
        
        edit_keyboard = [
            [InlineKeyboardButton("✏️ تعديل الاسم", callback_data=f"editf_name_{tenant_id}"), InlineKeyboardButton("✏️ تعديل العقار", callback_data=f"editf_prop_{tenant_id}")],
            [InlineKeyboardButton("💰 تعديل الإيجار", callback_data=f"editf_rent_{tenant_id}"), InlineKeyboardButton("💳 تعديل الرصيد", callback_data=f"editf_bal_{tenant_id}")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="menu_edit")]
        ]
        
        msg = (f"👤 **المستأجر:** {t[0]}\n"
               f"🏠 **العقار:** {t[1]}\n"
               f"💰 **الإيجار:** {t[2]}\n"
               f"💳 **الرصيد:** {t[3]}\n\n"
               f"👇 **ماذا تريد أن تعدل؟ (اختر من الأزرار):**")
        await query.message.edit_text(msg, reply_markup=InlineKeyboardMarkup(edit_keyboard), parse_mode="Markdown")

    # معالجة الضغط على أحد أزرار التعديل (الاسم، العقار، الإيجار، الرصيد)
    elif data.startswith("editf_"):
        parts = data.split("_")
        field_code = parts[1]
        tenant_id = int(parts[2])
        
        context.user_data['step'] = 'waiting_edit_field'
        context.user_data['edit_field'] = field_code
        context.user_data['tenant_id'] = tenant_id
        
        field_names = {"name": "الاسم", "prop": "العقار", "rent": "الإيجار", "bal": "الرصيد"}
        msg = f"✏️ حسناً، أرسل **{field_names[field_code]} الجديد** الآن في رسالة:"
        if field_code in ["rent", "bal"]:
            msg += "\n*(الرجاء كتابة رقم فقط)*"
            
        await query.message.edit_text(msg, reply_markup=InlineKeyboardMarkup(back_btn), parse_mode="Markdown")

    elif data.startswith("pay_"):
        tenant_id = int(data.split("_")[1])
        context.user_data['step'] = 'waiting_payment'
        context.user_data['tenant_id'] = tenant_id
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name, debt FROM tenants WHERE id = ?", (tenant_id,))
            t_info = cursor.fetchone()

        await query.message.edit_text(
            f"💰 **{t_info[0]}** (الرصيد الحالي: {t_info[1]} د.أ)\nأرسل **المبلغ المدفوع** كرقم فقط (مثال: 50):",
            reply_markup=InlineKeyboardMarkup(back_btn), parse_mode="Markdown"
        )

    elif data == "menu_add":
        context.user_data['step'] = 'waiting_add'
        await query.message.edit_text(
            "➕ أرسل بيانات المستأجر الجديد هكذا:\n`الاسم | العقار | الإيجار | الرصيد`\n*(مثال: أحمد | شقة 2 | 150 | 0)*",
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
                current_balance, name = cursor.fetchone()
                
                new_balance = current_balance + amount
                cursor.execute("UPDATE tenants SET debt = ? WHERE id = ?", (new_balance, tenant_id))
                
                payment_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
                cursor.execute("INSERT INTO payments (tenant_id, amount, date) VALUES (?, ?, ?)", (tenant_id, amount, payment_date))
                
            context.user_data.clear()
            status = "موجب (له رصيد)" if new_balance > 0 else ("سالب (عليه إيجار)" if new_balance < 0 else "صفر")
            await update.message.reply_text(
                f"✅ تم تسجيل الدفعة بنجاح.\n💳 الرصيد الجديد: **{new_balance} د.أ** ({status})",
                reply_markup=InlineKeyboardMarkup(back_btn), parse_mode="Markdown"
            )
        except Exception:
            await update.message.reply_text("الرجاء إرسال رقم صحيح فقط (مثال: 50).")

    elif step == 'waiting_add':
        try:
            text = update.message.text.strip()
            name, prop, rent, balance = [x.strip() for x in text.split('|')]
            
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("INSERT INTO tenants (name, property, rent, debt) VALUES (?, ?, ?, ?)", (name, prop, float(rent), float(balance)))
            
            context.user_data.clear()
            await update.message.reply_text(f"✅ تمت إضافة **{name}** بنجاح!", reply_markup=InlineKeyboardMarkup(back_btn), parse_mode="Markdown")
        except Exception:
            await update.message.reply_text("خطأ! الصيغة الصحيحة:\nالاسم | العقار | الإيجار | الرصيد")
            
    # --- التحديث الجديد: استلام الحقل المراد تعديله ---
    elif step == 'waiting_edit_field':
        field_code = context.user_data.get('edit_field')
        tenant_id = context.user_data.get('tenant_id')
        new_val = update.message.text.strip()
        
        try:
            if field_code == "rent":
                new_val = float(new_val)
                db_col = "rent"
            elif field_code == "bal":
                new_val = float(new_val)
                db_col = "debt"
            elif field_code == "name":
                db_col = "name"
            elif field_code == "prop":
                db_col = "property"
                
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(f"UPDATE tenants SET {db_col} = ? WHERE id = ?", (new_val, tenant_id))
                
            context.user_data.clear()
            await update.message.reply_text("✅ تم التعديل والحفظ بنجاح!", reply_markup=InlineKeyboardMarkup(back_btn), parse_mode="Markdown")
            
        except ValueError:
            await update.message.reply_text("❌ خطأ! الإيجار والرصيد يجب أن تكون أرقاماً فقط (مثال: 150).")
    else:
        await update.message.reply_text("استخدم الأزرار لإدارة النظام. أرسل /start لعرض القائمة.")

def monthly_rent_update():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE tenants SET debt = debt - rent")

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
