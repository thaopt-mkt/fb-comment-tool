from fastapi import FastAPI, Request, Response

app = FastAPI()

# "Mat khau" de Facebook va server nhan dien nhau khi cai dat webhook.
# Ban co the doi chuoi nay thanh gi tuy thich (khong dau, khong khoang trang).
VERIFY_TOKEN = "apero-comment-tool-2026"


@app.get("/")
def home():
    return {"status": "Tool dang chay!"}


# Facebook goi vao day MOT LAN de xac minh webhook (luc cai dat)
@app.get("/webhook")
def verify_webhook(request: Request):
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return Response(content=challenge, media_type="text/plain")
    return Response(content="Sai verify token", status_code=403)


# Facebook goi vao day MOI KHI co comment moi
@app.post("/webhook")
async def receive_event(request: Request):
    data = await request.json()
    print("==> CO SU KIEN MOI TU FACEBOOK:", flush=True)
    print(data, flush=True)
    return {"status": "ok"}
