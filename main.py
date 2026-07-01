import os
import requests
from fastapi import FastAPI, Request, Response, BackgroundTasks

app = FastAPI()

VERIFY_TOKEN = "apero-comment-tool-2026"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
PAGE_ACCESS_TOKEN = os.environ.get("PAGE_ACCESS_TOKEN", "")

BAT_TU_DONG_DANG = True


@app.get("/")
def home():
    return {"status": "Tool dang chay!"}


@app.get("/webhook")
def verify_webhook(request: Request):
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return Response(content=challenge, media_type="text/plain")
    return Response(content="Sai verify token", status_code=403)


@app.post("/webhook")
async def receive_event(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()
    print("CO SU KIEN MOI TU FACEBOOK:", flush=True)
    print(data, flush=True)
    background_tasks.add_task(xu_ly_su_kien, data)
    return {"status": "ok"}


@app.get("/test-ai")
def test_ai(request: Request):
    msg = request.query_params.get("msg", "San pham nay gia bao nhieu shop?")
    cau_tra_loi = soan_cau_tra_loi(msg)
    gui_discord("Khach test", msg, cau_tra_loi)
    return {"comment": msg, "ai_reply": cau_tra_loi}


@app.get("/test-post")
def test_post(request: Request):
    comment_id = request.query_params.get("comment_id", "")
    comment_text = request.query_params.get("msg", "San pham con hang khong shop?")
    if not comment_id:
        return {"error": "Thieu comment_id"}
    cau_tra_loi = soan_cau_tra_loi(comment_text)
    kq = dang_tra_loi(comment_id, cau_tra_loi)
    return {"comment_id": comment_id, "ai_reply": cau_tra_loi, "ket_qua": kq}


def xu_ly_su_kien(data):
    if data.get("object") != "page":
        print("Bo qua: khong phai su kien Page.", flush=True)
        return
    for entry in data.get("entry", []):
        page_id = entry.get("id")
        for change in entry.get("changes", []):
            if change.get("field") != "feed":
                continue
            value = change.get("value", {})
            if value.get("item") != "comment" or value.get("verb") != "add":
                continue
            if value.get("from", {}).get("id") == page_id:
                print("Bo qua: comment cua chinh Page.", flush=True)
                continue
            comment_id = value.get("comment_id")
            comment_text = value.get("message", "")
            ten_khach = value.get("from", {}).get("name", "Khach")
            if not comment_text:
                continue
            print("Comment tu " + ten_khach + ": " + comment_text, flush=True)
            cau_tra_loi = soan_cau_tra_loi(comment_text)
            print("AI goi y: " + cau_tra_loi, flush=True)
            gui_discord(ten_khach, comment_text, cau_tra_loi)
            if BAT_TU_DONG_DANG and comment_id:
                dang_tra_loi(comment_id, cau_tra_loi)


def soan_cau_tra_loi(comment_text):
    prompt = (
        "Ban la nhan vien cham soc khach hang cua mot fanpage. "
        "Tra loi binh luan cua khach lich su, than thien, ngan gon bang tieng Viet. "
        "Chi tra ve DUY NHAT cau tra loi.\n\n"
        "Binh luan: " + comment_text
    )
    try:
        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
        headers = {"Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY}
        body = {"contents": [{"parts": [{"text": prompt}]}]}
        r = requests.post(url, headers=headers, json=body, timeout=30)
        data = r.json()
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        print("LOI goi Gemini: " + str(e), flush=True)
        return "(Khong soan duoc cau tra loi)"


def dang_tra_loi(comment_id, message):
    url = "https://graph.facebook.com/v25.0/" + comment_id + "/comments"
    params = {"message": message, "access_token": PAGE_ACCESS_TOKEN}
    try:
        r = requests.post(url, params=params, timeout=30)
        kq = r.json()
        if "id" in kq:
            print("DA DANG TRA LOI: " + str(kq["id"]), flush=True)
        else:
            print("LOI dang tra loi: " + str(kq), flush=True)
        return kq
    except Exception as e:
        print("LOI dang (exception): " + str(e), flush=True)
        return {"error": str(e)}


def gui_discord(ten_khach, comment_text, cau_tra_loi):
    if not DISCORD_WEBHOOK_URL:
        return
    noi_dung = "Comment moi tu " + ten_khach + ":\n> " + comment_text + "\n\nAI goi y:\n" + cau_tra_loi
    try:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": noi_dung}, timeout=15)
    except Exception as e:
        print("LOI gui Discord: " + str(e), flush=True)
