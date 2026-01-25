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
        url = f"https://docs.google.com/document/d/{GOOGLE_DOC_ID}/export?format=txt"
        response = requests.get(url)
        if response.status_code == 200:
            content = response.text
            if "google.com/accounts" in content or "<html" in content[:100]:
                return "Error: Doc is Private. Please share as 'Anyone with the link'."
            return content
        else:
            return f"Error: Cannot fetch doc (Status: {response.status_code})"
    except Exception as e:
        return f"Error: {str(e)}"

# โหลดข้อมูลเก็บใส่ตัวแปร
WARD_KNOWLEDGE_BASE = fetch_ward_knowledge()

# --- รายชื่อโมเดล ---
MANUAL_MODEL_LIST = ['gemini-2.5-pro', 'gemini-1.5-flash', 'gemini-1.5-pro', 'gemini-pro']

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

def get_working_model(full_prompt):
    """ฟังก์ชันกุญแจผี V2: หาโมเดลที่ใช้ได้จริง"""
    last_errors = []

    # 1. Auto-Discovery
    try:
        app.logger.info("🔍 Auto-Discovery Models...")
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                model_name = m.name
                try:
                    model = genai.GenerativeModel(model_name)
                    response = model.generate_content(full_prompt)
                    if response.text:
                        return response.text
                except:
                    continue
    except Exception as e:
        app.logger.error(f"⚠️ Auto-Discovery Failed: {e}")

    # 2. Manual List Fallback
    for model_name in MANUAL_MODEL_LIST:
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(full_prompt)
            if response.text:
                return response.text
        except Exception as e:
            last_errors.append(f"[{model_name}]: {str(e)}")
            continue
            
    return f"พี่มึนๆ นิดหน่อย (AI Error) ทักใหม่นะจ๊ะ 😅\n\nสาเหตุ:\n" + "\n".join(last_errors)

def generate_answer(user_msg):
    if "Error" in WARD_KNOWLEDGE_BASE:
        return f"⚠️ ระบบเอกสารมีปัญหา: {WARD_KNOWLEDGE_BASE}"

    safe_knowledge = WARD_KNOWLEDGE_BASE[:30000]
    
    # --- ปรับ System Prompt ใหม่ตามความต้องการ ---
    system_prompt = f"""
    Role: ผู้ช่วยแพทย์อัจฉริยะ (Medical Order Assistant)
    
    หน้าที่สำคัญสูงสุด:
    1. หากคำถามเกี่ยวกับ "การรักษา", "ยา", "Order", "แก้ไขภาวะ..." (เช่น ปวด, Kต่ำ, Caต่ำ, หอบเหนื่อย, fever):
       - ให้ดึงข้อมูลจาก Ward Knowledge ในส่วน 'Common Order' มาตอบ
       - **ต้องตอบเป็นรายการ Order ที่นำไปเขียนสั่งการรักษาได้เลยทันที**
       - **ต้อง** ระบุหัวข้อสั้นๆ บรรทัดแรกว่า Order สำหรับอะไร (เช่น "Order แก้ปวด:", "Order แก้ K ต่ำ:")
       - **ห้าม** มีคำอธิบายต่อท้าย
       - **ห้าม** ใช้ตัวหนา (**bold**) หรือตัวเอียง (*italic*) หรือเครื่องหมายดอกจัน (*)
       - ใช้เครื่องหมายขีด (-) นำหน้าแต่ละรายการยา
       
    2. หากเป็นคำถามทั่วไปที่ไม่ใช่ออเดอร์ยา (เช่น ถามเบอร์โทร, สถานที่):
       - ให้ตอบแบบรุ่นพี่ใจดี กระชับ เข้าใจง่าย มีอิโมจิ 💖
    
    3. หากไม่พบข้อมูลใน Ward Knowledge:
       - ให้ตอบว่า "ไม่พบข้อมูลนี้ค่ะ" เท่านั้น ห้ามคิดเอง
    
    ตัวอย่างการตอบ (กรณีถาม Order):
    User: ปวด
    AI:
    Order แก้ปวด:
    - Paracetamol (500) 1 tab po prn q 4-6 h
    - Morphine 3 mg IV q 4-6 h
    - Fentanyl 25 mcg IV q 4-6 hr
    
    Ward Knowledge:
    {safe_knowledge}
    """
    
    full_prompt = f"{system_prompt}\n\nQuestion: {user_msg}"
    
    return get_working_model(full_prompt)

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_msg = event.message.text.strip()
    try:
        reply_text = generate_answer(user_msg)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
    except Exception as e:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"System Crash: {str(e)}"))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
