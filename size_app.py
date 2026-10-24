import streamlit as st
import json
from collections import defaultdict
from streamlit_gsheets import GSheetsConnection
import pandas as pd

# ============ 尺碼表 ============
# 只有汗衣需要尺碼轉換
HAN_YI_CHART = [(38, "S"), (40, "M"), (42, "L"), (44, "XL"), (46, "XXL")]
ALL_ITEMS = ["汗衣", "藍扯衫", "藍扯褲"]

# ============ Google Sheets 連接 ============
conn = st.connection("gsheets", type=GSheetsConnection)

def load_data():
    """從 Google Sheets 讀取資料，解析 JSON 字串"""
    try:
        df = conn.read(ttl=0)
        if df.empty:
            return []
        if 'record' not in df.columns:
            return []
        # 過濾掉空值和 NaN
        records = df['record'].dropna().tolist()
        return [json.loads(r) for r in records if r]
    except Exception as e:
        st.error(f"讀取資料失敗: {e}")
        return []

def save_data(data):
    """把整個資料列表寫回 Google Sheets"""
    try:
        records = [json.dumps(p, ensure_ascii=False) for p in data]
        df_to_save = pd.DataFrame({'record': records})
        conn.update(worksheet="data", data=df_to_save)
        return True
    except Exception as e:
        st.error(f"儲存資料失敗: {e}")
        return False

# ============ 尺寸 → 尺碼 (只限汗衣) ============
def to_size(item_type, dims):
    if item_type == "汗衣":
        if "chest" not in dims:
            return None
        return min(HAN_YI_CHART, key=lambda x: abs(x[0] - dims["chest"]))[1]
    return None  # 藍扯衫、藍扯褲不需要尺碼

# ============ 推薦演算法 ============
def recommend_one(item_type, height, weight, top_n=10):
    data = [p for p in load_data() if item_type in p.get("items", {})]
    if not data:
        return None
    
    bmi = weight / (height / 100) ** 2
    scored = []
    for p in data:
        p_bmi = p["weight"] / (p["height"] / 100) ** 2
        dist = ((p["height"] - height) / 5) ** 2 + ((p_bmi - bmi) / 2) ** 2
        scored.append((dist, p["items"][item_type]))
        
    scored.sort(key=lambda x: x[0])
    neighbors = scored[:top_n]

    dims_sum, total_w = defaultdict(float), 0.0
    for dist, item in neighbors:
        w = 1 / (dist + 0.1)
        total_w += w
        for k, v in item.items():
            dims_sum[k] += v * w
            
    dims = {k: round(v / total_w, 1) for k, v in dims_sum.items()}
    size = to_size(item_type, dims)
    conf = (1 / (neighbors[0][0] + 0.1)) / total_w
    return {"dims": dims, "size": size, "conf": conf}

# ============ 介面設計 ============
st.set_page_config(page_title="衣服尺寸推薦", page_icon="👕", layout="centered")
st.title("👕 衣服尺寸推薦系統")

tab1, tab2, tab3 = st.tabs(["🔍 查詢建議", "➕ 新增人員", "📊 資料分佈"])

# ---------- Tab 1：查詢 ----------
with tab1:
    st.subheader("輸入身高體重，即時獲得建議")
    col1, col2 = st.columns(2)
    with col1:
        height = st.number_input("身高 (cm)", 100.0, 250.0, 172.0, 0.5, key="q_h")
    with col2:
        weight = st.number_input("體重 (kg)", 20.0, 200.0, 70.0, 0.5, key="q_w")

    if st.button("🎯 推薦尺寸", type="primary", use_container_width=True):
        with st.spinner("計算中..."):
            data = load_data()
            if not data:
                st.warning("⚠️ 資料庫還是空的，請先到「➕ 新增人員」錄入資料。")
            else:
                st.markdown("---")
                for t in ALL_ITEMS:
                    r = recommend_one(t, height, weight)
                    if not r:
                        st.info(f"❌ {t}：資料庫尚無此品類資料")
                        continue
                    
                    # 組合部位尺寸字串                    # 組合部位尺寸字串（統一格式，避免文字過長被截斷）
                    if t == "汗衣":
                        dim_str = f"{r['dims'].get('chest','?')} 吋"
                    elif t == "藍扯衫":
                        dim_str = f"{r['dims'].get('a','?')} x {r['dims'].get('b','?')} 吋"
                    elif t == "藍扯褲":
                        dim_str = f"{r['dims'].get('waist','?')} x {r['dims'].get('length','?')} 吋"
                        
                    with st.container(border=True):
                        st.markdown(f"### {t}")
                        
                        # 如果係汗衣，顯示尺寸＋尺碼；其他只顯示尺寸
                        if t == "汗衣":
                            c1, c2, c3 = st.columns(3)
                            c1.metric("建議尺寸", dim_str)
                            c2.metric("建議尺碼", r["size"] or "—")
                            c3.metric("信心度", f"{r['conf']:.0%}")
                        else:
                            c1, c2 = st.columns(2)
                            c1.metric("建議尺寸", dim_str)
                            c2.metric("信心度", f"{r['conf']:.0%}")
                            
                        if r["conf"] < 0.5:
                            st.caption("⚠️ 信心度偏低，建議試穿")

# ---------- Tab 2：新增 ----------
with tab2:
    st.subheader("新增人員資料")
    with st.form("add_form"):
        name = st.text_input("姓名")
        c1, c2 = st.columns(2)
        with c1:
            h = st.number_input("身高 (cm)", 100.0, 250.0, 172.0, 0.5, key="a_h")
        with c2:
            w = st.number_input("體重 (kg)", 20.0, 200.0, 70.0, 0.5, key="a_w")
            
        st.markdown("**各品類尺寸（吋）— 留空表示沒有**")
        chest = st.number_input("汗衣 胸寬", 0.0, 60.0, 42.0, 0.5, key="a_c")
        shirt = st.text_input("藍扯衫 a x b（例 15x33）", "15x33")
        pants = st.text_input("藍扯褲 腰圍x褲長（例 32x42）", "32x42")

        submitted = st.form_submit_button("✅ 儲存", type="primary", use_container_width=True)
        if submitted:
            if not name.strip():
                st.error("請輸入姓名")
            else:
                items = {}
                if chest > 0:
                    items["汗衣"] = {"chest": float(chest)}
                if shirt.strip():
                    try:
                        a, b = shirt.lower().replace(" ", "").split("x")
                        items["藍扯衫"] = {"a": float(a), "b": float(b)}
                    except ValueError:
                        st.error("藍扯衫格式錯誤，應為 15x33")
                if pants.strip():
                    try:
                        wa, le = pants.lower().replace(" ", "").split("x")
                        items["藍扯褲"] = {"waist": float(wa), "length": float(le)}
                    except ValueError:
                        st.error("藍扯褲格式錯誤，應為 32x42")

                if items:
                    data = load_data()
                    data.append({"name": name.strip(), "height": h, "weight": w, "items": items})
                    if save_data(data):
                        st.success(f"✅ 已新增 {name}")
                        st.rerun()
                else:
                    st.warning("請至少填一項尺寸")

# ---------- Tab 3：分佈 ----------
with tab3:
    st.subheader("資料分佈")
    data = load_data()
    if not data:
        st.info("尚無資料。")
    else:
        st.write(f"共 **{len(data)}** 筆記錄")
        for t in ALL_ITEMS:
            rows = [p for p in data if t in p.get("items", {})]
            if not rows:
                continue
            st.markdown(f"#### {t}（{len(rows)} 筆）")
            table = []
            for p in rows:
                d = p["items"][t]
                parts = "  ".join(f"{k}={v}" for k, v in d.items())
                # 只有汗衣在資料分佈表顯示尺碼
                size_display = to_size(t, d) if t == "汗衣" else "—"
                table.append({"姓名": p["name"], "身高": p["height"], "體重": p["weight"], "尺寸": parts, "尺碼": size_display})
            st.dataframe(table, use_container_width=True, hide_index=True)

        st.markdown("---")
        c1, c2 = st.columns(2)
        with c1:
            st.download_button("⬇️ 匯出 JSON", json.dumps(data, ensure_ascii=False, indent=2),
                               file_name="clothing_data.json", mime="application/json", use_container_width=True)
        with c2:
            if st.button("🗑️ 清空所有資料", use_container_width=True):
                save_data([])
                st.rerun()
