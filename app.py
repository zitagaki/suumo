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
                options