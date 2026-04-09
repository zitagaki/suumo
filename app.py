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
from selenium.common.exceptions import NoSuchElementException
import streamlit as st
from sklearn.linear_model import LinearRegression

# =========================================================
# 1. データ抽出関数（変更なし）
# =========================================================
def scrape_suumo_refined(url):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    time.sleep(2)
    res = requests.get(url, headers=headers)
    res.encoding = res.apparent_encoding
    tree = html.fromstring(res.text)
    property_data = {"URL": url}
    
    xpath_dict = {
        "物件名": '//*[@id="wrapper"]/div[3]/div[1]/h1/text()',
        "家賃": '//*[@id="js-view_gallery"]/div/div[2]/div[2]/div/div[2]/div/div[1]/div/div[1]/text()',
        "間取り": '//*[@id="js-view_gallery"]/div/div[2]/div[3]/div[1]/div/div[2]/ul/li[1]/div/div[2]/text()',
        "専有面積": '//*[@id="js-view_gallery"]/div/div[2]/div[3]/div[1]/div/div[2]/ul/li[2]/div/div[2]/text()',
        "築年数": '//*[@id="js-view_gallery"]/div/div[2]/div[3]/div[1]/div/div[2]/ul/li[5]/div/div[2]/text()',
    }

    for key, path in xpath_dict.items():
        elements = tree.xpath(path)
        if elements:
            raw_text = "".join([e.strip() for e in elements if e.strip()])
            if key == "物件名":
                property_data[key] = raw_text.split(" - ")[0].strip()
            else:
                property_data[key] = raw_text
        else:
            property_data[key] = "-"

    for i in range(1, 4):
        transport_path = f'//*[@id="js-view_gallery"]/div/div[2]/div[3]/div[2]/div[1]/div/div[2]/div[{i}]//text()'
        transport_elements = tree.xpath(transport_path)
        if transport_elements:
            raw_text = "".join(transport_elements).strip()
            clean_text = re.sub(r'\s+', ' ', raw_text.replace('　', ' '))
            match = re.search(r'([^/]+)/\s*([^\s]+)\s+(.+)', clean_text)
            if match:
                property_data[f"沿線{i}"] = match.group(1).strip()
                property_data[f"駅{i}"] = match.group(2).strip()
                property_data[f"徒歩{i}"] = match.group(3).strip()
            else:
                property_data[f"徒歩{i}"] = "-"

    tables = tree.xpath('//table')
    for table in tables:
        rows = table.xpath('.//tr')
        for row in rows:
            ths = row.xpath('.//th')
            tds = row.xpath('.//td')
            for th, td in zip(ths, tds):
                key = "".join(th.xpath('.//text()')).strip()
                value = "".join(td.xpath('.//text()')).replace('\n', '').replace('\r', '').strip()
                if key and not any(ignore_word in key for ignore_word in ["コード", "周辺", "QR", "アドレス", "半角"]):
                    if key not in property_data:
                        property_data[key] = value

    return property_data


# =========================================================
# 2. データクレンジング関数（先ほど成功した数値化処理）
# =========================================================
def clean_data_flexible(df):
    df_clean = df.copy()

    def extract_number(text, is_float=False):
        if pd.isna(text) or text == "-":
            return np.nan
        if "新築" in str(text):
            return 0
        match = re.search(r'([0-9\.]+)', str(text).replace(',', ''))
        if match:
            num_str = match.group(1)
            return float(num_str) if is_float else int(float(num_str))
        return np.nan

    def extract_rent(text):
        val = extract_number(text, is_float=True)
        return int(val * 10000) if pd.notna(val) else np.nan

    if '家賃' in df_clean.columns:
        df_clean['家賃_数値'] = df_clean['家賃'].apply(extract_rent)
    if '専有面積' in df_clean.columns:
        df_clean['面積_数値'] = df_clean['専有面積'].apply(lambda x: extract_number(x, is_float=True))
    if '築年数' in df_clean.columns:
        df_clean['築年数_数値'] = df_clean['築年数'].apply(lambda x: extract_number(x, is_float=False))
    if '徒歩1' in df_clean.columns:
        df_clean['徒歩_数値'] = df_clean['徒歩1'].apply(lambda x: extract_number(x, is_float=False))

    # 分析に必須の4項目が揃っている行だけを残す（NaNの削除）
    df_clean = df_clean.dropna(subset=['家賃_数値', '面積_数値', '築年数_数値', '徒歩_数値'])
    return df_clean


# =========================================================
# 3. Streamlit メインアプリ画面
# =========================================================
def main():
    st.title("🏡 不動産データ収集 ＆ AI賃料査定システム")
    
    # タブの作成
    tab1, tab2 = st.tabs(["📊 データ収集 (スクレイピング)", "🤖 AI賃料査定 (重回帰分析)"])

    # -----------------------------------------------------
    # タブ1：スクレイピング機能（今までの機能）
    # -----------------------------------------------------
    with tab1:
        st.write("一覧ページのURLを入力して実行ボタンを押すと、自動でデータを抽出してExcel化します。")
        target_list_url = st.text_input("SUUMOの一覧ページのURLを入力:", placeholder="https://suumo.jp/...")

        if st.button("スクレイピングを実行する"):
            if not target_list_url:
                st.warning("URLが入力されていません。")
            else:
                st.subheader("Phase 1: ページ遷移とURL収集")
                status_text1 = st.empty()
                
                options = Options()
                options.add_argument('--headless')
                options.add_argument('--no-sandbox')
                options.add_argument('--disable-dev-shm-usage')
                options.add_argument('--disable-gpu')
                
                # Cloud環境用
                try:
                    service = Service('/usr/bin/chromedriver')
                    driver = webdriver.Chrome(service=service, options=options)
                except:
                    # ローカル環境用フォールバック
                    driver = webdriver.Chrome(options=options)
                
                try:
                    driver.get(target_list_url)
                    time.sleep(3)
                    
                    all_detail_urls = []
                    page_count = 1
                    
                    while True:
                        status_text1.info(f"{page_count}ページ目から物件URLを抽出中... (現在 {len(all_detail_urls)} 件)")
                        tree = html.fromstring(driver.page_source)
                        hrefs = tree.xpath('//a[contains(@href, "/chintai/bc_") or contains(@href, "/chintai/jnc_")]/@href')
                        
                        for href in hrefs:
                            full_url = urljoin("https://suumo.jp", href)
                            if full_url not in all_detail_urls:
                                all_detail_urls.append(full_url)
                        
                        time.sleep(random.uniform(3, 6))
                        
                        try:
                            next_button = driver.find_element(By.XPATH, '//a[contains(text(), "次へ")]')
                            next_button.click()
                            page_count += 1
                            time.sleep(3)
                        except:
                            status_text1.success(f"最後のページまで到達しました。合計 {len(all_detail_urls)} 件のURLを収集！")
                            break
                finally:
                    driver.quit()

                if all_detail_urls:
                    st.subheader("Phase 2: 詳細データの抽出")
                    progress_bar = st.progress(0)
                    status_text2 = st.empty()
                    
                    all_properties_data = []
                    total_urls = len(all_detail_urls)

                    for idx, url in enumerate(all_detail_urls, 1):
                        status_text2.text(f"[{idx}/{total_urls}] を処理中: {url}")
                        try:
                            data = scrape_suumo_refined(url)
                            all_properties_data.append(data)
                        except Exception as e:
                            st.error(f"エラー発生: {e}")
                        progress_bar.progress(idx / total_urls)

                    if all_properties_data:
                        df = pd.DataFrame(all_properties_data)
                        
                        # 重複削除
                        target_cols = ['物件名', '家賃', '間取り', '専有面積', '階']
                        valid_cols = [col for col in target_cols if col in df.columns]
                        df = df.drop_duplicates(subset=valid_cols, keep='first')
                        
                        st.success(f"🎉 抽出・クリーニング完了！({len(df)}件の物件データを取得)")
                        st.dataframe(df.head()) 
                        
                        excel_buffer = io.BytesIO()
                        df.to_excel(excel_buffer, index=False, engine="openpyxl")
                        st.download_button("📥 データをExcelでダウンロード", data=excel_buffer.getvalue(), file_name="suumo_properties.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


    # -----------------------------------------------------
    # タブ2：AI賃料査定機能（新規追加）
    # -----------------------------------------------------
    with tab2:
        st.write("抽出したExcelデータをアップロードして、AIによる賃料査定を行います。")
        
        # 1. データのアップロード
        uploaded_file = st.file_uploader("タブ1でダウンロードしたExcelファイルをアップロードしてください", type=["xlsx"])
        
        if uploaded_file is not None:
            # データの読み込みとクレンジング
            raw_df = pd.read_excel(uploaded_file)
            st.info("データを読み込み、AIが学習できる数値に変換しています...")
            df_ml = clean_data_flexible(raw_df)
            
            if len(df_ml) < 10:
                st.error("分析に使用できるデータが少なすぎます（10件以上必要です）。別のデータをアップロードしてください。")
            else:
                st.success(f"学習準備完了！ 有効データ数: {len(df_ml)} 件")
                
                # 2. AIモデル（重回帰分析）の学習
                # 説明変数（原因）と 目的変数（結果）をセット
                X = df_ml[['面積_数値', '築年数_数値', '徒歩_数値']]
                y = df_ml['家賃_数値']
                
                model = LinearRegression()
                model.fit(X, y) # ←ここでAIが学習しています！
                
                st.markdown("---")
                st.subheader("🤖 AI査定シミュレーター")
                st.write("スライダーを動かすと、学習したデータをもとにリアルタイムで適正家賃を計算します。")
                
                # 3. ユーザー入力用のUI（スライダー）
                # 取得したデータの最大値・最小値に合わせてスライダーの範囲を自動設定
                col1, col2, col3 = st.columns(3)
                with col1:
                    input_area = st.slider("専有面積 (㎡)", 
                                           min_value=float(df_ml['面積_数値'].min()), 
                                           max_value=float(df_ml['面積_数値'].max()), 
                                           value=float(df_ml['面積_数値'].median()))
                with col2:
                    input_age = st.slider("築年数 (年)", 
                                          min_value=0, 
                                          max_value=int(df_ml['築年数_数値'].max()), 
                                          value=int(df_ml['築年数_数値'].median()))
                with col3:
                    input_walk = st.slider("駅徒歩 (分)", 
                                           min_value=0, 
                                           max_value=int(df_ml['徒歩_数値'].max()), 
                                           value=int(df_ml['徒歩_数値'].median()))
                
                # 4. 査定結果の計算と表示
                # ユーザーが入力した数値をAIに渡して予測させる
                predicted_rent = model.predict([[input_area, input_age, input_walk]])[0]
                
                st.markdown(
                    f"""
                    <div style="background-color:#f0f2f6;padding:20px;border-radius:10px;text-align:center;">
                        <h3 style="margin:0;color:#333;">AIによる適正家賃（推定）</h3>
                        <h1 style="margin:0;color:#ff4b4b;font-size:48px;">{int(predicted_rent):,} 円</h1>
                    </div>
                    """, 
                    unsafe_allow_html=True
                )

if __name__ == "__main__":
    main()