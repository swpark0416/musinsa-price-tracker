import os
import requests
import json
import re
from supabase import create_client

# 환경변수에서 Supabase 접속 정보 읽기
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("Error: SUPABASE_URL 또는 SUPABASE_KEY가 설정되지 않았습니다.")
    exit(1)

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def get_musinsa_goods_info(goods_id):
    """
    무신사 상품 ID를 받아 최신 상품 정보를 파싱합니다.
    """
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
            price = json_data.get("price", 0)
            normal_price = json_data.get("normalPrice", price)
            
            return {
                "goods_id": str(goods_id),
                "normal_price": normal_price,
                "price": price
            }
    except Exception as e:
        print(f"[{goods_id}] 수집 중 오류 발생: {e}")
    return None

def run_collector():
    # 1. DB에서 추적 대상 상품 목록 가져오기
    try:
        response = supabase.table("tracked_products").select("goods_id, goods_name").execute()
        tracked_items = response.data
    except Exception as e:
        print(f"추적 상품 목록 불러오기 실패: {e}")
        return

    if not tracked_items:
        print("추적 중인 상품이 없습니다.")
        return

    print(f"총 {len(tracked_items)}개 상품의 가격을 수집합니다.")

    # 2. 각 상품별로 가격 업데이트
    for item in tracked_items:
        goods_id = item["goods_id"]
        goods_name = item["goods_name"]
        
        info = get_musinsa_goods_info(goods_id)
        if info:
            log_data = {
                "goods_id": goods_id,
                "normal_price": info["normal_price"],
                "price": info["price"]
            }
            # price_logs 테이블에 최신 가격 저장
            supabase.table("price_logs").insert(log_data).execute()
            print(f"✅ [{goods_name}] 정가: {info['normal_price']:,}원 | 할인가: {info['price']:,}원 기록 완료")

if __name__ == "__main__":
    run_collector()
