# iaeon

iAEON アプリの認証・電子レシート取得・食料在庫管理を行う Python ツールキット。

## インストール

```bash
pip install iaeon

# レシート画像レンダリングが必要な場合
pip install iaeon[image]
```

日本語フォント (NotoSansCJK) がシステムにインストールされていると、レシート画像が正しくレンダリングされる。

```bash
# Debian/Ubuntu
sudo apt install fonts-noto-cjk
```

## セットアップ

### 1. ログイン

`iaeon-login` で iAEON アカウントにログインし、アクセストークンを `.env` に保存する。

```bash
# 対話式
iaeon-login

# 引数で指定
iaeon-login --phone 09012345678 --password yourpassword
```

認証フロー:
1. 電話番号 + パスワードでログイン
2. SMS認証コードの送信・検証 (新デバイス時)
3. アクセストークン取得 → `.env` に保存

### 2. .env ファイル

```
ACCESS_TOKEN="..."
DEVICE_ID="bf533bf5-..."
RECEIPT_ACCOUNT_ID="..."
GOOGLE_API_KEY=""
GOOGLE_SEARCH_ENGINE_ID=""
```

- `RECEIPT_ACCOUNT_ID` は電子レシート機能に必要。iAEON アプリの通信から取得する。
- `GOOGLE_API_KEY` / `GOOGLE_SEARCH_ENGINE_ID` は商品情報検索用 (任意)。未設定でもローカルキーワードマッチで動作する。

## 電子レシート

```python
from iaeon.receipt import IAEONReceiptClient

client = IAEONReceiptClient(
    access_token="...",
    receipt_account_id="...",
)

# レシート一覧取得 (デフォルト: 今月)
receipts = client.list_receipts()

for r in receipts:
    print(f"{r.datetime}  {r.store_name}  ¥{r.total}")

    # レシート詳細取得
    detail = client.get_receipt_detail(r.receipt_id)

    # 画像として保存
    path = client.save_receipt_image(detail, output_dir="receipts")
    print(f"保存: {path}")
```

### 日付範囲を指定

```python
receipts = client.list_receipts(from_date="20260101", to_date="20260131")
```

### レンダリングオプション

```python
img = IAEONReceiptClient.render_receipt_image(
    detail,
    font_size=18,
    width=580,
    padding=20,
    bg_color="white",
    text_color="black",
)
img.save("receipt.png")
```

## 食料在庫管理

レシートから購入した食品を自動パースし、SQLite DB に登録して在庫管理する。

### CLI

```bash
# レシートから食料をインポート (デフォルト: 今月)
iaeon-inventory import

# 日付範囲を指定
iaeon-inventory import --from-date 20260201 --to-date 20260213

# 在庫一覧
iaeon-inventory stock

# 期限切れ間近の在庫 (デフォルト: 3日以内)
iaeon-inventory expiring
iaeon-inventory expiring --days 7
```

### Python API

```python
from iaeon.inventory import FoodInventoryDB

db = FoodInventoryDB()

# 在庫一覧
items = db.get_in_stock_items()
for item in items:
    print(f"{item['name']} x{item['total_quantity']} [{item['category']}]")

# 期限切れ間近
expiring = db.get_expiring_soon(days=3)

# 消費済みにマーク
db.mark_consumed("明治おいしい牛乳", count=1)

db.close()
```

### 商品分類

2段階で商品を自動分類する:

1. **ローカルキーワードマッチ** — 商品名から即座に分類 (API不要)
2. **Google Custom Search API** — ローカルで判定できない場合に Web 検索 (要API設定)

## API リファレンス

### IAEONAuth

| メソッド | 説明 |
|---|---|
| `full_login(phone, password)` | 完全なログインフロー (対話式、SMS入力あり) |
| `login(phone, password)` | ログイン。SMS認証が必要な場合 code `10021`/`10008` を返す |
| `request_sms()` | SMS認証コード送信リクエスト |
| `verify_sms_code(auth_code)` | SMS認証コード検証 |
| `login_token()` | Bearer トークン取得 |
| `get_access_token(client_id?)` | サービス用アクセストークン取得 |

### IAEONReceiptClient

| メソッド | 説明 |
|---|---|
| `list_receipts(from_date?, to_date?)` | レシート一覧を `ReceiptSummary` のリストで返す |
| `get_receipt_detail(receipt_id)` | レシート詳細を `ReceiptDetail` で返す |
| `get_store_info(store_code)` | 店舗情報の dict を返す |
| `render_receipt_image(detail, ...)` | レシートを `PIL.Image` にレンダリング (staticmethod) |
| `save_receipt_image(detail, output_dir, ...)` | レシート画像を PNG で保存 |
| `save_embedded_images(detail, output_dir)` | 埋め込み画像を個別保存 |

### FoodInventoryDB

| メソッド | 説明 |
|---|---|
| `import_receipt(receipt, product_infos?)` | レシート全体を DB にインポート |
| `get_in_stock_items()` | 在庫一覧を返す |
| `get_expiring_soon(days=3)` | 期限切れ間近の在庫を返す |
| `mark_consumed(product_name, count=1)` | 在庫を消費済みにマーク |

## ライセンス

MIT
