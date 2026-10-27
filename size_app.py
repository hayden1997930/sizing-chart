import streamlit as st
import json
from collections import defaultdict
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import requests

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

def load_data():
    try:
        df = conn.read(ttl="10s")
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

# ============ 推薦演算法 ============
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

# ============ AI 分析函數 (阿里雲百煉) ============
def get_ai_analysis(height, weight, results):
    # 已經將你的 API Key 直接寫在這裡
    api_key = "sk-ws-H.RMYLYIM.VCSC.MEQCIE_FN5tRLO5ulnVjUZW1QZaPykz9LeU9IZOX9yHVskKZAiAeaIUMHhVoB1b3rzj2zoRMqFo-uMyVZ0USkTy2ir3e5g"
    
    summary = f"用戶身高 {height}cm，體重 {weight}kg。系統推薦結果如下：\n"
    for t, r in results.items():
        if not r: continue
        if t == "汗衣":
            summary += f"- {t}：尺寸 {int(r['dims'].get('chest',0))} (尺碼 {r['size']})\n"
        elif t == "藍扯衫":
            summary += f"- {t}：{r['dims'].get('a')} x {r['dims'].get('b')}\n"
        elif t == "藍扯褲":
            summary += f"- {t}：{r['dims'].get('waist')} x {r['dims'].get('length')}\n"
        elif t == "安全鞋":
            summary += f"- {t}：{r['dims'].get('size')}\n"
        elif t == "水鞋":
            summary += f"- {t}：US {r['dims'].get('size')}\n"

    prompt = f"""
    你是一個專業的服裝與安全裝備顧問。
    {summary}
    請用兩至三句說話（廣東話），以專業但親切的語氣總結一下這個推薦，並提醒用戶在試穿時需要注意的地方（例如肩膀、褲長等）。
    不要重複列出所有尺寸，直接給出總結建議。
    """

    try:
        url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "qwen-turbo",
            "messages": [{"role": "user", "content": prompt}]
        }
        
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]
        else:
            return f"❌ AI 請求失敗 (Error {response.status_code})：請檢查 API Key 是否正確或餘額是否充足。"
    except Exception as e:
        return f"❌ 無法連接 AI 服務：{e}"

# ============ 介面設計 ============
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
                current_results = {}
                for t in ALL_ITEMS:
                    r = recommend_one(t, height, weight)
                    current_results[t] = r
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

                st.markdown("---")
                if st.button("🤖 讓 AI 顧問分析", use_container_width=True):
                    with st.spinner("AI 顧問正在為您分析..."):
                        ai_text = get_ai_analysis(height, weight, current_results)
                        st.info(ai_text)

# ---------- Tab 2：新增 ----------
with tab2:
    st.subheader("新增人員資料")
    
    # 使用 Session State 來控制彈窗
    if "show_success_dialog" not in st.session_state:
        st.session_state.show_success_dialog = False

    # 定義彈窗
    @st.dialog("✅ 儲存成功")
    def success_dialog():
        st.write("資料已成功寫入 Google Sheets 資料庫！")
        if st.button("確定", use_container_width=True):
            st.session_state.show_success_dialog = False
            st.rerun()

    # 如果狀態為 True，顯示彈窗
    if st.session_state.show_success_dialog:
        success_dialog()

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
                final_name = "匿名"
                data = load_data()
                data.append({"name": final_name, "height": h, "weight": w, "items": items})
                if save_data(data):
                    # 觸發彈窗
                    st.session_state.show_success_dialog = True
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
                
                if t == "汗衣":
                    parts = f"胸寬 {d.get('chest', '')}"
                elif t == "藍扯衫":
                    parts = f"{d.get('a', '')} x {d.get('b', '')}"
                elif t == "藍扯褲":
                    parts = f"{d.get('waist', '')} x {d.get('length', '')}"
                elif t == "安全鞋":
                    parts = f"鞋碼 {d.get('size', '')}"
                elif t == "水鞋":
                    parts = f"US {d.get('size', '')}"
                else:
                    parts = "  ".join(f"{k}={v}" for k, v in d.items())
                
                size_display = to_size(t, d) if t == "汗衣" else "—"
                table.append({
                    "姓名": p["name"], 
                    "身高": p["height"], 
                    "體重": p["weight"], 
                    "尺寸": parts, 
                    "尺碼": size_display
                })
            st.dataframe(table, use_container_width=True, hide_index=True)

        st.markdown("---")
        
        c1, c2 = st.columns(2)
        with c1:
            st.download_button("⬇️ 匯出 JSON", json.dumps(data, ensure_ascii=False, indent=2),
                               file_name="clothing_data.json", mime="application/json", use_container_width=True)
        with c2:
            with st.popover("🗑️ 清空所有資料", use_container_width=True):
                st.write("⚠️ 確定要刪除所有資料嗎？")
                pwd = st.text_input("請輸入管理員密碼", type="password", key="del_pwd")
                if st.button("確認刪除", type="primary", use_container_width=True):
                    if pwd == ADMIN_PASSWORD:
                        save_data([])
                        st.success("✅ 所有資料已清空！")
                        st.rerun()
                    else:
                        st.error("❌ 密碼錯誤，無法刪除！")
