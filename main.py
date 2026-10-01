import os
import requests
import json
import re

# 디스코드 웹훅 전송 함수
def send_discord_message(webhook_url, message):
    if not webhook_url:
        print("디스코드 웹훅 URL이 설정되지 않았습니다.")
        return
    payload = {"content": message}
    requests.post(webhook_url, json=payload)

# 무신사 상품 정보 수집 함수
def get_musinsa_goods_info(goods_id):
    url = f"https://www.musinsa.com/app/goods/{goods_id}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        res = requests.get(url, headers=headers)
        res.raise_for_status()
        match = re.search(r'window\.__MSS__\.product\.state\s*=\s*({.*?});', res.text, re.DOTALL)
        if match:
            json_data = json.loads(match.group(1))
            return {
                "goods_id": goods_id,
                "goods_name": json_data.get("goodsNm", "상품명 없음"),
                "price": json_data.get("price", 0),
                "url": url
            }
    except Exception as e:
        print(f"Error [{goods_id}]: {e}")
    return None

if __name__ == "__main__":
    # 추적할 무신사 상품 ID 목록 (원하는 상품 ID 숫자로 변경하세요)
    TARGET_ITEMS = ["2081557"]  
    
    DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

    results = []
    for g_id in TARGET_ITEMS:
        info = get_musinsa_goods_info(g_id)
        if info:
            msg = f"🛍️ **[{info['goods_name']}]**\n현재 가격: {info['price']:,}원\n👉 {info['url']}"
            results.append(msg)
            print(f"수집 성공: {info['goods_name']} - {info['price']}원")

    if results and DISCORD_WEBHOOK_URL:
        send_discord_message(DISCORD_WEBHOOK_URL, "\n\n".join(results))
