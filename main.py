import os
import sys
import logging
import subprocess
import asyncio
from fastapi import FastAPI, BackgroundTasks, Request
import requests

from dotenv import load_dotenv
load_dotenv()
# ===== LOGGING SETUP =====
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],  # ép log ra stdout
    force=True,
)
logger = logging.getLogger("opencode-bot")

app = FastAPI()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GITHUB_PAT = os.getenv("GITHUB_PAT")
REPO_URL = os.getenv("REPO_URL")

VAULT_DIR = "/tmp/obsidian_vault"


def send_telegram(chat_id: int, text: str):
    logger.info(f"[TELEGRAM] Gửi tới chat_id={chat_id}: {text[:100]}")
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)
        logger.info(f"[TELEGRAM] Status={resp.status_code} Response={resp.text[:200]}")
    except Exception as e:
        logger.error(f"[TELEGRAM] Lỗi khi gửi tin nhắn: {e}")


def run_cmd(cmd: list[str], cwd: str = None, check: bool = False):
    """Wrapper chạy subprocess + log đầy đủ stdout/stderr/returncode"""
    logger.info(f"[CMD] Chạy: {' '.join(cmd)} (cwd={cwd})")
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    logger.info(f"[CMD] returncode={result.returncode}")
    if result.stdout:
        logger.info(f"[CMD][stdout]\n{result.stdout}")
    if result.stderr:
        logger.info(f"[CMD][stderr]\n{result.stderr}")
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, cmd, result.stdout, result.stderr)
    return result


def setup_and_sync_git():
    logger.info("=== BẮT ĐẦU sync Git ===")
    if not os.getenv("GITHUB_PAT") or not os.getenv("REPO_URL"):
        logger.error("[GIT] Thiếu GITHUB_PAT hoặc REPO_URL trong biến môi trường!")
        raise RuntimeError("Missing GITHUB_PAT or REPO_URL env var")

    if not os.path.exists(VAULT_DIR):
        logger.info(f"[GIT] Thư mục {VAULT_DIR} chưa tồn tại -> clone mới")
        auth_repo_url = REPO_URL.replace("https://", f"https://x-access-token:{GITHUB_PAT}@")
        run_cmd(["git", "clone", auth_repo_url, VAULT_DIR], check=True)
        run_cmd(["git", "config", "user.name", "Render-Bot"], cwd=VAULT_DIR)
        run_cmd(["git", "config", "user.email", "bot@render.com"], cwd=VAULT_DIR)
        logger.info("[GIT] Clone + config xong")
    else:
        logger.info(f"[GIT] Thư mục {VAULT_DIR} đã tồn tại -> pull mới nhất")
        run_cmd(["git", "pull"], cwd=VAULT_DIR)
    logger.info("=== KẾT THÚC sync Git ===")


async def process_opencode_task(user_prompt: str, chat_id: int):
    logger.info(f"### BẮT ĐẦU TASK cho chat_id={chat_id} | prompt='{user_prompt}' ###")
    try:
        # 1. Sync Git
        setup_and_sync_git()

        # 2. Gọi Opencode CLI headless (chế độ 1-lần cho script)
        #    --auto: tự duyệt permission, tránh treo vì không có TTY
        #    GITHUB_TOKEN: dùng GITHUB_PAT sẵn có để chạy model free qua GitHub Copilot
        cmd = ["opencode", "run", "--auto", user_prompt]
        logger.info(f"[OPENCODE] Chạy lệnh: {' '.join(cmd)} (cwd={VAULT_DIR})")

        env = os.environ.copy()
        if not env.get("GITHUB_TOKEN") and GITHUB_PAT:
            env["GITHUB_TOKEN"] = GITHUB_PAT

        process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=VAULT_DIR,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        stdout_text = stdout.decode("utf-8", errors="replace")
        stderr_text = stderr.decode("utf-8", errors="replace")

        logger.info(f"[OPENCODE] returncode={process.returncode}")
        if stdout_text:
            logger.info(f"[OPENCODE][stdout]\n{stdout_text}")
        if stderr_text:
            logger.info(f"[OPENCODE][stderr]\n{stderr_text}")

        if process.returncode != 0:
            logger.error("[OPENCODE] Lệnh thất bại!")
            send_telegram(chat_id, f"❌ Lỗi Opencode: {stderr_text[:300] or stdout_text[:300]}")
            return

        # 3. Kiểm tra thay đổi trong repo
        status_res = run_cmd(["git", "status", "--porcelain"], cwd=VAULT_DIR)
        logger.info(f"[GIT] Trạng thái thay đổi:\n{status_res.stdout or '(không có gì thay đổi)'}")

        run_cmd(["git", "add", "."], cwd=VAULT_DIR)
        commit_res = run_cmd(
            ["git", "commit", "-m", f"auto: {user_prompt[:30]}"], cwd=VAULT_DIR
        )

        if "nothing to commit" not in commit_res.stdout:
            push_res = run_cmd(["git", "push"], cwd=VAULT_DIR)
            if push_res.returncode != 0:
                logger.error("[GIT] Push thất bại!")
                send_telegram(chat_id, f"❌ Push thất bại: {push_res.stderr[:300]}")
                return
            logger.info("[GIT] Push thành công")
            send_telegram(chat_id, "✅ Đã take note và push lên GitHub!")
        else:
            logger.info("[GIT] Không có gì để commit")
            send_telegram(chat_id, "ℹ️ Không có thay đổi nào được tạo.")

    except Exception as e:
        logger.exception(f"[EXCEPTION] Lỗi hệ thống trong process_opencode_task")
        send_telegram(chat_id, f"💥 Lỗi hệ thống: {str(e)}")
    finally:
        logger.info(f"### KẾT THÚC TASK cho chat_id={chat_id} ###")


@app.post("/webhook")
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()
    logger.info(f"[WEBHOOK] Nhận request: {data}")

    message = data.get("message", {})
    user_prompt = message.get("text", "")
    chat_id = message.get("chat", {}).get("id")

    logger.info(f"[WEBHOOK] user_prompt='{user_prompt}' chat_id={chat_id}")

    if user_prompt and chat_id:
        send_telegram(chat_id, "⏳ Đang chạy Opencode take note...")
        background_tasks.add_task(process_opencode_task, user_prompt, chat_id)
    else:
        logger.warning("[WEBHOOK] Thiếu user_prompt hoặc chat_id, bỏ qua")

    return {"status": "ok"}


@app.on_event("startup")
async def startup_event():
    logger.info("=== APP STARTUP ===")
    logger.info(f"TELEGRAM_BOT_TOKEN set: {bool(TELEGRAM_BOT_TOKEN)}")
    logger.info(f"GITHUB_PAT set: {bool(GITHUB_PAT)}")
    logger.info(f"REPO_URL: {REPO_URL}")