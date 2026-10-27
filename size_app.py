# ============ AI 分析與估算 (OpenRouter) ============
def get_ai_analysis_and_estimate(height, weight, results):
    # 從 Streamlit Secrets 讀取 API Key
    api_key = st.secrets.get("OPENROUTER_API_KEY")
    
    # 防呆機制：檢查是否成功讀取
    if not api_key or len(api_key) < 20:
        return f"⚠️ 系統讀取不到有效的 OpenRouter API Key。\n(目前讀到的長度: {len(api_key) if api_key else 0})，請確認 Secrets 是否已儲存並重啟。"
    
    summary = f"用戶身高 {height}cm，體重 {weight}kg。\n"
    summary += "【系統資料庫推薦結果】：\n"
    has_data = False
    for t, r in results.items():
        if not r: continue
        has_data = True
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
    
    if not has_data:
        summary += "（目前資料庫沒有任何數據）\n"

    prompt = f"""
    你是一個專業的服裝與安全裝備顧問。
    {summary}
    
    請執行以下兩個任務：
    1. 【參考估算】：請根據你對一般亞洲人體型的常識，直接為這個身高和體重的人，估算一套標準的尺寸（包括：汗衣胸寬吋數與尺碼、藍扯衫 a x b、藍扯褲腰圍 x 褲長、安全鞋碼、水鞋 US碼）。如果資料庫的數字與你的估算相差太遠，請以你的估算為準。
    2. 【試穿建議】：用一兩句廣東話總結，提醒用戶試穿時要注意的地方。

    請用清晰的點列式回答，語氣要專業且親切。不要說「根據資料庫」，直接給出你的專業判斷。
    """

    try:
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "meta-llama/llama-3.3-70b-instruct:free",
            "messages": [{"role": "user", "content": prompt}]
        }
        
        response = requests.post(url, headers=headers, json=payload, timeout=20)
        
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]
        else:
            return f"❌ AI 分析失敗 (Error {response.status_code})：請檢查 API Key 或額度。\n回傳訊息：{response.text}"
    except Exception as e:
        return f"❌ 無法連接 AI 服務：{e}"
