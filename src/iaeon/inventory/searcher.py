"""商品情報検索 - ローカルキーワードマッチ + Google Custom Search API"""

import json
import os
import re
from typing import Optional

import requests

from .db import FoodInventoryDB
from .models import ProductInfo

# ── ローカルキーワード辞書 ──
# 商品名に含まれるキーワード → (category, subcategory, storage_type, shelf_life_days)

KEYWORD_RULES: list[tuple[list[str], dict]] = [
    # 飲料
    (["牛乳", "ﾐﾙｸ", "ミルク"], {"category": "飲料", "subcategory": "牛乳・乳飲料", "storage_type": "冷蔵", "shelf_life_days": 7}),
    (["豆乳"], {"category": "飲料", "subcategory": "豆乳", "storage_type": "常温", "shelf_life_days": 180}),
    (["ヨーグルト", "ﾖｰｸﾞﾙﾄ"], {"category": "乳製品", "subcategory": "ヨーグルト", "storage_type": "冷蔵", "shelf_life_days": 14}),
    (["チーズ", "ﾁｰｽﾞ"], {"category": "乳製品", "subcategory": "チーズ", "storage_type": "冷蔵", "shelf_life_days": 30}),
    (["ジュース", "ｼﾞｭｰｽ"], {"category": "飲料", "subcategory": "ジュース", "storage_type": "常温", "shelf_life_days": 270}),
    (["お茶", "緑茶", "麦茶", "ほうじ茶", "ｵﾁｬ", "ﾘｮｸﾁｬ"], {"category": "飲料", "subcategory": "茶系飲料", "storage_type": "常温", "shelf_life_days": 270}),
    (["コーヒー", "ｺｰﾋｰ", "珈琲"], {"category": "飲料", "subcategory": "コーヒー", "storage_type": "常温", "shelf_life_days": 270}),
    (["ミネラルウォーター", "ﾐﾈﾗﾙｳｫｰﾀｰ", "天然水", "水 "], {"category": "飲料", "subcategory": "水", "storage_type": "常温", "shelf_life_days": 730}),
    (["ビール", "ﾋﾞｰﾙ", "発泡酒"], {"category": "酒類", "subcategory": "ビール系", "storage_type": "常温", "shelf_life_days": 270}),
    (["ワイン", "ﾜｲﾝ"], {"category": "酒類", "subcategory": "ワイン", "storage_type": "常温", "shelf_life_days": 730}),
    (["チューハイ", "ﾁｭｰﾊｲ", "酎ハイ", "サワー", "ｻﾜｰ"], {"category": "酒類", "subcategory": "チューハイ", "storage_type": "常温", "shelf_life_days": 365}),
    # 肉類
    (["鶏肉", "鶏むね", "鶏もも", "ささみ", "ﾁｷﾝ", "チキン", "とりにく"], {"category": "肉類", "subcategory": "鶏肉", "storage_type": "冷蔵", "shelf_life_days": 3}),
    (["豚肉", "豚バラ", "豚ロース", "豚こま", "ﾌﾞﾀ", "ぶたにく", "豚ひき"], {"category": "肉類", "subcategory": "豚肉", "storage_type": "冷蔵", "shelf_life_days": 3}),
    (["牛肉", "牛バラ", "牛ロース", "牛こま", "ｷﾞｭｳ", "牛ひき"], {"category": "肉類", "subcategory": "牛肉", "storage_type": "冷蔵", "shelf_life_days": 3}),
    (["合挽", "合びき", "ひき肉", "ﾐﾝﾁ", "ミンチ"], {"category": "肉類", "subcategory": "ひき肉", "storage_type": "冷蔵", "shelf_life_days": 2}),
    (["ハム", "ﾊﾑ"], {"category": "肉類", "subcategory": "ハム・ソーセージ", "storage_type": "冷蔵", "shelf_life_days": 14}),
    (["ソーセージ", "ｿｰｾｰｼﾞ", "ウインナー", "ｳｲﾝﾅｰ", "ウィンナー"], {"category": "肉類", "subcategory": "ハム・ソーセージ", "storage_type": "冷蔵", "shelf_life_days": 14}),
    (["ベーコン", "ﾍﾞｰｺﾝ"], {"category": "肉類", "subcategory": "ベーコン", "storage_type": "冷蔵", "shelf_life_days": 14}),
    # 魚介類
    (["鮭", "サーモン", "ｻｰﾓﾝ", "しゃけ"], {"category": "魚介類", "subcategory": "鮭・サーモン", "storage_type": "冷蔵", "shelf_life_days": 2}),
    (["まぐろ", "マグロ", "ﾏｸﾞﾛ", "鮪"], {"category": "魚介類", "subcategory": "まぐろ", "storage_type": "冷蔵", "shelf_life_days": 2}),
    (["えび", "エビ", "ｴﾋﾞ", "海老"], {"category": "魚介類", "subcategory": "えび", "storage_type": "冷蔵", "shelf_life_days": 2}),
    (["刺身", "さしみ", "ｻｼﾐ"], {"category": "魚介類", "subcategory": "刺身", "storage_type": "冷蔵", "shelf_life_days": 1}),
    (["ちくわ", "チクワ", "ﾁｸﾜ"], {"category": "魚介類", "subcategory": "練り物", "storage_type": "冷蔵", "shelf_life_days": 7}),
    (["かまぼこ", "蒲鉾", "ｶﾏﾎﾞｺ"], {"category": "魚介類", "subcategory": "練り物", "storage_type": "冷蔵", "shelf_life_days": 7}),
    # 野菜・果物
    (["キャベツ", "ｷｬﾍﾞﾂ"], {"category": "野菜", "subcategory": "葉物", "storage_type": "冷蔵", "shelf_life_days": 7}),
    (["レタス", "ﾚﾀｽ"], {"category": "野菜", "subcategory": "葉物", "storage_type": "冷蔵", "shelf_life_days": 5}),
    (["ほうれん草", "ﾎｳﾚﾝｿｳ", "ほうれんそう"], {"category": "野菜", "subcategory": "葉物", "storage_type": "冷蔵", "shelf_life_days": 4}),
    (["トマト", "ﾄﾏﾄ"], {"category": "野菜", "subcategory": "果菜", "storage_type": "冷蔵", "shelf_life_days": 7}),
    (["きゅうり", "キュウリ", "ｷｭｳﾘ"], {"category": "野菜", "subcategory": "果菜", "storage_type": "冷蔵", "shelf_life_days": 5}),
    (["にんじん", "人参", "ﾆﾝｼﾞﾝ"], {"category": "野菜", "subcategory": "根菜", "storage_type": "冷蔵", "shelf_life_days": 14}),
    (["大根", "ﾀﾞｲｺﾝ", "だいこん"], {"category": "野菜", "subcategory": "根菜", "storage_type": "冷蔵", "shelf_life_days": 10}),
    (["じゃがいも", "ジャガイモ", "ﾊﾞﾚｲｼｮ", "ばれいしょ", "馬鈴薯", "ポテト"], {"category": "野菜", "subcategory": "根菜", "storage_type": "常温", "shelf_life_days": 30}),
    (["玉ねぎ", "たまねぎ", "タマネギ", "ﾀﾏﾈｷﾞ", "玉葱"], {"category": "野菜", "subcategory": "根菜", "storage_type": "常温", "shelf_life_days": 60}),
    (["もやし", "モヤシ", "ﾓﾔｼ"], {"category": "野菜", "subcategory": "もやし", "storage_type": "冷蔵", "shelf_life_days": 3}),
    (["ねぎ", "ネギ", "ﾈｷﾞ", "長ねぎ"], {"category": "野菜", "subcategory": "ねぎ", "storage_type": "冷蔵", "shelf_life_days": 7}),
    (["バナナ", "ﾊﾞﾅﾅ"], {"category": "果物", "subcategory": "バナナ", "storage_type": "常温", "shelf_life_days": 5}),
    (["りんご", "リンゴ", "ﾘﾝｺﾞ", "林檎"], {"category": "果物", "subcategory": "りんご", "storage_type": "冷蔵", "shelf_life_days": 30}),
    (["みかん", "ミカン", "ﾐｶﾝ"], {"category": "果物", "subcategory": "みかん", "storage_type": "常温", "shelf_life_days": 14}),
    # 豆腐・納豆
    (["豆腐", "とうふ", "ﾄｳﾌ"], {"category": "大豆製品", "subcategory": "豆腐", "storage_type": "冷蔵", "shelf_life_days": 5}),
    (["納豆", "なっとう", "ﾅｯﾄｳ"], {"category": "大豆製品", "subcategory": "納豆", "storage_type": "冷蔵", "shelf_life_days": 7}),
    (["油揚", "あぶらあげ", "ｱﾌﾞﾗｱｹﾞ"], {"category": "大豆製品", "subcategory": "油揚げ", "storage_type": "冷蔵", "shelf_life_days": 5}),
    # 卵
    (["たまご", "卵", "玉子", "ﾀﾏｺﾞ", "エッグ"], {"category": "卵", "subcategory": "鶏卵", "storage_type": "冷蔵", "shelf_life_days": 14}),
    # パン
    (["食パン", "ｼｮｸﾊﾟﾝ"], {"category": "パン", "subcategory": "食パン", "storage_type": "常温", "shelf_life_days": 4}),
    (["パン", "ﾊﾟﾝ", "ロールパン", "クロワッサン"], {"category": "パン", "subcategory": "パン", "storage_type": "常温", "shelf_life_days": 3}),
    # 米・麺
    (["米 ", "こめ", "ｺﾒ", "お米", "白米", "無洗米"], {"category": "米", "subcategory": "白米", "storage_type": "常温", "shelf_life_days": 90}),
    (["うどん", "ｳﾄﾞﾝ"], {"category": "麺類", "subcategory": "うどん", "storage_type": "冷蔵", "shelf_life_days": 5}),
    (["そば", "蕎麦", "ｿﾊﾞ"], {"category": "麺類", "subcategory": "そば", "storage_type": "冷蔵", "shelf_life_days": 5}),
    (["ラーメン", "ﾗｰﾒﾝ", "らーめん"], {"category": "麺類", "subcategory": "ラーメン", "storage_type": "常温", "shelf_life_days": 240}),
    (["パスタ", "ﾊﾟｽﾀ", "スパゲティ", "ｽﾊﾟｹﾞﾃｨ"], {"category": "麺類", "subcategory": "パスタ", "storage_type": "常温", "shelf_life_days": 1095}),
    # 菓子
    (["チョコ", "ﾁｮｺ"], {"category": "菓子", "subcategory": "チョコレート", "storage_type": "常温", "shelf_life_days": 180}),
    (["クッキー", "ｸｯｷｰ", "ビスケット", "ﾋﾞｽｹｯﾄ"], {"category": "菓子", "subcategory": "クッキー・ビスケット", "storage_type": "常温", "shelf_life_days": 180}),
    (["ポテトチップ", "ﾎﾟﾃﾄﾁｯﾌﾟ", "ポテチ"], {"category": "菓子", "subcategory": "スナック菓子", "storage_type": "常温", "shelf_life_days": 120}),
    (["せんべい", "煎餅", "ｾﾝﾍﾞｲ"], {"category": "菓子", "subcategory": "米菓", "storage_type": "常温", "shelf_life_days": 180}),
    (["アイス", "ｱｲｽ", "アイスクリーム"], {"category": "菓子", "subcategory": "アイスクリーム", "storage_type": "冷凍", "shelf_life_days": 365}),
    (["ガム", "ｶﾞﾑ"], {"category": "菓子", "subcategory": "ガム", "storage_type": "常温", "shelf_life_days": 365}),
    (["グミ", "ｸﾞﾐ"], {"category": "菓子", "subcategory": "グミ", "storage_type": "常温", "shelf_life_days": 180}),
    (["飴", "あめ", "ｱﾒ", "キャンディ"], {"category": "菓子", "subcategory": "飴・キャンディ", "storage_type": "常温", "shelf_life_days": 365}),
    # 調味料
    (["醤油", "しょうゆ", "ｼｮｳﾕ"], {"category": "調味料", "subcategory": "醤油", "storage_type": "常温", "shelf_life_days": 365}),
    (["味噌", "みそ", "ﾐｿ"], {"category": "調味料", "subcategory": "味噌", "storage_type": "冷蔵", "shelf_life_days": 180}),
    (["マヨネーズ", "ﾏﾖﾈｰｽﾞ", "マヨ"], {"category": "調味料", "subcategory": "マヨネーズ", "storage_type": "冷蔵", "shelf_life_days": 90}),
    (["ケチャップ", "ｹﾁｬｯﾌﾟ"], {"category": "調味料", "subcategory": "ケチャップ", "storage_type": "冷蔵", "shelf_life_days": 90}),
    (["ソース", "ｿｰｽ"], {"category": "調味料", "subcategory": "ソース", "storage_type": "常温", "shelf_life_days": 365}),
    (["砂糖", "ｻﾄｳ", "さとう"], {"category": "調味料", "subcategory": "砂糖", "storage_type": "常温", "shelf_life_days": 1095}),
    (["塩 ", "しお", "ｼｵ"], {"category": "調味料", "subcategory": "塩", "storage_type": "常温", "shelf_life_days": 1825}),
    (["酢 ", "ｽ"], {"category": "調味料", "subcategory": "酢", "storage_type": "常温", "shelf_life_days": 730}),
    (["ドレッシング", "ﾄﾞﾚｯｼﾝｸﾞ"], {"category": "調味料", "subcategory": "ドレッシング", "storage_type": "冷蔵", "shelf_life_days": 60}),
    # 冷凍食品
    (["冷凍", "ﾚｲﾄｳ"], {"category": "冷凍食品", "subcategory": "冷凍食品", "storage_type": "冷凍", "shelf_life_days": 365}),
    # カップ麺・インスタント
    (["カップ", "ｶｯﾌﾟ"], {"category": "インスタント", "subcategory": "カップ麺", "storage_type": "常温", "shelf_life_days": 180}),
    (["インスタント", "ｲﾝｽﾀﾝﾄ", "即席"], {"category": "インスタント", "subcategory": "インスタント食品", "storage_type": "常温", "shelf_life_days": 180}),
    # 缶詰
    (["缶", "ｶﾝ"], {"category": "缶詰・瓶詰", "subcategory": "缶詰", "storage_type": "常温", "shelf_life_days": 1095}),
    # 惣菜・弁当
    (["弁当", "ﾍﾞﾝﾄｳ", "べんとう"], {"category": "惣菜", "subcategory": "弁当", "storage_type": "冷蔵", "shelf_life_days": 1}),
    (["おにぎり", "ｵﾆｷﾞﾘ"], {"category": "惣菜", "subcategory": "おにぎり", "storage_type": "常温", "shelf_life_days": 1}),
    (["サンドイッチ", "ｻﾝﾄﾞｲｯﾁ", "サンド"], {"category": "惣菜", "subcategory": "サンドイッチ", "storage_type": "冷蔵", "shelf_life_days": 1}),
    (["寿司", "すし", "ｽｼ"], {"category": "惣菜", "subcategory": "寿司", "storage_type": "冷蔵", "shelf_life_days": 1}),
    (["惣菜", "ｿｳｻﾞｲ", "サラダ", "ｻﾗﾀﾞ", "コロッケ", "ｺﾛｯｹ", "天ぷら", "ﾃﾝﾌﾟﾗ", "唐揚", "からあげ"], {"category": "惣菜", "subcategory": "惣菜", "storage_type": "冷蔵", "shelf_life_days": 1}),
    # 非食品
    (["ティッシュ", "ﾃｨｯｼｭ"], {"category": "日用品", "subcategory": "ティッシュ", "storage_type": "常温", "is_food": False}),
    (["トイレットペーパー", "ﾄｲﾚｯﾄﾍﾟｰﾊﾟｰ", "ﾄｲﾚｯﾄ"], {"category": "日用品", "subcategory": "トイレットペーパー", "storage_type": "常温", "is_food": False}),
    (["洗剤", "ｾﾝｻﾞｲ"], {"category": "日用品", "subcategory": "洗剤", "storage_type": "常温", "is_food": False}),
    (["シャンプー", "ｼｬﾝﾌﾟｰ", "リンス", "ﾘﾝｽ", "コンディショナー"], {"category": "日用品", "subcategory": "ヘアケア", "storage_type": "常温", "is_food": False}),
    (["歯ブラシ", "ﾊﾌﾞﾗｼ", "歯磨", "ﾊﾐｶﾞｷ"], {"category": "日用品", "subcategory": "オーラルケア", "storage_type": "常温", "is_food": False}),
    (["レジ袋", "ﾚｼﾞﾌﾞｸﾛ", "ﾏｲﾊﾞｯｸﾞ", "袋"], {"category": "その他", "subcategory": "レジ袋", "storage_type": "常温", "is_food": False}),
]

# 非食品キーワード（大まかな判定用）
NON_FOOD_KEYWORDS = [
    "ティッシュ", "ﾃｨｯｼｭ", "トイレ", "ﾄｲﾚ", "洗剤", "ｾﾝｻﾞｲ",
    "シャンプー", "ｼｬﾝﾌﾟｰ", "石鹸", "ｾｯｹﾝ", "歯ブラシ", "ﾊﾌﾞﾗｼ",
    "電池", "ﾃﾞﾝﾁ", "ゴミ袋", "ｺﾞﾐﾌﾞｸﾛ", "ラップ", "ﾗｯﾌﾟ",
    "アルミホイル", "ｱﾙﾐﾎｲﾙ", "キッチンペーパー",
    "レジ袋", "ﾚｼﾞﾌﾞｸﾛ", "マスク", "ﾏｽｸ",
]


def search_product_info(
    product_name: str, db: FoodInventoryDB
) -> ProductInfo:
    """商品名から商品情報を検索する。

    1. DBキャッシュをチェック
    2. ローカルキーワードマッチ
    3. Google Custom Search API（フォールバック）

    Args:
        product_name: 商品名
        db: データベース（キャッシュ用）

    Returns:
        ProductInfo
    """
    # 1. キャッシュチェック
    cached = db.get_search_cache(product_name)
    if cached:
        return ProductInfo(**cached)

    # 2. ローカルキーワードマッチ
    info = _match_local_keywords(product_name)
    if info:
        db.set_search_cache(product_name, _info_to_dict(info))
        return info

    # 3. Google Custom Search API
    info = _search_google(product_name)
    if info:
        db.set_search_cache(product_name, _info_to_dict(info))
        return info

    # フォールバック: 非食品チェックだけ行う
    is_food = not any(kw in product_name for kw in NON_FOOD_KEYWORDS)
    info = ProductInfo(is_food=is_food)
    db.set_search_cache(product_name, _info_to_dict(info))
    return info


def _match_local_keywords(product_name: str) -> Optional[ProductInfo]:
    """ローカルキーワード辞書で商品を分類"""
    for keywords, attrs in KEYWORD_RULES:
        for kw in keywords:
            if kw in product_name:
                return ProductInfo(
                    category=attrs.get("category", ""),
                    subcategory=attrs.get("subcategory", ""),
                    storage_type=attrs.get("storage_type", "常温"),
                    is_food=attrs.get("is_food", True),
                )
    return None


def _search_google(product_name: str) -> Optional[ProductInfo]:
    """Google Custom Search API で商品情報を検索"""
    api_key = os.environ.get("GOOGLE_API_KEY")
    engine_id = os.environ.get("GOOGLE_SEARCH_ENGINE_ID")

    if not api_key or not engine_id:
        return None

    query = f"{product_name} 商品情報 内容量"

    try:
        resp = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params={
                "key": api_key,
                "cx": engine_id,
                "q": query,
                "num": 3,
                "lr": "lang_ja",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, json.JSONDecodeError):
        return None

    items = data.get("items", [])
    if not items:
        return None

    # スニペットからカテゴリ・内容量・メーカーを抽出
    info = ProductInfo()
    snippets = " ".join(item.get("snippet", "") for item in items)

    # 内容量パターン: "100g", "500ml", "1L", "6個" etc.
    amount_match = re.search(
        r'(\d+(?:\.\d+)?)\s*(g|kg|ml|mL|L|ℓ|個|枚|本|袋|食|パック|切)',
        snippets,
    )
    if amount_match:
        info.content_amount = float(amount_match.group(1))
        info.content_unit = amount_match.group(2)

    # メーカーパターン
    maker_match = re.search(
        r'(?:製造|販売|メーカー|ブランド)[：:]?\s*([^\s,、。]+)',
        snippets,
    )
    if maker_match:
        info.manufacturer = maker_match.group(1)

    # 非食品判定
    info.is_food = not any(kw in product_name for kw in NON_FOOD_KEYWORDS)

    return info


def _info_to_dict(info: ProductInfo) -> dict:
    """ProductInfo を dict に変換（キャッシュ保存用）"""
    return {
        "category": info.category,
        "subcategory": info.subcategory,
        "content_amount": info.content_amount,
        "content_unit": info.content_unit,
        "manufacturer": info.manufacturer,
        "storage_type": info.storage_type,
        "is_food": info.is_food,
    }
