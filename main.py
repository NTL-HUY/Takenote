import os
import subprocess
import asyncio
from fastapi import FastAPI, BackgroundTasks, Request
import requests

app = FastAPI()

# Token bot Telegram và GitHub Token lấy từ Environment Variables trên Render
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GITHUB_PAT = os.getenv("GITHUB_PAT")  # Personal Access Token để push Git
REPO_URL = os.getenv("REPO_URL")  # ví dụ: https://github.com/username/my-obsidian-vault.git

VAULT_DIR = "/tmp/obsidian_vault"


def send_telegram(chat_id: int, text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": text})


def setup_and_sync_git():
    """Clone hoặc pull vault từ GitHub về thư mục /tmp"""
    if not os.path.exists(VAULT_DIR):
        # Cấu hình authenticated URL để push/pull tự động
        auth_repo_url = REPO_URL.replace("https://", f"https://x-access-token:{GITHUB_PAT}@")
        subprocess.run(["git", "clone", auth_repo_url, VAULT_DIR], check=True)
        # Config Git user
        subprocess.run(["git", "config", "user.name", "Render-Bot"], cwd=VAULT_DIR)
        subprocess.run(["git", "config", "user.email", "bot@render.com"], cwd=VAULT_DIR)
    else:
        subprocess.run(["git", "pull"], cwd=VAULT_DIR)


async def process_opencode_task(user_prompt: str, chat_id: int):
    try:
        # 1. Sync Vault mới nhất từ GitHub
        setup_and_sync_git()

        # 2. Gọi Opencode CLI xử lý prompt
        # (Lưu ý: Opencode cần đọc agent.md có sẵn trong repo)
        cmd = f'opencode "{user_prompt}"'
        process = await asyncio.create_subprocess_shell(
            cmd,
            cwd=VAULT_DIR,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error_msg = stderr.decode('utf-8')
            send_telegram(chat_id, f"❌ Lỗi Opencode: {error_msg[:200]}")
            return

        # 3. Commit và Push thay đổi lên GitHub Private Repo
        subprocess.run(["git", "add", "."], cwd=VAULT_DIR)
        commit_res = subprocess.run(["git", "commit", "-m", f"auto: {user_prompt[:30]}"], cwd=VAULT_DIR,
                                    capture_output=True, text=True)

        if "nothing to commit" not in commit_res.stdout:
            subprocess.run(["git", "push"], cwd=VAULT_DIR, check=True)
            send_telegram(chat_id, f"✅ Đã take note và push lên GitHub!")
        else:
            send_telegram(chat_id, "ℹ️ Không có thay đổi nào được tạo.")

    except Exception as e:
        send_telegram(chat_id, f"💥 Lỗi hệ thống: {str(e)}")


@app.post("/webhook")
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()
    message = data.get("message", {})
    user_prompt = message.get("text", "")
    chat_id = message.get("chat", {}).get("id")

    if user_prompt and chat_id:
        send_telegram(chat_id, "⏳ Đang chạy Opencode take note...")
        background_tasks.add_task(process_opencode_task, user_prompt, chat_id)

    return {"status": "ok"}