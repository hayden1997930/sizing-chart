import streamlit as st
import json
from collections import defaultdict
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import numpy as np
import time
from datetime import datetime

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

# ============ 尺碼表與選項設定 ============
HAN_YI_CHART = [(38, "S"), (40, "M"), (42, "L"), (44, "XL"), (46, "XXL")]
ALL_ITEMS = ["汗衣", "藍扯衫", "藍扯褲", "安全鞋", "水鞋"]
ADMIN_PASSWORD = "admin123"

# 自動生成選項清單
def generate_options(start, end, step):
    return [float(x) for x in np.arange(start, end + 0.1, step)]

# 1. 汗衣專屬選項 (顯示相應 Size)
CHEST_OPTIONS_RAW = [38.0, 40.0, 42.0, 44.0, 46.0]
CHEST_OPTIONS_DISPLAY = [f"{int(c)} ({next(s for v, s in HAN_YI_CHART if v == c)})" for c in CHEST_OPTIONS_RAW]

# 2. 其他品類選項 (0.5 一格)
SHIRT_A_OPTIONS = generate_options(13.0, 17.0, 0.5)  # 藍扯衫 a (13-17)
SHIRT_B_OPTIONS = generate_options(28.0, 40.0, 0.5)  # 藍扯衫 b
PANTS_W_OPTIONS = generate_options(28.0, 38.0, 0.5)  # 藍扯褲 waist
PANTS_L_OPTIONS = generate_options(36.0, 46.0, 0.5)  # 藍扯褲 length
SAFETY_OPTIONS = generate_options(36.0, 48.0, 0.5)   # 安全鞋 (36-48)
BOOTS_OPTIONS = generate_options(6.0, 11.0, 0.5)     # 水鞋 (US 6-11)

# ============ 跨性別偏移量配置 ============
FEMALE_OFFSET_CONFIG = {
    "汗衣": {"chest": -1.5},
    "藍扯衫": {"a": -1.0, "b": -1.5},
    "藍扯褲": {"waist": -1.5, "length": -1.0},
    "安全鞋": {"size": -1.5},
    "水鞋": {"size": -1.5}
}

# ============ Google Sheets 連接 ============
conn = st.connection("gsheets", type=GSheetsConnection)

def load_data():
    try:
        df = conn.read(ttl="15s")
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
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"儲存資料失敗: {e}")
        return False

# ============ 尺寸 → 尺碼 ============
def to_size(item_type, dims):
    if item_type == "汗衣":
        if "chest" not in dims:
            return None
        return min(HAN_YI_CHART, key=lambda x: abs(x[0] - dims["chest"]))[1]
    return None

# ============ 推薦演算法 (KNN) ============
def recommend_one(item_type, height, weight, target_gender, build, fit_pref, top_n=5, female_threshold=5):
    all_data = load_data()
    same_gender_data = [p for p in all_data if p.get("gender", "男") == target_gender and item_type in p.get("items", {})]
    
    is_using_offset = False
    use_data = same_gender_data
    
    if target_gender == "女" and len(same_gender_data) < female_threshold:
        use_data = [p for p in all_data if p.get("gender", "男") == "男" and item_type in p.get("items", {})]
        is_using_offset = True
        
    if not use_data:
        return None

    heights = np.array([p["height"] for p in use_data])
    weights = np.array([p["weight"] for p in use_data])
    bmis = weights / ((heights / 100) ** 2)
    
    h_mean, h_std = np.mean(heights), np.std(heights)
    b_mean, b_std = np.mean(bmis), np.std(bmis)
    h_std = h_std if h_std > 0 else 1.0
    b_std = b_std if b_std > 0 else 1.0
    
    input_bmi = weight / ((height / 100) ** 2)
    target_h_norm = (height - h_mean) / h_std
    target_bmi_norm = (input_bmi - b_mean) / b_std
    
    if item_type == "藍扯褲":
        w_height, w_bmi = 1.2, 0.8
    else:
        w_height, w_bmi = 1.0, 1.25

    scored = []
    for p in use_data:
        p_bmi = p["weight"] / ((p["height"] / 100) ** 2)
        p_h_norm = (p["height"] - h_mean) / h_std
        p_bmi_norm = (p_bmi - b_mean) / b_std
        
        dist = np.sqrt(w_height * ((p_h_norm - target_h_norm) ** 2) + w_bmi * ((p_bmi_norm - target_bmi_norm) ** 2))
        
        if build and p.get("build") and build != p["build"]:
            dist += 0.5
            
        scored.append((dist, p["items"][item_type]))
        
    scored.sort(key=lambda x: x[0])
    neighbors = scored[:min(top_n, len(scored))]

    dims_sum, total_w = defaultdict(float), 0.0
    for dist, item in neighbors:
        w = 1.0 / (dist + 0.1)
        total_w += w
        for k, v in item.items():
            dims_sum[k] += v * w
            
    raw_dims = {k: v / total_w for k, v in dims_sum.items()}

    if is_using_offset and item_type in FEMALE_OFFSET_CONFIG:
        offsets = FEMALE_OFFSET_CONFIG[item_type]
        for k, offset_val in offsets.items():
            if k in raw_dims:
                raw_dims[k] += offset_val

    adjust_val = 0
    if fit_pref == "寬鬆 / 預留空間":
        adjust_val = 1.0 if item_type != "汗衣" else 2.0
    elif fit_pref == "修身 / 偏緊":
        adjust_val = -0.5 if item_type != "汗衣" else -1.0

    dims = {}
    if item_type == "汗衣":
        raw_chest = raw_dims.get("chest", 42.0) + adjust_val
        dims["chest"] = float(round(raw_chest / 2) * 2)
    else:
        for k, v in raw_dims.items():
            if k in ["waist", "a", "size"]:
                dims[k] = round((v + adjust_val) * 2) / 2
            else:
                dims[k] = round(v * 2) / 2
            
    size = to_size(item_type, dims)
    return {"dims": dims, "size": size, "is_offset_used": is_using_offset}

# ============ 介面設計 ============
st.title("👕 衣服尺寸推薦系統")

tab1, tab2, tab3 = st.tabs(["🔍 查詢建議", "➕ 新增人員", "📊 資料管理"])

# ---------- Tab 1：查詢 ----------
with tab1:
    st.subheader("輸入身形資料，即時獲得建議")
    
    c0, c1, c2 = st.columns(3)
    with c0:
        gender = st.selectbox("性別", ["男", "女"], key="q_g")
    with c1:
        height = st.number_input("身高 (cm)", 100.0, 250.0, 172.0, 0.5, key="q_h")
    with c2:
        weight = st.number_input("體重 (kg)", 20.0, 200.0, 70.0, 0.5, key="q_w")
        
    c3, c4 = st.columns(2)
    with c3:
        build = st.selectbox("身型（選填）", ["不確定", "精壯 / 運動型", "標準", "偏肉 / 寬體"])
        if build == "不確定": build = None
    with c4:
        fit_pref = st.selectbox("穿著偏好", ["標準合身", "寬鬆 / 預留空間", "修身 / 偏緊"])

    if st.button("🎯 推薦尺寸", type="primary", use_container_width=True):
        with st.spinner("正在分析身形並計算最適合您的尺寸..."):
            data = load_data()
            if not data:
                st.warning("⚠️ 資料庫還是空的，請先到「➕ 新增人員」錄入資料。")
            else:
                st.markdown("---")
                for t in ALL_ITEMS:
                    r = recommend_one(t, height, weight, gender, build, fit_pref)
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
                            
                        if r.get("is_offset_used"):
                            st.caption("ℹ️ 女性樣本累積中，當前建議已套用人體工學比例轉換 (Gender Offset Mapping)。")

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
        c0, c1, c2 = st.columns(3)
        with c0:
            gender_input = st.radio("性別", ["男", "女"], horizontal=True)
        with c1:
            h = st.number_input("身高 (cm)", 100.0, 250.0, 172.0, 0.5, key="a_h")
        with c2:
            w = st.number_input("體重 (kg)", 20.0, 200.0, 70.0, 0.5, key="a_w")
            
        build_input = st.selectbox("身型", ["標準", "精壯 / 運動型", "偏肉 / 寬體"])
        
        st.markdown("**各品類尺寸 — 留空表示沒有**")
        
        # 汗衣 (顯示 Size)
        chest_display_sel = st.selectbox("汗衣 胸寬", ["留空"] + CHEST_OPTIONS_DISPLAY)
        
        st.markdown("**藍扯衫尺寸**")
        cs1, cs2 = st.columns(2)
        with cs1:
            shirt_a_sel = st.selectbox("藍扯衫 a", ["留空"] + SHIRT_A_OPTIONS)
        with cs2:
            shirt_b_sel = st.selectbox("藍扯衫 b", ["留空"] + SHIRT_B_OPTIONS)
            
        st.markdown("**藍扯褲尺寸**")
        cp1, cp2 = st.columns(2)
        with cp1:
            pants_w_sel = st.selectbox("藍扯褲 腰圍", ["留空"] + PANTS_W_OPTIONS)
        with cp2:
            pants_l_sel = st.selectbox("藍扯褲 褲長", ["留空"] + PANTS_L_OPTIONS)

        cs1, cs2 = st.columns(2)
        with cs1:
            safety_sel = st.selectbox("安全鞋 尺寸", ["留空"] + SAFETY_OPTIONS)
        with cs2:
            boots_sel = st.selectbox("水鞋 US尺寸", ["留空"] + BOOTS_OPTIONS)

        submitted = st.form_submit_button("✅ 儲存", type="primary", use_container_width=True)
        
        if submitted:
            items = {}
            
            # 處理汗衣的顯示字串轉換回數字
            if chest_display_sel != "留空":
                chest_val = float(chest_display_sel.split(" ")[0])
                items["汗衣"] = {"chest": chest_val}
                
            if shirt_a_sel != "留空" and shirt_b_sel != "留空":
                items["藍扯衫"] = {"a": float(shirt_a_sel), "b": float(shirt_b_sel)}
                
            if pants_w_sel != "留空" and pants_l_sel != "留空":
                items["藍扯褲"] = {"waist": float(pants_w_sel), "length": float(pants_l_sel)}
                
            if safety_sel != "留空":
                items["安全鞋"] = {"size": float(safety_sel)}
                
            if boots_sel != "留空":
                items["水鞋"] = {"size": float(boots_sel)}

            if items:
                data = load_data()
                new_id = int(time.time() * 1000)
                current_time = datetime.now().strftime("%Y-%m-%d %H:%M")
                data.append({
                    "id": new_id, 
                    "name": "匿名", 
                    "gender": gender_input,
                    "build": build_input,
                    "height": h, 
                    "weight": w, 
                    "items": items,
                    "created_at": current_time
                })
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
            row = {
                "ID": p.get("id", "-"), 
                "性別": p.get("gender", "-"),
                "身型": p.get("build", "-"),
                "新增時間": p.get("created_at", "-"),
                "身高(cm)": p["height"], 
                "體重(kg)": p["weight"]
            }
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
        
        # ==========================================
        # 數據視覺化
        # ==========================================
        st.markdown("---")
        st.markdown("### 📈 各品類尺寸分佈圖")
        
        chart_item = st.selectbox("選擇要查看的品類圖表：", ALL_ITEMS)
        
        chart_data = []
        for p in data:
            if chart_item in p.get("items", {}):
                dims = p["items"][chart_item]
                
                if chart_item == "汗衣":
                    label = to_size(chart_item, dims)
                elif chart_item == "藍扯衫":
                    label = f"{dims.get('a', '')}x{dims.get('b', '')}"
                elif chart_item == "藍扯褲":
                    label = f"{dims.get('waist', '')}x{dims.get('length', '')}"
                elif chart_item == "安全鞋":
                    label = f"鞋碼 {dims.get('size', '')}"
                elif chart_item == "水鞋":
                    label = f"US {dims.get('size', '')}"
                
                if label:
                    chart_data.append({
                        "身高": p["height"],
                        "體重": p["weight"],
                        "尺寸": str(label)
                    })
        
        if chart_data:
            df_chart = pd.DataFrame(chart_data)
            st.scatter_chart(
                df_chart,
                x="身高",
                y="體重",
                color="尺寸",
                use_container_width=True
            )
            st.caption("💡 提示：滑鼠懸停在點上可查看詳細數值。不同顏色代表不同的尺寸，方便觀察群聚效應與異常值。")
        else:
            st.info(f"尚無足夠的 {chart_item} 數據可供繪製圖表。")
            
        st.markdown("---")
        st.markdown("### ⚙️ 管理與修改")
        
        if "admin_authenticated" not in st.session_state:
            st.session_state.admin_authenticated = False
            
        if not st.session_state.admin_authenticated:
            pwd = st.text_input("請輸入管理員密碼以解鎖管理功能：", type="password")
            if st.button("🔓 解鎖"):
                if pwd == ADMIN_PASSWORD:
                    st.session_state.admin_authenticated = True
                    st.rerun()
                else:
                    st.error("❌ 密碼錯誤！")
        else:
            st.success("✅ 已解鎖管理權限")
            
            st.info("💡 如果你是剛加入時間功能，可以點擊下方按鈕，將所有沒有時間的舊資料設為當前時間。")
            if st.button("⏱️ 一鍵補齊舊資料時間", use_container_width=True):
                current_time = datetime.now().strftime("%Y-%m-%d %H:%M")
                updated_count = 0
                for p in data:
                    if "created_at" not in p or p["created_at"] == "-":
                        p["created_at"] = current_time
                        updated_count += 1
                if updated_count > 0:
                    if save_data(data):
                        st.session_state.dialog_type = f"補齊時間（共 {updated_count} 筆）"
                        st.rerun()
                else:
                    st.warning("沒有需要補齊時間的舊資料。")
                    
            st.markdown("---")
            
            if st.button("🔒 鎖定權限"):
                st.session_state.admin_authenticated = False
                st.rerun()
                
            st.markdown("#### ✏️ 修改或刪除現有資料")
            options = {f"ID: {p.get('id', '-')} | {p.get('gender', '-')} | {p.get('build', '-')} | {p['height']}cm {p['weight']}kg": p for p in data}
            selected_label = st.selectbox("選擇要操作的紀錄：", list(options.keys()))
            
            if selected_label:
                selected_person = options[selected_label]
                
                edit_tab, delete_tab = st.tabs(["✏️ 修改資料", "🗑️ 刪除資料"])
                
                with edit_tab:
                    with st.form("edit_form"):
                        st.write("修改基本資料：")
                        ec0, ec1, ec2 = st.columns(3)
                        with ec0:
                            edit_gender = st.radio("性別", ["男", "女"], index=0 if selected_person.get("gender") == "男" else 1, horizontal=True)
                        with ec1:
                            new_h = st.number_input("身高 (cm)", value=float(selected_person["height"]), step=0.5)
                        with ec2:
                            new_w = st.number_input("體重 (kg)", value=float(selected_person["weight"]), step=0.5)
                            
                        build_options = ["標準", "精壯 / 運動型", "偏肉 / 寬體"]
                        default_build_idx = build_options.index(selected_person["build"]) if selected_person.get("build") in build_options else 0
                        edit_build = st.selectbox("身型", build_options, index=default_build_idx)
                            
                        st.write("修改尺寸（全部使用下拉選單）：")
                        old_items = selected_person.get("items", {})
                        
                        # 汗衣 (修改時也用顯示 Size 的選單)
                        old_chest = old_items.get("汗衣", {}).get("chest", None)
                        old_chest_display = "留空"
                        if old_chest in CHEST_OPTIONS_RAW:
                            idx = CHEST_OPTIONS_RAW.index(old_chest)
                            old_chest_display = CHEST_OPTIONS_DISPLAY[idx]
                            
                        chest_edit_display = st.selectbox("汗衣 胸寬", ["留空"] + CHEST_OPTIONS_DISPLAY, index=(["留空"] + CHEST_OPTIONS_DISPLAY).index(old_chest_display))
                        
                        # 藍扯衫
                        st.markdown("**藍扯衫尺寸**")
                        old_shirt = old_items.get("藍扯衫", {})
                        cs1, cs2 = st.columns(2)
                        with cs1:
                            default_a = old_shirt.get("a", "留空")
                            shirt_a_edit = st.selectbox("藍扯衫 a", ["留空"] + SHIRT_A_OPTIONS, index=(["留空"] + SHIRT_A_OPTIONS).index(default_a) if default_a in SHIRT_A_OPTIONS else 0)
                        with cs2:
                            default_b = old_shirt.get("b", "留空")
                            shirt_b_edit = st.selectbox("藍扯衫 b", ["留空"] + SHIRT_B_OPTIONS, index=(["留空"] + SHIRT_B_OPTIONS).index(default_b) if default_b in SHIRT_B_OPTIONS else 0)
                        
                        # 藍扯褲
                        st.markdown("**藍扯褲尺寸**")
                        old_pants = old_items.get("藍扯褲", {})
                        cp1, cp2 = st.columns(2)
                        with cp1:
                            default_w = old_pants.get("waist", "留空")
                            pants_w_edit = st.selectbox("藍扯褲 腰圍", ["留空"] + PANTS_W_OPTIONS, index=(["留空"] + PANTS_W_OPTIONS).index(default_w) if default_w in PANTS_W_OPTIONS else 0)
                        with cp2:
                            default_l = old_pants.get("length", "留空")
                            pants_l_edit = st.selectbox("藍扯褲 褲長", ["留空"] + PANTS_L_OPTIONS, index=(["留空"] + PANTS_L_OPTIONS).index(default_l) if default_l in PANTS_L_OPTIONS else 0)

                        # 安全鞋與水鞋
                        cs1, cs2 = st.columns(2)
                        old_safety = old_items.get("安全鞋", {}).get("size", "留空")
                        with cs1:
                            safety_edit = st.selectbox("安全鞋 尺寸", ["留空"] + SAFETY_OPTIONS, index=(["留空"] + SAFETY_OPTIONS).index(old_safety) if old_safety in SAFETY_OPTIONS else 0)
                            
                        old_boots = old_items.get("水鞋", {}).get("size", "留空")
                        with cs2:
                            boots_edit = st.selectbox("水鞋 US尺寸", ["留空"] + BOOTS_OPTIONS, index=(["留空"] + BOOTS_OPTIONS).index(old_boots) if old_boots in BOOTS_OPTIONS else 0)
                        
                        update_btn = st.form_submit_button("💾 儲存修改", type="primary")
                        
                        if update_btn:
                            new_items = {}
                            
                            if chest_edit_display != "留空":
                                chest_val = float(chest_edit_display.split(" ")[0])
                                new_items["汗衣"] = {"chest": chest_val}
                                
                            if shirt_a_edit != "留空" and shirt_b_edit != "留空":
                                new_items["藍扯衫"] = {"a": float(shirt_a_edit), "b": float(shirt_b_edit)}
                            if pants_w_edit != "留空" and pants_l_edit != "留空":
                                new_items["藍扯褲"] = {"waist": float(pants_w_edit), "length": float(pants_l_edit)}
                            if safety_edit != "留空": new_items["安全鞋"] = {"size": float(safety_edit)}
                            if boots_edit != "留空": new_items["水鞋"] = {"size": float(boots_edit)}
                            
                            for i, p in enumerate(data):
                                if p.get("id") == selected_person.get("id"):
                                    data[i]["gender"] = edit_gender
                                    data[i]["build"] = edit_build
                                    data[i]["height"] = new_h
                                    data[i]["weight"] = new_w
                                    data[i]["items"] = new_items
                                    break
                                    
                            if save_data(data):
                                st.session_state.dialog_type = "修改"
                                st.rerun()

                with delete_tab:
                    st.warning(f"⚠️ 你確定要永久刪除這筆資料嗎？（ID: {selected_person.get('id')} | {selected_person['height']}cm {selected_person['weight']}kg）")
                    if st.button("🗑️ 確認刪除此筆資料", type="primary", use_container_width=True):
                        new_data = [p for p in data if p.get("id") != selected_person.get("id")]
                        if save_data(new_data):
                            st.session_state.dialog_type = "刪除"
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
