import os
import sys
import logging
from flask import Flask, request, abort

# ไลบรารีหลักของ LINE และ Google Gemini
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import google.generativeai as genai

# เริ่มต้นแอพพลิเคชัน Flask
app = Flask(__name__)

# ตั้งค่า Logger เพื่อดูข้อความแจ้งเตือนเวลาเกิด Error
logging.basicConfig(level=logging.INFO)

# --- 1. ดึงกุญแจจาก Render (Environment Variables) ---
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')

# ตรวจสอบว่าใส่กุญแจครบไหม ถ้าไม่ครบให้แจ้งเตือนทันที
if not all([LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET, GEMINI_API_KEY]):
    app.logger.error("❌ กุญแจไม่ครบ! กรุณาตรวจสอบ Environment Variables ใน Render")
    # ไม่สั่งปิดโปรแกรม แต่จะแจ้งเตือนใน Logs แทน เพื่อให้ Server ยังทำงานได้
else:
    app.logger.info("✅ พบกุญแจครบถ้วน พร้อมทำงาน!")

# --- 2. ตั้งค่าการเชื่อมต่อ ---
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
genai.configure(api_key=GEMINI_API_KEY)

# --- 3. เลือกโมเดล AI (จุดสำคัญ!) ---
# ใช้ 'gemini-pro' เพื่อความเสถียรสูงสุด (แก้ปัญหา Error 404)
try:
    model = genai.GenerativeModel('gemini-pro')
    app.logger.info("🤖 โหลดโมเดล Gemini Pro สำเร็จ")
except Exception as e:
    app.logger.error(f"❌ โหลดโมเดลไม่สำเร็จ: {e}")

# --- 4. บุคลิกของ AI ---
SYSTEM_PROMPT = """
บทบาท: คุณคือพี่รหัส (Mentor) ของนักศึกษาแพทย์
นิสัย: ใจดี, อบอุ่น, ให้กำลังใจ, มีความรู้แน่นปึ้ก, และมีอารมณ์ขันเล็กน้อย
หน้าที่: ตอบคำถามน้องๆ เกี่ยวกับการเตรียมตัวขึ้นคลินิก, การใช้ชีวิตในวอร์ด, หรือเรื่องทั่วไป
คำเตือน: 
- ถ้าเป็นเรื่องการรักษาคนไข้ ให้ตอบเป็นแนวทางทฤษฎี และย้ำเสมอว่า "ควรปรึกษา Staff หรือ Resident หน้างานอีกครั้งนะครับ"
- ใช้ภาษาไทยที่สุภาพแต่เป็นกันเอง มี Emoji ประกอบบ้างตามความเหมาะสม
"""

@app.route("/", methods=['GET'])
def home():
    """หน้าแรกสำหรับตรวจสอบสถานะ Server"""
    return "<h1>✅ LINE Bot is Running! (Version: Gemini Pro)</h1>"

@app.route("/callback", methods=['POST'])
def callback():
    """ฟังก์ชันหลักที่รอรับข้อความจาก LINE"""
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    app.logger.info("📩 ได้รับข้อความใหม่: " + body)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.error("❌ ลายเซ็นไม่ถูกต้อง (Invalid Signature)")
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    """ฟังก์ชันประมวลผลข้อความและตอบกลับ"""
    user_msg = event.message.text.strip()
    user_id = event.source.user_id
    
    app.logger.info(f"💬 น้อง {user_id} ถามว่า: {user_msg}")

    try:
        # รวมคำสั่ง System Prompt เข้ากับคำถามของน้อง
        full_prompt = f"{SYSTEM_PROMPT}\n\nคำถามของน้อง: {user_msg}"
        
        # ส่งให้ Gemini คิดคำตอบ
        response = model.generate_content(full_prompt)
        reply_text = response.text.strip()

        # ส่งข้อความตอบกลับไปที่ LINE
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text)
        )
        app.logger.info("✅ ตอบกลับสำเร็จ")
        
    except Exception as e:
        app.logger.error(f"❌ เกิดข้อผิดพลาด: {e}")
        # กรณี AI มีปัญหา ให้ตอบข้อความสำรองกลับไป
        error_msg = "ตอนนี้พี่มึนๆ นิดหน่อย (ระบบ AI ขัดข้อง) ลองถามใหม่อีกทีนะจ๊ะ 😅"
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=error_msg)
        )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
