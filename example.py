#!/usr/bin/env python3
"""
iAEON 電子レシート取得サンプル

使い方:
1. .env ファイルに ACCESS_TOKEN と RECEIPT_ACCOUNT_ID を設定
2. このスクリプトを実行
"""

import os
import sys
from dotenv import load_dotenv
from iaeon.receipt import IAEONReceiptClient

# .envファイルを読み込む
load_dotenv()

# 環境変数から値を取得
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
RECEIPT_ACCOUNT_ID = os.getenv("RECEIPT_ACCOUNT_ID")

def main():
    # 値が取得できたかチェック
    if not ACCESS_TOKEN or not RECEIPT_ACCOUNT_ID:
        print("エラー: .env ファイルから ACCESS_TOKEN または RECEIPT_ACCOUNT_ID が読み込めませんでした。")
        print(".env ファイルが正しい場所にあり、値が設定されているか確認してください。")
        sys.exit(1)

    client = IAEONReceiptClient(
        access_token=ACCESS_TOKEN,
        receipt_account_id=RECEIPT_ACCOUNT_ID,
    )

    # 1. レシートサービス認証
    print("=== レシートサービス認証 ===")
    try:
        jwt = client.auth_receipt()
        print(f"Receipt JWT: {jwt[:50]}...")
    except Exception as e:
        print(f"認証エラー: {e}")
        return

    # 2. 今月のレシート一覧を取得
    print("\n=== レシート一覧 ===")
    receipts = client.list_receipts()
    if not receipts:
        print("レシートが見つかりませんでした。")
    
    for r in receipts:
        print(f"  {r.datetime}  {r.store_name}  ¥{r.total}")

    # 3. 各レシートの詳細を取得して画像保存
    print("\n=== レシート画像保存 ===")
    for r in receipts:
        print(f"\n--- {r.store_name} ({r.datetime}) ---")
        detail = client.get_receipt_detail(r.receipt_id)

        # テキスト行を表示
        for line in detail.lines:
            # PrintBitmap/PrintBarCode等の制御コマンドを除いた表示
            clean = line
            if "PrintBitmap" in clean:
                import re
                clean = re.sub(r"PrintBitmap\([^)]+\)", "[LOGO]", clean)
            if "PrintDouble" in clean:
                import re
                clean = re.sub(r"PrintDouble\('([^']*)',\s*\d+\)", r"\1", clean)
            if "PrintBarCode" in clean:
                clean = "[BARCODE]"
            print(f"  {clean}")

        # レシート画像を保存
        path = client.save_receipt_image(detail, output_dir="receipts")
        print(f"  → 画像保存: {path}")

        # 埋め込みロゴ画像を保存
        logos = client.save_embedded_images(detail, output_dir="receipts/logos")
        for logo in logos:
            print(f"  → ロゴ保存: {logo}")


if __name__ == "__main__":
    main()