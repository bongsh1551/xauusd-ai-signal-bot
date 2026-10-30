import os
import sys

import requests


def main():
    # 定时运行先跳过，避免测试消息每五分钟重复发送。
    if os.getenv("GITHUB_EVENT_NAME") != "workflow_dispatch":
        print("测试阶段：跳过定时任务，请手动运行。")
        return

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()

    if not token or not chat_id:
        print("缺少 TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID。")
        sys.exit(1)

    message = (
        "✅ GoldScalp AI 连线测试成功！\n\n"
        "GitHub Actions → Telegram 已接通。\n"
        "品种：XAUUSD 黄金\n"
        "当前阶段：系统测试\n\n"
        "这不是交易信号，没有执行任何下单操作。"
    )

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message},
            timeout=30,
        )
        result = response.json()
    except (requests.RequestException, ValueError):
        print("Telegram 请求失败，请检查网络或稍后重试。")
        sys.exit(1)

    if response.status_code != 200 or not result.get("ok"):
        print(
            "Telegram 返回错误：",
            result.get("error_code", response.status_code),
            result.get("description", "未知错误"),
        )
        sys.exit(1)

    print("Telegram 测试消息发送成功。")


if __name__ == "__main__":
    main()
