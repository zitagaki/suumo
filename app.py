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
# 1. データ抽出関数
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
        "管理費・共益費": '//*[@id="js-view_gallery"]/div/div[2]/div[2]/div/div[2]/div/div[1]/div/div[2]/div/div[2]/text()',
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
# 2. データクレンジング関数（エラー対策・フラグ化対応版）
# =========================================================
def clean_data_flexible(df):
    df_clean = df.copy()

    def extract_number(text, is_float=False):
        if pd.isna(text) or str(text) == "-": return np.nan
        if "新築" in str(text): return 0
        match = re.search(r'([0-9\.]+)', str(text).replace(',', ''))
        if match:
            return float(match.group(1)) if is_float else int(float(match.group(1)))
        return np.nan

    if '家賃' in df_clean.columns:
        df_clean['家賃_数値'] = df_clean['家賃'].apply(lambda x: int(extract_number(x, True) * 10000) if pd.notna(extract_number(x, True)) else np.nan)
    if '管理費・共益費' in df_clean.columns:
        df_clean['管理費_数値'] = df_clean['管理費・共益費'].apply(lambda x: extract_number(x, False) if '円' in str(x) else 0)
    if '専有面積' in df_clean.columns:
        df_clean['面積_数値'] = df_clean['専有面積'].apply(lambda x: extract_number(x, True))
    if '築年数' in df_clean.columns:
        df_clean['築年数_数値'] = df_clean['築年数'].apply(lambda x: extract_number(x, False))
    if '徒歩1' in df_clean.columns:
        df_clean['徒歩_数値'] = df_clean['徒歩1'].apply(lambda x: extract_number(x, False))

    # --- 設備・条件のフラグ化 ---
    def check_keyword(text, keywords):
        if pd.isna(text): return 0
        for kw in keywords:
            if kw in str(text): return 1
        return 0

    # 安全策：列が存在しない場合は空文字で作成
    for col in ['部屋の特徴・設備', '備考', '建物種別']:
        if col not in df_clean.columns:
            df_clean[col] = ""

    facilities = df_clean['部屋の特徴・設備'].astype(str) + " " + df_clean['備考'].astype(str)
    b_type = df_clean['建物種別'].astype(str)

    df_clean['バストイレ別'] = facilities.apply(lambda x: check_keyword(x, ['バストイレ別', 'バス・トイレ別']))
    df_clean['独立洗面台'] = facilities.apply(lambda x: check_keyword(x, ['独立洗面台', '洗面所独立']))
    df_clean['室内洗濯機置場'] = facilities.apply(lambda x: check_keyword(x, ['室内洗濯機置場']))
    df_clean['オートロック'] = facilities.apply(lambda x: check_keyword(x, ['オートロック']))
    df_clean['ネット無料'] = facilities.apply(lambda x: check_keyword(x, ['インターネット無料', 'ネット無料']))
    df_clean['ペット相談'] = facilities.apply(lambda x: check_keyword(x, ['ペット相談', 'ペット可']))
    
    df_clean['マンション'] = b_type.apply(lambda x: check_keyword(x, ['マンション']))
    df_clean['木造'] = b_type.apply(lambda x: check_keyword(x, ['木造']))
    df_clean['鉄筋コンクリート'] = b_type.apply(lambda x: check_keyword(x, ['RC', 'SRC', '鉄筋コンクリート']))

    # 必須項目が欠損している行を削除
    df_clean = df_clean.dropna(subset=['家賃_数値', '面積_数値', '築年数_数値', '徒歩_数値'])
    return df_clean


# =========================================================
# 3. Streamlit メインアプリ画面
# =========================================================
def main():
    st.title("🏡 不動産データ収集 ＆ AI賃料査定システム")
    tab1, tab2 = st.tabs(["📊 データ収集 (スクレイピング)", "🤖 AI賃料査定 (重回帰分析)"])

    # --- タブ1：スクレイピング機能 ---
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
                
                try:
                    service = Service('/usr/bin/chromedriver')
                    driver = webdriver.Chrome(service=service, options=options)
                except:
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

    # --- タブ2：AI賃料査定機能 ---
    with tab2:
        st.write("抽出したExcelデータをアップロードして、AIによる詳細な賃料査定を行います。")
        uploaded_file = st.file_uploader("タブ1でダウンロードしたExcelファイルをアップロード", type=["xlsx"])
        
        if uploaded_file is not None:
            raw_df = pd.read_excel(uploaded_file)
            st.info("データを読み込み、AIが学習できる数値に変換しています...")
            df_ml = clean_data_flexible(raw_df)
            
            if len(df_ml) < 10:
                st.error("分析に使用できるデータが少なすぎます。")
            else:
                st.success(f"学習準備完了！ 有効データ数: {len(df_ml)} 件")
                
                # AIに学習させる項目のリスト
                feature_cols = [
                    '面積_数値', '築年数_数値', '徒歩_数値', 
                    'バストイレ別', '独立洗面台', '室内洗濯機置場', 
                    'オートロック', 'ネット無料', 'ペット相談', 
                    'マンション', '木造', '鉄筋コンクリート'
                ]
                
                # 実際にデータに存在する列だけを使う
                valid_features = [col for col in feature_cols if col in df_ml.columns]
                
                X = df_ml[valid_features]
                y = df_ml['家賃_数値']
                
                # モデルの学習
                model = LinearRegression()
                model.fit(X, y)
                
                # 影響度一覧表の表示 (applymap -> map に修正済み)
                st.markdown("---")
                st.subheader("📊 各条件が家賃に与える影響額（AI算出）")
                coef_df = pd.DataFrame({
                    '査定項目': X.columns,
                    '影響額（円）': np.round(model.coef_).astype(int)
                }).sort_values('影響額（円）', ascending=False).reset_index(drop=True)

                def color_negative_red(val):
                    return 'color: red' if val < 0 else 'color: blue'
                st.dataframe(coef_df.style.map(color_negative_red, subset=['影響額（円）']), use_container_width=True)

                # 詳細査定シミュレーター
                st.markdown("---")
                st.subheader("🤖 詳細査定シミュレーター")
                
                # 基本設定（スライダー）
                c1, c2, c3 = st.columns(3)
                with c1:
                    i_area = st.slider("専有面積 (㎡)", float(df_ml['面積_数値'].min()), float(df_ml['面積_数値'].max()), float(df_ml['面積_数値'].median()))
                with c2:
                    i_age = st.slider("築年数 (年)", 0, int(df_ml['築年数_数値'].max()), int(df_ml['築年数_数値'].median()))
                with c3:
                    i_walk = st.slider("駅徒歩 (分)", 0, int(df_ml['徒歩_数値'].max()), int(df_ml['徒歩_数値'].median()))

                # 設備設定（チェックボックス）
                st.markdown("**室内・建物設備**")
                c4, c5, c6 = st.columns(3)
                with c4:
                    i_bt = st.checkbox("バストイレ別", value=True)
                    i_wash = st.checkbox("独立洗面台", value=True)
                with c5:
                    i_laund = st.checkbox("室内洗濯機置場", value=True)
                    i_net = st.checkbox("ネット無料", value=False)
                with c6:
                    i_auto = st.checkbox("オートロック", value=False)
                    i_pet = st.checkbox("ペット相談", value=False)

                st.markdown("**建物構造・種別**")
                c7, c8 = st.columns(2)
                with c7:
                    b_type = st.radio("建物種別", ["マンション", "アパート", "その他"])
                with c8:
                    s_type = st.radio("構造", ["鉄筋コンクリート", "木造", "その他"])

                # 予測用データの組み立て
                input_data = []
                for col in valid_features:
                    if col == '面積_数値': input_data.append(i_area)
                    elif col == '築年数_数値': input_data.append(i_age)
                    elif col == '徒歩_数値': input_data.append(i_walk)
                    elif col == 'バストイレ別': input_data.append(1 if i_bt else 0)
                    elif col == '独立洗面台': input_data.append(1 if i_wash else 0)
                    elif col == '室内洗濯機置場': input_data.append(1 if i_laund else 0)
                    elif col == 'ネット無料': input_data.append(1 if i_net else 0)
                    elif col == 'オートロック': input_data.append(1 if i_auto else 0)
                    elif col == 'ペット相談': input_data.append(1 if i_pet else 0)
                    elif col == 'マンション': input_data.append(1 if b_type == "マンション" else 0)
                    elif col == '木造': input_data.append(1 if s_type == "木造" else 0)
                    elif col == '鉄筋コンクリート': input_data.append(1 if s_type == "鉄筋コンクリート" else 0)
                    else: input_data.append(0)

                # 予測の実行
                predicted_rent = model.predict([input_data])[0]
                
                st.markdown(
                    f"""
                    <div style="background-color:#f0f2f6;padding:20px;border-radius:10px;text-align:center;">
                        <h3 style="margin:0;color:#333;">AI推定賃料（各種条件反映）</h3>
                        <h1 style="margin:0;color:#ff4b4b;font-size:48px;">{int(predicted_rent):,} 円</h1>
                    </div>
                    """, 
                    unsafe_allow_html=True
                )

if __name__ == "__main__":
    main()