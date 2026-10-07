import streamlit as st
import pandas as pd
from supabase import create_client
import plotly.express as px
import requests
import json
import re
import time

# 페이지 기본 설정
st.set_page_config(page_title="무신사 스마트 트래커", page_icon="🛍️", layout="wide")

# ---------------------------------------------------------
# 모바일 패딩 및 여백 최적화 CSS
# ---------------------------------------------------------
st.markdown("""<style>
.main .block-container {
    padding-left: 6px !important;
    padding-right: 6px !important;
    padding-top: 10px !important;
    max-width: 100vw !important;
    overflow-x: hidden !important;
}
p, span, div, h1, h2, h3, h4, a {
    word-break: break-all !important;
    overflow-wrap: break-word !important;
}
a {
    text-decoration: none !important;
    color: inherit !important;
}

/* Sub Tab 세그먼트 버튼 모바일 커스텀 */
div[data-testid="stRadio"] > div {
    display: flex !important;
    flex-direction: row !important;
    gap: 4px !important;
    width: 100% !important;
}
div[data-testid="stRadio"] label {
    flex: 1 !important;
    text-align: center !important;
    background: #f1f3f5 !important;
    padding: 6px 4px !important;
    border-radius: 6px !important;
    font-size: 11px !important;
    font-weight: bold !important;
    cursor: pointer !important;
}
div[data-testid="stRadio"] label[data-checked="true"] {
    background: #228be6 !important;
    color: white !important;
}
</style>""", unsafe_allow_html=True)

st.title("🛍️ 무신사 스마트 트래커")

# Supabase 연결 설정 (Secrets 사용)
try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"].strip().rstrip("/")
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"].strip()
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    st.error(f"❌ Supabase 연결 실패: {e}")
    st.stop()

# ---------------------------------------------------------
# URL Query Parameter 탐지 (카드 클릭 시 앱 내부 이동 처리)
# ---------------------------------------------------------
if "sub_tab" not in st.session_state:
    st.session_state["sub_tab"] = "➕ 추적 상품 관리"

qp = st.query_params
if qp.get("tab") == "detail" and "goods_id" in qp:
    st.session_state["sub_tab"] = "📊 개별 상품 가격 추이"
    st.session_state["selected_goods_id"] = str(qp.get("goods_id"))
    st.query_params.clear()

# ---------------------------------------------------------
# 무신사 크롤링 및 파싱 함수
# ---------------------------------------------------------
def parse_goods_id(url_or_id):
    """공유 링크, 단축 URL, 일반 웹주소에서 진짜 상품 ID를 추출합니다."""
    text = url_or_id.strip()
    
    if text.startswith("http"):
        headers = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Musinsa/4.88.0"
        }
        try:
            res = requests.get(text, headers=headers, allow_redirects=True, timeout=3)
            text = res.url
            
            match_body = re.search(r'musinsa\.com/(?:app/goods|products)/(\d+)', res.text)
            if match_body:
                return match_body.group(1)
        except Exception:
            pass

    match = re.search(r'(?:goods|products)/(\d+)', text)
    if match:
        return match.group(1)

    digits = re.findall(r'\b\d{5,8}\b', text)
    if digits:
        return digits[0]

    all_digits = re.findall(r'\d+', text)
    if all_digits:
        longest = max(all_digits, key=len)
        if len(longest) >= 4:
            return longest

    return None

def extract_brand_name(raw_text, data=None):
    """JSON 및 HTML 구조 전체를 탐색하여 실제 브랜드명을 정밀 추출합니다."""
    if data and isinstance(data, dict):
        b_info = data.get("brand") or data.get("brandInfo") or data.get("brandSub")
        if isinstance(b_info, dict):
            bn = b_info.get("brandName") or b_info.get("brandNm") or b_info.get("brandNameKo") or b_info.get("name")
            if bn and bn.upper() != "MUSINSA":
                return bn
        elif isinstance(b_info, str) and b_info.upper() != "MUSINSA":
            return b_info

        bn = data.get("brandName") or data.get("brandNm") or data.get("brandNameKo") or data.get("brandEng")
        if bn and bn.upper() != "MUSINSA":
            return bn

    patterns = [
        r'"brandName"\s*:\s*"([^"]+)"',
        r'"brandNm"\s*:\s*"([^"]+)"',
        r'"brandNameKo"\s*:\s*"([^"]+)"',
        r'<meta\s+property="product:brand"\s+content="([^"]+)"',
        r'<meta\s+property="og:brand"\s+content="([^"]+)"',
        r'\(([^)]+)\)</a',                      
        r'goods_brand_name"\s*:\s*"([^"]+)"'
    ]
    for p in patterns:
        m = re.search(p, raw_text)
        if m:
            val = m.group(1).strip()
            if val and val.upper() != "MUSINSA":
                return val
    return "MUSINSA"

def get_musinsa_goods_info(goods_id):
    """무신사 상품 정보 및 브랜드명을 수집합니다 (타임아웃 3초 적용)."""
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Musinsa/4.88.0",
        "Accept": "application/json, text/html, */*",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Referer": f"https://www.musinsa.com/products/{goods_id}"
    }

    endpoints = [
        f"https://goods-detail.musinsa.com/goods/{goods_id}",
        f"https://www.musinsa.com/products/{goods_id}",
        f"https://www.musinsa.com/app/goods/{goods_id}"
    ]

    session = requests.Session()

    for url in endpoints:
        try:
            res = session.get(url, headers=headers, timeout=3)

            if res.status_code == 200:
                raw_text = res.text

                try:
                    data = res.json()
                    if isinstance(data, dict):
                        if "data" in data and isinstance(data["data"], dict):
                            data = data["data"]

                        goods_name = data.get("goodsNm") or data.get("goodsName") or data.get("name") or data.get("title")
                        brand_name = extract_brand_name(raw_text, data)

                        price = data.get("price") or data.get("salePrice") or data.get("finalPrice")
                        normal_price = data.get("normalPrice") or data.get("originalPrice") or price

                        if goods_name and price:
                            price = int(price)
                            normal_price = int(normal_price) if normal_price else price
                            discount_rate = round(((normal_price - price) / normal_price) * 100, 1) if normal_price > price else 0

                            return {
                                "goods_id": str(goods_id),
                                "goods_name": goods_name,
                                "brand_name": brand_name,
                                "category": "의류",
                                "normal_price": normal_price,
                                "price": price,
                                "discount_rate": discount_rate,
                                "url": f"https://www.musinsa.com/products/{goods_id}"
                            }
                except Exception:
                    pass

                name_match = (
                    re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', raw_text) or
                    re.search(r'"goodsNm"\s*:\s*"([^"]+)"', raw_text) or
                    re.search(r'"goodsName"\s*:\s*"([^"]+)"', raw_text)
                )
                price_match = (
                    re.search(r'<meta\s+property="product:price:amount"\s+content="(\d+)"', raw_text) or
                    re.search(r'"price"\s*:\s*(\d+)', raw_text) or
                    re.search(r'"salePrice"\s*:\s*(\d+)', raw_text)
                )
                normal_price_match = (
                    re.search(r'"normalPrice"\s*:\s*(\d+)', raw_text) or
                    re.search(r'"originalPrice"\s*:\s*(\d+)', raw_text)
                )

                if name_match and price_match:
                    goods_name = name_match.group(1).replace(" - 무신사", "").replace(" - MUSINSA", "").strip()
                    brand_name = extract_brand_name(raw_text)
                    price = int(price_match.group(1))
                    normal_price = int(normal_price_match.group(1)) if normal_price_match else price
                    discount_rate = round(((normal_price - price) / normal_price) * 100, 1) if normal_price > price else 0

                    return {
                        "goods_id": str(goods_id),
                        "goods_name": goods_name,
                        "brand_name": brand_name,
                        "category": "의류",
                        "normal_price": normal_price,
                        "price": price,
                        "discount_rate": discount_rate,
                        "url": f"https://www.musinsa.com/products/{goods_id}"
                    }

        except Exception:
            continue

    return None

# DB 데이터 렌더링 헬퍼
def load_tracked_products():
    try:
        res = supabase.table("tracked_products").select("*").order("created_at", desc=True).execute()
        return pd.DataFrame(res.data)
    except Exception:
        return pd.DataFrame()

def load_price_logs():
    try:
        res = supabase.table("price_logs").select("*").order("created_at", desc=False).execute()
        df = pd.DataFrame(res.data)
        if not df.empty:
            df["created_at"] = pd.to_datetime(df["created_at"], format='mixed', errors='coerce', utc=True)
            df = df.dropna(subset=["created_at"])
            df = df.sort_values("created_at", ascending=True) # 날짜 오름차순 정렬 보장

            df["created_at_kst"] = df["created_at"].dt.tz_convert("Asia/Seoul")
            df["date_str"] = df["created_at_kst"].dt.strftime("%m/%d")         # 차트용 MM/DD 표기
            df["full_date_str"] = df["created_at_kst"].dt.strftime("%Y-%m-%d") # 당일 최신화 확인용 YYYY-MM-DD
            
            df["discount_rate"] = df.apply(
                lambda r: round(((r["normal_price"] - r["price"]) / r["normal_price"]) * 100, 1) 
                if r["normal_price"] > r["price"] else 0, axis=1
            )
        return df
    except Exception:
        return pd.DataFrame()

# 앱 접속 시 오늘 가격 자동 동기화 함수
def sync_today_prices_if_needed(products_df):
    if products_df.empty:
        return

    today_str = pd.Timestamp.now(tz="Asia/Seoul").strftime("%Y-%m-%d")
    
    try:
        today_start = f"{today_str}T00:00:00Z"
        res = supabase.table("price_logs").select("goods_id").gte("created_at", today_start).execute()
        synced_goods_ids = set([row["goods_id"] for row in res.data]) if res.data else set()
    except Exception:
        synced_goods_ids = set()

    unsynced_products = products_df[~products_df["goods_id"].isin(synced_goods_ids)]
    
    if not unsynced_products.empty:
        updated_count = 0
        for idx, row in unsynced_products.iterrows():
            g_id = row["goods_id"]
            info = get_musinsa_goods_info(g_id)
            if info:
                log_data = {
                    "goods_id": info["goods_id"],
                    "normal_price": info["normal_price"],
                    "price": info["price"]
                }
                try:
                    supabase.table("price_logs").insert(log_data).execute()
                    updated_count += 1
                except Exception:
                    pass
                time.sleep(0.2)
        
        if updated_count > 0:
            st.toast(f"⚡ 오늘자 신규 가격 정보({updated_count}건)가 자동으로 동기화되었습니다!", icon="✅")

# 당일 최신화 상태 확인 헬퍼
def get_today_sync_status_badge(logs_df):
    today_str = pd.Timestamp.now(tz="Asia/Seoul").strftime("%Y-%m-%d")
    if not logs_df.empty and "full_date_str" in logs_df.columns:
        is_synced = (logs_df["full_date_str"] == today_str).any()
        if is_synced:
            return f"✅ 당일 최신화 완료 ({today_str})"
    return f"⚠️ 당일 가격 미업데이트 ({today_str})"

# =========================================================
# 최상위 2개 메인 탭 구성
# =========================================================
main_tab1, main_tab2 = st.tabs([
    "🛍 무신사 스마트 트래커", 
    "🏷 태그별 가격 비교"
])

# =========================================================
# MAIN TAB 1: 무신사 개별 상품 트래커
# =========================================================
with main_tab1:
    sub_tabs = ["➕ 추적 상품 관리", "📊 개별 상품 가격 추이", "⚡ 실시간 조회 (테스트)"]
    
    current_index = sub_tabs.index(st.session_state["sub_tab"]) if st.session_state["sub_tab"] in sub_tabs else 0
    selected_sub_tab = st.radio(
        "서브메뉴", 
        sub_tabs, 
        index=current_index, 
        horizontal=True, 
        label_visibility="collapsed",
        key="sub_tab_radio_select"
    )
    st.session_state["sub_tab"] = selected_sub_tab

    st.divider()

    # -----------------------------------------------------
    # SUB TAB 1: 무신사 추적 상품 관리 (첫 화면)
    # -----------------------------------------------------
    if selected_sub_tab == "➕ 추적 상품 관리":
        products_df = load_tracked_products()
        tracked_df = products_df

        # 앱 첫 접속 시 자동 동기화 실행 (타임아웃 3초)
        if "today_synced" not in st.session_state and not products_df.empty:
            with st.spinner("🔄 오늘자 최신 가격 정보를 자동으로 확인하는 중..."):
                sync_today_prices_if_needed(products_df)
            st.session_state["today_synced"] = True

        logs_df = load_price_logs()

        # 최상단 당일 최신화 상태 표시
        sync_badge = get_today_sync_status_badge(logs_df)
        st.markdown(f"""
        <div style="background-color: #ebfbee; padding: 8px 12px; border-radius: 6px; border: 1px solid #b2f2bb; font-size: 12px; font-weight: bold; color: #2b8a3e; margin-bottom: 12px;">
            {sync_badge}
        </div>
        """, unsafe_allow_html=True)

        # DB에 등록된 기존 태그 추출
        existing_tags = set()
        if not products_df.empty and "tags" in products_df.columns:
            for t_str in products_df["tags"].dropna():
                parts = [p.strip() for p in re.split(r'[,; ]+', str(t_str)) if p.strip()]
                for p in parts:
                    tag_name = p if p.startswith('#') else f"#{p}"
                    existing_tags.add(tag_name)
        existing_tag_list = sorted(list(existing_tags))

        st.subheader("➕ 새로운 추적 상품 추가")

        with st.form("add_product_form", clear_on_submit=True):
            input_url = st.text_input("무신사 상품 URL 또는 ID", placeholder="예: https://www.musinsa.com/app/goods/2081557 또는 2081557")
            
            selected_existing_tags = st.multiselect(
                "🏷️ 기존 태그에서 선택",
                options=existing_tag_list,
                placeholder="클릭하여 기존 태그 선택"
            )
            input_new_tags = st.text_input("✏️ 새 태그 직접 입력 (선택)", placeholder="예: #봄아우터, #가성비")
            
            submit_button = st.form_submit_button("추적 등록하기")

        if submit_button:
            if not input_url.strip():
                st.warning("⚠️ 상품 URL 또는 ID를 입력해 주세요.")
            else:
                goods_id = parse_goods_id(input_url)
                if not goods_id:
                    st.error("❌ 입력된 내용에서 올바른 무신사 상품 ID(숫자)를 찾을 수 없습니다.")
                else:
                    combined_tags = list(selected_existing_tags)
                    if input_new_tags.strip():
                        new_parts = [p.strip() for p in re.split(r'[,; ]+', input_new_tags) if p.strip()]
                        for p in new_parts:
                            tag_name = p if p.startswith('#') else f"#{p}"
                            if tag_name not in combined_tags:
                                combined_tags.append(tag_name)
                    
                    final_tag_str = ", ".join(combined_tags) if combined_tags else ""

                    with st.spinner(f"상품 ID({goods_id}) 정보를 수집하고 DB에 등록하는 중..."):
                        info = get_musinsa_goods_info(goods_id)
                        if info:
                            prod_data = {
                                "goods_id": info["goods_id"],
                                "goods_name": info["goods_name"],
                                "brand_name": info["brand_name"],
                                "category": "의류",
                                "tags": final_tag_str,
                                "url": info["url"]
                            }
                            
                            try:
                                supabase.table("tracked_products").upsert(prod_data).execute()
                            except Exception:
                                prod_data.pop("brand_name", None)
                                if info["brand_name"] and info["brand_name"] != "MUSINSA":
                                    prod_data["goods_name"] = f"[{info['brand_name']}] {info['goods_name']}"
                                supabase.table("tracked_products").upsert(prod_data).execute()

                            log_data = {
                                "goods_id": info["goods_id"],
                                "normal_price": info["normal_price"],
                                "price": info["price"]
                            }
                            supabase.table("price_logs").insert(log_data).execute()

                            st.success(f"✅ **[{info['brand_name']}] {info['goods_name']}** 상품이 등록되었습니다!")
                            st.rerun()
                        else:
                            st.error("🚨 상품 정보 수집에 실패하여 DB에 등록하지 못했습니다.")

        st.divider()

        st.subheader("📋 현재 추적 중인 상품 목록")

        if tracked_df.empty:
            st.info("등록된 추적 상품이 없습니다.")
        else:
            manage_tag_options = ["전체"] + existing_tag_list
            selected_manage_tag = st.selectbox("🏷 태그 필터링", manage_tag_options, key="manage_tab_tag_select")

            filtered_tracked = tracked_df.copy()
            if selected_manage_tag != "전체":
                clean_tag = selected_manage_tag.lstrip('#')
                filtered_tracked = filtered_tracked[
                    filtered_tracked["tags"].fillna('').str.contains(clean_tag, case=False, regex=False)
                ]

            if filtered_tracked.empty:
                st.info(f"선택한 **{selected_manage_tag}** 태그에 해당하는 상품이 없습니다.")
            else:
                cards_html_list = []

                for _, row in filtered_tracked.iterrows():
                    brand = row.get("brand_name") if "brand_name" in row and pd.notna(row.get("brand_name")) else "무신사"
                    curr_tag = row.get("tags") if pd.notna(row.get("tags")) and str(row.get("tags")).strip() else "태그없음"

                    p_logs = logs_df[logs_df["goods_id"] == row["goods_id"]] if not logs_df.empty else pd.DataFrame()
                    
                    price_html_str = "수집중"
                    bg_color = "#ffffff"       # 기본 배경색: 흰색
                    border_style = "1px solid #e9ecef"   # 기본 테두리: 연회색

                    if not p_logs.empty:
                        p_logs_daily = p_logs.drop_duplicates(subset=["full_date_str"], keep="last")
                        p_logs_daily = p_logs_daily.sort_values("created_at", ascending=True)
                        
                        latest_p = p_logs_daily.iloc[-1]
                        c_price = int(latest_p['price'])
                        n_price = int(latest_p['normal_price'])
                        disc = latest_p.get('discount_rate', 0)

                        initial_price = int(p_logs_daily.iloc[0]['price'])  # 최초 등록 가격
                        min_price = int(p_logs['price'].min())              # 역대 최저가

                        if len(p_logs_daily) >= 2:
                            prev_price = int(p_logs_daily.iloc[-2]['price'])
                            if c_price < prev_price:
                                bg_color = "#e7f5ff"
                                border_style = "1px solid #74c0fc"
                            elif c_price > prev_price:
                                bg_color = "#fff5f5"
                                border_style = "1px solid #ffc9c9"

                        if c_price == min_price and c_price < initial_price:
                            border_style = "2px solid #fcc419"

                        if n_price > c_price and disc > 0:
                            price_html_str = f"<span style='color:#d9480f;'>{disc}%</span> {c_price:,}원"
                        else:
                            price_html_str = f"{c_price:,}원"

                    single_card = (
                        f'<a href="?goods_id={row["goods_id"]}&tab=detail" target="_self" style="text-decoration:none; color:inherit; display:block;">'
                        f'<div style="background:{bg_color}; border:{border_style}; border-radius:6px; padding:6px; box-sizing:border-box; overflow:hidden; display:flex; flex-direction:column; justify-content:space-between; cursor:pointer;">'
                        f'<div>'
                        f'<div style="font-size:9px; color:#868e96; font-weight:600; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">{brand}</div>'
                        f'<div style="font-size:10px; font-weight:bold; color:#212529; line-height:1.25; height:25px; overflow:hidden; text-overflow:ellipsis; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; margin:2px 0 4px 0;">{row["goods_name"]}</div>'
                        f'</div>'
                        f'<div>'
                        f'<div style="font-size:10px; font-weight:bold; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; margin-bottom:3px;">{price_html_str}</div>'
                        f'<div style="font-size:9px; color:#2b8a3e; background:#e6fcf5; display:inline-block; padding:1px 4px; border-radius:3px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:100%;">🏷️ {curr_tag}</div>'
                        f'</div>'
                        f'</div>'
                        f'</a>'
                    )
                    cards_html_list.append(single_card)

                full_grid_html = (
                    f'<div style="display:grid; grid-template-columns:repeat(3, 1fr); gap:6px; width:100%; box-sizing:border-box; margin-bottom:15px;">'
                    f'{"".join(cards_html_list)}'
                    f'</div>'
                )

                st.markdown(full_grid_html, unsafe_allow_html=True)

                # -------------------------------------------------
                # 하단 전용 상품 관리 패널 (태그 수정 및 삭제)
                # -------------------------------------------------
                st.markdown("#### ⚙️ 상품 관리 (태그 수정 / 삭제)")
                
                manage_options = {
                    f"[{r.get('brand_name', '무신사')}] {r['goods_name']}": r
                    for _, r in filtered_tracked.iterrows()
                }

                selected_label = st.selectbox("관리할 상품 선택", list(manage_options.keys()), key="manage_prod_select")
                selected_prod = manage_options[selected_label]

                col_m1, col_m2 = st.columns([2, 1])

                curr_prod_tag_str = selected_prod.get("tags") if pd.notna(selected_prod.get("tags")) else ""
                curr_prod_tags = [p.strip() if p.strip().startswith('#') else f"#{p.strip()}" for p in re.split(r'[,; ]+', str(curr_prod_tag_str)) if p.strip()]
                
                edit_option_tags = sorted(list(set(existing_tag_list + curr_prod_tags)))

                with col_m1:
                    with st.form(key=f"manage_tag_form_{selected_prod['goods_id']}"):
                        edit_selected = st.multiselect(
                            "🏷️ 기존 태그 선택/수정", 
                            options=edit_option_tags, 
                            default=[t for t in curr_prod_tags if t in edit_option_tags]
                        )
                        edit_new = st.text_input("✏️ 새 태그 추가 (선택)", placeholder="예: #봄아우터")
                        
                        if st.form_submit_button("🏷️ 태그 저장", use_container_width=True):
                            combined_edit = list(edit_selected)
                            if edit_new.strip():
                                new_parts = [p.strip() for p in re.split(r'[,; ]+', edit_new) if p.strip()]
                                for p in new_parts:
                                    tag_name = p if p.startswith('#') else f"#{p}"
                                    if tag_name not in combined_edit:
                                        combined_edit.append(tag_name)
                            
                            final_edit_tag_str = ", ".join(combined_edit) if combined_edit else ""

                            supabase.table("tracked_products").update({"tags": final_edit_tag_str}).eq("goods_id", selected_prod["goods_id"]).execute()
                            st.toast("✅ 태그가 성공적으로 수정되었습니다!", icon="🎉")
                            time.sleep(0.3)
                            st.rerun()

                with col_m2:
                    st.write("")
                    st.write("")
                    if st.button("🗑️ 추적 삭제", key=f"manage_del_btn_{selected_prod['goods_id']}", use_container_width=True):
                        supabase.table("tracked_products").delete().eq("goods_id", selected_prod["goods_id"]).execute()
                        st.success("삭제되었습니다.")
                        time.sleep(0.3)
                        st.rerun()

    # -----------------------------------------------------
    # SUB TAB 2: 개별 상품 가격 추이 대시보드
    # -----------------------------------------------------
    elif selected_sub_tab == "📊 개별 상품 가격 추이":
        products_df = load_tracked_products()
        logs_df = load_price_logs()

        if products_df.empty:
            st.info("아직 추적 중인 상품이 없습니다. '➕ 추적 상품 관리' 탭에서 상품을 추가해 보세요!")
        else:
            tag_options = ["전체"]
            if "tags" in products_df.columns:
                extracted_tags = set()
                for t_str in products_df["tags"].dropna():
                    parts = [p.strip() for p in re.split(r'[,; ]+', str(t_str)) if p.strip()]
                    for p in parts:
                        tag_name = p if p.startswith('#') else f"#{p}"
                        extracted_tags.add(tag_name)
                tag_options += sorted(list(extracted_tags))

            col_f1, col_f2 = st.columns(2)
            with col_f1:
                selected_tag = st.selectbox("🏷 태그 필터", tag_options)

            filtered_products = products_df.copy()
            if selected_tag != "전체":
                clean_tag = selected_tag.lstrip('#')
                filtered_products = filtered_products[
                    filtered_products["tags"].fillna('').str.contains(clean_tag, case=False, regex=False)
                ]

            if filtered_products.empty:
                st.warning("선택한 태그에 지정된 상품이 없습니다.")
            else:
                filtered_products["display_name"] = filtered_products.apply(
                    lambda r: f"[{r['brand_name']}] {r['goods_name']}" if pd.notna(r.get('brand_name')) and str(r.get('brand_name')).strip() else r['goods_name'],
                    axis=1
                )

                display_options = list(filtered_products["display_name"].unique())

                default_idx = 0
                if "selected_goods_id" in st.session_state:
                    target_gid = str(st.session_state["selected_goods_id"])
                    target_row = filtered_products[filtered_products["goods_id"].astype(str) == target_gid]
                    if not target_row.empty:
                        target_disp = target_row.iloc[0]["display_name"]
                        if target_disp in display_options:
                            default_idx = display_options.index(target_disp)

                with col_f2:
                    selected_display_name = st.selectbox("🛍 조회할 상품 선택", display_options, index=default_idx)

                product_info = filtered_products[filtered_products["display_name"] == selected_display_name].iloc[0]
                g_id = product_info["goods_id"]

                brand = product_info.get("brand_name") if "brand_name" in product_info and pd.notna(product_info.get("brand_name")) else ""
                if brand:
                    st.caption(f"🏷 **{brand}**")
                st.subheader(product_info["goods_name"])
                st.caption(f"태그: {product_info.get('tags', '-')}")
                
                product_logs = logs_df[logs_df["goods_id"] == g_id] if not logs_df.empty else pd.DataFrame()
                
                if not product_logs.empty:
                    product_logs = product_logs.sort_values("created_at", ascending=True) # 시간순 오름차순
                    latest_row = product_logs.iloc[-1]
                    min_price = int(product_logs["price"].min())
                    max_discount = product_logs["discount_rate"].max()
                    norm_price = int(latest_row['normal_price'])
                    curr_price = int(latest_row['price'])

                    st.markdown(f"""<div style="background-color: #f8f9fa; padding: 10px 14px; border-radius: 8px; border: 1px solid #e9ecef; margin: 8px 0;"><div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; font-size: 12px;"><div><span style="color: #6c757d;">정가:</span> <del style="color: #868e96;">{norm_price:,}원</del></div><div><span style="color: #6c757d;">현재 판매가:</span> <b style="color: #212529; font-size: 13px;">{curr_price:,}원</b></div><div><span style="color: #6c757d;">기간 내 최저가:</span> <b style="color: #1971c2;">{min_price:,}원</b></div><div><span style="color: #6c757d;">최대 할인율:</span> <b style="color: #d9480f;">{max_discount}% 🔥</b></div></div></div>""", unsafe_allow_html=True)

                st.markdown(f"👉 [무신사 상품 페이지 바로가기]({product_info['url']})")

                st.divider()

                if not product_logs.empty:
                    st.markdown("### 📈 가격 및 할인율 변동 추이")
                    
                    p_min = int(product_logs["price"].min())
                    p_max = int(product_logs["price"].max())
                    p_pad = max(5000, int((p_max - p_min) * 0.2)) if p_max != p_min else 10000

                    fig_price = px.line(
                        product_logs, 
                        x="date_str", 
                        y="price", 
                        markers=True,
                        labels={"date_str": "날짜 (월/일)", "price": "판매가(원)"}
                    )
                    fig_price.update_traces(
                        marker=dict(size=10),
                        hovertemplate="<b>날짜:</b> %{x}<br><b>판매가:</b> %{y:,}원<extra></extra>"
                    )
                    fig_price.update_xaxes(type='category', tickangle=0)
                    fig_price.update_yaxes(
                        range=[max(0, p_min - p_pad), p_max + p_pad], 
                        tickformat=",d", 
                        ticksuffix="원"
                    )
                    fig_price.update_layout(margin=dict(l=10, r=10, t=10, b=10))
                    st.plotly_chart(fig_price, use_container_width=True)

                    min_d = product_logs["discount_rate"].min()
                    max_d = product_logs["discount_rate"].max()

                    d_min = max(0, (int(min_d) // 5) * 5 - 5)
                    d_max = min(100, ((int(max_d) // 5) + 1) * 5 + 5)
                    if d_min >= d_max:
                        d_max = d_min + 10

                    fig_discount = px.line(
                        product_logs, 
                        x="date_str", 
                        y="discount_rate", 
                        markers=True,
                        labels={"date_str": "날짜 (월/일)", "discount_rate": "할인율 (%)"}
                    )
                    fig_discount.update_traces(
                        marker=dict(size=10),
                        hovertemplate="<b>날짜:</b> %{x}<br><b>할인율:</b> %{y}%<extra></extra>"
                    )
                    fig_discount.update_xaxes(type='category', tickangle=0)
                    fig_discount.update_yaxes(dtick=5, range=[d_min, d_max], ticksuffix="%")
                    fig_discount.update_layout(margin=dict(l=10, r=10, t=10, b=10))
                    st.plotly_chart(fig_discount, use_container_width=True)
                else:
                    st.info("아직 누적된 가격 로그 데이터가 없습니다.")

    # -----------------------------------------------------
    # SUB TAB 3: 무신사 실시간 조회
    # -----------------------------------------------------
    elif selected_sub_tab == "⚡ 실시간 조회 (테스트)":
        st.subheader("⚡ 실시간 가격 조회 (DB 저장 X)")
        test_input = st.text_input("테스트할 무신사 상품 URL 또는 ID", value="2081557")
        if st.button("🔍 실시간 조회"):
            if not test_input.strip():
                st.warning("⚠️ URL 또는 상품 ID를 입력해 주세요.")
            else:
                g_id = parse_goods_id(test_input)
                if not g_id:
                    st.error("❌ 올바른 상품 ID(숫자)를 추출하지 못했습니다.")
                else:
                    with st.spinner(f"상품 ID({g_id}) 실시간 정보 조회 중..."):
                        live = get_musinsa_goods_info(g_id)
                        if live:
                            st.success("🎉 실시간 조회 성공!")
                            st.write(f"**브랜드:** {live['brand_name']}")
                            st.write(f"**상품명:** {live['goods_name']}")
                            st.markdown(f"**정가:** ~~{live['normal_price']:,} 원~~")
                            st.markdown(f"**판매가:** {live['price']:,} 원")
                            st.markdown(f"**할인율:** {live['discount_rate']}% 🔥")
                            st.markdown(f"👉 [페이지 열기]({live['url']})")
                        else:
                            st.error("🚨 실시간 가격 조회에 실패했습니다.")

# =========================================================
# MAIN TAB 2: 무신사 태그별 가격 비교 대시보드
# =========================================================
with main_tab2:
    st.subheader("🏷️ 태그별 상품 가격 비교 대시보드")
    products_df = load_tracked_products()
    logs_df = load_price_logs()

    if products_df.empty:
        st.info("추적 중인 상품이 없습니다.")
    else:
        tag_options = ["전체"]
        if "tags" in products_df.columns:
            extracted_tags = set()
            for t_str in products_df["tags"].dropna():
                parts = [p.strip() for p in re.split(r'[,; ]+', str(t_str)) if p.strip()]
                for p in parts:
                    tag_name = p if p.startswith('#') else f"#{p}"
                    extracted_tags.add(tag_name)
            tag_options += sorted(list(extracted_tags))

        selected_tag = st.selectbox("🏷️ 비교할 태그 선택", tag_options)

        if selected_tag == "전체":
            tagged_products = products_df.copy()
            st.success(f"**전체** 상품: 총 **{len(tagged_products)}개**")
        else:
            clean_tag = selected_tag.lstrip('#')
            tagged_products = products_df[
                products_df["tags"].fillna('').str.contains(clean_tag, case=False, regex=False)
            ]
            st.success(f"**{selected_tag}** 태그 지정 상품: 총 **{len(tagged_products)}개**")

        if tagged_products.empty:
            st.info(f"현재 선택한 조건에 해당하는 상품이 없습니다.")
        else:
            if not logs_df.empty:
                tag_goods_ids = tagged_products["goods_id"].tolist()
                tag_logs = logs_df[logs_df["goods_id"].isin(tag_goods_ids)].copy()

                if not tag_logs.empty:
                    # 시간순 오름차순 정렬 보장
                    tag_logs = tag_logs.sort_values("created_at", ascending=True)
                    tag_logs = tag_logs.merge(tagged_products[["goods_id", "goods_name", "brand_name"]], on="goods_id", how="left")
                    tag_logs["display_name"] = tag_logs.apply(
                        lambda r: f"[{r['brand_name']}] {r['goods_name']}" if pd.notna(r['brand_name']) and r['brand_name'] else r['goods_name'],
                        axis=1
                    )

                    t_min = int(tag_logs["price"].min())
                    t_max = int(tag_logs["price"].max())
                    t_pad = max(5000, int((t_max - t_min) * 0.2)) if t_max != t_min else 10000

                    st.markdown(f"#### 📈 {'전체' if selected_tag == '전체' else selected_tag} 상품 가격 비교 추이")

                    fig_tag = px.line(
                        tag_logs,
                        x="date_str",
                        y="price",
                        color="display_name",
                        markers=True,
                        labels={"date_str": "날짜 (월/일)", "price": "판매가(원)", "display_name": "상품명"}
                    )
                    fig_tag.update_traces(
                        marker=dict(size=8),
                        hovertemplate="<b>%{fullData.name}</b><br>날짜: %{x}<br>판매가: %{y:,}원<extra></extra>"
                    )
                    fig_tag.update_xaxes(type='category', tickangle=0)
                    fig_tag.update_yaxes(
                        range=[max(0, t_min - t_pad), t_max + t_pad], 
                        tickformat=",d", 
                        ticksuffix="원"
                    )
                    fig_tag.update_layout(
                        margin=dict(l=10, r=10, t=20, b=80),
                        legend=dict(
                            orientation="h",
                            yanchor="top",
                            y=-0.25,
                            xanchor="left",
                            x=0,
                            font=dict(size=10)
                        )
                    )
                    st.plotly_chart(fig_tag, use_container_width=True)

            st.divider()
            st.markdown(f"#### 📋 {'전체' if selected_tag == '전체' else selected_tag} 포함 상품 목록")

            for _, p_row in tagged_products.iterrows():
                b_str = f"[{p_row['brand_name']}] " if pd.notna(p_row.get('brand_name')) and p_row.get('brand_name') else ""
                st.markdown(f"**{b_str}{p_row['goods_name']}**")
                st.caption(f"태그: `{p_row.get('tags', '-')}` | [상품 이동]({p_row['url']})")
                st.divider()
