import os
import time
import secrets
import requests
import psycopg2
from fastapi import FastAPI, Request, Response, BackgroundTasks, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

VERIFY_TOKEN = "apero-comment-tool-2026"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
PAGE_ACCESS_TOKEN = os.environ.get("PAGE_ACCESS_TOKEN", "")
PIXART_PAGE_TOKEN = os.environ.get("PIXART_PAGE_TOKEN", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "apero2026")

BAT_TU_DONG_DANG = True

security = HTTPBasic()


def check_auth(credentials: HTTPBasicCredentials = Depends(security)):
    dung = secrets.compare_digest(credentials.password, DASHBOARD_PASSWORD)
    if not dung:
        raise HTTPException(
            status_code=401,
            detail="Sai mat khau",
            headers={"WWW-Authenticate": "Basic"},
        )
    return True


def get_conn():
    return psycopg2.connect(DATABASE_URL)


def init_db():
    if not DATABASE_URL:
        print("Chua co DATABASE_URL, bo qua init DB.", flush=True)
        return
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE IF NOT EXISTS pages ("
        "id SERIAL PRIMARY KEY, name TEXT, page_id TEXT, "
        "token TEXT, owner TEXT, created_at TIMESTAMP DEFAULT NOW())"
    )
    cur.execute("DROP TABLE IF EXISTS reply_log")
    cur.execute(
        "CREATE TABLE reply_log ("
        "comment_id TEXT PRIMARY KEY, "
        "page_id TEXT, "
        "post_id TEXT, "
        "customer_name TEXT, "
        "comment_text TEXT, "
        "ai_reply_text TEXT, "
        "status TEXT, "
        "replied_at TIMESTAMP DEFAULT NOW())"
    )
    conn.commit()
    cur.close()
    conn.close()
    print("DB init OK", flush=True)


@app.on_event("startup")
def _startup():
    try:
        init_db()
    except Exception as e:
        print("DB init LOI: " + str(e), flush=True)


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


@app.get("/reply-batch")
def reply_batch(request: Request):
    post_id = request.query_params.get("post_id", "")
    limit = request.query_params.get("limit", "10")
    token = PIXART_PAGE_TOKEN
    if not post_id:
        return {"error": "Thieu post_id. Them ?post_id=... vao link."}
    if not token:
        return {"error": "Chua co PIXART_PAGE_TOKEN tren Render."}
    try:
        me = requests.get(
            "https://graph.facebook.com/v20.0/me",
            params={"fields": "id", "access_token": token}, timeout=30
        ).json()
        page_id = me.get("id")
    except Exception as e:
        return {"error": "Khong lay duoc page id: " + str(e)}
    url = "https://graph.facebook.com/v20.0/" + post_id + "/comments"
    params = {
        "fields": "id,message,from,comments{from}",
        "limit": limit,
        "access_token": token,
    }
    try:
        r = requests.get(url, params=params, timeout=30).json()
    except Exception as e:
        return {"error": "Khong lay duoc comment: " + str(e)}
    if "error" in r:
        return {"error_lay_comment": r["error"]}
    comments = r.get("data", [])
    ket_qua = []
    for c in comments:
        cid = c.get("id")
        ctext = c.get("message", "")
        if not ctext:
            ket_qua.append({"comment_id": cid, "status": "bo qua (khong co chu)"})
            continue
        if c.get("from", {}).get("id") == page_id:
            ket_qua.append({"comment_id": cid, "status": "bo qua (comment cua Page)"})
            continue
        replies = c.get("comments", {}).get("data", [])
        da_tra_loi = False
        for rep in replies:
            if rep.get("from", {}).get("id") == page_id:
                da_tra_loi = True
                break
        if da_tra_loi:
            ket_qua.append({"comment_id": cid, "status": "bo qua (da tra loi truoc do)"})
            continue
        cau_tra_loi = soan_cau_tra_loi(ctext)
        kq = dang_tra_loi_voi_token(cid, cau_tra_loi, token)
        ket_qua.append({
            "comment_id": cid,
            "comment": ctext,
            "reply": cau_tra_loi,
            "status": "da dang" if "id" in kq else "loi",
            "chi_tiet": kq,
        })
        time.sleep(3)
    da_dang = sum(1 for x in ket_qua if x.get("status") == "da dang")
    return {"post_id": post_id, "tong_xu_ly": len(ket_qua), "da_dang": da_dang, "chi_tiet": ket_qua}


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(auth: bool = Depends(check_auth)):
    with open("static/index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.get("/api/pages")
def api_list_pages(auth: bool = Depends(check_auth)):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, name, page_id, owner FROM pages ORDER BY owner, name")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    pages = [{"id": r[0], "name": r[1], "page_id": r[2], "owner": r[3]} for r in rows]
    return {"pages": pages}


@app.post("/api/pages")
async def api_add_page(request: Request, auth: bool = Depends(check_auth)):
    body = await request.json()
    token = (body.get("token") or "").strip()
    owner = (body.get("owner") or "").strip()
    if not token:
        return {"error": "Chua nhap token cua Page."}
    if not owner:
        return {"error": "Chua nhap ten nguoi quan ly Page."}
    try:
        info = requests.get(
            "https://graph.facebook.com/v20.0/me",
            params={"fields": "id,name", "access_token": token}, timeout=20
        ).json()
    except Exception as e:
        return {"error": "Khong ket noi duoc Facebook: " + str(e)}
    if "error" in info:
        return {"error": "Token khong dung: " + str(info["error"].get("message", ""))}
    page_id = info.get("id", "")
    name = info.get("name", "(khong ro ten)")
    
    # Tu dong dang ky Webhook cho Page nay
    try:
        sub_url = f"https://graph.facebook.com/v20.0/{page_id}/subscribed_apps"
        sub_res = requests.post(
            sub_url,
            params={"subscribed_fields": "feed", "access_token": token},
            timeout=20
        ).json()
        print("Ket qua dang ky Webhook:", sub_res, flush=True)
    except Exception as e:
        print("Loi dang ky Webhook cho Page:", e, flush=True)
        
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO pages (name, page_id, token, owner) VALUES (%s, %s, %s, %s)",
        (name, page_id, token, owner),
    )
    conn.commit()
    cur.close()
    conn.close()
    return {"ok": True, "name": name, "page_id": page_id}


@app.post("/api/pages/delete")
async def api_delete_page(request: Request, auth: bool = Depends(check_auth)):
    body = await request.json()
    pid = body.get("id")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM pages WHERE id = %s", (pid,))
    conn.commit()
    cur.close()
    conn.close()
    return {"ok": True}

@app.get("/api/pages/{page_id}/posts")
def api_get_page_posts(page_id: str, auth: bool = Depends(check_auth)):
    token = lay_token_page(page_id)
    if not token or token == PAGE_ACCESS_TOKEN:
        return {"error": "Khong tim thay token rieng cho page nay, vui long them page vao he thong lai."}
    url = f"https://graph.facebook.com/v20.0/{page_id}/posts"
    params = {"fields": "id,message,created_time,full_picture,comments.summary(total_count)", "limit": 20, "access_token": token}
    try:
        r = requests.get(url, params=params, timeout=30).json()
        if "error" in r:
            return {"error": r["error"].get("message", "Loi Facebook API")}
        return {"posts": r.get("data", [])}
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/pages/{page_id}/logs")
def api_get_page_logs(page_id: str, auth: bool = Depends(check_auth)):
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT comment_id, post_id, customer_name, comment_text, ai_reply_text, status, replied_at FROM reply_log WHERE page_id = %s ORDER BY replied_at DESC LIMIT 50", (page_id,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        logs = [{"comment_id": r[0], "post_id": r[1], "customer_name": r[2], "comment_text": r[3], "ai_reply_text": r[4], "status": r[5], "replied_at": str(r[6])} for r in rows]
        return {"logs": logs}
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/logs")
def api_get_all_logs(auth: bool = Depends(check_auth)):
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT comment_id, page_id, post_id, customer_name, comment_text, ai_reply_text, status, replied_at FROM reply_log ORDER BY replied_at DESC LIMIT 100")
        rows = cur.fetchall()
        cur.close()
        conn.close()
        logs = [{"comment_id": r[0], "page_id": r[1], "post_id": r[2], "customer_name": r[3], "comment_text": r[4], "ai_reply_text": r[5], "status": r[6], "replied_at": str(r[7])} for r in rows]
        return {"logs": logs}
    except Exception as e:
        return {"error": str(e)}


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
                token = lay_token_page(page_id)
                status_text = "Thất bại"
                if token:
                    kq = dang_tra_loi_voi_token(comment_id, cau_tra_loi, token)
                    if kq and "id" in kq:
                        status_text = "Thành công"
                else:
                    print(f"Khong tim thay token cho page {page_id}, fallback...", flush=True)
                    kq = dang_tra_loi(comment_id, cau_tra_loi)
                    if kq and "id" in kq:
                        status_text = "Thành công (fallback)"
                
                post_id = value.get("post_id", "")
                ghi_log_reply(comment_id, page_id, post_id, ten_khach, comment_text, cau_tra_loi, status_text)

def ghi_log_reply(comment_id, page_id, post_id, customer_name, comment_text, ai_reply_text, status):
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO reply_log (comment_id, page_id, post_id, customer_name, comment_text, ai_reply_text, status) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (comment_id, page_id, post_id, customer_name, comment_text, ai_reply_text, status)
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print("Loi ghi log DB:", e, flush=True)

def lay_token_page(page_id):
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT token FROM pages WHERE page_id = %s", (page_id,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            return row[0]
    except Exception as e:
        print("Loi lay token tu DB:", e, flush=True)
    return PAGE_ACCESS_TOKEN


def soan_cau_tra_loi(comment_text):
    prompt = (
        "You are a friendly customer support agent for a fanpage. "
        "Reply to the customer's comment politely, warmly, and briefly. "
        "IMPORTANT: Always reply in the SAME language as the comment "
        "(if the comment is in Vietnamese, reply in Vietnamese; "
        "if in English, reply in English; match whatever language they use). "
        "Return ONLY the reply text, nothing else.\n\n"
        "Comment: " + comment_text
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


def dang_tra_loi_voi_token(comment_id, message, token):
    url = "https://graph.facebook.com/v20.0/" + comment_id + "/comments"
    params = {"message": message, "access_token": token}
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


def dang_tra_loi(comment_id, message):
    url = "https://graph.facebook.com/v20.0/" + comment_id + "/comments"
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


