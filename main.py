import os
import requests
from fastapi import FastAPI, Request, Response, BackgroundTasks

app = FastAPI()

VERIFY_TOKEN = "apero-comment-tool-2026"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
PAGE_ACCESS_TOKEN = os.environ.get("PAGE_ACCESS_TOKEN", "")


@app.get("/")
def home():
    return {"status": "Tool dang chay!"}


# Facebook xac minh webhook (luc cai dat)
@app.get("/webhook")
def verify_webhook(request: Request):
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return Response(content=challenge, media_type="text/plain")
    return Response(content="Sai verify token", status_code=403)


# Facebook gui su kien moi vao day
@app.post("/webhook")
async def receive_event(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()
    print("==> CO SU KIEN MOI TU FACEBOOK:", flush=True)
    print(data, flush=True)
    # Tra loi Facebook ngay, xu ly o nen de tranh timeout
    background_tasks.add_task(xu_ly_su_kien, data)
    return {"status": "ok"}


# Endpoint de TU TEST phan AI (mo bang trinh duyet)
@app.get("/test-ai")
def test_ai(request: Request):
    msg = request.query_params.get("msg", "San pham nay gia bao nhieu vay shop?")
    cau_tra_loi = soan_cau_tra_loi(msg)
    gui_discord("Khach test", msg, cau_tra_loi)
    return {"comment": msg, "ai_reply": cau_tra_loi}


def xu_ly_su_kien(data):
    if data.get("object") != "page":
        print("--> Bo qua: khong phai su kien Page (co the la test gia).", flush=True)
        return
    for entry in data.get("entry", []):
        page_id = entry.get("id")
        for change in entry.get("changes", []):
            if change.get("field") != "feed":
                continue
            value = change.get("value", {})
            if value.get("item") != "comment" or value.get("verb") != "add":
                continue
            from_id = value.get("from", {}).get("id")
            if from_id == page_id:
                print("--> Bo qua: comment do chinh Page dang.", flush=True)
                continue
            comment_text = value.get("message", "")
            ten_khach = value.get("from", {}).get("name", "Khach")
            if not comment_text:
                print("--> Bo qua: comment khong co chu.", flush=True)
                continue
            print(f"--> Comment tu [{ten_khach}]: {comment_text}", flush=True)
            cau_tra_loi = soan_cau_tra_loi(comment_text)
            print(f"--> AI goi y: {cau_tra_loi}", flush=True)
            gui_discord(ten_khach, comment_text, cau_tra_loi)


def soan_cau_tra_loi(comment_text):
    prompt = (
        "Ban la nhan vien cham soc khach hang cua mot fanpage. "
        "Hay tra loi binh luan cua khach mot cach lich su, than thien, ngan gon bang tieng Viet. "
        "Chi tra ve DUY NHAT cau tra loi, khong giai thich gi them.\n\n"
        f"Binh luan: \"{comment_text}\""
    )
    try:
        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
        headers = {"Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY}
        body = {"contents": [{"parts": [{"text": prompt}]}]}
        r = requests.post(url, headers=headers, json=body, timeout=30)
        data = r.json()
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        print(f"--> LOI goi Gemini: {e}", flush=True)
        return "(Khong soan duoc cau tra loi)"


def gui_discord(ten_khach, comment_text, cau_tra_loi):
    if not DISCORD_WEBHOOK_URL:
        return
    noi_dung = (
        f"**Comment moi tu {ten_khach}:**\n> {comment_text}\n\n"
        f"**AI goi y tra loi:**\n{cau_tra_loi}"
    )
    try:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": noi_dung}, timeout=15)
    except Exception as e:
        print(f"--> LOI gui Discord: {e}", flush=True)
