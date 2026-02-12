#!/usr/bin/env python3
"""
食料在庫管理 CLI

Usage:
    python inventory.py import [--from-date YYYYMMDD] [--to-date YYYYMMDD]
    python inventory.py stock
    python inventory.py expiring [--days 3]
"""

import argparse
import os
import sys

from dotenv import load_dotenv

load_dotenv()


def cmd_import(args):
    """レシートから食料をインポート"""
    from iaeon.receipt import IAEONReceiptClient
    from iaeon.inventory import FoodInventoryDB, parse_receipt, search_product_info

    access_token = os.getenv("ACCESS_TOKEN")
    receipt_account_id = os.getenv("RECEIPT_ACCOUNT_ID")
    if not access_token or not receipt_account_id:
        print("エラー: .env に ACCESS_TOKEN / RECEIPT_ACCOUNT_ID を設定してください。")
        sys.exit(1)

    client = IAEONReceiptClient(access_token, receipt_account_id)
    db = FoodInventoryDB()

    # 1. レシートサービス認証
    print("認証中...")
    try:
        client.auth_receipt()
    except Exception as e:
        print(f"認証エラー: {e}")
        sys.exit(1)

    # 2. レシート一覧取得
    print(f"レシート一覧を取得中... (期間: {args.from_date or '今月初'} ~ {args.to_date or '今月末'})")
    receipts = client.list_receipts(from_date=args.from_date, to_date=args.to_date)
    if not receipts:
        print("レシートが見つかりませんでした。")
        return

    print(f"{len(receipts)} 件のレシートを取得しました。\n")

    total_imported = 0
    total_skipped = 0

    for summary in receipts:
        # 重複チェック
        if db.is_receipt_imported(summary.receipt_id):
            print(f"  [スキップ] {summary.datetime} {summary.store_name} (インポート済み)")
            total_skipped += 1
            continue

        # 3. レシート詳細取得
        print(f"  [処理中] {summary.datetime} {summary.store_name} ¥{summary.total or '?'}")
        detail = client.get_receipt_detail(summary.receipt_id)

        # 4. 商品パース
        receipt_products = parse_receipt(detail, summary)
        if not receipt_products.products:
            print(f"    → 商品が見つかりませんでした")
            continue

        # 5. 商品情報検索
        product_infos = {}
        for product in receipt_products.products:
            info = search_product_info(product.name, db)
            product_infos[product.name] = info

        # 6. DB登録
        count = db.import_receipt(receipt_products, product_infos)
        total_imported += count

        # サマリー表示
        food_count = sum(1 for p in receipt_products.products if product_infos.get(p.name, None) is None or product_infos[p.name].is_food)
        non_food_count = len(receipt_products.products) - food_count
        print(f"    → {count} 件登録 (食品: {food_count}, 非食品: {non_food_count})")

        for product in receipt_products.products:
            info = product_infos.get(product.name)
            tag = ""
            if info and info.category:
                tag = f" [{info.category}/{info.subcategory}]"
            if info and not info.is_food:
                tag += " (非食品)"
            price_str = f"¥{product.price}"
            if product.discount:
                price_str += f" (-¥{product.discount})"
            print(f"      {product.name}  {price_str}{tag}")

    print(f"\n完了: {total_imported} 件インポート, {total_skipped} 件スキップ")
    db.close()


def cmd_stock(args):
    """在庫一覧を表示"""
    from iaeon.inventory import FoodInventoryDB

    db = FoodInventoryDB()
    items = db.get_in_stock_items()

    if not items:
        print("在庫はありません。")
        db.close()
        return

    print(f"=== 在庫一覧 ({len(items)} 品目) ===\n")

    # カテゴリ別にグループ化
    by_category: dict[str, list] = {}
    for item in items:
        cat = item["category"] or "未分類"
        by_category.setdefault(cat, []).append(item)

    for category, category_items in sorted(by_category.items()):
        print(f"【{category}】")
        for item in category_items:
            qty = item["total_quantity"]
            storage = item["storage_type"]
            amount = ""
            if item["content_amount"]:
                amount = f" ({item['content_amount']}{item['content_unit']})"
            shelf = ""
            if item["shelf_life_days"]:
                shelf = f" [保存: {item['shelf_life_days']}日]"
            print(f"  {item['name']} x{qty}{amount} [{storage}]{shelf}")
            print(f"    購入: {item['last_purchased'][:10]}  店舗: {item['store_name']}")
        print()

    db.close()


def cmd_expiring(args):
    """期限切れ間近の在庫を表示"""
    from iaeon.inventory import FoodInventoryDB

    db = FoodInventoryDB()
    items = db.get_expiring_soon(days=args.days)

    if not items:
        print(f"期限切れ間近（{args.days}日以内）の在庫はありません。")
        db.close()
        return

    print(f"=== 期限切れ間近 ({args.days}日以内, {len(items)} 品目) ===\n")

    for item in items:
        remaining = int(item["days_remaining"])
        if remaining < 0:
            status = f"【期限切れ {-remaining}日超過】"
        elif remaining == 0:
            status = "【本日期限】"
        else:
            status = f"残り{remaining}日"

        print(f"  {item['name']}  {status}")
        print(f"    購入: {item['purchased_at'][:10]}  期限: {item['expires_at']}  [{item['storage_type']}]")

    db.close()


def main():
    parser = argparse.ArgumentParser(description="食料在庫管理")
    subparsers = parser.add_subparsers(dest="command")

    # import コマンド
    p_import = subparsers.add_parser("import", help="レシートから食料をインポート")
    p_import.add_argument("--from-date", help="開始日 (YYYYMMDD)")
    p_import.add_argument("--to-date", help="終了日 (YYYYMMDD)")

    # stock コマンド
    subparsers.add_parser("stock", help="在庫一覧を表示")

    # expiring コマンド
    p_expiring = subparsers.add_parser("expiring", help="期限切れ間近の在庫を表示")
    p_expiring.add_argument("--days", type=int, default=3, help="期限切れまでの日数 (デフォルト: 3)")

    args = parser.parse_args()

    if args.command == "import":
        cmd_import(args)
    elif args.command == "stock":
        cmd_stock(args)
    elif args.command == "expiring":
        cmd_expiring(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
