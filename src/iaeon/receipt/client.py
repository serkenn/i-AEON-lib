"""
iAEON 電子レシート API クライアント

mitmproxy等で取得した Bearer トークンを使って、
iAEON アプリの電子レシートを取得・画像として保存するライブラリ。

APIフロー:
1. Bearer トークンでレシートアカウント情報を取得
2. レシートサービス認証 → receipt JWT 取得
3. レシート一覧取得 (日付範囲)
4. レシート詳細取得 (テキスト行 + 埋め込み画像)
5. レシート画像レンダリング
"""

import base64
import io
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests
from PIL import Image, ImageDraw, ImageFont


BASE_URL = "https://aeonapp.aeon.com"
STORE_URL = "https://aeonapp-web.aeon.com"

USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 14; SO-54C Build/64.2.C.2.268; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/144.0.7559.132 "
    "Mobile Safari/537.36 iAEON-AeonPay/1.1.684"
)


@dataclass
class ReceiptSummary:
    """レシート一覧の1件分"""
    receipt_id: str
    store_name: str
    store_code: str
    datetime: str
    total: Optional[str] = None
    workstation_id: Optional[str] = None


@dataclass
class ReceiptDetail:
    """レシート詳細データ"""
    receipt_id: str
    lines: list[str] = field(default_factory=list)
    images: dict[str, bytes] = field(default_factory=dict)  # name -> BMP bytes
    raw: Optional[dict] = None


class IAEONReceiptClient:
    """iAEON 電子レシート API クライアント"""

    def __init__(self, access_token: str, receipt_account_id: str):
        """
        Args:
            access_token: iAEON の Bearer トークン
                例: "EMLBl6dengx27u7f6AxFQ0hNdA0MZwmn_00000000000000000000000000000000_4300077585681162"
                mitmproxy の Authorization ヘッダーから "Bearer " を除いた部分。
            receipt_account_id: レシートサービスの accountId
                mitmproxy で /receipt/members/auth のリクエストボディから取得。
                例: "iighiqrqusuxrsyv"
        """
        self.access_token = access_token
        self.receipt_account_id = receipt_account_id
        self._receipt_jwt: Optional[str] = None
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Charset": "UTF-8",
        })

    def _auth_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        url = f"{BASE_URL}{path}"
        resp = self._session.get(url, headers=self._auth_headers(), params=params)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, json_body: dict, headers: Optional[dict] = None) -> dict:
        url = f"{BASE_URL}{path}"
        hdrs = self._auth_headers()
        if headers:
            hdrs.update(headers)
        resp = self._session.post(url, headers=hdrs, json=json_body)
        resp.raise_for_status()
        return resp.json()

    # ── 認証 ──

    def get_user_receipt_info(self) -> dict:
        """レシートアカウント情報を取得。

        Returns:
            {"receipt_account_id": "...", "use_receipt": "1"}
        """
        data = self._get(
            "/api/iaeon/user/1.0/account/information",
            params={"user_info_key": "receipt_account_id,use_receipt"},
        )
        info = data.get("user_info", {})
        return {
            k: v.get("value") for k, v in info.items()
            if k in ("receipt_account_id", "use_receipt")
        }

    def auth_receipt(self) -> str:
        """レシートサービスに認証し、receipt JWT を取得。

        Returns:
            receipt_jwt: レシート API 用の JWT トークン
        """
        data = self._post(
            "/api/aeonapp/1.0/receipt/members/auth",
            json_body={
                "accountId": self.receipt_account_id,
                "accessToken": self.access_token,
            },
        )
        results = data.get("results", {})
        self._receipt_jwt = results["access_token"]
        return self._receipt_jwt

    @property
    def receipt_jwt(self) -> str:
        if self._receipt_jwt is None:
            self.auth_receipt()
        return self._receipt_jwt

    # ── レシート一覧 ──

    def list_receipts(
        self,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> list[ReceiptSummary]:
        """指定期間のレシート一覧を取得。

        Args:
            from_date: 開始日 "YYYYMMDD" (デフォルト: 今月1日)
            to_date:   終了日 "YYYYMMDD" (デフォルト: 今月末日)

        Returns:
            ReceiptSummary のリスト
        """
        now = datetime.now()
        if from_date is None:
            from_date = now.replace(day=1).strftime("%Y%m%d")
        if to_date is None:
            next_month = now.replace(day=28) + timedelta(days=4)
            last_day = next_month.replace(day=1) - timedelta(days=1)
            to_date = last_day.strftime("%Y%m%d")

        data = self._post(
            "/api/aeonapp/1.0/receipt/receipts",
            json_body={
                "accessToken": self.receipt_jwt,
                "companyCode": "",
                "companyName": "",
                "storeCode": "",
                "storeName": "",
                "from": f"{from_date}000000",
                "to": f"{to_date}235959",
            },
        )

        results = []
        for item in data.get("results", {}).get("DigitalReceiptIndex", []):
            txn = item.get("Transaction", {})
            unit = txn.get("BusinessUnit", {}).get("UnitID", {})
            retail = txn.get("RetailTransaction", {})

            total = None
            for t in retail.get("Total", []):
                if t.get("@@TotalType") == "TransactionBalanceDueAmount":
                    total = t.get("#Value")

            results.append(ReceiptSummary(
                receipt_id=item.get("ReceiptID", ""),
                store_name=unit.get("@@Name", ""),
                store_code=unit.get("#Value", ""),
                datetime=txn.get("ReceiptDateTime", ""),
                total=total,
                workstation_id=txn.get("WorkstationID"),
            ))

        return results

    # ── レシート詳細 ──

    def get_receipt_detail(self, receipt_id: str) -> ReceiptDetail:
        """レシート詳細 (テキスト行 + 埋め込み画像) を取得。

        Args:
            receipt_id: レシートID

        Returns:
            ReceiptDetail (lines=テキスト行, images=埋め込みBMP画像)
        """
        data = self._post(
            "/api/aeonapp/1.0/receipt/receipts/stringArray",
            json_body={
                "accessToken": self.receipt_jwt,
                "receiptId": receipt_id,
            },
        )

        receipt = data.get("results", {}).get("DigitalReceipt", {})
        txn = receipt.get("Transaction", {})
        receipt_image = txn.get("ReceiptImage", {})
        lines = receipt_image.get("ReceiptLine", [])

        # 埋め込み画像を抽出
        images = {}
        retail = txn.get("RetailTransaction", {})
        for item in retail.get("LineItem", []):
            ad = item.get("Advertising", {})
            ad_id = ad.get("AdvertisingID", "")
            img_data = ad.get("ImageData")
            if img_data:
                images[ad_id] = base64.b64decode(img_data)

        return ReceiptDetail(
            receipt_id=receipt.get("ReceiptID", receipt_id),
            lines=lines,
            images=images,
            raw=data,
        )

    # ── 店舗情報 ──

    def get_store_info(self, store_code: str) -> dict:
        """店舗情報を取得。

        Args:
            store_code: 店舗コード (5桁)。一覧の store_code を 10桁にゼロ埋め。

        Returns:
            店舗情報の dict
        """
        padded = store_code.zfill(10)
        url = f"{STORE_URL}/api/storelist/v2/stores/0000{padded}"
        resp = self._session.post(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "x-public-application-token": "P_MVUJTRUPGXTS",
            },
            data="type=code",
        )
        resp.raise_for_status()
        return resp.json().get("store", {})

    # ── レシート画像レンダリング ──

    @staticmethod
    def render_receipt_image(
        detail: ReceiptDetail,
        font_size: int = 20,
        width: int = 640,
        padding: int = 20,
        bg_color: str = "white",
        text_color: str = "black",
    ) -> Image.Image:
        """レシートのテキスト行を画像にレンダリング。

        Args:
            detail: ReceiptDetail
            font_size: フォントサイズ
            width: 画像幅 (px)
            padding: 余白 (px)

        Returns:
            PIL.Image
        """
        # フォントを探す
        font = _find_font(font_size)
        bold_font = _find_font(int(font_size * 1.4), bold=True)

        # 各行の高さを計算
        line_height = font_size + 6
        bold_line_height = int(font_size * 1.4) + 8

        # 埋め込み画像の高さを算出
        bmp_images = {}
        for name, bmp_data in detail.images.items():
            try:
                img = Image.open(io.BytesIO(bmp_data))
                # 幅をレシート幅に合わせてリサイズ
                ratio = (width - padding * 2) / img.width
                new_h = int(img.height * ratio)
                bmp_images[name] = img.resize((width - padding * 2, new_h))
            except Exception:
                pass

        # 全体の高さを計算
        total_height = padding
        for line in detail.lines:
            bmp_match = re.match(r"PrintBitmap\(\d+,\s*'([^']+)'", line)
            if bmp_match:
                name = bmp_match.group(1)
                if name in bmp_images:
                    total_height += bmp_images[name].height + 4
                # PrintBitmap の後のテキスト部分
                text_after = re.sub(r"PrintBitmap\([^)]+\)", "", line).strip()
                if text_after:
                    total_height += bold_line_height
            elif "PrintBarCode" in line:
                total_height += 60  # バーコード用のスペース
            elif "PrintDouble" in line:
                total_height += bold_line_height
            else:
                total_height += line_height
        total_height += padding

        # 画像を作成
        img = Image.new("RGB", (width, total_height), bg_color)
        draw = ImageDraw.Draw(img)
        y = padding

        for line in detail.lines:
            # PrintBitmap: 埋め込み画像を描画
            bmp_match = re.match(r"PrintBitmap\(\d+,\s*'([^']+)'", line)
            if bmp_match:
                name = bmp_match.group(1)
                if name in bmp_images:
                    bmp_img = bmp_images[name]
                    img.paste(bmp_img, (padding, y))
                    y += bmp_img.height + 4
                # PrintBitmap の後のテキスト部分も描画
                text_after = re.sub(r"PrintBitmap\([^)]+\)", "", line).strip()
                if text_after:
                    draw.text((padding, y), text_after, fill=text_color, font=bold_font)
                    y += bold_line_height
                continue

            # PrintBarCode: バーコード領域をプレースホルダーとして描画
            if "PrintBarCode" in line:
                barcode_match = re.search(r"PrintBarCode\('([^']+)'", line)
                code = barcode_match.group(1) if barcode_match else ""
                draw.rectangle(
                    [(padding, y), (width - padding, y + 40)],
                    fill="white", outline="black",
                )
                draw.text(
                    (padding + 10, y + 10), f"||||| {code} |||||",
                    fill=text_color, font=font,
                )
                y += 60
                continue

            # PrintDouble: 太字テキスト
            double_match = re.search(r"PrintDouble\('([^']*)',\s*\d+\)", line)
            if double_match:
                replacement = double_match.group(1).replace("\\\\", "\\")
                display_line = line[:double_match.start()] + replacement + line[double_match.end():]
                # 複数の PrintDouble がある場合も処理
                while True:
                    m = re.search(r"PrintDouble\('([^']*)',\s*\d+\)", display_line)
                    if not m:
                        break
                    rep = m.group(1).replace("\\\\", "\\")
                    display_line = display_line[:m.start()] + rep + display_line[m.end():]
                draw.text((padding, y), display_line, fill=text_color, font=bold_font)
                y += bold_line_height
                continue

            # 通常テキスト行
            draw.text((padding, y), line, fill=text_color, font=font)
            y += line_height

        return img

    def save_receipt_image(
        self,
        detail: ReceiptDetail,
        output_dir: str = ".",
        prefix: str = "receipt",
        **render_kwargs,
    ) -> Path:
        """レシートを画像ファイルとして保存。

        Args:
            detail: ReceiptDetail
            output_dir: 保存先ディレクトリ
            prefix: ファイル名の接頭辞

        Returns:
            保存先の Path
        """
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        img = self.render_receipt_image(detail, **render_kwargs)

        # ファイル名: receipt_20260212_122613_39029.png
        dt_match = re.search(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})", "")
        # ReceiptID からタイムスタンプを抽出
        rid = detail.receipt_id
        # フォーマット: 20260212122616N000...
        ts = rid[:14] if len(rid) > 14 else datetime.now().strftime("%Y%m%d%H%M%S")
        filename = f"{prefix}_{ts}.png"

        filepath = out / filename
        img.save(str(filepath))
        return filepath

    def save_embedded_images(
        self, detail: ReceiptDetail, output_dir: str = "."
    ) -> list[Path]:
        """埋め込みBMP画像を個別に保存。

        Returns:
            保存先 Path のリスト
        """
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        saved = []
        for name, bmp_data in detail.images.items():
            filepath = out / name
            filepath.write_bytes(bmp_data)
            # PNG にも変換
            try:
                bmp = Image.open(io.BytesIO(bmp_data))
                png_path = filepath.with_suffix(".png")
                bmp.save(str(png_path))
                saved.append(png_path)
            except Exception:
                saved.append(filepath)
        return saved


def _find_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """利用可能な日本語フォントを探す。"""
    if bold:
        font_paths = [
            # Linux - CJK fonts (日本語対応、全角文字対応)
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            # macOS
            "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
        ]
    else:
        font_paths = [
            # Linux - CJK fonts (日本語対応、全角文字対応)
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",
            # macOS
            "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
            "/Library/Fonts/Osaka.ttf",
            # Fallback
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
        ]
    for path in font_paths:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()
