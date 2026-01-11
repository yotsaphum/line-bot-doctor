import os
import sys
from flask import Flask, request, abort

# ไลบรารี LINE และ Google Gemini
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import google.generativeai as genai

app = Flask(__name__)

# --- ดึงกุญแจจาก "ตู้เซฟ" ของ Server (Environment Variables) ---
# วิธีนี้ปลอดภัยกว่าการแปะรหัสในโค้ดโดยตรง
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')

# ตรวจสอบว่าใส่กุญแจครบไหม
if not all([LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET, GEMINI_API_KEY]):
    print("Error: กุญแจ (Environment Variables) ไม่ครบครับ โปรดตรวจสอบที่ Render Dashboard")
    sys.exit(1)

# ตั้งค่าการเชื่อมต่อ
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# ตั้งค่า Persona (บุคลิก) ของบอท
SYSTEM_PROMPT = """
บทบาท: คุณคือพี่รหัส (Mentor) ของนักศึกษาแพทย์
นิสัย: ใจดี, อบอุ่น, ให้กำลังใจ, แต่มีความรู้แน่น
หน้าที่: ตอบคำถามน้องๆ เกี่ยวกับการเตรียมตัวขึ้นคลินิก หรือเรื่องทั่วไป
คำเตือน: ถ้าเป็นเรื่องการรักษาคนไข้ ให้ตอบเป็นแนวทางทฤษฎี และย้ำให้ปรึกษา Staff/Resident หน้างานเสมอ
"""

@app.route("/", methods=['GET'])
def home():
    return "Hello! บอททำงานอยู่ครับ (Bot is running ok)"

@app.route("/callback", methods=['POST'])
def callback():
    # รับ Signature จาก LINE
    signature = request.headers.get('X-Line-Signature', '')
    # รับข้อความ
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    # ตรวจสอบความถูกต้อง
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_msg = event.message.text.strip()
    
    try:
        # 1. ส่งข้อความไปให้ Gemini คิด
        full_prompt = f"{SYSTEM_PROMPT}\n\nน้องถามว่า: {user_msg}"
        response = model.generate_content(full_prompt)
        reply_text = response.text.strip()

        # 2. ส่งคำตอบกลับไปที่ LINE
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text)
        )
    except Exception as e:
        print(f"Error: {e}")
        # กรณีฉุกเฉิน ตอบกลับไปหน่อย
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="ตอนนี้พี่มึนๆ นิดหน่อย ถามใหม่นะจ๊ะ 😅")
        )

if __name__ == "__main__":
    # ใช้พอร์ตที่ Server กำหนดให้
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
