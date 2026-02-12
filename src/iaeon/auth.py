"""
iAEON 認証モジュール

iAEON アプリのログインフローを再現し、アクセストークンを取得する。

認証フロー:
1. POST /api/iaeon/auth/1.0/login              電話番号 + パスワードハッシュ → session_id
2. PUT  /api/iaeon/auth/1.0/sms                SMS認証コード送信リクエスト
3. POST /api/iaeon/auth/1.0/auth_code          SMS認証コード検証
4. POST /api/iaeon/auth/1.0/login/token        device_id → Bearerトークン取得
5. POST /api/iaeon/auth/1.0/account/access_token  サービス用アクセストークン取得
"""

import hashlib
import uuid
from typing import Callable, Optional

import requests

BASE_URL = "https://aeonapp.aeon.com"

USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 14; SO-54C Build/64.2.C.2.268; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/144.0.7559.132 "
    "Mobile Safari/537.36 iAEON-AeonPay/1.1.684"
)

# iAEON アプリ本体の client_id
CLIENT_ID_APP = "00000000000000000000000000000000"
# サービス用 client_id (レシート等)
CLIENT_ID_SERVICE = "00000000000000000000000000000003"


class IAEONAuthError(Exception):
    """認証エラー"""
    def __init__(self, code: str, message: str = ""):
        self.code = code
        super().__init__(f"iAEON Auth Error [{code}]: {message}")


class IAEONAuth:
    """iAEON 認証クライアント"""

    def __init__(self, device_id: Optional[str] = None):
        """
        Args:
            device_id: デバイスID (UUID形式)。省略時は自動生成。
                       同じデバイスIDを使い続けることで、SMS認証をスキップできる場合がある。
        """
        self.device_id = device_id or str(uuid.uuid4())
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Charset": "UTF-8",
            "Host": "aeonapp.aeon.com",
        })
        self._auth_session: Optional[str] = None
        self._access_token: Optional[str] = None

    @staticmethod
    def hash_password(password: str) -> str:
        """パスワードをSHA-256でハッシュ化"""
        return hashlib.sha256(password.encode("utf-8")).hexdigest()

    def login(self, phone_number: str, password: str) -> dict:
        """
        ログインリクエスト (Step 1)

        Args:
            phone_number: 電話番号 (例: "09012345678")
            password: パスワード (平文)

        Returns:
            APIレスポンスのdict。
            code="10021" の場合、SMS認証が必要 (session_idが含まれる)。
            code="00000" の場合、ログイン成功。

        Raises:
            IAEONAuthError: 認証失敗時
        """
        pwhash = self.hash_password(password)

        resp = self._session.post(
            f"{BASE_URL}/api/iaeon/auth/1.0/login",
            data={
                "number": phone_number,
                "device_id": self.device_id,
                "pwhash": pwhash,
                "version": "2",
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            },
        )

        result = resp.json()
        code = result.get("code", "")

        # session_id があればSMS認証フローに進める
        if "session_id" in result:
            self._auth_session = result["session_id"]

        if code in ("10021", "10008"):
            # 10021: SMS認証が必要
            # 10008: 新デバイスでのSMS認証が必要
            return result
        elif code == "00000":
            return result
        else:
            raise IAEONAuthError(code, f"Login failed: {result}")

    def request_sms(self) -> dict:
        """
        SMS認証コード送信リクエスト (Step 2)

        login() で code="10021" が返された後に呼び出す。

        Returns:
            APIレスポンスのdict (code="00000" で成功)

        Raises:
            IAEONAuthError: リクエスト失敗時
        """
        if not self._auth_session:
            raise IAEONAuthError("NO_SESSION", "login() を先に呼び出してください")

        resp = self._session.put(
            f"{BASE_URL}/api/iaeon/auth/1.0/sms",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "x-auth-session": self._auth_session,
            },
        )

        result = resp.json()
        if result.get("code") != "00000":
            raise IAEONAuthError(result.get("code", "UNKNOWN"), f"SMS request failed: {result}")
        return result

    def verify_sms_code(self, auth_code: str) -> dict:
        """
        SMS認証コード検証 (Step 3)

        Args:
            auth_code: SMSで受信した6桁の認証コード

        Returns:
            APIレスポンスのdict (code="00000" で成功)

        Raises:
            IAEONAuthError: 検証失敗時
        """
        if not self._auth_session:
            raise IAEONAuthError("NO_SESSION", "login() を先に呼び出してください")

        resp = self._session.post(
            f"{BASE_URL}/api/iaeon/auth/1.0/auth_code",
            data={"auth_code": auth_code},
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "x-auth-session": self._auth_session,
            },
        )

        result = resp.json()
        if result.get("code") != "00000":
            raise IAEONAuthError(result.get("code", "UNKNOWN"), f"Auth code verification failed: {result}")
        return result

    def login_token(self) -> str:
        """
        Bearerトークン取得 (Step 4)

        SMS認証完了後、device_id と x-auth-session を使って
        アプリ本体用のBearerトークンを取得する。

        Returns:
            Bearerトークン文字列

        Raises:
            IAEONAuthError: トークン取得失敗時
        """
        if not self._auth_session:
            raise IAEONAuthError("NO_SESSION", "login() を先に呼び出してください")

        resp = self._session.post(
            f"{BASE_URL}/api/iaeon/auth/1.0/login/token",
            data={"device_id": self.device_id},
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "x-auth-session": self._auth_session,
            },
        )

        result = resp.json()
        code = result.get("code", "")
        if code != "00000":
            raise IAEONAuthError(code, f"Login token request failed (HTTP {resp.status_code}): {result}")

        token = result.get("access_token", "")
        if not token:
            raise IAEONAuthError("NO_TOKEN", f"Response has no access_token: {result}")

        self._access_token = token
        return token

    def get_access_token(self, client_id: str = CLIENT_ID_SERVICE) -> str:
        """
        アクセストークン取得 (Step 4)

        SMS認証完了後、またはログイン済みBearerトークンを使って
        アクセストークンを取得する。

        Args:
            client_id: 取得するトークンのclient_id。
                       デフォルトはアプリ本体用。

        Returns:
            アクセストークン文字列

        Raises:
            IAEONAuthError: トークン取得失敗時
        """
        headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        }
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        if self._auth_session:
            headers["x-auth-session"] = self._auth_session

        resp = self._session.post(
            f"{BASE_URL}/api/iaeon/auth/1.0/account/access_token",
            data={"client_id": client_id},
            headers=headers,
        )

        result = resp.json()
        if result.get("code") != "00000":
            raise IAEONAuthError(
                result.get("code", "UNKNOWN"),
                f"Access token request failed (HTTP {resp.status_code}): {result}",
            )

        token = result["access_token"]
        # アプリ本体用トークンの場合、以降のリクエストに使う
        if client_id == CLIENT_ID_APP:
            self._access_token = token
        return token

    @property
    def access_token(self) -> Optional[str]:
        """現在のアクセストークン"""
        return self._access_token

    def full_login(
        self,
        phone_number: str,
        password: str,
        otp_provider: Optional[Callable[[], str]] = None,
    ) -> str:
        """
        完全なログインフロー (対話式)

        ログイン → SMS認証 → アクセストークン取得 を一括で行う。
        SMS認証コードの入力をユーザーに求める。

        Args:
            phone_number: 電話番号
            password: パスワード
            otp_provider: OTP取得コールバック。指定時は input() の代わりに使用。

        Returns:
            アクセストークン
        """
        print(f"ログイン中... (電話番号: {phone_number[:3]}****{phone_number[-4:]})")
        result = self.login(phone_number, password)

        if result.get("code") in ("10021", "10008"):
            print("SMS認証が必要です。認証コードを送信します...")
            self.request_sms()
            print("SMSを送信しました。")

            if otp_provider is not None:
                auth_code = otp_provider()
            else:
                auth_code = input("SMSで届いた6桁の認証コードを入力してください: ").strip()
            self.verify_sms_code(auth_code)
            print("SMS認証成功。")

        # Bearerトークンを取得 (login/token)
        print("Bearerトークンを取得中...")
        token = self.login_token()
        print("アクセストークンを取得しました。")
        return token

    def get_service_token(self) -> str:
        """
        サービス用アクセストークンを取得

        アプリ本体用トークン取得後に呼び出す。
        レシート等の各種サービスAPIで使用する。

        Returns:
            サービス用アクセストークン
        """
        if not self._access_token:
            raise IAEONAuthError("NO_TOKEN", "先にログインしてアクセストークンを取得してください")
        return self.get_access_token(CLIENT_ID_SERVICE)
