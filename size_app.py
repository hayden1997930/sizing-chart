import streamlit as st
import json
from collections import defaultdict
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import time

# ============ 頁面設定與隱藏工具列 ============
st.set_page_config(page_title="衣服尺寸推薦", page_icon="👕", layout="centered", menu_items={})

hide_streamlit_style = """
            <style>
            #MainMenu {visibility: hidden;}
            header {visibility: hidden;}
            footer {visibility: hidden;}
            .stDeployButton {display:none;}
            [data-testid="stStatusWidget"] {visibility: hidden;}
            </style>
            """
st.markdown(hide_streamlit_style, unsafe_allow_html=True)

# ============ 尺碼表 ============
HAN_YI_CHART = [(38, "S"), (40, "M"), (42, "L"), (44, "XL"), (46, "XXL")]
ALL_ITEMS = ["汗衣", "藍扯衫", "藍扯褲", "安全鞋", "水鞋"]
ADMIN_PASSWORD = "admin123"

# ============ Google Sheets 連接 ============
conn = st.connection("gsheets", type=GSheetsConnection)

# 取消 ttl="10s" 的快取，確保每次都讀取最新資料
def load_data():
    try:
        df = conn.read(ttl=0)
        if df.empty or 'record' not in df.columns:
            return []
        records = df['record'].dropna().tolist()
        return [json.loads(r) for r in records if r]
    except Exception as e:
        st.error(f"讀取資料失敗: {e}")
        return []

def save_data(data):
    try:
        records = [json.dumps(p, ensure_ascii=False) for p in data]
        df_to_save = pd.DataFrame({'record': records})
        conn.update(worksheet="data", data=df_to_save)
        # 清除 Streamlit 的資料快取，強制下次重新讀取
        st.cache_data.clear()
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
    return None

# ============ 推薦演算法 (KNN) ============
def recommend_one(item_type, height, weight, top_n=10):
    data = [p for p in load_data() if item_type in p.get("items", {})]
    if not data:
        return None
    
    bmi = weight / (height / 100) ** 2
    scored = []
    for p in data:
        p_bmi = p["weight"] / (p["height"] / 100) ** 2
        dist = ((p["height"] - height) / 2) ** 2 + ((p_bmi - bmi) / 2) ** 2
        scored.append((dist, p["items"][item_type]))
        
    scored.sort(key=lambda x: x[0])
    neighbors = scored[:top_n]

    dims_sum, total_w = defaultdict(float), 0.0
    for dist, item in neighbors:
        w = 1 / (dist + 0.1)
        total_w += w
        for k, v in item.items():
            dims_sum[k] += v * w
            
    raw_dims = {k: v / total_w for k, v in dims_sum.items()}
    
    dims = {}
    if item_type == "汗衣":
        raw_chest = raw_dims.get("chest", 42.0)
        closest_even = round(raw_chest / 2) * 2
        dims["chest"] = float(closest_even)
    else:
        for k, v in raw_dims.items():
            dims[k] = round(v * 2) / 2
            
    size = to_size(item_type, dims)
    return {"dims": dims, "size": size}

# ============ 介面設計 ============
st.title("👕 衣服尺寸推薦系統")

tab1, tab2, tab3 = st.tabs(["🔍 查詢建議", "➕ 新增人員", "📊 資料管理"])

# ---------- Tab 1：查詢 ----------
with tab1:
    st.subheader("輸入身高體重，即時獲得建議")
    col1, col2 = st.columns(2)
    with col1:
        height = st.number_input("身高 (cm)", 100.0, 250.0, 172.0, 0.5, key="q_h")
    with col2:
        weight = st.number_input("體重 (kg)", 20.0, 200.0, 70.0, 0.5, key="q_w")

    if st.button("🎯 推薦尺寸", type="primary", use_container_width=True):
        with st.spinner("正在計算最適合您的尺寸..."):
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
                    
                    if t == "汗衣":
                        dim_str = f"{int(r['dims'].get('chest', 0))}"
                    elif t == "藍扯衫":
                        dim_str = f"{r['dims'].get('a','?')} x {r['dims'].get('b','?')}"
                    elif t == "藍扯褲":
                        dim_str = f"{r['dims'].get('waist','?')} x {r['dims'].get('length','?')}"
                    elif t == "安全鞋":
                        dim_str = f"{r['dims'].get('size','?')}"
                    elif t == "水鞋":
                        dim_str = f"US {r['dims'].get('size','?')}"
                        
                    with st.container(border=True):
                        st.markdown(f"### {t}")
                        if t == "汗衣":
                            c1, c2 = st.columns(2)
                            c1.metric("建議尺寸", dim_str)
                            c2.metric("建議尺碼", r["size"] or "—")
                        else:
                            st.metric("建議尺寸", dim_str)

# ---------- 定義共用彈窗 ----------
if "dialog_type" not in st.session_state:
    st.session_state.dialog_type = None

@st.dialog("✅ 操作成功")
def success_dialog(action_type):
    st.write(f"資料已成功{action_type}！")
    if st.button("確定", use_container_width=True):
        st.session_state.dialog_type = None
        st.rerun()

if st.session_state.dialog_type:
    success_dialog(st.session_state.dialog_type)

# ---------- Tab 2：新增 ----------
with tab2:
    st.subheader("新增人員資料")
    with st.form("add_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            h = st.number_input("身高 (cm)", 100.0, 250.0, 172.0, 0.5, key="a_h")
        with c2:
            w = st.number_input("體重 (kg)", 20.0, 200.0, 70.0, 0.5, key="a_w")
            
        st.markdown("**各品類尺寸 — 留空表示沒有**")
        chest = st.number_input("汗衣 胸寬 (38/40/42/44...)", 0.0, 60.0, 42.0, 2.0, key="a_c")
        shirt = st.text_input("藍扯衫 a x b（例 15x33）", "15x33")
        pants = st.text_input("藍扯褲 腰圍x褲長（例 32x42）", "32x42")
        safety_shoes = st.number_input("安全鞋 尺寸（例 42）", 0.0, 50.0, 0.0, 0.5, key="a_s")
        rain_boots = st.text_input("水鞋 US尺寸（例 9）", "")

        submitted = st.form_submit_button("✅ 儲存", type="primary", use_container_width=True)
        
        if submitted:
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
            if safety_shoes > 0:
                items["安全鞋"] = {"size": float(safety_shoes)}
            if rain_boots.strip():
                try:
                    items["水鞋"] = {"size": float(rain_boots)}
                except ValueError:
                    st.error("水鞋格式錯誤，請輸入數字（例如 9 或 8.5）")

            if items:
                data = load_data()
                new_id = int(time.time() * 1000)
                data.append({"id": new_id, "name": "匿名", "height": h, "weight": w, "items": items})
                if save_data(data):
                    st.session_state.dialog_type = "新增"
                    st.rerun()
            else:
                st.warning("請至少填一項尺寸")

# ---------- Tab 3：資料管理 ----------
with tab3:
    st.subheader("📊 資料庫一覽與修改")
    
    data = load_data()
    if not data:
        st.info("尚無資料。")
    else:
        display_table = []
        for p in data:
            row = {"ID": p.get("id", "-"), "身高(cm)": p["height"], "體重(kg)": p["weight"]}
            for t in ALL_ITEMS:
                if t in p.get("items", {}):
                    d = p["items"][t]
                    if t == "汗衣":
                        row[t] = f"{int(d.get('chest', ''))} ({to_size(t, d)})"
                    elif t == "藍扯衫":
                        row[t] = f"{d.get('a', '')} x {d.get('b', '')}"
                    elif t == "藍扯褲":
                        row[t] = f"{d.get('waist', '')} x {d.get('length', '')}"
                    elif t == "安全鞋":
                        row[t] = f"{d.get('size', '')}"
                    elif t == "水鞋":
                        row[t] = f"US {d.get('size', '')}"
                else:
                    row[t] = "—"
            display_table.append(row)
            
        st.dataframe(display_table, use_container_width=True, hide_index=True)
        
        st.markdown("---")
        st.markdown("### ⚙️ 管理與修改")
        
        if "admin_authenticated" not in st.session_state:
            st.session_state.admin_authenticated = False
            
        if not st.session_state.admin_authenticated:
            pwd = st.text_input("請輸入管理員密碼以解鎖修改功能：", type="password")
            if st.button("🔓 解鎖"):
                if pwd == ADMIN_PASSWORD:
                    st.session_state.admin_authenticated = True
                    st.rerun()
                else:
                    st.error("❌ 密碼錯誤！")
        else:
            st.success("✅ 已解鎖管理權限")
            if st.button("🔒 鎖定權限"):
                st.session_state.admin_authenticated = False
                st.rerun()
                
            st.markdown("#### ✏️ 修改現有資料")
            options = {f"ID: {p.get('id', '-')} | {p['height']}cm {p['weight']}kg": p for p in data}
            selected_label = st.selectbox("選擇要修改的紀錄：", list(options.keys()))
            
            if selected_label:
                selected_person = options[selected_label]
                
                with st.form("edit_form"):
                    st.write("修改基本資料：")
                    ec1, ec2 = st.columns(2)
                    with ec1:
                        new_h = st.number_input("身高 (cm)", value=float(selected_person["height"]), step=0.5)
                    with ec2:
                        new_w = st.number_input("體重 (kg)", value=float(selected_person["weight"]), step=0.5)
                        
                    st.write("修改尺寸（留空或填 0 表示刪除此項目）：")
                    old_items = selected_person.get("items", {})
                    
                    old_chest = old_items.get("汗衣", {}).get("chest", 0.0)
                    new_chest = st.number_input("汗衣 胸寬", value=float(old_chest), step=2.0)
                    
                    old_shirt = old_items.get("藍扯衫", {})
                    new_shirt = st.text_input("藍扯衫 a x b", value=f"{old_shirt.get('a', '')}x{old_shirt.get('b', '')}" if old_shirt else "")
                    
                    old_pants = old_items.get("藍扯褲", {})
                    new_pants = st.text_input("藍扯褲 腰圍x褲長", value=f"{old_pants.get('waist', '')}x{old_pants.get('length', '')}" if old_pants else "")
                    
                    old_safety = old_items.get("安全鞋", {}).get("size", 0.0)
                    new_safety = st.number_input("安全鞋 尺寸", value=float(old_safety), step=0.5)
                    
                    old_boots = old_items.get("水鞋", {}).get("size", 0.0)
                    new_boots = st.number_input("水鞋 US尺寸", value=float(old_boots), step=0.5)
                    
                    update_btn = st.form_submit_button("💾 儲存修改", type="primary")
                    
                    if update_btn:
                        new_items = {}
                        if new_chest > 0: new_items["汗衣"] = {"chest": float(new_chest)}
                        if new_shirt.strip():
                            try:
                                a, b = new_shirt.lower().replace(" ", "").split("x")
                                new_items["藍扯衫"] = {"a": float(a), "b": float(b)}
                            except:
                                st.error("藍扯衫格式錯誤")
                        if new_pants.strip():
                            try:
                                wa, le = new_pants.lower().replace(" ", "").split("x")
                                new_items["藍扯褲"] = {"waist": float(wa), "length": float(le)}
                            except:
                                st.error("藍扯褲格式錯誤")
                        if new_safety > 0: new_items["安全鞋"] = {"size": float(new_safety)}
                        if new_boots > 0: new_items["水鞋"] = {"size": float(new_boots)}
                        
                        for i, p in enumerate(data):
                            if p.get("id") == selected_person.get("id"):
                                data[i]["height"] = new_h
                                data[i]["weight"] = new_w
                                data[i]["items"] = new_items
                                break
                                
                        if save_data(data):
                            st.session_state.dialog_type = "修改"
                            st.rerun()

        st.markdown("---")
        
        c1, c2 = st.columns(2)
        with c1:
            st.download_button("⬇️ 匯出 JSON", json.dumps(data, ensure_ascii=False, indent=2),
                               file_name="clothing_data.json", mime="application/json", use_container_width=True)
        with c2:
            if st.session_state.admin_authenticated:
                with st.popover("🗑️ 清空所有資料", use_container_width=True):
                    st.write("⚠️ 確定要刪除所有資料嗎？")
                    if st.button("確認清空", type="primary", use_container_width=True):
                        save_data([])
                        st.success("✅ 所有資料已清空！")
                        st.rerun()
            else:
                st.button("🗑️ 清空所有資料 (需解鎖)", disabled=True, use_container_width=True)
