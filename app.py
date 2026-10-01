import streamlit as st
import pandas as pd
from supabase import create_client
import plotly.express as px
import requests
import json
import re
from datetime import datetime

# 페이지 기본 설정
st.set_page_config(page_title="무신사 스마트 가격 트래커", page_icon="🛍️", layout="wide")
st.title("🛍️ 무신사 스마트 가격 트래커")

# Supabase 연결 설정 (Secrets 사용)
try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception:
    st.error("Supabase API 키가 설정되지 않았습니다. Streamlit Secrets 설정을 확인해 주세요.")
    st.stop()

# ---------------------------------------------------------
# 무신사 크롤링 및 데이터 추출 함수
# ---------------------------------------------------------
def parse_goods_id(url_or_id):
    """URL 문자열에서 상품 ID(숫자)만 추출합니다."""
    match = re.search(r'\d+', url_or_id)
    return match.group(0) if match else None

def get_musinsa_goods_info(goods_id):
    """무신사 상품 페이지에서 상세 정보를 수집합니다."""
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
            
            # 이미지 및 카테고리 추출
            image_url = json_data.get("thumbnailImageUrl", "")
            if image_url and not image_url.startswith("http"):
                image_url = f"https:{image_url}"
                
            category = json_data.get("category", {}).get("categoryDepth2Name", "기타")
            
            # 할인율 계산
            discount_rate = 0
            if normal_price > 0 and normal_price > price:
                discount_rate = round(((normal_price - price) / normal_price) * 100, 1)

            return {
                "goods_id": str(goods_id),
                "goods_name": json_data.get("goodsNm", "상품명 없음"),
                "image_url": image_url,
                "category": category,
                "normal_price": normal_price,
                "price": price,
                "discount_rate": discount_rate,
                "url": url
            }
    except Exception as e:
        st.error(f"정보 수집 에러: {e}")
    return None

# DB 데이터 렌더링 헬퍼
def load_tracked_products():
    res = supabase.table("tracked_products").select("*").order("created_at", desc=True).execute()
    return pd.DataFrame(res.data)

def load_price_logs():
    res = supabase.table("price_logs").select("*").order("created_at", desc=False).execute()
    df = pd.DataFrame(res.data)
    if not df.empty:
        df["created_at"] = pd.to_datetime(df["created_at"]).dt.strftime('%Y-%m-%d %H:%M')
        df["discount_rate"] = df.apply(
            lambda r: round(((r["normal_price"] - r["price"]) / r["normal_price"]) * 100, 1) 
            if r["normal_price"] > r["price"] else 0, axis=1
        )
    return df

# ---------------------------------------------------------
# 탭 구성
# ---------------------------------------------------------
tab1, tab2, tab3 = st.tabs(["📊 가격 추이 대시보드", "➕ 추적 상품 관리", "⚡ 실시간 조회 (테스트)"])

# =========================================================
# TAB 1: 가격 추이 대시보드
# =========================================================
with tab1:
    products_df = load_tracked_products()
    logs_df = load_price_logs()

    if products_df.empty:
        st.info("아직 추적 중인 상품이 없습니다. '➕ 추적 상품 관리' 탭에서 상품을 추가해 보세요!")
    else:
        # 카테고리 및 태그 필터링 사이드바/옵션
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            categories = ["전체"] + list(products_df["category"].dropna().unique())
            selected_cat = st.selectbox("📂 카테고리 필터", categories)
        
        filtered_products = products_df if selected_cat == "전체" else products_df[products_df["category"] == selected_cat]

        if filtered_products.empty:
            st.warning("해당 카테고리에 등록된 상품이 없습니다.")
        else:
            with col_f2:
                selected_goods_name = st.selectbox("🛍️ 조회할 상품 선택", filtered_products["goods_name"].unique())

            # 선택된 상품 정보
            product_info = filtered_products[filtered_products["goods_name"] == selected_goods_name].iloc[0]
            g_id = product_info["goods_id"]

            # 상품 카드 UI
            card_col1, card_col2 = st.columns([1, 3])
            with card_col1:
                if product_info["image_url"]:
                    st.image(product_info["image_url"], use_column_width=True)
            with card_col2:
                st.subheader(product_info["goods_name"])
                st.caption(f"카테고리: {product_info['category']} | 태그: {product_info.get('tags', '-')}")
                
                # 로그 기반 가격 통계
                product_logs = logs_df[logs_df["goods_id"] == g_id] if not logs_df.empty else pd.DataFrame()
                
                if not product_logs.empty:
                    latest_row = product_logs.iloc[-1]
                    min_price = product_logs["price"].min()
                    max_discount = product_logs["discount_rate"].max()

                    m1, m2, m3, m4 = st.columns(4)
                    m1.markdown(f"**최근 정가**\n\n~~{int(latest_row['normal_price']):,} 원~~")
                    m2.metric("최근 판매가", f"{int(latest_row['price']):,} 원")
                    m3.metric("기간 내 최저가", f"{int(min_price):,} 원")
                    m4.metric("최대 할인율", f"{max_discount}% 🔥")
                
                st.markdown(f"👉 [무신사 상품 페이지 바로가기]({product_info['url']})")

            st.divider()

            # 그래프 표시
            if not product_logs.empty:
                st.markdown("### 📈 가격 및 할인율 변동 추이")
                fig_price = px.line(
                    product_logs, x="created_at", y="price", 
                    title="판매가 변동 추이 (원)", markers=True
                )
                st.plotly_chart(fig_price, use_container_width=True)

                fig_discount = px.bar(
                    product_logs, x="created_at", y="discount_rate", 
                    title="할인율 변동 추이 (%)", text_auto=True
                )
                st.plotly_chart(fig_discount, use_container_width=True)
            else:
                st.info("아직 누적된 가격 로그 데이터가 없습니다.")

# =========================================================
# TAB 2: 추적 상품 관리 (등록 / 삭제)
# =========================================================
with tab2:
    st.subheader("➕ 새로운 추적 상품 추가")
    st.caption("무신사 상품 URL 또는 ID를 입력하면 수집 대상에 추가되고 초기 데이터가 저장됩니다.")

    with st.form("add_product_form"):
        input_url = st.text_input("무신사 상품 URL 또는 ID", placeholder="https://www.musinsa.com/app/goods/2081557 또는 2081557")
        input_tags = st.text_input("커스텀 태그 (선택)", placeholder="예: #봄아우터, #위시리스트")
        submit_button = st.form_submit_button("추적 등록하기")

    if submit_button and input_url:
        goods_id = parse_goods_id(input_url)
        if not goods_id:
            st.error("올바른 상품 ID/URL을 입력해 주세요.")
        else:
            with st.spinner("상품 정보를 수집하고 DB에 등록하는 중..."):
                info = get_musinsa_goods_info(goods_id)
                if info:
                    # 1. tracked_products 추가
                    prod_data = {
                        "goods_id": info["goods_id"],
                        "goods_name": info["goods_name"],
                        "image_url": info["image_url"],
                        "category": info["category"],
                        "tags": input_tags,
                        "url": info["url"]
                    }
                    supabase.table("tracked_products").upsert(prod_data).execute()

                    # 2. 초기 가격 기록 저장 (Backfill)
                    log_data = {
                        "goods_id": info["goods_id"],
                        "normal_price": info["normal_price"],
                        "price": info["price"]
                    }
                    supabase.table("price_logs").insert(log_data).execute()

                    st.success(f"✅ **[{info['goods_name']}]** 상품이 추적 목록에 등록되었습니다!")
                    st.rerun()

    st.divider()

    # 등록된 상품 목록 및 삭제 관리
    st.subheader("📋 현재 추적 중인 상품 목록")
    tracked_df = load_tracked_products()

    if not tracked_df.empty:
        for idx, row in tracked_df.iterrows():
            col_img, col_desc, col_del = st.columns([1, 4, 1])
            with col_img:
                if row["image_url"]:
                    st.image(row["image_url"], width=80)
            with col_desc:
                st.markdown(f"**{row['goods_name']}** (ID: `{row['goods_id']}`)")
                st.caption(f"카테고리: {row['category']} | 태그: {row.get('tags', '-')}")
            with col_del:
                if st.button("🗑️ 삭제", key=f"del_{row['goods_id']}"):
                    supabase.table("tracked_products").delete().eq("goods_id", row["goods_id"]).execute()
                    st.success("삭제되었습니다.")
                    st.rerun()
            st.divider()

# =========================================================
# TAB 3: 실시간 조회 (테스트)
# =========================================================
with tab3:
    st.subheader("⚡ 실시간 가격 조회 (DB 저장 X)")
    st.caption("DB에 저장하지 않고 입력한 URL의 현재 정보를 즉시 파싱해 봅니다.")

    test_input = st.text_input("테스트할 무신사 상품 URL 또는 ID", value="2081557")
    if st.button("🔍 실시간 조회"):
        g_id = parse_goods_id(test_input)
        if g_id:
            with st.spinner("실시간 정보 조회 중..."):
                live = get_musinsa_goods_info(g_id)
                if live:
                    st.success("조회 성공!")
                    tc1, tc2 = st.columns([1, 3])
                    with tc1:
                        if live["image_url"]:
                            st.image(live["image_url"], use_column_width=True)
                    with tc2:
                        st.write(f"**상품명:** {live['goods_name']}")
                        st.write(f"**카테고리:** {live['category']}")
                        st.markdown(f"**정가:** ~~{live['normal_price']:,} 원~~")
                        st.markdown(f"**판매가:** {live['price']:,} 원")
                        st.markdown(f"**할인율:** {live['discount_rate']}% 🔥")
                        st.markdown(f"👉 [페이지 열기]({live['url']})")
