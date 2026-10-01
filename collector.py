import os
import re
import json
import time
import requests
from supabase import create_client

# ---------------------------------------------------------
# Supabase 연결 설정 (GitHub Secrets 사용)
# ---------------------------------------------------------
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ SUPABASE_URL 또는 SUPABASE_KEY 환경변수가 설정되지 않았습니다.")
    exit(1)

try:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("✅ Supabase 클라이언트 연결 성공")
except Exception as e:
    print(f"❌ Supabase 연결 실패: {e}")
    exit(1)

# ---------------------------------------------------------
# 무신사 순수 API 전용 수집 함수 (www.musinsa.com 우회)
# ---------------------------------------------------------
def get_musinsa_goods_info_api(goods_id):
    """
    www.musinsa.com 웹페이지를 방문하지 않고,
    Cloudflare 검사를 받지 않는 pure API 엔드포인트만 직접 조회합니다.
    """
    session = requests.Session()
    
    # 모바일 앱 API 호출용 헤더
    headers = {
        "User-Agent": "Musinsa/4.88.0 (iPhone; iOS 17.5; Scale/3.00)",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Origin": "https://goods-detail.musinsa.com",
        "Referer": f"https://goods-detail.musinsa.com/goods/{goods_id}"
    }

    # API 엔드포인트 리스트
    api_urls = [
        f"https://goods-detail.musinsa.com/goods/{goods_id}",
        f"https://goods-detail.musinsa.com/api/goods/v1/detail/{goods_id}",
        f"https://goods-detail.musinsa.com/goods/{goods_id}/price"
    ]

    last_status = None

    for url in api_urls:
        try:
            res = session.get(url, headers=headers, timeout=8)
            last_status = res.status_code

            if res.status_code == 200:
                data = res.json()
                if isinstance(data, dict):
                    if "data" in data and isinstance(data["data"], dict):
                        data = data["data"]

                    goods_name = data.get("goodsNm") or data.get("goodsName") or data.get("name") or data.get("title")
                    price = data.get("price") or data.get("salePrice") or data.get("finalPrice")
                    normal_price = data.get("normalPrice") or data.get("originalPrice") or price

                    if goods_name and price:
                        price = int(price)
                        normal_price = int(normal_price) if normal_price else price
                        
                        return {
                            "goods_id": str(goods_id),
                            "goods_name": goods_name,
                            "normal_price": normal_price,
                            "price": price
                        }
        except Exception:
            continue

    print(f"⚠️ [{goods_id}] API 수집 실패 (최종 HTTP 상태 코드: {last_status or 'Timeout'})")
    return None

# ---------------------------------------------------------
# 메인 자동 수집 실행 로직
# ---------------------------------------------------------
def main():
    print("\n🚀 [Musinsa Price Daily Collector] 배치 수집 시작")

    try:
        res = supabase.table("tracked_products").select("goods_id, goods_name").execute()
        tracked_products = res.data
    except Exception as e:
        print(f"❌ DB 조회 실패: {e}")
        return

    if not tracked_products:
        print("ℹ️ 추적 중인 상품이 없습니다. 스크립트를 종료합니다.")
        return

    print(f"📦 총 {len(tracked_products)}개의 상품 가격 정보 수집을 시도합니다.\n")

    success_count = 0
    fail_count = 0

    for prod in tracked_products:
        goods_id = prod["goods_id"]
        goods_name = prod.get("goods_name", "상품명 미상")

        info = get_musinsa_goods_info_api(goods_id)
        if info:
            try:
                log_data = {
                    "goods_id": info["goods_id"],
                    "normal_price": info["normal_price"],
                    "price": info["price"]
                }
                supabase.table("price_logs").insert(log_data).execute()
                print(f"✅ [{info['goods_name']}] 정가: {info['normal_price']:,}원 | 판매가: {info['price']:,}원 수집 성공")
                success_count += 1
            except Exception as e:
                print(f"❌ [{goods_name}] DB 저장 실패: {e}")
                fail_count += 1
        else:
            print(f"❌ [{goods_name}] (ID: {goods_id}) 정보 수집 실패")
            fail_count += 1

        time.sleep(1)

    print(f"\n🎉 수집 완료! (성공: {success_count}건 / 실패: {fail_count}건)")

if __name__ == "__main__":
    main()
