"""レシートから商品をパースする"""

import re
from typing import Optional

from iaeon.receipt.client import ReceiptDetail, ReceiptSummary

from .models import ParsedProduct, ReceiptProducts


def parse_receipt(
    detail: ReceiptDetail, summary: ReceiptSummary
) -> ReceiptProducts:
    """レシート詳細から商品リストを抽出する。

    2段階パース:
    1. 構造化データ優先: raw の RetailTransaction.LineItem[].Sale から取得
    2. テキスト行フォールバック: lines からregexで抽出

    Args:
        detail: レシート詳細データ
        summary: レシートサマリー（店舗名・日時）

    Returns:
        ReceiptProducts
    """
    products = _parse_from_raw(detail.raw) if detail.raw else []

    if not products:
        products = _parse_from_lines(detail.lines)

    return ReceiptProducts(
        receipt_id=detail.receipt_id,
        store_name=summary.store_name,
        purchased_at=summary.datetime,
        products=products,
    )


def _parse_from_raw(raw: dict) -> list[ParsedProduct]:
    """構造化データ (RetailTransaction.LineItem[].Sale) からパース"""
    products = []

    try:
        receipt = raw.get("results", {}).get("DigitalReceipt", {})
        txn = receipt.get("Transaction", {})
        retail = txn.get("RetailTransaction", {})
        line_items = retail.get("LineItem", [])
    except (AttributeError, TypeError):
        return []

    if not isinstance(line_items, list):
        line_items = [line_items]

    for item in line_items:
        sale = item.get("Sale")
        if not sale:
            continue

        # 商品名
        name = ""
        desc = sale.get("ItemDescription")
        if isinstance(desc, dict):
            name = desc.get("#Value", "")
        elif isinstance(desc, str):
            name = desc

        if not name:
            continue

        # 価格
        price = 0
        ext_amount = sale.get("ExtendedAmount")
        if isinstance(ext_amount, dict):
            price = _to_int(ext_amount.get("#Value", "0"))
        elif ext_amount is not None:
            price = _to_int(ext_amount)

        # 数量
        quantity = 1
        qty_val = sale.get("Quantity")
        if isinstance(qty_val, dict):
            quantity = _to_int(qty_val.get("#Value", "1")) or 1
        elif qty_val is not None:
            quantity = _to_int(qty_val) or 1

        # 値引き
        discount = 0
        disc = sale.get("Discount")
        if disc:
            disc_amount = disc.get("Amount") if isinstance(disc, dict) else None
            if isinstance(disc_amount, dict):
                discount = _to_int(disc_amount.get("#Value", "0"))
            elif disc_amount is not None:
                discount = _to_int(disc_amount)

        # バーコード
        barcode = None
        item_id = sale.get("ItemID")
        if isinstance(item_id, dict):
            barcode = item_id.get("#Value")
        elif isinstance(item_id, str):
            barcode = item_id

        products.append(ParsedProduct(
            name=name.strip(),
            price=price,
            quantity=quantity,
            discount=discount,
            barcode=barcode,
        ))

    return products


def _parse_from_lines(lines: list[str]) -> list[ParsedProduct]:
    """テキスト行からregexで商品をパース（フォールバック）

    レシートのテキスト行パターン:
    - 通常: "商品名          ¥123" or "商品名          123"
    - PrintDouble: "PrintDouble('商品名          ¥123', width)"
    - 値引: "値引             -50" (直前の商品に適用)
    """
    products = []

    # 商品行パターン: 商品名 + 空白 + 価格（※や*がつく場合あり）
    # 例: "ﾄｯﾌﾟﾊﾞﾘｭ ﾐﾈﾗﾙｳｫｰﾀｰ      ¥88※"
    product_pattern = re.compile(
        r'^(.+?)\s{2,}[¥\\]?(\d{1,6})[※＊*]?\s*$'
    )
    # PrintDouble内の商品パターン
    double_pattern = re.compile(
        r"PrintDouble\('(.+?)\s{2,}[¥\\]?(\d{1,6})[※＊*]?\s*',\s*\d+\)"
    )
    # 値引きパターン
    discount_pattern = re.compile(
        r'(?:値引|割引|ﾜﾘﾋﾞｷ|ｸｰﾎﾟﾝ).*?[-ー](\d{1,6})'
    )

    for line in lines:
        # PrintBitmapやPrintBarCodeはスキップ
        if "PrintBitmap" in line or "PrintBarCode" in line:
            continue

        # PrintDouble内の商品を抽出
        dm = double_pattern.search(line)
        if dm:
            name = dm.group(1).strip()
            price = _to_int(dm.group(2))
            if name and price > 0 and not _is_skip_line(name):
                products.append(ParsedProduct(name=name, price=price))
            continue

        # 通常行の商品を抽出
        pm = product_pattern.match(line)
        if pm:
            name = pm.group(1).strip()
            price = _to_int(pm.group(2))
            if name and price > 0 and not _is_skip_line(name):
                products.append(ParsedProduct(name=name, price=price))
            continue

        # 値引きを直前の商品に適用
        dm2 = discount_pattern.search(line)
        if dm2 and products:
            products[-1].discount = _to_int(dm2.group(1))

    return products


def _is_skip_line(name: str) -> bool:
    """合計・小計等の非商品行を除外"""
    skip_words = [
        "合計", "小計", "お預り", "お釣", "税込", "税抜",
        "ポイント", "WAON", "ワオン", "現金", "クレジット",
        "お買上", "点数", "外税", "内税", "非課税",
    ]
    return any(w in name for w in skip_words)


def _to_int(value) -> int:
    """文字列を安全にintに変換"""
    if value is None:
        return 0
    try:
        return int(float(str(value).replace(",", "").replace("¥", "")))
    except (ValueError, TypeError):
        return 0
