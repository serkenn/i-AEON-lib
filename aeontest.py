import requests
import json

# 解析データから取得したヘッダー情報
# 注意: Authorizationトークンは短時間で期限切れになります
HEADERS = {
    "Host": "aeonapp.aeon.com",
    "User-Agent": "Mozilla/5.0 (Linux; Android 14; SO-54C Build/64.2.C.2.268; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/144.0.7559.132 Mobile Safari/537.36 iAEON-AeonPay/1.1.684",
    "Content-Type": "application/json",
    "Accept": "application/json",
    "X-Content-Type-Options": "nosniff",
    # 実際のmitmproxyで取得した 'Bearer ...' 以降の文字列を入れてください
    "Authorization": "Bearer <YOUR_ACCESS_TOKEN_HERE>" 
}

def get_user_info():
    """
    認証が通るかテストするための関数（ユーザー情報取得）
    """
    url = "https://aeonapp.aeon.com/api/iaeon/user/1.0/account/information"
    params = {
        "user_info_key": "aeon_memberid,membership_card_type"
    }

    try:
        response = requests.get(url, headers=HEADERS, params=params)
        response.raise_for_status() # エラーなら例外を発生
        
        print("Success!")
        print(json.dumps(response.json(), indent=2, ensure_ascii=False))

    except requests.exceptions.HTTPError as e:
        print(f"HTTP Error: {e}")
        # Akamaiにブロックされた場合、403 Forbiddenなどが返ります
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    get_user_info()