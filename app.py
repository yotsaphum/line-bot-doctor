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

# ตรวจสอบกุญแจ
if not all([LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET, GEMINI_API_KEY]):
    app.logger.error("❌ กุญแจไม่ครบ! โปรดตรวจสอบ Environment Variables ใน Render")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
genai.configure(api_key=GEMINI_API_KEY)

# --- 🎯 จุดเปลี่ยนสำคัญ: ระบบเลือกโมเดลอัจฉริยะ (Auto-Fallback) ---
# เราจะตั้งค่าให้ลองใช้รุ่นใหม่ล่าสุดก่อน ถ้าไม่ได้ให้ถอยกลับรุ่นเสถียร
target_model = 'gemini-2.5-pro'
fallback_model = 'gemini-1.5-pro'

try:
    # ลองตั้งค่าเป็นรุ่นใหม่ล่าสุด
    model = genai.GenerativeModel(target_model)
    app.logger.info(f"✅ Setup Model Priority: {target_model}")
except Exception as e:
    # ถ้าตั้งค่าไม่ผ่าน (เช่น ชื่อผิด) ให้ใช้รุ่นสำรอง
    app.logger.warning(f"⚠️ หาโมเดล {target_model} ไม่เจอ ใช้รุ่นสำรองแทน")
    model = genai.GenerativeModel(fallback_model)

# บุคลิก: พี่หมอ AI (อัปเกรดความฉลาด)
SYSTEM_PROMPT = """
คุณคือ "พี่หมอ AI" (Resident Mentoring Bot) ที่มีความรู้ทางการแพทย์ที่ทันสมัยที่สุด
- นิสัย: อบอุ่น, ให้เกียรติ, อธิบาย Pathophysiology ได้ลึกซึ้งแต่เข้าใจง่าย
- หน้าที่: เป็นที่ปรึกษาให้น้อง นศพ. ทั้งเรื่องความรู้แพทย์ (Medical Knowledge) และ Soft Skills ในวอร์ด
- คำเตือน: หากคำถามเกี่ยวกับการวินิจฉัยคนไข้จริง ให้ตอบแนวทาง Differential Diagnosis ที่เป็นไปได้ และย้ำให้ Consult Staff เสมอ
"""

@app.route("/", methods=['GET'])
def home():
    return f"<h1>✅ LINE Bot Live! (Target: {target_model})</h1>"

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_msg = event.message.text.strip()
    try:
        # ส่งให้ AI คิด
        full_prompt = f"{SYSTEM_PROMPT}\n\nคำถามน้อง: {user_msg}"
        
        # ลองเรียกใช้งานโมเดล
        try:
            response = model.generate_content(full_prompt)
            reply_text = response.text
        except Exception as e_gen:
            # ถ้าเรียกใช้รุ่นใหม่แล้ว Error (เช่น 404 Not Found ตอนรันจริง)
            app.logger.error(f"❌ รุ่น {target_model} ใช้งานไม่ได้ ({e_gen}) -> กำลังสลับไปใช้รุ่นสำรอง...")
            # สลับไปใช้รุ่นสำรองทันทีแบบ Real-time
            backup_model = genai.GenerativeModel(fallback_model)
            response = backup_model.generate_content(full_prompt)
            reply_text = response.text + "\n(ตอบโดยรุ่น 1.5 Pro)" # แจ้งเตือนเล็กน้อย (ลบออกได้)

        if reply_text:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="ขอโทษทีจ้ะ พี่นึกคำตอบไม่ออก (Empty Response)"))
            
    except Exception as e:
        app.logger.error(f"Critical Error: {e}")
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="ระบบพี่รวนนิดหน่อย ทักใหม่นะจ๊ะ 😅"))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
