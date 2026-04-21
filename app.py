import pandas as pd
import numpy as np
import re
import requests
from bs4 import BeautifulSoup
import lxml.html 
import time
import random
import streamlit as st
import io

# =========================================================
# 1. ページ設定と初期化
# =========================================================
st.set_page_config(page_title="不動産ハイブリッド査定システム", layout="wide")

# アプリの記憶（Session State）の初期化
if 'raw_df' not in st.session_state:
    st.session_state['raw_df'] = pd.DataFrame()
if 'scraping_log' not in st.session_state:
    st.session_state['scraping_log'] = ""

st.title("🏡 不動産ハイブリッド査定システム (AI × プロの相場観)")

# =========================================================
# 2. スクレイピングエンジン (逐次保存・レスキュー型)
# =========================================================
def get_xpath_text(tree, xpath_str):
    try:
        elements = tree.xpath(xpath_str)
        if not elements and '/tbody' in xpath_str:
            elements = tree.xpath(xpath_str.replace('/tbody', ''))
        if elements:
            if isinstance(elements[0], str): return elements[0].strip()
            else:
                text = elements[0].text_content()
                return re.sub(r'\s+', ' ', text).strip()
    except Exception: pass
    return ""

def scrape_suumo_list_v2(base_url, max_pages, p_min, p_max, d_min, d_max):
    session = requests.Session()
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Referer': 'https://suumo.jp/',
    }
    
    # URLの調整
    base_url = base_url.replace('FR301FC005', 'FR301FC001').replace('FR301FC006', 'FR301FC001').replace('FR301FC007', 'FR301FC001')
    base_url = re.sub(r'&pn=\d+', '', base_url)
    separator = '&' if '?' in base_url else '?'
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    new_data = []

    for page in range(1, max_pages + 1):
        url = f"{base_url}{separator}pn={page}"
        try:
            status_text.text(f"⏳ {page}ページ目の待機中...")
            time.sleep(random.uniform(p_min, p_max))
            
            res = session.get(url, headers=headers, timeout=15)
            
            if res.status_code == 403:
                st.session_state['scraping_log'] = f"❌ {page}ページ目の一覧表示でブロック(403)されました。"
                break
            
            res.raise_for_status()
            soup = BeautifulSoup(res.content, 'html.parser')
            items = soup.find_all("div", class_="cassetteitem")
            
            if not items: break

            for item in items:
                # 物件基本情報の取得
                title = item.find("div", class_="cassetteitem_content-title").text.strip() if item.find("div", class_="cassetteitem_content-title") else ""
                address = item.find("li", class_="cassetteitem_detail-col1").text.strip() if item.find("li", class_="cassetteitem_detail-col1") else ""
                
                tbodies = item.find_all("tbody")
                for tbody in tbodies:
                    # 部屋ごとの詳細URL取得
                    a_tag = tbody.find("a", href=re.compile(r'/chintai/(jnc|bc)_'))
                    if not a_tag: continue
                    full_url = "https://suumo.jp" + a_tag.get("href")

                    # 詳細ページ取得
                    time.sleep(random.uniform(d_min, d_max))
                    d_res = session.get(full_url, headers=headers, timeout=10)
                    
                    if d_res.status_code == 403:
                        st.session_state['scraping_log'] = f"❌ {page}ページ目・物件「{title}」の詳細取得中にブロックされました。"
                        # 💡 途中でブロックされたら、そこまでのデータを保存して終了
                        temp_df = pd.DataFrame(new_data)
                        st.session_state['raw_df'] = pd.concat([st.session_state['raw_df'], temp_df]).drop_duplicates()
                        return # 関数を抜ける
                    
                    d_tree = lxml.html.fromstring(d_res.content)
                    
                    # データ抽出 (一部抜粋)
                    new_data.append({
                        "物件名": title,
                        "住所": address,
                        "家賃": tbody.find("span", class_="cassetteitem_price cassetteitem_price--rent").text.strip() if tbody.find("span", class_="cassetteitem_price cassetteitem_price--rent") else "",
                        "共益費": tbody.find("span", class_="cassetteitem_price cassetteitem_price--administration").text.strip() if tbody.find("span", class_="cassetteitem_price cassetteitem_price--administration") else "",
                        "間取り": tbody.find("span", class_="cassetteitem_madori").text.strip() if tbody.find("span", class_="cassetteitem_madori") else "",
                        "専有面積": tbody.find("span", class_="cassetteitem_menseki").text.strip() if tbody.find("span", class_="cassetteitem_menseki") else "",
                        "URL": full_url,
                        "設備": get_xpath_text(d_tree, '//*[@id="bkdt-option"]/div/ul/li') # 簡易版
                    })
                    status_text.text(f"🚀 取得中: {page}ページ目 ({len(new_data)}部屋目)...")

            # 💡 1ページ終わるごとに「記憶」にセーブ
            temp_df = pd.DataFrame(new_data)
            st.session_state['raw_df'] = pd.concat([st.session_state['raw_df'], temp_df]).drop_duplicates()
            new_data = [] # リセットして次のページへ
            
            progress_bar.progress(page / max_pages)

        except Exception as e:
            st.session_state['scraping_log'] = f"⚠️ エラー発生: {str(e)}"
            break

    status_text.success("処理が終了しました。")
    progress_bar.empty()

# =========================================================
# 3. UI画面
# =========================================================
tab1, tab2, tab3 = st.tabs(["📂 データ取得", "🤖 査定シミュレーター", "🏘️ エリア分析"])

with tab1:
    col_l, col_r = st.columns([2, 1])
    
    with col_l:
        target_url = st.text_input("SUUMOの検索結果URL")
        max_p = st.number_input("最大取得ページ数", 1, 100, 3)
        if st.button("🚀 スクレイピング開始"):
            st.session_state['raw_df'] = pd.DataFrame() # 新規開始時はリセット
            st.session_state['scraping_log'] = "取得中..."
            scrape_suumo_list_v2(target_url, max_p, 3.0, 5.0, 1.0, 2.0)

    with col_r:
        st.markdown("### 📥 レスキュー・ダウンロード")
        # 💡 ここにボタンを置くことで、中断してもデータがあればダウンロードできる
        if not st.session_state['raw_df'].empty:
            st.write(f"現在の取得件数: {len(st.session_state['raw_df'])} 件")
            
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                st.session_state['raw_df'].to_excel(writer, index=False)
            
            st.download_button(
                label="📁 取得済みデータを今すぐ保存",
                data=buffer.getvalue(),
                file_name="suumo_rescue_data.xlsx",
                mime="application/vnd.ms-excel"
            )
        
        if st.session_state['scraping_log']:
            st.warning(st.session_state['scraping_log'])

    if not st.session_state['raw_df'].empty:
        st.write("取得データのプレビュー:")
        st.dataframe(st.session_state['raw_df'].head(10))

# (※TAB2, TAB3のコードはこれまでのものをそのまま繋げてご利用いただけます)