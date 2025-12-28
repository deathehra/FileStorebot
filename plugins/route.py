from aiohttp import web
import aiohttp
import os
import urllib.parse
from datetime import datetime

from database.database import db

routes = web.RouteTableDef()

BOT_USERNAME = os.getenv("BOT_USERNAME")
SHORT_URL = os.getenv("SHORTLINK_URL")
SHORT_API_KEY = os.getenv("SHORTLINK_API")


def detect_browser(request: web.Request) -> str:
    ua = request.headers.get("User-Agent", "").lower()
    if "telegram" in ua:
        return "telegram"
    if "chrome" in ua:
        return "chrome"
    if "firefox" in ua:
        return "firefox"
    return "unknown"


@routes.get("/telegram/{user_id}/{page_token}", allow_head=True)
async def telegram_verify(request: web.Request):
    user_id = int(request.match_info["user_id"])
    page_token = request.match_info["page_token"]

    # 1️⃣ DB CHECK
    user = await db.get_verify_status(user_id)
    if not user or user.get("page_token") != page_token:
        return error_page("Invalid or expired link")

    if user.get("used"):
        return error_page("Verification link already used")

    # 2️⃣ TELEGRAM LINK
    telegram_link = (
        f"https://t.me/{BOT_USERNAME}"
        f"?start=verify_{user['verify_token']}"
    )

    # 3️⃣ SHORT URL (CACHE)
    short_url = user.get("short_url")
    if not short_url:
        encoded = urllib.parse.quote(telegram_link, safe="")
        api_url = (
            f"https://{SHORT_URL}/api"
            f"?api={SHORT_API_KEY}"
            f"&url={encoded}"
        )

        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, timeout=15) as resp:
                data = await resp.json()

        short_url = data.get("shortenedUrl")
        if not short_url:
            return error_page("Shortener failed")

    # 4️⃣ TRACK + MARK USED
    await db.mark_used(
        user_id=user_id,
        short_url=short_url,
        browser=detect_browser(request),
        ip=request.remote,
        used_at=datetime.utcnow()
    )

    # 5️⃣ FLASH VERIFICATION PAGE (NO SHORTENER SHOWN)
    html = f"""
<!DOCTYPE html>
<html>
<head>
  <title>Verifying…</title>
  <meta http-equiv="refresh" content="1;url=/go/{user_id}">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    body {{
      margin:0;
      height:100vh;
      display:flex;
      align-items:center;
      justify-content:center;
      font-family:Arial;
      background:#f1f5f9;
    }}
    .box {{
      text-align:center;
      background:#fff;
      padding:30px;
      border-radius:16px;
      box-shadow:0 20px 40px rgba(0,0,0,.1);
    }}
    .loader {{
      width:40px;
      height:40px;
      border:4px solid #e5e7eb;
      border-top-color:#3b82f6;
      border-radius:50%;
      animation:spin 1s linear infinite;
      margin:auto;
    }}
    @keyframes spin {{ to {{ transform:rotate(360deg) }} }}
  </style>
</head>
<body>
  <div class="box">
    <div class="loader"></div>
    <h3>Verifying…</h3>
    <p>Please wait</p>
  </div>
</body>
</html>
"""
    return web.Response(text=html, content_type="text/html")


@routes.get("/go/{user_id}", allow_head=True)
async def final_redirect(request: web.Request):
    user_id = int(request.match_info["user_id"])
    user = await db.get_verify_status(user_id)

    if not user or not user.get("used") or not user.get("short_url"):
        return error_page("Verification failed")

    raise web.HTTPFound(user["short_url"])


def error_page(msg: str):
    return web.Response(
        text=f"<h3>{msg}</h3>",
        content_type="text/html",
        status=400
    )


def setup_routes(app):
    app.add_routes(routes)
