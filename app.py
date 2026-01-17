import os
import sys
import logging
import requests
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import google.generativeai as genai

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# --- กุญแจ ---
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
GOOGLE_DOC_ID = "1-5sv2IDXNZVIOMagq84VecbR7ZxCh9-M7SGcGcYMNRc" # ไอดี Doc ของคุณ

if not all([LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET, GEMINI_API_KEY]):
    app.logger.error("❌ กุญแจไม่ครบ!")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
genai.configure(api_key=GEMINI_API_KEY)

# --- ฟังก์ชันดึงความรู้จาก Google Doc ---
def fetch_ward_knowledge():
    """ดึงข้อความทั้งหมดจาก Google Doc มาเก็บไว้"""
    try:
        url = f"https://docs.google.com/document/d/{GOOGLE_DOC_ID}/export?format=txt"
        response = requests.get(url)
        if response.status_code == 200:
            content = response.text
            app.logger.info(f"✅ ดึงข้อมูลจาก Google Doc สำเร็จ ({len(content)} ตัวอักษร)")
            return content
        else:
            app.logger.error(f"❌ ดึงข้อมูลไม่สำเร็จ Status: {response.status_code}")
            return "ไม่สามารถเข้าถึงข้อมูลวอร์ดได้"
    except Exception as e:
        app.logger.error(f"❌ Error fetching doc: {e}")
        return "เกิดข้อผิดพลาดในการดึงข้อมูล"

# โหลดความรู้มาเก็บไว้ในตัวแปรทันทีที่เปิด Server
# (ถ้ามีการแก้ Doc ต้องกด Deploy ใหม่ หรือรอ Server รีสตาร์ทเองข้อมูลถึงจะอัปเดต)
WARD_KNOWLEDGE_BASE = fetch_ward_knowledge()

# --- ระบบเลือกโมเดล (ใช้ 1.5 Flash เป็นหลักเพราะอ่าน Doc ยาวๆ ได้ไว) ---
MODEL_LIST = ['gemini-1.5-flash', 'gemini-1.5-pro', 'gemini-pro']

@app.route("/", methods=['GET'])
def home():
    return f"<h1>✅ LINE Bot with Knowledge Base is Live!</h1><p>Doc Length: {len(WARD_KNOWLEDGE_BASE)} chars</p>"

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

def generate_answer(user_msg):
    # สร้าง Prompt แบบ RAG (Retrieval-Augmented Generation)
    # คือการแนบข้อมูล (Context) ไปพร้อมกับคำถาม
    system_prompt = f"""
    บทบาท: คุณคือ "พี่รหัสสุดใจดี" (Resident Mentoring Bot)
    - หน้าที่: ช่วยแนะนำรุ่นน้องไม่ให้สับสนกับงานในวอร์ด โดยใช้ข้อมูลที่ให้มาตอบคำถามเป็นหลัก
    - สไตล์: กระชับ, เข้าใจง่าย, เป็นธรรมชาติ, ใช้ภาษาพูด, และมี Emoji 💖 ประกอบเสมอ
    
    ข้อมูลความรู้วอร์ด (Context):
    {WARD_KNOWLEDGE_BASE}
    
    คำสั่ง:
    1. ตอบคำถามโดยอ้างอิงข้อมูลใน Context เป็นหลัก
    2. ถ้ามีข้อมูล: สรุปสั้นๆ ให้ได้ใจความ ไม่ต้องยาวเยิ่นเย้อ
    3. ถ้าข้อมูลไม่เกี่ยวข้อง/ไม่มีใน Doc: ให้ตอบว่า "ยังไม่มีข้อมูลนี้ในฐานข้อมูลจ้ะ 😅" แต่สามารถแนะนำความรู้ทั่วไปเบื้องต้นได้ 
       และปิดท้ายว่า "⚠️ ข้อมูลนี้เป็นคำแนะนำเบื้องต้น ควรศึกษาเพิ่มเติมหรือถามพี่ Staff อีกทีนะจ๊ะ"
    """
    
    full_prompt = f"{system_prompt}\n\nคำถามน้อง: {user_msg}"

    for model_name in MODEL_LIST:
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(full_prompt)
            if response.text:
                return response.text
        except:
            continue
            
    return "พี่มึนๆ นิดหน่อย ทักใหม่นะจ๊ะ 😅"

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_msg = event.message.text.strip()
    reply_text = generate_answer(user_msg)
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
