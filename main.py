import os
import time
import secrets
import requests
import psycopg2
from fastapi import FastAPI, Request, Response, BackgroundTasks, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

app = FastAPI()

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
        "comment_id TEXT PRIMARY KEY, replied_at TIMESTAMP DEFAULT NOW())"
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
    return DASHBOARD_HTML


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
                if token:
                    dang_tra_loi_voi_token(comment_id, cau_tra_loi, token)
                else:
                    print(f"Khong tim thay token cho page {page_id}, fallback...", flush=True)
                    dang_tra_loi(comment_id, cau_tra_loi)

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


DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bang dieu khien tra loi comment</title>
<style>
  :root {
    --bg: #f5f6f8;
    --card: #ffffff;
    --ink: #1a2230;
    --muted: #6b7688;
    --line: #e5e8ee;
    --brand: #2f6f6a;
    --brand-soft: #e7f1f0;
    --danger: #b23c3c;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--ink);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    line-height: 1.5;
  }
  header {
    background: var(--card); border-bottom: 1px solid var(--line);
    padding: 20px 24px;
  }
  header h1 { margin: 0; font-size: 19px; letter-spacing: -0.01em; }
  header p { margin: 4px 0 0; color: var(--muted); font-size: 13px; }
  main { max-width: 860px; margin: 0 auto; padding: 24px 20px 60px; }
  .card {
    background: var(--card); border: 1px solid var(--line);
    border-radius: 12px; padding: 20px; margin-bottom: 20px;
  }
  .card h2 { margin: 0 0 4px; font-size: 15px; }
  .card .hint { margin: 0 0 16px; color: var(--muted); font-size: 13px; }
  label { display: block; font-size: 13px; font-weight: 600; margin: 12px 0 6px; }
  input, textarea {
    width: 100%; padding: 10px 12px; border: 1px solid var(--line);
    border-radius: 8px; font-size: 14px; font-family: inherit; background: #fbfcfd;
  }
  textarea { min-height: 70px; resize: vertical; }
  input:focus, textarea:focus { outline: 2px solid var(--brand-soft); border-color: var(--brand); }
  button {
    margin-top: 14px; background: var(--brand); color: #fff; border: none;
    padding: 10px 18px; border-radius: 8px; font-size: 14px; font-weight: 600;
    cursor: pointer;
  }
  button:hover { filter: brightness(1.05); }
  button:disabled { opacity: 0.6; cursor: default; }
  .msg { margin-top: 12px; font-size: 13px; padding: 10px 12px; border-radius: 8px; display: none; }
  .msg.ok { background: var(--brand-soft); color: var(--brand); display: block; }
  .msg.err { background: #fbe9e9; color: var(--danger); display: block; }
  table { width: 100%; border-collapse: collapse; margin-top: 4px; }
  th, td { text-align: left; padding: 10px 8px; font-size: 14px; border-bottom: 1px solid var(--line); }
  th { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.03em; }
  .owner-pill {
    display: inline-block; background: var(--brand-soft); color: var(--brand);
    padding: 2px 10px; border-radius: 999px; font-size: 12px; font-weight: 600;
  }
  .del { background: none; color: var(--danger); margin: 0; padding: 4px 8px; font-size: 13px; }
  .empty { color: var(--muted); font-size: 14px; padding: 16px 0; }
  code { background: #eef0f4; padding: 1px 6px; border-radius: 4px; font-size: 12px; }
</style>
</head>
<body>
<header>
  <h1>Bang dieu khien tra loi comment</h1>
  <p>Quan ly cac Page va token de tra loi binh luan tu dong.</p>
</header>
<main>
  <div class="card">
    <h2>Them Page</h2>
    <p class="hint">Dan Page Access Token va ten nguoi quan ly. He thong tu lay ten Page tu Facebook.</p>
    <label>Nguoi quan ly (ten ban)</label>
    <input id="owner" placeholder="Vi du: Thao">
    <label>Page Access Token</label>
    <textarea id="token" placeholder="Dan token bat dau bang EAA..."></textarea>
    <button id="addBtn" onclick="addPage()">Them Page</button>
    <div id="addMsg" class="msg"></div>
  </div>

  <div class="card">
    <h2>Danh sach Page</h2>
    <p class="hint">Cac Page dang duoc quan ly boi tool.</p>
    <div id="list"><div class="empty">Dang tai...</div></div>
  </div>
</main>

<script>
async function loadPages() {
  const box = document.getElementById('list');
  try {
    const res = await fetch('/api/pages');
    const data = await res.json();
    const pages = data.pages || [];
    if (pages.length === 0) {
      box.innerHTML = '<div class="empty">Chua co Page nao. Them Page o tren.</div>';
      return;
    }
    let html = '<table><tr><th>Ten Page</th><th>Nguoi quan ly</th><th>Page ID</th><th></th></tr>';
    for (const p of pages) {
      html += '<tr>' +
        '<td>' + escapeHtml(p.name) + '</td>' +
        '<td><span class="owner-pill">' + escapeHtml(p.owner || '-') + '</span></td>' +
        '<td><code>' + escapeHtml(p.page_id || '-') + '</code></td>' +
        '<td><button class="del" onclick="delPage(' + p.id + ')">Xoa</button></td>' +
        '</tr>';
    }
    html += '</table>';
    box.innerHTML = html;
  } catch (e) {
    box.innerHTML = '<div class="empty">Loi tai danh sach: ' + e + '</div>';
  }
}

async function addPage() {
  const btn = document.getElementById('addBtn');
  const msg = document.getElementById('addMsg');
  const owner = document.getElementById('owner').value.trim();
  const token = document.getElementById('token').value.trim();
  msg.className = 'msg';
  msg.style.display = 'none';
  btn.disabled = true;
  btn.textContent = 'Dang them...';
  try {
    const res = await fetch('/api/pages', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ owner: owner, token: token })
    });
    const data = await res.json();
    if (data.error) {
      msg.className = 'msg err';
      msg.textContent = data.error;
    } else {
      msg.className = 'msg ok';
      msg.textContent = 'Da them Page: ' + data.name;
      document.getElementById('token').value = '';
      loadPages();
    }
  } catch (e) {
    msg.className = 'msg err';
    msg.textContent = 'Loi: ' + e;
  }
  btn.disabled = false;
  btn.textContent = 'Them Page';
}

async function delPage(id) {
  if (!confirm('Xoa Page nay khoi tool?')) return;
  await fetch('/api/pages/delete', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id: id })
  });
  loadPages();
}

function escapeHtml(s) {
  return String(s || '').replace(/[&<>"']/g, function(c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
  });
}

loadPages();
</script>
</body>
</html>
"""
