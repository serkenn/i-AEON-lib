# iaeon

iAEON アプリの認証・電子レシート取得・食料在庫管理を行う Python ツールキット。

`iaeon-login` で iAEON にログインしてアクセストークンを取得し、電子レシート API を操作できる。
`iaeon-inventory` でレシートから購入食品を自動パースし、在庫DBに登録・管理できる。

## インストール

```bash
pip install iaeon

# レシート画像レンダリングが必要な場合
pip install iaeon[image]
```

開発用（editable install）:

```bash
pip install -e ".[image]"
```

日本語フォント (NotoSansCJK) がシステムにインストールされていると、レシート画像が正しくレンダリングされる。

```bash
# Debian/Ubuntu
sudo apt install fonts-noto-cjk
```

## ログイン

`iaeon-login` でiAEONアカウントにログインし、アクセストークンを `.env` に保存する。

```bash
# 対話式 (電話番号・パスワードを入力)
iaeon-login

# 引数で指定
iaeon-login --phone 09012345678 --password yourpassword

# デバイスIDを指定 (同じIDを使い続けるとSMS認証をスキップできる場合がある)
iaeon-login --phone 09012345678 --password yourpassword --device-id <UUID>
```

認証フロー:
1. 電話番号 + パスワードでログイン
2. SMS認証コードの送信・検証 (新デバイス時)
3. Bearerトークン取得
4. アクセストークン取得 → `.env` に `ACCESS_TOKEN` と `DEVICE_ID` を保存

### receipt_account_id の取得

電子レシート機能を使うには `RECEIPT_ACCOUNT_ID` も必要。
mitmproxy で `/api/aeonapp/1.0/receipt/members/auth` へのPOSTリクエストボディから取得する。

```json
{
  "accountId": "iighiqrqusuxrsyv",  // <-- この値
  "accessToken": "..."
}
```

### .env ファイル

```
ACCESS_TOKEN="..."
DEVICE_ID="bf533bf5-..."
RECEIPT_ACCOUNT_ID="iighiqrqusuxrsyv"
GOOGLE_API_KEY=""
GOOGLE_SEARCH_ENGINE_ID=""
```

`GOOGLE_API_KEY` / `GOOGLE_SEARCH_ENGINE_ID` は食料在庫の商品情報検索用（任意）。未設定でもローカルキーワードマッチで動作する。

## 電子レシート

### 基本的な流れ

```python
from iaeon.receipt import IAEONReceiptClient

client = IAEONReceiptClient(
    access_token="Bearer以降の値",
    receipt_account_id="accountIdの値",
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

### レシートのテキスト行を取得

```python
detail = client.get_receipt_detail(receipt_id)
for line in detail.lines:
    print(line)
```

出力例:

```
PrintBitmap(0, 'Electro.bmp', -11, -2)RCみらい長崎ココウォーク店
TEL095-847-0540 FAX095-847-0541
ﾚｼﾞ0144   2026/ 2/12(木)   12:26
クランキーエクセレント   428※
ジャ-ジ-ニュウ           238※
  割引        10%        -24
大粒ラムネ               118※
________________________________
合  計                  PrintDouble('\820', 2)
```

### 埋め込みロゴ画像を保存

```python
logos = client.save_embedded_images(detail, output_dir="receipts/logos")
```

### 店舗情報を取得

```python
store = client.get_store_info("39029")
print(store["name"])       # レッドキャベツみらい長崎ココウォーク店
print(store["prefecture"]) # 長崎県
```

### レンダリングオプション

```python
from iaeon.receipt import IAEONReceiptClient

img = IAEONReceiptClient.render_receipt_image(
    detail,
    font_size=18,     # フォントサイズ (default: 20)
    width=580,        # 画像幅 px (default: 640)
    padding=20,       # 余白 px (default: 20)
    bg_color="white", # 背景色
    text_color="black", # 文字色
)
img.save("receipt.png")
```

## 食料在庫管理

レシートから購入した食品を自動パースし、SQLite DBに登録して在庫管理する。

### CLI

```bash
# レシートから食料をインポート (デフォルト: 今月)
iaeon-inventory import

# 日付範囲を指定
iaeon-inventory import --from-date 20260201 --to-date 20260213

# 在庫一覧を表示
iaeon-inventory stock

# 期限切れ間近の在庫を表示 (デフォルト: 3日以内)
iaeon-inventory expiring
iaeon-inventory expiring --days 7
```

### パイプライン

`iaeon-inventory import` の処理フロー:

1. iAEON認証 → レシート一覧取得
2. 各レシートの詳細を取得
3. 商品をパース（構造化データ優先 → テキスト行regexフォールバック）
4. 商品情報を検索（ローカルキーワードマッチ → Google API フォールバック）
5. SQLite DBに登録（重複インポート防止付き）
6. サマリー表示

### 商品分類

2段階で商品を分類する:

1. **ローカルキーワードマッチ**: 商品名のキーワードから即座に分類（API不要）
   - `牛乳` → 飲料/牛乳・乳飲料 (冷蔵, 7日)
   - `チョコ` → 菓子/チョコレート (常温, 180日)
   - `鶏むね` → 肉類/鶏肉 (冷蔵, 3日)
   - `ティッシュ` → 日用品 (非食品)
2. **Google Custom Search API**: ローカルで判定できない場合にWeb検索（要API設定）

### DB構成

`food_inventory.db` (SQLite):

| テーブル | 説明 |
|---|---|
| `products` | 商品マスタ（名前, カテゴリ, 内容量, 保存方法, 賞味期限日数） |
| `purchases` | 購入履歴（商品, レシート, 店舗, 価格, 日時） |
| `inventory` | 在庫状態（`in_stock` / `consumed` / `expired`） |
| `search_cache` | Web検索結果キャッシュ |

### Python API

```python
from iaeon.inventory import FoodInventoryDB

db = FoodInventoryDB()

# 在庫一覧 (Cookpad/LLMエージェント用)
items = db.get_in_stock_items()
for item in items:
    print(f"{item['name']} x{item['total_quantity']} [{item['category']}]")

# 期限切れ間近 (LLMエージェント用)
expiring = db.get_expiring_soon(days=3)

# 消費済みにマーク
db.mark_consumed("明治おいしい牛乳", count=1)

db.close()
```

## API リファレンス

### IAEONAuth

| メソッド | 説明 |
|---|---|
| `login(phone, password)` | ログイン。SMS認証が必要な場合 code `10021`/`10008` を返す |
| `request_sms()` | SMS認証コード送信リクエスト |
| `verify_sms_code(auth_code)` | SMS認証コード検証 |
| `login_token()` | Bearerトークン取得。`_access_token` に保存される |
| `get_access_token(client_id?)` | サービス用アクセストークン取得 |
| `full_login(phone, password)` | 完全なログインフロー (対話式、SMS入力あり) |
| `get_service_token()` | サービス用 (client_id=...0003) アクセストークン取得 |

### IAEONReceiptClient

| メソッド | 説明 |
|---|---|
| `auth_receipt()` | レシートサービス認証。JWT を返す。通常は自動呼出し。 |
| `get_user_receipt_info()` | レシートアカウント情報 (`receipt_account_id`, `use_receipt`) を返す |
| `list_receipts(from_date?, to_date?)` | レシート一覧を `ReceiptSummary` のリストで返す |
| `get_receipt_detail(receipt_id)` | レシート詳細を `ReceiptDetail` で返す |
| `get_store_info(store_code)` | 店舗情報の dict を返す |
| `render_receipt_image(detail, ...)` | レシートを `PIL.Image` にレンダリング (staticmethod) |
| `save_receipt_image(detail, output_dir, ...)` | レシート画像を PNG で保存。Path を返す |
| `save_embedded_images(detail, output_dir)` | 埋め込みBMP画像を個別保存。Path リストを返す |

### FoodInventoryDB

| メソッド | 説明 |
|---|---|
| `import_receipt(receipt, product_infos?)` | レシート全体をDBにインポート。登録件数を返す |
| `is_receipt_imported(receipt_id)` | 重複インポート防止チェック |
| `upsert_product(name, info?)` | 商品マスタ登録/更新。product_id を返す |
| `get_in_stock_items()` | 在庫一覧を返す（Cookpad/LLM用） |
| `get_expiring_soon(days=3)` | 期限切れ間近の在庫を返す（LLM用） |
| `mark_consumed(product_name, count=1)` | 在庫を消費済みにマーク |
| `get_search_cache(product_name)` | 検索キャッシュ取得 |
| `set_search_cache(product_name, result)` | 検索キャッシュ保存 |

### データクラス

**ReceiptSummary**

| フィールド | 型 | 説明 |
|---|---|---|
| `receipt_id` | str | レシートID |
| `store_name` | str | 店舗名 |
| `store_code` | str | 店舗コード |
| `datetime` | str | 日時 (`2026-02-12T12:26:13`) |
| `total` | str? | 合計金額 |
| `workstation_id` | str? | レジ番号 |

**ReceiptDetail**

| フィールド | 型 | 説明 |
|---|---|---|
| `receipt_id` | str | レシートID |
| `lines` | list[str] | レシートテキスト行 |
| `images` | dict[str, bytes] | 埋め込み画像 (名前 -> BMPバイナリ) |
| `raw` | dict? | API レスポンス生データ |

**ParsedProduct**

| フィールド | 型 | 説明 |
|---|---|---|
| `name` | str | 商品名 |
| `price` | int | 価格 |
| `quantity` | int | 数量 (デフォルト: 1) |
| `discount` | int | 値引額 (デフォルト: 0) |
| `barcode` | str? | バーコード |

**ProductInfo**

| フィールド | 型 | 説明 |
|---|---|---|
| `category` | str | 大分類 (飲料, 菓子, 肉類 等) |
| `subcategory` | str | 小分類 (チョコレート, 牛乳・乳飲料 等) |
| `content_amount` | float? | 内容量 |
| `content_unit` | str | 単位 (g, ml, 個 等) |
| `manufacturer` | str | メーカー |
| `storage_type` | str | 保存方法 (常温/冷蔵/冷凍) |
| `is_food` | bool | 食品かどうか |

## API エンドポイント

### 認証

| メソッド | エンドポイント | 説明 |
|---|---|---|
| POST | `/api/iaeon/auth/1.0/login` | ログイン (電話番号 + パスワードハッシュ) |
| PUT | `/api/iaeon/auth/1.0/sms` | SMS認証コード送信 |
| POST | `/api/iaeon/auth/1.0/auth_code` | SMS認証コード検証 |
| POST | `/api/iaeon/auth/1.0/login/token` | Bearerトークン取得 |
| POST | `/api/iaeon/auth/1.0/account/access_token` | サービス用アクセストークン取得 |

### 電子レシート

| メソッド | エンドポイント | 説明 |
|---|---|---|
| GET | `/api/iaeon/user/1.0/account/information` | ユーザー情報取得 |
| POST | `/api/aeonapp/1.0/receipt/members/auth` | レシートサービス認証 |
| POST | `/api/aeonapp/1.0/receipt/receipts` | レシート一覧 |
| POST | `/api/aeonapp/1.0/receipt/receipts/stringArray` | レシート詳細 |
| POST | `/api/storelist/v2/stores/{code}` | 店舗情報 |

## レシートテキストの特殊コマンド

レシートの `lines` には POS プリンター制御コマンドが含まれる。

| コマンド | 説明 |
|---|---|
| `PrintBitmap(0, 'name.bmp', ...)` | 埋め込みBMP画像の描画位置 |
| `PrintDouble('text', 2)` | テキストを倍角 (太字) で描画 |
| `PrintBarCode('code', ...)` | バーコードの描画 |

`render_receipt_image()` はこれらを自動的に解釈してレンダリングする。

## mitmproxy でのキャプチャ手順

1. PC で mitmproxy を起動
   ```bash
   mitmproxy --listen-port 8080
   ```
2. Android 端末の Wi-Fi プロキシを PC の IP:8080 に設定
3. ブラウザで `http://mitm.it` を開き、CA 証明書をインストール
4. iAEON アプリを起動し、電子レシート画面を開く
5. mitmproxy でフローを保存
   ```bash
   mitmdump -r flows -n --set flow_detail=2 | grep receipt
   ```

## ファイル構成

```
pyproject.toml
LICENSE
src/iaeon/
├── __init__.py            # バージョン + 主要クラス re-export
├── auth.py                # iAEON 認証モジュール (IAEONAuth)
├── receipt/
│   ├── __init__.py        # パッケージエクスポート
│   └── client.py          # IAEONReceiptClient, ReceiptSummary, ReceiptDetail
├── inventory/
│   ├── __init__.py        # パッケージエクスポート
│   ├── models.py          # ParsedProduct, ProductInfo, ReceiptProducts
│   ├── db.py              # FoodInventoryDB (SQLite)
│   ├── parser.py          # レシート商品パーサー
│   └── searcher.py        # 商品情報検索 (キーワードマッチ + Google API)
└── cli/
    ├── __init__.py
    ├── login.py            # iaeon-login コマンド
    └── inventory_cmd.py    # iaeon-inventory コマンド
```
