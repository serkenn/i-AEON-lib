"""食料在庫システム データモデル定義"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ParsedProduct:
    """レシートから抽出した商品情報"""
    name: str
    price: int
    quantity: int = 1
    discount: int = 0
    barcode: Optional[str] = None


@dataclass
class ProductInfo:
    """Web検索で取得した商品詳細情報"""
    category: str = ""           # 大分類（飲料, 菓子, 肉類, etc.）
    subcategory: str = ""        # 小分類（チョコレート, 牛乳・乳飲料, etc.）
    content_amount: Optional[float] = None  # 内容量
    content_unit: str = ""       # 単位（g, ml, 個, etc.）
    manufacturer: str = ""       # メーカー
    storage_type: str = "常温"   # 保存方法（常温/冷蔵/冷凍）
    is_food: bool = True         # 食品かどうか


@dataclass
class ReceiptProducts:
    """1レシート分の商品リスト"""
    receipt_id: str
    store_name: str
    purchased_at: str            # ISO format datetime
    products: list[ParsedProduct] = field(default_factory=list)
