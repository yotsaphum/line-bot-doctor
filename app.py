import os
import sys
import logging
import requests
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, PostbackEvent, ImageSendMessage
import google.generativeai as genai

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# ==========================================
# 🔴 ส่วนตั้งค่ากุญแจ
# ==========================================
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
GOOGLE_DOC_ID = "1-5sv2IDXNZVIOMagq84VecbR7ZxCh9-M7SGcGcYMNRc"

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
genai.configure(api_key=GEMINI_API_KEY)

# ==========================================
# 🧠 ฟังก์ชันดึงข้อมูลจาก Google Doc (ระบบเก่า ยังอยู่ครบ)
# ==========================================
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

WARD_KNOWLEDGE_BASE = fetch_ward_knowledge()
MANUAL_MODEL_LIST = ['gemini-2.5-pro', 'gemini-1.5-flash', 'gemini-1.5-pro', 'gemini-pro']

@app.route("/", methods=['GET'])
def home():
    status = "OK" if "Error" not in WARD_KNOWLEDGE_BASE else "Error"
    return f"<h1>Bot Status: {status} (Rich Menu & AI Order Ready)</h1>"

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
    last_errors = []
    try:
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                model_name = m.name
                try:
                    model = genai.GenerativeModel(model_name)
                    response = model.generate_content(full_prompt)
                    if response.text: return response.text
                except: continue
    except: pass

    for model_name in MANUAL_MODEL_LIST:
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(full_prompt)
            if response.text: return response.text
        except Exception as e:
            last_errors.append(f"[{model_name}]: {str(e)}")
            continue
    return f"พี่มึนๆ นิดหน่อย ทักใหม่นะจ๊ะ 😅"

def generate_answer(user_msg):
    if "Error" in WARD_KNOWLEDGE_BASE:
        return f"⚠️ ระบบเอกสารมีปัญหา: {WARD_KNOWLEDGE_BASE}"
    safe_knowledge = WARD_KNOWLEDGE_BASE[:30000]
    
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
    
    Ward Knowledge:
    {safe_knowledge}
    """
    full_prompt = f"{system_prompt}\n\nQuestion: {user_msg}"
    return get_working_model(full_prompt)

# ==========================================
# 🎯 ส่วนที่ 1: แชท AI (ตอบออเดอร์ยา/ปรึกษา)
# ==========================================
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_msg = event.message.text.strip()
    try:
        reply_text = generate_answer(user_msg)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
    except Exception as e:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"System Crash: {str(e)}"))

# ==========================================
# 🎯 ส่วนที่ 2: ระบบรับการกดปุ่มเมนู (ส่งรูปภาพ/ส่งข้อความ)
# ==========================================
@handler.add(PostbackEvent)
def handle_postback(event):
    data = event.postback.data
    
    try:
        # 1. ระบบส่งรูปภาพ (เวลากดช่อง 1 ในหน้าวอร์ด)
        if data.startswith('send_image_'):
            ward_name = data.split('_')[2]
            
            # 🔴 คุณต้องเอาลิงก์รูปแนะนำวอร์ด (ไฟล์ .jpg/.png) มาใส่ที่นี่
            ward_images = {
                "med": "https://i.ibb.co/wF9ZhXdQ/DALL-E-2024-08-29-19-40-34-A-cute-and-whimsical-sticker-featuring-a-Halloween-themed-scarecrow-in.webp.jpg",      # ตัวอย่างลิงก์
                "surg": "https://i.ibb.co/wF9ZhXdQ/DALL-E-2024-08-29-19-40-34-A-cute-and-whimsical-sticker-featuring-a-Halloween-themed-scarecrow-in.webp",     # ตัวอย่างลิงก์
                "obgyn": "https://i.imgur.com/KxYZ8qB.jpg",    # ตัวอย่างลิงก์
                "ped": "https://i.imgur.com/KxYZ8qB.jpg",      # ตัวอย่างลิงก์
                "rehab": "https://i.imgur.com/KxYZ8qB.jpg",    # ตัวอย่างลิงก์
                "ent": "https://i.imgur.com/KxYZ8qB.jpg",      # ตัวอย่างลิงก์
                "forensic": "https://i.imgur.com/KxYZ8qB.jpg", # ตัวอย่างลิงก์
                "commed": "https://i.imgur.com/KxYZ8qB.jpg"    # ตัวอย่างลิงก์
            }
            
            img_url = ward_images.get(ward_name, "https://i.imgur.com/KxYZ8qB.jpg")
            
            image_message = ImageSendMessage(
                original_content_url=img_url,
                preview_image_url=img_url
            )
            line_bot_api.reply_message(event.reply_token, image_message)

        # 2. ตอบกลับเวลากดปุ่ม "วิธีใช้"
        elif data == 'action_howto':
            msg = "วิธีใช้งานบอทพี่รหัส 💖\n1. พิมพ์อาการหรือภาวะ (เช่น Kต่ำ) เพื่อดู Order ได้เลย\n2. กดเมนูเพื่อค้นหาเอกสารแยกวอร์ด"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=msg))
            
        # 3. ตอบกลับเวลากดปุ่ม "Order ใช้บ่อย"
        elif data == 'action_common_order':
            msg = "พิมพ์อาการหรือภาวะที่ต้องการหาออเดอร์มาได้เลยจ้า เช่น ปวด, Kต่ำ, Caต่ำ 💊"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=msg))
            
        # 4. ตอบกลับเวลากดปุ่ม "ปรึกษา"
        elif data == 'action_consult':
            msg = "มีอะไรอยากปรึกษา หรืออยากให้ช่วยหาข้อมูลในวอร์ด พิมพ์ถามมาได้เลยนะ พี่สแตนด์บายจ้า 💖"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=msg))

    except Exception as e:
        app.logger.error(f"Postback Error: {e}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
