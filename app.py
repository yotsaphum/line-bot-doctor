import os
import sys
import logging
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import google.generativeai as genai

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# --- ดึงกุญแจ ---
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')

if not all([LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET, GEMINI_API_KEY]):
    app.logger.error("❌ กุญแจไม่ครบ! โปรดตรวจสอบ Environment Variables")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
genai.configure(api_key=GEMINI_API_KEY)

# --- ฟังก์ชันตรวจสอบรายชื่อโมเดล (Debugger) ---
# จะรันตอนเริ่มระบบเพื่อดูว่า API Key นี้เห็นโมเดลอะไรบ้าง
available_models = []
try:
    app.logger.info("🔍 กำลังตรวจสอบรายชื่อโมเดลที่ใช้ได้...")
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            available_models.append(m.name)
    app.logger.info(f"📋 รายชื่อโมเดลที่ใช้ได้ (Total: {len(available_models)}):")
    for name in available_models:
        app.logger.info(f"  - {name}")
except Exception as e:
    app.logger.error(f"❌ ไม่สามารถดึงรายชื่อโมเดลได้: {e}")

# --- รายชื่อโมเดลที่จะลองเรียกใช้ (Priority List) ---
# เราจะลองไล่จากตัวที่เราอยากได้ที่สุดก่อน
PRIORITY_MODELS = [
    'gemini-2.5-pro',
    'gemini-1.5-pro',
    'gemini-1.5-flash',
    'gemini-pro'
]

SYSTEM_PROMPT = """
คุณคือ "พี่หมอ AI" (Resident Mentoring Bot)
- นิสัย: อบอุ่น, ใจดี, ให้เกียรติ, มีความรู้แพทย์แน่น
- หน้าที่: ให้คำปรึกษาน้อง นศพ. เรื่องการเรียนและการใช้ชีวิตในวอร์ด
- คำเตือน: ถ้าถามเรื่องการรักษาคนไข้ ให้ตอบทฤษฎีและย้ำให้ Consult Staff เสมอ
"""

@app.route("/", methods=['GET'])
def home():
    return f"<h1>✅ LINE Bot Live! <br>Found {len(available_models)} models. Check Logs for details.</h1>"

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

def generate_safe_response(user_msg):
    """ฟังก์ชันกุญแจผี: ลองเรียกโมเดลทีละตัวจนกว่าจะตอบได้"""
    full_prompt = f"{SYSTEM_PROMPT}\n\nคำถามน้อง: {user_msg}"
    
    # 1. ลองวนลูปหาจากรายการที่เราเตรียมไว้
    for model_name in PRIORITY_MODELS:
        try:
            # ตรวจสอบก่อนว่าชื่อโมเดลนี้ มีอยู่ในลิสต์ที่ API อนุญาตไหม (เพื่อลด Error)
            # เราจะลองเรียกใช้ต่อเมื่อมันมีชื่อใกล้เคียง หรือเราจะเสี่ยงดวงเรียกเลยก็ได้
            # แต่วิธีที่ชัวร์คือ ลองเรียกเลย ถ้า Error ค่อยข้าม
            
            app.logger.info(f"🔄 กำลังลองเรียกใช้: {model_name}")
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(full_prompt)
            
            if response.text:
                app.logger.info(f"✅ สำเร็จ! ตอบโดย: {model_name}")
                return response.text
                
        except Exception as e:
            app.logger.warning(f"⚠️ {model_name} ใช้ไม่ได้ ({e}) -> กำลังลองตัวถัดไป...")
            continue
            
    # 2. ถ้าทุกตัวในลิสต์พังหมด ลองใช้ตัวแรกสุดที่เจอใน available_models (ไม้ตายก้นหีบ)
    if available_models:
        backup_name = available_models[0] # หยิบตัวแรกมาใช้เลย
        try:
            app.logger.info(f"🆘 ลองไม้ตายก้นหีบ: {backup_name}")
            model = genai.GenerativeModel(backup_name)
            response = model.generate_content(full_prompt)
            return response.text
        except:
            pass

    return "ขอโทษจ้ะ พี่พยายามนึกแล้วแต่นึกไม่ออกจริงๆ (ระบบ AI ขัดข้องทุกโมเดล)"

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_msg = event.message.text.strip()
    try:
        reply_text = generate_safe_response(user_msg)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
    except Exception as e:
        app.logger.error(f"Critical Error: {e}")
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="ระบบรวนหนักมาก ทักใหม่นะ 😅"))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
