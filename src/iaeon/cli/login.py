#!/usr/bin/env python3
"""
iAEON ログインスクリプト

電話番号とパスワードでログインし、アクセストークンを取得して .env に保存する。

使い方:
  python login.py
  python login.py --phone 09012345678 --password yourpassword
  python login.py --phone 09012345678 --password yourpassword --device-id <UUID>
"""

import argparse
import getpass
import os
import sys

from dotenv import load_dotenv

from iaeon.auth import IAEONAuth, IAEONAuthError

load_dotenv()


def update_env(updates: dict[str, str], env_path: str = ".env"):
    """
    .env ファイルのキーを更新する。
    既存のキーは値を上書き、新しいキーは末尾に追加。
    """
    lines = []
    found_keys = set()

    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            for line in f:
                key = line.split("=", 1)[0].strip() if "=" in line else None
                if key and key in updates:
                    lines.append(f'{key}="{updates[key]}"\n')
                    found_keys.add(key)
                else:
                    lines.append(line)

    for key, value in updates.items():
        if key not in found_keys:
            lines.append(f'{key}="{value}"\n')

    with open(env_path, "w") as f:
        f.writelines(lines)


def main():
    parser = argparse.ArgumentParser(description="iAEON ログイン")
    parser.add_argument("--phone", help="電話番号 (例: 09012345678)")
    parser.add_argument("--password", help="パスワード (省略時は対話入力)")
    parser.add_argument("--device-id", help="デバイスID (UUID, 省略時は自動生成)")
    parser.add_argument("--env", default=".env", help=".envファイルのパス (default: .env)")
    args = parser.parse_args()

    phone = args.phone or os.getenv("PHONE_NUMBER") or input("電話番号を入力してください: ").strip()
    password = args.password or os.getenv("PASSWORD") or getpass.getpass("パスワードを入力してください: ")

    if not phone or not password:
        print("エラー: 電話番号とパスワードは必須です。", file=sys.stderr)
        sys.exit(1)

    device_id = args.device_id or os.getenv("DEVICE_ID")
    auth = IAEONAuth(device_id=device_id)
    print(f"デバイスID: {auth.device_id}")

    try:
        access_token = auth.full_login(phone, password)

        # サービス用トークンも取得
        print("\nサービス用アクセストークンを取得中...")
        service_token = auth.get_service_token()

        print(f"\n=== 取得結果 ===")
        print(f"アプリ用トークン:     {access_token[:20]}...")
        print(f"サービス用トークン:   {service_token[:20]}...")
        print(f"有効期限: トークン取得から約10時間")

        # .env に保存
        update_env({
            "ACCESS_TOKEN": access_token,
            "DEVICE_ID": auth.device_id,
        }, args.env)
        print(f"\n.env ファイルに ACCESS_TOKEN と DEVICE_ID を保存しました。")

    except IAEONAuthError as e:
        print(f"\n認証エラー: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n中断しました。")
        sys.exit(1)


if __name__ == "__main__":
    main()
