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
GOOGLE_DOC_ID = "1ogQGGyCZekpLAl6UlUyTzkOQQ9qrBU7iVYGJ945wVmw"

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
# ⚡ ปรับให้ใช้รุ่น flash ก่อนเพื่อนเพราะตอบไวสุด
MANUAL_MODEL_LIST = ['gemini-1.5-flash', 'gemini-2.5-pro', 'gemini-1.5-pro', 'gemini-pro']

# ⚡ ตัวแปรความจำ: จำว่าโมเดลไหนใช้งานได้ จะได้ไม่ต้องหาใหม่ทุกรอบ
WORKING_MODEL_NAME = None 

@app.route("/", methods=['GET'])
def home():
    status = "OK" if "Error" not in WARD_KNOWLEDGE_BASE else "Error"
    return f"<h1>Bot Status: {status} (Playful AI + Speed Boost Ready)</h1>"

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
    global WORKING_MODEL_NAME
    
    # ⚡ ถ้าจำได้ว่าโมเดลไหนเวิร์ก ให้ใช้โมเดลนั้นเลย (ไม่ต้องไปวนลูปหาให้เสียเวลา)
    if WORKING_MODEL_NAME:
        try:
            model = genai.GenerativeModel(WORKING_MODEL_NAME)
            response = model.generate_content(full_prompt)
            if response.text: 
                return response.text
        except Exception as e:
            app.logger.warning(f"Cached model {WORKING_MODEL_NAME} failed: {e}. Retrying...")
            WORKING_MODEL_NAME = None # ถ้าพัง ค่อยล้างความจำแล้วหาใหม่
            
    last_errors = []
    
    # วนหาจาก Manual List ทันที (ตัดส่วน Auto-Discovery ที่ช้าทิ้งไป)
    for model_name in MANUAL_MODEL_LIST:
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(full_prompt)
            if response.text: 
                WORKING_MODEL_NAME = model_name # ⚡ จำไว้ใช้รอบหน้า!
                return response.text
        except Exception as e:
            last_errors.append(f"[{model_name}]: {str(e)}")
            continue
            
    return f"พี่มึนๆ นิดหน่อย ทักใหม่นะจ๊ะ 😅"

def generate_answer(user_msg):
    if "Error" in WARD_KNOWLEDGE_BASE:
        return f"⚠️ ระบบเอกสารมีปัญหา: {WARD_KNOWLEDGE_BASE}"
    safe_knowledge = WARD_KNOWLEDGE_BASE[:30000]
    
    system_prompt = f"""
    Role: รุ่นพี่แพทย์สุดใจดี และแอบกวนนิดๆ (Friendly & Playful Senior Medical Assistant)
    
    🛑 กฎเหล็กข้อที่ 0 (สำคัญที่สุด): 
    - **ห้าม** พิมพ์กระบวนการคิด (Thinking process) หรือภาษาอังกฤษออกมาเด็ดขาด พิมพ์แค่คำตอบภาษาไทย
    
    หน้าที่สำคัญสูงสุด:
    1. หากคำถามเกี่ยวกับ "การรักษา", "ยา", "Order", "แก้ไขภาวะ..." (เช่น ปวด, Kต่ำ, Caต่ำ, หอบเหนื่อย, fever):
       - ให้ดึงข้อมูลจาก Ward Knowledge ในส่วน 'Common Order' มาตอบ
       - **ต้องตอบเป็นรายการ Order ที่นำไปเขียนสั่งการรักษาได้เลยทันที**
       - **ต้อง** ระบุหัวข้อสั้นๆ บรรทัดแรกว่า Order สำหรับอะไร (เช่น "Order แก้ปวด:", "Order แก้ K ต่ำ:")
       - **ห้าม** มีคำอธิบายต่อท้าย
       - **ห้าม** ใช้ตัวหนา (**bold**) หรือตัวเอียง (*italic*) หรือเครื่องหมายดอกจัน (*)
       - ใช้เครื่องหมายขีด (-) นำหน้าแต่ละรายการยา
       
    2. กรณีคุยเล่น, บ่น, ถามเรื่องสัพเพเหระ (เช่น หิว, ง่วง, อยากรวย, จีบได้ไหม):
       - ให้ตอบแบบรุ่นพี่ที่สนิทกัน กวนๆ ขำๆ กระชับ เข้าใจง่าย มีอิโมจิ 💖 แต่ยังมีความน่ารักและให้กำลังใจ 💖
       - สามารถใช้ความรู้ทั่วไปของ AI ตอบได้เลย (ไม่ต้องหาในเอกสาร)
       
    3. กรณีถามเรื่องงานในวอร์ด แต่ "ไม่มีข้อมูล" ในเอกสารจริงๆ:
       - ให้ตอบประมาณว่า "พี่หาข้อมูลนี้ไม่เจอจ้ะ ลองถามเพื่อนหรือ Staff ดูน้า 😅
       
    ตัวอย่างการตอบ (ห้ามใช้ตัวหนา หรืออธิบายต่อท้ายเด็ดขาด):
    
    User: ปวด
    AI:
    Order แก้ปวด:
    - Paracetamol (500) 1 tab po prn q 4-6 h
    - Morphine 3 mg IV q 4-6 h
    - Fentanyl 25 mcg IV q 4-6 hr
    - Tramadol (Tramol) 50 mg 1×3 po pc prn
    - MOIR (10) 1/2 tab po prn q 2 hr
    
    User: แก้ K ต่ำ
    AI:
    Order แก้ K ต่ำ:
    - EKCl (13mEq/15ml) 15 ml po q 3-4 h x 2 doses
    - KCl 20-40 mEq in NSS 1000 ml IV rate 80 ml/hr
    - K2PO4 20-40mEq + NSS 1000ml IV drip 40-80ml/hr (ใช้กรณีแก้พร้อม Phos ต่ำ)

    User: แก้ K สูง
    AI:
    Order แก้ K สูง:
    - 10% Ca gluconate 10 ml IV slowly push
    - RI 10 ū + 50% Glucose 50 ml IV (K shift)
    - 7.5% NaHCO3 50 ml iv slowly push (K shift)
    - Kalimate 15 g + Water 150 ml po + Lactulose 30 ml po hs

    User: Ca ต่ำ
    AI:
    Order แก้ Ca ต่ำ:
    - 10% Ca gluconate 10 ml IV slowly push

    User: P ต่ำ
    AI:
    Order แก้ PO4 ต่ำ:
    - Phosphate mixture 30 ml PO q 3 hour × 2 dose
    - glycophos 20 mEq + NSS 200 ml IV drip in 6 hr
    - K2PO4 40 mEq + 5DN/2 1000 ml IV rate 80 ml/h

    User: Mg ต่ำ
    AI:
    Order แก้ Mg ต่ำ:
    - 50% MgSO4 4 g + 5DW 100 ml IV drip in 4 hr × 3 days

    User: หอบเหนื่อย
    AI:
    Order หอบเหนื่อย:
    - Oxygen cannula 3 LPM keep SpO2 > 94%
    - Salbutamol NB 1 dose prn for wheezing
    
    User: ง่วงนอนไม่อยากตื่นไปวอร์ด
    AI:
    ไม่ได้นะน้องหมอ! คนไข้รออยู่ รีบตื่นไปราวด์วอร์ดเดี๋ยวนี้เลยยย ดื่มกาแฟสักแก้วแล้วลุย! ☕✌️

    User: อยากรวยทำไงพี่
    AI:
    ตั้งใจเรียนจบไปเป็นหมอก่อนเลยจ้า! หรือไม่ก็แวะไปแผงลอตเตอรี่หน้าโรงพยาบาลนะ สู้ๆ 💸
    
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
# 🎯 ส่วนที่ 2: ระบบรับการกดปุ่มเมนู (ส่งรูปภาพ + ข้อความ)
# ==========================================
@handler.add(PostbackEvent)
def handle_postback(event):
    data = event.postback.data
    
    try:
        # 1. ระบบส่งรูปภาพ + ข้อความ (เวลากดช่อง 1 ในหน้าวอร์ด)
        if data.startswith('send_image_'):
            ward_name = data.split('_')[2]
            
            # 🔴 คลังเก็บลิงก์รูปแนะนำวอร์ด
            ward_images = {
                "med": "https://i.ibb.co/G3NML7T6/Gemini-Generated-Image-5h0pm85h0pm85h0p.png",
                "surg": "https://i.ibb.co/bRmbCrn3/Gemini-Generated-Image-8858zn8858zn8858.png",
                "obgyn": "https://i.ibb.co/QBzL0R8/Gemini-Generated-Image-yefn6uyefn6uyefn.png",
                "ped": "https://i.ibb.co/wF7gwkKf/Gemini-Generated-Image-ldfokcldfokcldfo.png",
                "rehab": "https://i.ibb.co/gL2Bb2pf/Gemini-Generated-Image-490woq490woq490w.png",
                "ent": "https://i.ibb.co/KxC8LxWZ/Gemini-Generated-Image-b6ti71b6ti71b6ti.png",
                "forensic": "https://i.ibb.co/21xYTCf8/Gemini-Generated-Image-hzmr14hzmr14hzmr.png",
                "commed": "https://i.ibb.co/kVGVFjxg/Gemini-Generated-Image-wx1ccawx1ccawx1c.png"
            }
            img_url = ward_images.get(ward_name, "https://i.ibb.co/G3NML7T6/Gemini-Generated-Image-5h0pm85h0pm85h0p.png")
            
            # 🔴 คลังเก็บข้อความต้อนรับของแต่ละวอร์ด (แก้ภาษาไทยได้เลย!)
            ward_texts = {
                "med": "ยินดีต้อนรับสู่วอร์ดอายุรกรรม (Med) จ้า 🩺\nขอให้สนุกกับการเรียนนะ!\n \nSurvival guide MED ลองอ่านดูเพื่อเพิ่มความเข้าใจจจ \nhttps://drive.google.com/file/d/19LXhe-klT2OP-CydKMffpB3GhCB1qIo3/view?usp=drive_link",
                "surg": "ยินดีต้อนรับสู่วอร์ดศัลยกรรม (Surg) จ้า 🔪\nเตรียมตัวให้พร้อม สู้ๆ!\n \nSurvival guide Surg ลองอ่านดูเพื่อเพิ่มความเข้าใจจจ \nhttps://drive.google.com/file/d/10_469aJQifhtpjXE82PF-kaQAYMm2dod/view?usp=drive_link",
                "obgyn": "ยินดีต้อนรับสู่วอร์ดสูตินรีเวช (OBGYN) จ้า 👶\nสู้ๆ นะน้องหมอ!\n \nSurvival guide OBGYN ลองอ่านดูเพื่อเพิ่มความเข้าใจจจ \nhttps://drive.google.com/file/d/1k3hhjwwYOz6bpatTv7kT9n84O1LMlwtN/view?usp=drive_link",
                "ped": "ยินดีต้อนรับสู่วอร์ดกุมารเวชกรรม (Ped) จ้า 🍼\nเด็กๆ น่ารัก สู้ๆ นะ!\n \nSurvival guide Ped ลองอ่านดูเพื่อเพิ่มความเข้าใจจจ \nhttps://drive.google.com/file/d/1AZ4b5Xi5RAtT-MgLetihuyuSTrAI6SIg/view?usp=drive_link",
                "rehab": "ยินดีต้อนรับสู่วอร์ดเวชศาสตร์ฟื้นฟู (Rehab) จ้า 🏃\nลุยเลยจ้า!\n \nSurvival guide Rehab ลองอ่านดูเพื่อเพิ่มความเข้าใจจจ \nhttps://drive.google.com/file/d/18la53uxr3rfhbtcRXHv6Q2I35nEZbP40/view?usp=drive_link",
                "ent": "ยินดีต้อนรับสู่วอร์ดหูคอจมูก (ENT) จ้า 👂\nขอให้โชคดีนะ!\n \nSurvival guide ENT ลองอ่านดูเพื่อเพิ่มความเข้าใจจจ \nhttps://drive.google.com/file/d/18la53uxr3rfhbtcRXHv6Q2I35nEZbP40/view?usp=drive_link",
                "forensic": "ยินดีต้อนรับสู่วอร์ดนิติเวช (Forensic) จ้า 🕵️\nเรียนรู้ให้เต็มที่เลย!\n \nSurvival guide Forensic ลองอ่านดูเพื่อเพิ่มความเข้าใจจจ \nhttps://drive.google.com/file/d/18la53uxr3rfhbtcRXHv6Q2I35nEZbP40/view?usp=drive_link",
                "commed": "ยินดีต้อนรับสู่วอร์ดเวชศาสตร์ชุมชน (Commed) จ้า 🏘️\nลุยชุมชนให้สนุกนะ!\n \nSurvival guide Commed ลองอ่านดูเพื่อเพิ่มความเข้าใจจจ \nhttps://drive.google.com/file/d/18la53uxr3rfhbtcRXHv6Q2I35nEZbP40/view?usp=drive_link"
            }
            text_msg = ward_texts.get(ward_name, "ยินดีต้อนรับสู่วอร์ดจ้า 💖\nสู้ๆ นะ!")

            # เตรียมข้อความรูปภาพ และ ข้อความตัวหนังสือ
            image_message = ImageSendMessage(
                original_content_url=img_url,
                preview_image_url=img_url
            )
            text_message = TextSendMessage(text=text_msg)

            # ส่งกลับไปพร้อมกัน 2 อย่าง (รูป + ข้อความ)
            line_bot_api.reply_message(event.reply_token, [image_message, text_message])

    except Exception as e:
        app.logger.error(f"Postback Error: {e}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
