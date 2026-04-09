import time
import random
import requests
import re
import pandas as pd
import io
from lxml import html
from urllib.parse import urljoin
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import NoSuchElementException
import streamlit as st

# =========================================================
# データ抽出関数（変更なし）
# =========================================================
def scrape_suumo_refined(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    time.sleep(2)
    res = requests.get(url, headers=headers)
    res.encoding = res.apparent_encoding
    tree = html.fromstring(res.text)
    property_data = {"URL": url}
    
    xpath_dict = {
        "物件名": '//*[@id="wrapper"]/div[3]/div[1]/h1/text()',
        "家賃": '//*[@id="js-view_gallery"]/div/div[2]/div[2]/div/div[2]/div/div[1]/div/div[1]/text()',
        "管理費・共益費": '//*[@id="js-view_gallery"]/div/div[2]/div[2]/div/div[2]/div/div[1]/div/div[2]/div/div[2]/text()',
        "敷金": '//*[@id="js-view_gallery"]/div/div[2]/div[2]/div/div[2]/div/div[2]/ul/li[1]/div/div[2]/span[1]/text()',
        "礼金": '//*[@id="js-view_gallery"]/div/div[2]/div[2]/div/div[2]/div/div[2]/ul/li[1]/div/div[2]/span[3]/text()',
        "保証金": '//*[@id="js-view_gallery"]/div/div[2]/div[2]/div/div[2]/div/div[2]/ul/li[2]/div/div[2]/text()',
        "敷引・償却": '//*[@id="js-view_gallery"]/div/div[2]/div[2]/div/div[2]/div/div[2]/ul/li[3]/div/div[2]/text()',
        "間取り": '//*[@id="js-view_gallery"]/div/div[2]/div[3]/div[1]/div/div[2]/ul/li[1]/div/div[2]/text()',
        "専有面積": '//*[@id="js-view_gallery"]/div/div[2]/div[3]/div[1]/div/div[2]/ul/li[2]/div/div[2]/text()',
        "向き": '//*[@id="js-view_gallery"]/div/div[2]/div[3]/div[1]/div/div[2]/ul/li[3]/div/div[2]/text()',
        "建物種別": '//*[@id="js-view_gallery"]/div/div[2]/div[3]/div[1]/div/div[2]/ul/li[4]/div/div[2]/text()',
        "築年数": '//*[@id="js-view_gallery"]/div/div[2]/div[3]/div[1]/div/div[2]/ul/li[5]/div/div[2]/text()',
        "所在地": '//*[@id="js-view_gallery"]/div/div[2]/div[3]/div[2]/div[2]/div/div[2]/div/text()',
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

    store_xpaths = [
        '//*[@id="contents"]/div[6]/div/div/p[1]/a//text()',
        '//*[@id="contents"]/div[5]/div/div/div[1]/div[2]/div/div[2]/div/div[1]//text()',
        '//p[contains(@class, "bkc-store-name")]/a//text()',
        '//div[contains(@class, "bkc-store")]//text()'
    ]
    property_data["取扱店舗名"] = "-"
    for path in store_xpaths:
        elements = tree.xpath(path)
        if elements:
            raw_text = "".join([e.strip() for e in elements if e.strip()])
            if raw_text:
                property_data["取扱店舗名"] = raw_text
                break

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
                property_data[f"沿線{i}"] = clean_text
                property_data[f"駅{i}"] = "-"
                property_data[f"徒歩{i}"] = "-"

    features_path = '//*[@id="bkdt-option"]/div/ul/li/text()'
    feature_elements = tree.xpath(features_path)
    if feature_elements:
        property_data["部屋の特徴・設備"] = "、".join([f.strip() for f in feature_elements if f.strip()])

    tables = tree.xpath('//table')
    for table in tables:
        rows = table.xpath('.//tr')
        for row in rows:
            ths = row.xpath('.//th')
            tds = row.xpath('.//td')
            for th, td in zip(ths, tds):
                key = "".join(th.xpath('.//text()')).strip()
                value = "".join(td.xpath('.//text()')).replace('\n', '').replace('\r', '').strip()
                
                if not key:
                    continue
                if "コード" in key and "戸" in value:
                    key = "総戸数"
                ignore_list = [
                    "周辺情報", "携帯用QRコード", "スマートフォン", 
                    "取扱い店舗物件コード", "SUUMO物件コード",
                    "半角", "英数", "メールアドレス", "PCアドレス"
                ]
                if any(ignore_word in key + value for ignore_word in ignore_list):
                    continue
                if key not in property_data:
                    property_data[key] = value

    if "備考" in property_data:
        clean_remarks = property_data["備考"].split("周辺情報")[0].strip()
        clean_remarks = clean_remarks.split("携帯用QRコード")[0].strip()
        property_data["備考"] = clean_remarks

    return property_data


# =========================================================
# Streamlit Webアプリの画面構成とメイン処理
# =========================================================
def main():
    # 画面のタイトル
    st.title("🏡 SUUMO 物件データ一括スクレイピング")
    st.write("一覧ページのURLを入力して実行ボタンを押すと、自動でデータを抽出してCSV化します。")

    # ユーザー入力フォーム
    target_list_url = st.text_input("SUUMOの一覧ページのURLを入力してください:", placeholder="https://suumo.jp/...")

    # 実行ボタンが押されたら処理開始
    if st.button("スクレイピングを実行する"):
        if not target_list_url:
            st.warning("URLが入力されていません。")
            return

        # --- フェーズ1：URL収集 ---
        st.subheader("Phase 1: ページ遷移とURL収集")
        status_text1 = st.empty() # 文字を書き換えるための空の枠
        
        # Webアプリではブラウザ画面を出さない（ヘッドレスモード）のが基本
        from selenium.webdriver.chrome.service import Service
        
        # クラウド(Linux)環境でSeleniumを安定して動かすための特別設定
        options = Options()
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        
        # Streamlit Cloud上のChromeDriverのパスを指定
        service = Service('/usr/bin/chromedriver')
        driver = webdriver.Chrome(service=service, options=options)
        
        try:
            driver.get(target_list_url)
            time.sleep(3)
        except Exception as e:
            st.error(f"URLへのアクセスに失敗しました。URLが正しいか確認してください。\n{e}")
            driver.quit()
            return

        all_detail_urls = []
        page_count = 1
        
        try:
            while True:
                status_text1.info(f"{page_count}ページ目から物件URLを抽出中... (現在 {len(all_detail_urls)} 件取得)")
                
                tree = html.fromstring(driver.page_source)
                hrefs = tree.xpath('//a[contains(@href, "/chintai/bc_") or contains(@href, "/chintai/jnc_")]/@href')
                
                for href in hrefs:
                    full_url = urljoin("https://suumo.jp", href)
                    if full_url not in all_detail_urls:
                        all_detail_urls.append(full_url)
                
                wait_time = random.uniform(3, 6)
                time.sleep(wait_time)
                
                try:
                    next_page_xpath = '//a[contains(text(), "次へ")]'
                    next_button = driver.find_element(By.XPATH, next_page_xpath)
                    next_button.click()
                    page_count += 1
                    time.sleep(3)
                    
                except NoSuchElementException:
                    status_text1.success(f"最後のページまで到達しました。合計 {len(all_detail_urls)} 件のURLを収集しました！")
                    break
                except Exception as e:
                    st.warning(f"ページ遷移中にエラーが発生しました: {e}")
                    break
        except Exception as e:
            st.error(f"URL収集プロセスでエラーが発生しました: {e}")
        finally:
            driver.quit()

        if not all_detail_urls:
            st.error("物件URLが1件も取得できませんでした。")
            return

        # --- フェーズ2：詳細データの抽出 ---
        st.subheader("Phase 2: 詳細データの抽出")
        progress_bar = st.progress(0) # プログレスバーの設置
        status_text2 = st.empty()
        
        all_properties_data = []
        total_urls = len(all_detail_urls)

        for idx, url in enumerate(all_detail_urls, 1):
            status_text2.text(f"[{idx}/{total_urls}] を処理中: {url}")
            try:
                data = scrape_suumo_refined(url)
                all_properties_data.append(data)
            except Exception as e:
                st.error(f"エラー発生 ({url}): {e}")
            
            # プログレスバーを更新（0.0 ~ 1.0 の割合）
            progress_bar.progress(idx / total_urls)

# --- フェーズ3：Excel保存とダウンロードボタン表示 ---
        if all_properties_data:
            df = pd.DataFrame(all_properties_data)
            
            # 【新規追加】重複データの自動クリーニング
            original_count = len(df)
            # 物件名、家賃、間取り、専有面積が全て同じものを重複とみなして、最初の1件だけ残す
            df = df.drop_duplicates(subset=['物件名', '家賃', '間取り', '専有面積', '階数'], keep='first')
            dedup_count = len(df)
            removed_count = original_count - dedup_count
            
            # 完了メッセージ（重複削除の件数も報告）
            st.success(f"🎉 抽出完了！ (重複した {removed_count} 件を自動削除し、{dedup_count} 件の物件を抽出しました)")
            
            # 抽出したデータを画面上に少しだけプレビュー表示
            st.write("▼ 抽出結果プレビュー")
            st.dataframe(df.head(5)) 
            
            # Excelデータに変換してメモリ上に保持
            excel_buffer = io.BytesIO()
            df.to_excel(excel_buffer, index=False, engine="openpyxl")
            excel_data = excel_buffer.getvalue()

            # Excelダウンロードボタンの作成
            st.download_button(
                label="📥 抽出したデータをExcelでダウンロード",
                data=excel_data,
                file_name="suumo_properties.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.error("保存できるデータがありませんでした。")
if __name__ == "__main__":
    main()