import time
import random
import requests
import re
import pandas as pd
import numpy as np
import io
from lxml import html
from urllib.parse import urljoin
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from sklearn.linear_model import LinearRegression
import streamlit as st

# =========================================================
# 1. データ抽出関数（Selenium完全統合）
# =========================================================
def scrape_suumo_refined(url, driver):
    time.sleep(random.uniform(1.5, 3.0))
    driver.get(url)
    tree = html.fromstring(driver.page_source)
    property_data = {"URL": url}
    
    xpath_dict = {
        "物件名": '//*[@id="wrapper"]/div[3]/div[1]/h1/text()',
        "家賃": '//*[@id="js-view_gallery"]/div/div[2]/div[2]/div/div[2]/div/div[1]/div/div[1]/text()',
        "間取り": '//*[@id="js-view_gallery"]/div/div[2]/div[3]/div[1]/div/div[2]/ul/li[1]/div/div[2]/text()',
        "専有面積": '//*[@id="js-view_gallery"]/div/div[2]/div[3]/div[1]/div/div[2]/ul/li[2]/div/div[2]/text()',
        "建物種別": '//*[@id="js-view_gallery"]/div/div[2]/div[3]/div[1]/div/div[2]/ul/li[4]/div/div[2]/text()',
        "築年数": '//*[@id="js-view_gallery"]/div/div[2]/div[3]/div[1]/div/div[2]/ul/li[5]/div/div[2]/text()',
        "階": '//*[@id="js-view_gallery"]/div/div[2]/div[3]/div[1]/div/div[2]/ul/li[3]/div/div[2]/text()',
    }

    for key, path in xpath_dict.items():
        elements = tree.xpath(path)
        if elements:
            raw_text = "".join([e.strip() for e in elements if e.strip()])
            property_data[key] = raw_text.split(" - ")[0].strip() if key == "物件名" else raw_text
        else:
            property_data[key] = "-"

    for i in range(1, 4):
        transport_path = f'//*[@id="js-view_gallery"]/div/div[2]/div[3]/div[2]/div[1]/div/div[2]/div[{i}]//text()'
        transport_elements = tree.xpath(transport_path)
        if transport_elements:
            clean_text = re.sub(r'\s+', ' ', "".join(transport_elements).strip().replace('　', ' '))
            match = re.search(r'([^/]+)/\s*([^\s]+)\s+(.+)', clean_text)
            if match:
                property_data[f"沿線{i}"] = match.group(1).strip()
                property_data[f"駅{i}"] = match.group(2).strip()
                property_data[f"徒歩{i}"] = match.group(3).strip()
            else:
                property_data[f"徒歩{i}"] = "-"

    feature_elements = tree.xpath('//*[@id="bkdt-option"]/div/ul/li/text()')
    if feature_elements:
        property_data["部屋の特徴・設備"] = "、".join([f.strip() for f in feature_elements if f.strip()])

    return property_data

# =========================================================
# 2. データクレンジング ＆ 間取りグループ化
# =========================================================
def clean_data_flexible(df):
    df_clean = df.copy()

    def extract_number(text, is_float=False):
        if pd.isna(text) or str(text) == "-": return np.nan
        if "新築" in str(text): return 0
        match = re.search(r'([0-9\.]+)', str(text).replace(',', ''))
        if match: return float(match.group(1)) if is_float else int(float(match.group(1)))
        return np.nan

    if '家賃' in df_clean.columns: df_clean['家賃_数値'] = df_clean['家賃'].apply(lambda x: int(extract_number(x, True) * 10000) if pd.notna(extract_number(x, True)) else np.nan)
    if '専有面積' in df_clean.columns: df_clean['面積_数値'] = df_clean['専有面積'].apply(lambda x: extract_number(x, True))
    if '築年数' in df_clean.columns: df_clean['築年数_数値'] = df_clean['築年数'].apply(lambda x: extract_number(x, False))
    if '徒歩1' in df_clean.columns: df_clean['徒歩_数値'] = df_clean['徒歩1'].apply(lambda x: extract_number(x, False))

    # 間取りグループの判定
    def get_layout_group(madori):
        m = str(madori)
        if any(x in m for x in ['1R']): return 'ワンルーム'
        if any(x in m for x in ['1K', '1DK']): return '1K・1DK'
        if any(x in m for x in ['1LDK']): return '1LDK'
        if any(x in m for x in ['2K', '2DK']): return '2K・2DK'
        if any(x in m for x in ['2LDK']): return '2LDK'
        if any(x in m for x in ['3K', '3DK']): return '3K・3DK'
        return '3LDK'
    
    if '間取り' in df_clean.columns:
        df_clean['間取りグループ'] = df_clean['間取り'].apply(get_layout_group)

    # 設備フラグ
    for col in ['部屋の特徴・設備', '備考']:
        if col not in df_clean.columns: df_clean[col] = ""
    fac = df_clean['部屋の特徴・設備'].astype(str) + " " + df_clean['備考'].astype(str)
    
    df_clean['バストイレ別'] = fac.apply(lambda x: 1 if 'バストイレ別' in str(x) or 'バス・トイレ別' in str(x) else 0)
    df_clean['オートロック'] = fac.apply(lambda x: 1 if 'オートロック' in str(x) else 0)

    return df_clean.dropna(subset=['家賃_数値', '面積_数値', '築年数_数値', '徒歩_数値'])

# =========================================================
# 3. カスタムルール計算エンジン
# =========================================================
def calc_rule_adjustments(area, walk, age, bt_flag, auto_flag, rules_dict, layout):
    """ルール表に基づく加減算額（ハコ代以外の価値）を計算"""
    r = rules_dict.get(layout, rules_dict.get('1K・1DK', {}))
    adj = 0
    
    # 徒歩ペナルティ
    if walk <= 10:
        adj += walk * r.get('徒歩10分以内単価', -300)
    else:
        adj += (10 * r.get('徒歩10分以内単価', -300)) + r.get('徒歩10分超固定ペナルティ', -3000) + ((walk - 10) * r.get('徒歩10分超追加単価', -100))

    # 築年数ペナルティ
    if age == 0: age_unit = r.get('築年_新築単価', 150)
    elif 1 <= age <= 3: age_unit = r.get('築年_1_3年単価', 50)
    elif 4 <= age <= 6: age_unit = r.get('築年_4_6年単価', 20)
    elif 7 <= age <= 10: age_unit = r.get('築年_7_10年単価', 0)
    elif 11 <= age <= 20: age_unit = r.get('築年_11_20年単価', -20)
    elif 21 <= age <= 30: age_unit = r.get('築年_21_30年単価', -50)
    else: age_unit = r.get('築年_31年以降', -100)
    adj += age_unit * area

    # 設備ボーナス
    if bt_flag: adj += r.get('バス・トイレ別', 3000) # rules.csvに無い場合は仮置き
    if auto_flag: adj += r.get('オートロック', 2000)
    
    return adj


# =========================================================
# 4. Streamlit メインアプリ画面
# =========================================================
def main():
    st.set_page_config(layout="wide")
    st.title("🏡 不動産ハイブリッド査定システム (AI × プロの相場観)")
    tab1, tab2 = st.tabs(["📊 ①対象エリアのデータ収集", "🤖 ②ハイブリッド査定の実行"])

    with tab1:
        st.write("対象としたい駅やエリアのSUUMO一覧URLを入力し、相場の基準となるデータを収集します。")
        target_list_url = st.text_input("SUUMOの一覧ページのURL:", placeholder="https://suumo.jp/...")
        if st.button("スクレイピングを実行する"):
            if target_list_url:
                # （スクレイピングのコードは前回と同じなので省略せずそのまま維持します）
                st.info("データ抽出を開始します...")
                options = Options()
                options.add_argument('--headless')
                options.add_argument('--no-sandbox')
                options.add_argument('--disable-dev-shm-usage')
                
                try:
                    driver = webdriver.Chrome(service=Service('/usr/bin/chromedriver'), options=options)
                except:
                    driver = webdriver.Chrome(options=options)
                
                all_properties_data = []
                try:
                    driver.get(target_list_url)
                    time.sleep(3)
                    all_detail_urls = []
                    page_count = 1
                    
                    while True:
                        st.write(f"{page_count}ページ目からURLを抽出中...")
                        tree = html.fromstring(driver.page_source)
                        hrefs = tree.xpath('//a[contains(@href, "/chintai/bc_") or contains(@href, "/chintai/jnc_")]/@href')
                        for href in hrefs:
                            full_url = urljoin("https://suumo.jp", href)
                            if full_url not in all_detail_urls: all_detail_urls.append(full_url)
                        
                        try:
                            driver.find_element(By.XPATH, '//a[contains(text(), "次へ")]').click()
                            page_count += 1
                            time.sleep(3)
                        except:
                            break
                            
                    progress_bar = st.progress(0)
                    for idx, url in enumerate(all_detail_urls, 1):
                        try:
                            all_properties_data.append(scrape_suumo_refined(url, driver))
                        except Exception: pass
                        progress_bar.progress(idx / len(all_detail_urls))
                        
                finally:
                    driver.quit()

                if all_properties_data:
                    df = pd.DataFrame(all_properties_data)
                    df = df.drop_duplicates(subset=[col for col in ['物件名', '家賃', '間取り', '専有面積', '階'] if col in df.columns], keep='first')
                    st.success(f"🎉 {len(df)}件のデータを取得しました。Excelをダウンロードしてタブ2へ進んでください。")
                    excel_buffer = io.BytesIO()
                    df.to_excel(excel_buffer, index=False, engine="openpyxl")
                    st.download_button("📥 データをExcelでダウンロード", data=excel_buffer.getvalue(), file_name="local_area_data.xlsx")

    with tab2:
        st.write("対象エリアの「Excelデータ」と、あなたの相場観をまとめた「rules.csv」をアップロードしてください。")
        colA, colB = st.columns(2)
        with colA: local_file = st.file_uploader("1. 対象エリアのデータ (Excel)", type=["xlsx"])
        with colB: rules_file = st.file_uploader("2. 共通ルール表 (rules.csv)", type=["csv"])
        
        if local_file and rules_file:
            # ルールの読み込み（転置フォーマット対応）
            rules_df = pd.read_csv(rules_file)
            rules_dict = {}
            layouts = ['ワンルーム', '1K・1DK', '1LDK', '2K・2DK', '2LDK', '3K・3DK', '3LDK']
            for layout in layouts:
                if layout in rules_df.columns:
                    rules_dict[layout] = {}
                    for _, row in rules_df.iterrows():
                        rule_name = str(row['間取りグループ']).strip()
                        val = row[layout]
                        rules_dict[layout][rule_name] = float(val) if pd.notna(val) else 0.0

            # エリアデータの読み込みと逆算
            df_ml = clean_data_flexible(pd.read_excel(local_file))
            
            # 各物件の「純粋なハコ代（ルール適用後の残り家賃）」を計算
            def get_base_rent(row):
                adj = calc_rule_adjustments(row['面積_数値'], row['徒歩_数値'], row['築年数_数値'], row['バストイレ別'], row['オートロック'], rules_dict, row['間取りグループ'])
                return row['家賃_数値'] - adj
            
            df_ml['ハコ代'] = df_ml.apply(get_base_rent, axis=1)
            df_ml['計算用面積'] = df_ml['面積_数値'].apply(lambda x: max(0, x - 10)) # 設備面積10㎡を引く
            
            local_base_prices = {}
            local_unit_prices = {}
            
            # 間取りごとに相場（切片と傾き）をAIで逆算
            for layout in layouts:
                target_df = df_ml[df_ml['間取りグループ'] == layout]
                if len(target_df) >= 3:
                    model = LinearRegression().fit(target_df[['計算用面積']], target_df['ハコ代'])
                    local_base_prices[layout] = model.intercept_
                    local_unit_prices[layout] = model.coef_[0]
                else:
                    # データが足りない間取りは、エリア全体の平均水準で代用
                    model = LinearRegression().fit(df_ml[['計算用面積']], df_ml['ハコ代'])
                    local_base_prices[layout] = model.intercept_
                    local_unit_prices[layout] = model.coef_[0]

            st.success("✅ ルールの適用と、エリア相場の逆算が完了しました！")
            
            # 逆算された相場を可視化
            st.markdown("### 📍 このエリアの自動算出相場（間取り別）")
            market_df = pd.DataFrame({
                "間取り": layouts,
                "ベース価格(設備10㎡分)": [int(local_base_prices[l]) for l in layouts],
                "㎡単価(10㎡超過分)": [int(local_unit_prices[l]) for l in layouts]
            })
            st.dataframe(market_df.T, use_container_width=True)

            st.markdown("---")
            st.subheader("🤖 詳細査定シミュレーター")
            
            col1, col2, col3, col4 = st.columns(4)
            with col1: target_layout = st.selectbox("間取りタイプ", layouts, index=1)
            with col2: i_area = st.number_input("専有面積 (㎡)", min_value=10.0, max_value=200.0, value=25.0)
            with col3: i_age = st.number_input("築年数 (年) ※新築は0", min_value=0, max_value=100, value=5)
            with col4: i_walk = st.number_input("駅徒歩 (分)", min_value=0, max_value=60, value=8)

            st.markdown("**付加価値・設備条件**")
            col5, col6, col7 = st.columns(3)
            with col5: i_bt = st.checkbox("バス・トイレ別", value=True)
            with col6: i_auto = st.checkbox("オートロック", value=False)
            with col7: i_premium = st.number_input("駅プレミアム加算額 (円)", value=0, step=1000)

            # 最終査定額の計算 = [逆算されたベース] + [逆算㎡単価 × 超過面積] + [ルール加減算] + [手動加算]
            base = local_base_prices[target_layout]
            unit = local_unit_prices[target_layout]
            
            rent_hako = base + (max(0, i_area - 10) * unit)
            rent_rules = calc_rule_adjustments(i_area, i_walk, i_age, i_bt, i_auto, rules_dict, target_layout)
            predicted_rent = rent_hako + rent_rules + i_premium
            
            st.markdown(
                f"""
                <div style="background-color:#e8f4f8;padding:20px;border-radius:10px;text-align:center;margin-top:20px;">
                    <h3 style="margin:0;color:#333;">ハイブリッド推定家賃</h3>
                    <h1 style="margin:0;color:#0066cc;font-size:48px;">{int(predicted_rent):,} 円</h1>
                    <p style="color:#666; margin:0;">(エリアベース: {int(rent_hako):,}円 ＋ ルール加減点: {int(rent_rules):,}円 ＋ プレミアム: {i_premium}円)</p>
                </div>
                """, 
                unsafe_allow_html=True
            )

if __name__ == "__main__":
    main()