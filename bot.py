import sqlite3
import datetime
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from apscheduler.schedulers.background import BackgroundScheduler

# خادم ويب وهمي بسيط جداً لترضية منصة Render المجانية وإبقاء البوت شغالاً
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive!")

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), SimpleHandler)
    server.serve_forever()

def init_db():
    conn = sqlite3.connect('property_manager.db')
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
    conn.commit()
    conn.close()

init_db()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    keyboard = [
        [InlineKeyboardButton("📋 عرض جميع المستأجرين والحسابات", callback_data="list_all")],
        [InlineKeyboardButton("👤 كشف حساب مستأجر (عرض الدفعات)", callback_data="menu_details")],
        [InlineKeyboardButton("💰 تسجيل دفعة مالية جديدة", callback_data="menu_pay")],
        [InlineKeyboardButton("➕ إضافة مستأجر جديد", callback_data="menu_add")],
        [InlineKeyboardButton("❌ حذف مستأجر", callback_data="menu_delete")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = "🏠 **نظام إدارة العقارات والأملاك**\nاختر العملية التي تريدها بالضغط على الزر المناسب:"
    
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

    elif data == "list_all":
        conn = sqlite3.connect('property_manager.db')
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, property, rent, debt FROM tenants")
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            await query.message.edit_text("لا يوجد مستأجرين مسجلين حالياً.", reply_markup=InlineKeyboardMarkup(back_btn))
            return

        response = "📋 **قائمة المستأجرين والعقارات:**\n\n"
        total_rent = 0
        total_debt = 0

        for row in rows:
            response += f"🆔 ID: {row[0]}\n👤 الاسم: {row[1]}\n🏠 العقار: {row[2]}\n💰 الإيجار: {row[3]} د.أ\n⚠️ الدين: {row[4]} د.أ\n-------------------\n"
            total_rent += row[3]
            total_debt += row[4]
        
        response += f"\n📊 **المجموع الكلي للإيجارات:** {total_rent} د.أ\n"
        response += f"📊 **المجموع الكلي للديون المستحقة:** {total_debt} د.أ"
        
        await query.message.edit_text(response, reply_markup=InlineKeyboardMarkup(back_btn), parse_mode="Markdown")

    elif data == "menu_details" or data == "menu_pay" or data == "menu_delete":
        conn = sqlite3.connect('property_manager.db')
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, property FROM tenants")
        tenants = cursor.fetchall()
        conn.close()

        if not tenants:
            await query.message.edit_text("لا يوجد مستأجرين مسجلين.", reply_markup=InlineKeyboardMarkup(back_btn))
            return

        keyboard = []
        for t in tenants:
            prefix = "det_" if data == "menu_details" else ("pay_" if data == "menu_pay" else "del_")
            keyboard.append([InlineKeyboardButton(f"👤 {t[1]} ({t[2]})", callback_data=f"{prefix}{t[0]}")])

        keyboard.append([InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")])
        title = "اختر المستأجر لعرض كشف الحساب:" if data == "menu_details" else ("اختر المستأجر لتسجيل الدفعة:" if data == "menu_pay" else "اختر المستأجر المراد حذفه:")
        await query.message.edit_text(title, reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("det_"):
        tenant_id = int(data.split("_")[1])
        conn = sqlite3.connect('property_manager.db')
        cursor = conn.cursor()
        cursor.execute("SELECT name, property, rent, debt FROM tenants WHERE id = ?", (tenant_id,))
        tenant = cursor.fetchone()
        
        cursor.execute("SELECT amount, date FROM payments WHERE tenant_id = ?", (tenant_id,))
        payments = cursor.fetchall()
        conn.close()
        
        response = f"👤 **كشف حساب المستأجر:**\n"
        response += f"👤 الاسم: {tenant[0]}\n"
        response += f"🏠 العقار: {tenant[1]}\n"
        response += f"💰 الإيجار الشهري: {tenant[2]} د.أ\n"
        response += f"⚠️ الدين الحالي المتبقي: {tenant[3]} د.أ\n\n"
        response += f"📜 **سجل الدفعات السابقة:**\n"
        
        if not payments:
            response += "لا توجد دفعات مسجلة حتى الآن."
        else:
            for p in payments:
                response += f"• دفع مبلغ **{p[0]} د.أ** بتاريخ: `{p[1]}`\n"
                
        await query.message.edit_text(response, reply_markup=InlineKeyboardMarkup(back_btn), parse_mode="Markdown")

    elif data.startswith("del_"):
        tenant_id = int(data.split("_")[1])
        conn = sqlite3.connect('property_manager.db')
        cursor = conn.cursor()
        cursor.execute("DELETE FROM tenants WHERE id = ?", (tenant_id,))
        cursor.execute("DELETE FROM payments WHERE tenant_id = ?", (tenant_id,))
        conn.commit()
        conn.close()
        
        await query.message.edit_text("✅ تم حذف المستأجر بنجاح.", reply_markup=InlineKeyboardMarkup(back_btn))

    elif data.startswith("pay_"):
        tenant_id = int(data.split("_")[1])
        context.user_data['step'] = 'waiting_payment'
        context.user_data['tenant_id'] = tenant_id
        
        conn = sqlite3.connect('property_manager.db')
        cursor = conn.cursor()
        cursor.execute("SELECT name, debt FROM tenants WHERE id = ?", (tenant_id,))
        t_info = cursor.fetchone()
        conn.close()

        await query.message.edit_text(
            f"💰 المستأجر: **{t_info[0]}** (الدين الحالي: {t_info[1]} د.أ)\n\n"
            "الرجاء كتابة **المبلغ المدفوع** فقط برقم صحيح (مثال: `50`) وإرساله في المحادثة:",
            reply_markup=InlineKeyboardMarkup(back_btn), parse_mode="Markdown"
        )

    elif data == "menu_add":
        context.user_data['step'] = 'waiting_add'
        await query.message.edit_text(
            "➕ **إضافة مستأجر جديد**\n\n"
            "أرسل البيانات في رسالة واحدة بالترتيب المفصول بفاصلة `|` هكذا:\n"
            "`اسم المستأجر | اسم العقار | الإيجار الشهري | الدين الحالي`\n\n"
            "مثال:\n`أحمد علي | شقة 2 | 150 | 0`",
            reply_markup=InlineKeyboardMarkup(back_btn), parse_mode="Markdown"
        )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get('step')
    back_btn = [[InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")]]

    if step == 'waiting_payment':
        try:
            amount = float(update.message.text.strip())
            tenant_id = context.user_data['tenant_id']
            
            conn = sqlite3.connect('property_manager.db')
            cursor = conn.cursor()
            cursor.execute("SELECT debt, name FROM tenants WHERE id = ?", (tenant_id,))
            result = cursor.fetchone()
            
            if result:
                current_debt, name = result
                new_debt = max(0, current_debt - amount)
                cursor.execute("UPDATE tenants SET debt = ? WHERE id = ?", (new_debt, tenant_id))
                
                payment_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
                cursor.execute("INSERT INTO payments (tenant_id, amount, date) VALUES (?, ?, ?)", (tenant_id, amount, payment_date))
                conn.commit()
                conn.close()
                
                context.user_data.clear()
                await update.message.reply_text(
                    f"✅ تم تسجيل دفعة بقيمة **{amount} د.أ** للمستأجر **{name}** بنجاح.\n"
                    f"📅 التاريخ: {payment_date}\n"
                    f"⚠️ الدين المتبقي: **{new_debt} د.أ**",
                    reply_markup=InlineKeyboardMarkup(back_btn), parse_mode="Markdown"
                )
        except Exception as e:
            await update.message.reply_text("الرجاء إدخال رقم صحيح للمبلغ فقط (مثلاً: 50).")

    elif step == 'waiting_add':
        try:
            text = update.message.text.strip()
            parts = text.split('|')
            name = parts[0].strip()
            property_name = parts[1].strip()
            rent = float(parts[2].strip())
            debt = float(parts[3].strip())

            conn = sqlite3.connect('property_manager.db')
            cursor = conn.cursor()
            cursor.execute("INSERT INTO tenants (name, property, rent, debt) VALUES (?, ?, ?, ?)", (name, property_name, rent, debt))
            conn.commit()
            conn.close()

            context.user_data.clear()
            await update.message.reply_text(f"✅ تم إضافة المستأجر **{name}** بنجاح!", reply_markup=InlineKeyboardMarkup(back_btn), parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text("خطأ في الصيغة! يرجى الإرسال بالشكل الصحيح:\nالاسم | العقار | الإيجار | الدين")
    else:
        await update.message.reply_text("استخدم الأزرار التفاعلية لإدارة العقارات بسهولة. أرسل /start لعرض القائمة.")

def monthly_rent_update():
    conn = sqlite3.connect('property_manager.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE tenants SET debt = debt + rent")
    conn.commit()
    conn.close()

if __name__ == '__main__':
    # تشغيل خادم الويب الوهمي في الخلفية ليتوافق مع Render المجاني (Web Service)
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

    print("البوت يعمل الآن بنظام الأزرار والخادم الوهمي...")
    app.run_polling()
