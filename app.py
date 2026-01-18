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

# --- ส่วนตั้งค่ากุญแจ ---
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
GOOGLE_DOC_ID = "1-5sv2IDXNZVIOMagq84VecbR7ZxCh9-M7SGcGcYMNRc"

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
genai.configure(api_key=GEMINI_API_KEY)

# --- ฟังก์ชันดึงข้อมูลจาก Google Doc ---
def fetch_ward_knowledge():
    try:
        # แก้ไข URL ให้ถูกต้อง (ลบ Markdown tags ออก)
        url = f"https://docs.google.com/document/d/{GOOGLE_DOC_ID}/export?format=txt"
        response = requests.get(url)
        if response.status_code == 200:
            content = response.text
            # ตรวจสอบว่าติดหน้า Login หรือไม่
            if "google.com/accounts" in content or "<html" in content[:100]:
                return "Error: Doc is Private. Please share as 'Anyone with the link'."
            return content
        else:
            return f"Error: Cannot fetch doc (Status: {response.status_code})"
    except Exception as e:
        return f"Error: {str(e)}"

# โหลดข้อมูลเก็บใส่ตัวแปร
WARD_KNOWLEDGE_BASE = fetch_ward_knowledge()

MODEL_LIST = ['gemini-1.5-flash', 'gemini-1.5-pro', 'gemini-pro']

@app.route("/", methods=['GET'])
def home():
    status = "OK" if "Error" not in WARD_KNOWLEDGE_BASE else "Error"
    return f"<h1>Bot Status: {status}</h1>"

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
    # ถ้า Doc มีปัญหา ให้แจ้งเตือน
    if "Error" in WARD_KNOWLEDGE_BASE:
        return f"⚠️ ระบบเอกสารมีปัญหา: {WARD_KNOWLEDGE_BASE}"

    # Prompt สำหรับ Gemini
    system_prompt = f"""
    Role: Senior Medical Student Mentor (Thai Language)
    Task: Answer questions based on the provided Ward Knowledge.
    Condition: If info is missing, say you don't know but give general advice. Use Emojis.
    
    Ward Knowledge:
    {WARD_KNOWLEDGE_BASE}
    """
    
    full_prompt = f"{system_prompt}\n\nQuestion: {user_msg}"
    
    for model_name in MODEL_LIST:
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(full_prompt)
            if response.text:
                return response.text
        except:
            continue
            
    return "พี่มึนๆ นิดหน่อย (AI Error) ทักใหม่นะจ๊ะ 😅"

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_msg = event.message.text.strip()
    try:
        reply_text = generate_answer(user_msg)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
    except Exception as e:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="System Error"))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
