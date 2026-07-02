import os
import re
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
    cur.execute(
        "CREATE TABLE IF NOT EXISTS reply_log ("
        "comment_id TEXT PRIMARY KEY, "
        "page_id TEXT, "
        "post_id TEXT, "
        "customer_name TEXT, "
        "comment_text TEXT, "
        "ai_reply_text TEXT, "
        "status TEXT, "
        "replied_at TIMESTAMP DEFAULT NOW())"
    )
    cur.execute(
        "CREATE TABLE IF NOT EXISTS monitored_posts ("
        "id SERIAL PRIMARY KEY, "
        "page_db_id INTEGER, "
        "page_id TEXT, "
        "post_id TEXT, "
        "created_at TIMESTAMP DEFAULT NOW())"
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
            "https://graph.facebook.com/v25.0/me",
            params={"fields": "id", "access_token": token}, timeout=30
        ).json()
        page_id = me.get("id")
    except Exception as e:
        return {"error": "Khong lay duoc page id: " + str(e)}
    url = "https://graph.facebook.com/v25.0/" + post_id + "/comments"
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
            "https://graph.facebook.com/v25.0/me",
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
        sub_url = f"https://graph.facebook.com/v25.0/{page_id}/subscribed_apps"
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
    url = f"https://graph.facebook.com/v25.0/{page_id}/posts"
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


def da_tra_loi_chua(comment_id):
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM reply_log WHERE comment_id = %s", (comment_id,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        return row is not None
    except Exception as e:
        print("Loi kiem tra reply_log:", e, flush=True)
        return False


def lay_danh_sach_bai(page_id, token, so_bai):
    post_ids = []
    for edge in ["feed", "ads_posts", "promotable_posts"]:
        try:
            params = {"fields": "id", "limit": str(so_bai), "access_token": token}
            r = requests.get(
                "https://graph.facebook.com/v25.0/" + str(page_id) + "/" + edge,
                params=params, timeout=30,
            ).json()
            if "error" in r:
                print("Bo qua " + edge + ": " + str(r["error"].get("message", "")), flush=True)
                continue
            for p in r.get("data", []):
                pid = p.get("id")
                if pid and pid not in post_ids:
                    post_ids.append(pid)
        except Exception as e:
            print("Loi lay " + edge + ": " + str(e), flush=True)
    return post_ids


def quet_mot_page(name, page_id, token, so_bai, so_cmt, gioi_han_tra_loi):
    ket_qua = {"page": name, "so_bai": 0, "da_tra_loi": 0, "bo_qua": 0, "loi": 0}
    post_ids = lay_danh_sach_bai(page_id, token, so_bai)
    ket_qua["so_bai"] = len(post_ids)
    print("Page " + str(name) + " tim thay " + str(len(post_ids)) + " bai", flush=True)
    for post_id in post_ids:
        try:
            rc = requests.get(
                "https://graph.facebook.com/v25.0/" + str(post_id) + "/comments",
                params={"fields": "id,message,from", "limit": str(so_cmt), "access_token": token},
                timeout=30,
            ).json()
        except Exception:
            continue
        comments = rc.get("data", [])
        for c in comments:
            if ket_qua["da_tra_loi"] >= gioi_han_tra_loi:
                return ket_qua
            cid = c.get("id")
            ctext = c.get("message", "")
            ten_khach = c.get("from", {}).get("name", "Khach")
            from_id = c.get("from", {}).get("id")
            if not ctext:
                ket_qua["bo_qua"] += 1
                continue
            if from_id == str(page_id):
                ket_qua["bo_qua"] += 1
                continue
            if da_tra_loi_chua(cid):
                ket_qua["bo_qua"] += 1
                continue
            cau = soan_cau_tra_loi(ctext)
            kq = dang_tra_loi_voi_token(cid, cau, token)
            if "id" in kq:
                ghi_log_reply(cid, str(page_id), str(post_id), ten_khach, ctext, cau, "da_dang")
                ket_qua["da_tra_loi"] += 1
            else:
                ghi_log_reply(cid, str(page_id), str(post_id), ten_khach, ctext, cau, "loi")
                ket_qua["loi"] += 1
            time.sleep(2)
    return ket_qua


@app.get("/scan-and-reply")
def scan_and_reply(request: Request):
    key = request.query_params.get("key", "")
    if not secrets.compare_digest(key, DASHBOARD_PASSWORD):
        return {"error": "Sai key"}
    so_bai = int(request.query_params.get("posts", "15"))
    so_cmt = int(request.query_params.get("comments", "50"))
    gioi_han = int(request.query_params.get("max", "40"))
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT name, page_id, token FROM pages")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    tong = []
    for name, page_id, token in rows:
        kq = quet_mot_page(name, page_id, token, so_bai, so_cmt, gioi_han)
        tong.append(kq)
        print("QUET XONG PAGE: " + str(kq), flush=True)
    # Quet cac bai theo doi (bai quang cao dan tay)
    kq_theo_doi = quet_cac_bai_theo_doi(so_cmt, gioi_han)
    tong.append(kq_theo_doi)
    print("QUET XONG BAI THEO DOI: " + str(kq_theo_doi), flush=True)
    tong_tra_loi = sum(x["da_tra_loi"] for x in tong)
    return {"tong_tra_loi": tong_tra_loi, "chi_tiet": tong}


def quet_mot_bai(post_id, page_id, token, so_cmt, gioi_han, ket_qua):
    try:
        rc = requests.get(
            "https://graph.facebook.com/v25.0/" + str(post_id) + "/comments",
            params={"fields": "id,message,from", "limit": str(so_cmt), "access_token": token},
            timeout=30,
        ).json()
    except Exception:
        return
    if "error" in rc:
        print("Loi lay comment bai " + str(post_id) + ": " + str(rc["error"].get("message", "")), flush=True)
        return
    for c in rc.get("data", []):
        if ket_qua["da_tra_loi"] >= gioi_han:
            return
        cid = c.get("id")
        ctext = c.get("message", "")
        ten_khach = c.get("from", {}).get("name", "Khach")
        from_id = c.get("from", {}).get("id")
        if not ctext:
            ket_qua["bo_qua"] += 1
            continue
        if from_id == str(page_id):
            ket_qua["bo_qua"] += 1
            continue
        if da_tra_loi_chua(cid):
            ket_qua["bo_qua"] += 1
            continue
        cau = soan_cau_tra_loi(ctext)
        kq = dang_tra_loi_voi_token(cid, cau, token)
        if "id" in kq:
            ghi_log_reply(cid, str(page_id), str(post_id), ten_khach, ctext, cau, "da_dang")
            ket_qua["da_tra_loi"] += 1
        else:
            ghi_log_reply(cid, str(page_id), str(post_id), ten_khach, ctext, cau, "loi")
            ket_qua["loi"] += 1
        time.sleep(2)


def quet_cac_bai_theo_doi(so_cmt, gioi_han):
    ket_qua = {"loai": "bai_theo_doi", "so_bai": 0, "da_tra_loi": 0, "bo_qua": 0, "loi": 0}
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT m.post_id, m.page_id, p.token FROM monitored_posts m "
            "JOIN pages p ON m.page_db_id = p.id"
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        print("Loi doc monitored_posts: " + str(e), flush=True)
        return ket_qua
    ket_qua["so_bai"] = len(rows)
    for post_id, page_id, token in rows:
        quet_mot_bai(post_id, page_id, token, so_cmt, gioi_han, ket_qua)
    return ket_qua


def trich_post_id(link, page_id):
    link = (link or "").strip()
    if not link:
        return None
    m = re.search(r"(\d{5,}_\d{5,})", link)
    if m:
        return m.group(1)
    m = re.search(r"/posts/(\d{5,})", link)
    if m:
        return str(page_id) + "_" + m.group(1)
    m = re.search(r"(?:fbid=|story_fbid=|/videos/|multi_permalinks=)(\d{5,})", link)
    if m:
        return m.group(1)
    m = re.search(r"(\d{8,})", link)
    if m:
        return m.group(1)
    return None


@app.get("/api/monitored")
def api_list_monitored(auth: bool = Depends(check_auth)):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT m.id, m.post_id, p.name FROM monitored_posts m "
        "JOIN pages p ON m.page_db_id = p.id ORDER BY m.id DESC"
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return {"posts": [{"id": r[0], "post_id": r[1], "page_name": r[2]} for r in rows]}


@app.post("/api/monitored")
async def api_add_monitored(request: Request, auth: bool = Depends(check_auth)):
    body = await request.json()
    page_db_id = body.get("page_db_id")
    links = body.get("links", "")
    if not page_db_id:
        return {"error": "Chua chon Page"}
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT page_id FROM pages WHERE id = %s", (page_db_id,))
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        return {"error": "Page khong ton tai"}
    page_id = row[0]
    them = 0
    bo_qua = 0
    for dong in links.splitlines():
        pid = trich_post_id(dong, page_id)
        if not pid:
            bo_qua += 1
            continue
        cur.execute(
            "SELECT 1 FROM monitored_posts WHERE post_id = %s AND page_db_id = %s",
            (pid, page_db_id),
        )
        if cur.fetchone():
            bo_qua += 1
            continue
        cur.execute(
            "INSERT INTO monitored_posts (page_db_id, page_id, post_id) VALUES (%s, %s, %s)",
            (page_db_id, page_id, pid),
        )
        them += 1
    conn.commit()
    cur.close()
    conn.close()
    return {"ok": True, "them": them, "bo_qua": bo_qua}


@app.post("/api/monitored/delete")
async def api_delete_monitored(request: Request, auth: bool = Depends(check_auth)):
    body = await request.json()
    mid = body.get("id")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM monitored_posts WHERE id = %s", (mid,))
    conn.commit()
    cur.close()
    conn.close()
    return {"ok": True}


@app.get("/posts", response_class=HTMLResponse)
def posts_page(auth: bool = Depends(check_auth)):
    return POSTS_HTML


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
    url = "https://graph.facebook.com/v25.0/" + comment_id + "/comments"
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




POSTS_HTML = """
<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bai viet theo doi</title>
<style>
  :root { --bg:#f5f6f8; --card:#fff; --ink:#1a2230; --muted:#6b7688; --line:#e5e8ee; --brand:#2f6f6a; --brand-soft:#e7f1f0; --danger:#b23c3c; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--ink); font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; line-height:1.5; }
  header { background:var(--card); border-bottom:1px solid var(--line); padding:20px 24px; }
  header h1 { margin:0; font-size:19px; }
  header p { margin:4px 0 0; color:var(--muted); font-size:13px; }
  main { max-width:860px; margin:0 auto; padding:24px 20px 60px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:20px; margin-bottom:20px; }
  .card h2 { margin:0 0 4px; font-size:15px; }
  .hint { margin:0 0 16px; color:var(--muted); font-size:13px; }
  label { display:block; font-size:13px; font-weight:600; margin:12px 0 6px; }
  select, textarea { width:100%; padding:10px 12px; border:1px solid var(--line); border-radius:8px; font-size:14px; font-family:inherit; background:#fbfcfd; }
  textarea { min-height:120px; resize:vertical; }
  button { margin-top:14px; background:var(--brand); color:#fff; border:none; padding:10px 18px; border-radius:8px; font-size:14px; font-weight:600; cursor:pointer; }
  button:disabled { opacity:.6; }
  .msg { margin-top:12px; font-size:13px; padding:10px 12px; border-radius:8px; display:none; }
  .msg.ok { background:var(--brand-soft); color:var(--brand); display:block; }
  .msg.err { background:#fbe9e9; color:var(--danger); display:block; }
  table { width:100%; border-collapse:collapse; margin-top:4px; }
  th, td { text-align:left; padding:10px 8px; font-size:14px; border-bottom:1px solid var(--line); }
  th { color:var(--muted); font-size:12px; text-transform:uppercase; }
  code { background:#eef0f4; padding:1px 6px; border-radius:4px; font-size:12px; }
  .del { background:none; color:var(--danger); margin:0; padding:4px 8px; font-size:13px; }
  .empty { color:var(--muted); font-size:14px; padding:16px 0; }
</style>
</head>
<body>
<header>
  <h1>Bai viet theo doi (bai quang cao)</h1>
  <p>Dan link cac bai quang cao de tool tra loi comment tren do.</p>
</header>
<main>
  <div class="card">
    <h2>Them bai viet</h2>
    <p class="hint">Chon Page, roi dan link bai viet (moi link 1 dong, dan nhieu link cung duoc).</p>
    <label>Page</label>
    <select id="page"></select>
    <label>Link bai viet</label>
    <textarea id="links" placeholder="https://www.facebook.com/.../posts/...&#10;https://www.facebook.com/photo?fbid=..."></textarea>
    <button id="addBtn" onclick="addPosts()">Them bai</button>
    <div id="msg" class="msg"></div>
  </div>
  <div class="card">
    <h2>Danh sach bai dang theo doi</h2>
    <div id="list"><div class="empty">Dang tai...</div></div>
  </div>
</main>
<script>
async function loadPages() {
  const sel = document.getElementById('page');
  const res = await fetch('/api/pages');
  const data = await res.json();
  sel.innerHTML = '';
  for (const p of (data.pages || [])) {
    const o = document.createElement('option');
    o.value = p.id; o.textContent = p.name + ' (' + (p.owner || '-') + ')';
    sel.appendChild(o);
  }
}
async function loadPosts() {
  const box = document.getElementById('list');
  const res = await fetch('/api/monitored');
  const data = await res.json();
  const posts = data.posts || [];
  if (posts.length === 0) { box.innerHTML = '<div class="empty">Chua co bai nao.</div>'; return; }
  let html = '<table><tr><th>Post ID</th><th>Page</th><th></th></tr>';
  for (const p of posts) {
    html += '<tr><td><code>' + esc(p.post_id) + '</code></td><td>' + esc(p.page_name) +
      '</td><td><button class="del" onclick="delPost(' + p.id + ')">Xoa</button></td></tr>';
  }
  html += '</table>';
  box.innerHTML = html;
}
async function addPosts() {
  const btn = document.getElementById('addBtn');
  const msg = document.getElementById('msg');
  const page_db_id = document.getElementById('page').value;
  const links = document.getElementById('links').value;
  msg.className = 'msg'; btn.disabled = true; btn.textContent = 'Dang them...';
  try {
    const res = await fetch('/api/monitored', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ page_db_id: parseInt(page_db_id), links: links })
    });
    const data = await res.json();
    if (data.error) { msg.className = 'msg err'; msg.textContent = data.error; }
    else {
      msg.className = 'msg ok';
      msg.textContent = 'Da them ' + data.them + ' bai (bo qua ' + data.bo_qua + ').';
      document.getElementById('links').value = '';
      loadPosts();
    }
  } catch (e) { msg.className = 'msg err'; msg.textContent = 'Loi: ' + e; }
  btn.disabled = false; btn.textContent = 'Them bai';
}
async function delPost(id) {
  if (!confirm('Xoa bai nay?')) return;
  await fetch('/api/monitored/delete', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id: id })
  });
  loadPosts();
}
function esc(s){return String(s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
loadPages();
loadPosts();
</script>
</body>
</html>
"""
