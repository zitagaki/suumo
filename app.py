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

# 💡 今回追加した地図と座標変換のパッケージ（これがないとエラーになります）
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter

# =========================================================
# 1. ページ設定
# =========================================================
st.set_page_config(page_title="不動産ハイブリッド査定システム", layout="wide")
st.title("🏡 不動産ハイブリッド査定システム (AI × プロの相場観)")

# =========================================================
# 2. スクレイピングエンジン (セーフティネット搭載版)
# =========================================================
def get_xpath_text(tree, xpath_str):
    try:
        elements = tree.xpath(xpath_str)
        if not elements and '/tbody' in xpath_str:
            elements = tree.xpath(xpath_str.replace('/tbody', ''))
            
        if elements:
            if isinstance(elements[0], str):
                return elements[0].strip()
            else:
                text = elements[0].text_content()
                return re.sub(r'\s+', ' ', text).strip()
    except Exception:
        pass
    return ""

def scrape_suumo_list(base_url, max_pages, p_min, p_max, d_min, d_max):
    all_data = []
    error_msg = ""
    
    session = requests.Session()
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'ja,en-US;q=0.9,en;q=0.8',
        'Referer': 'https://suumo.jp/',
        'Connection': 'keep-alive'
    }
    
    base_url = base_url.replace('FR301FC005', 'FR301FC001')
    base_url = base_url.replace('FR301FC006', 'FR301FC001')
    base_url = base_url.replace('FR301FC007', 'FR301FC001')

    base_url = re.sub(r'&pn=\d+', '', base_url)
    base_url = re.sub(r'&page=\d+', '', base_url)
    separator = '&' if '?' in base_url else '?'
    
    progress_bar = st.progress(0)
    status_text = st.empty()

    for page in range(1, max_pages + 1):
        url = f"{base_url}{separator}pn={page}"
        
        try:
            wait_time = random.uniform(p_min, p_max)
            status_text.text(f"ページ遷移の待機中... ({wait_time:.1f}秒)")
            time.sleep(wait_time)
            
            res = session.get(url, headers=headers, timeout=15)
            
            if res.status_code == 403:
                error_msg = f"一覧ページ（{page}ページ目）でSUUMOのアクセス制限（403 Forbidden）を検知しました。"
                break
                
            res.raise_for_status() 
            res.encoding = res.apparent_encoding 
            
            soup = BeautifulSoup(res.content, 'html.parser')
            items = soup.find_all("div", class_="cassetteitem")
            
            if not items:
                st.warning(f"⚠️ ページ {page} から物件データを抽出できませんでした。（データが終了した可能性があります）")
                break
                
            total_rooms = sum([len(item.find_all("tbody")) for item in items])
            room_count = 0
            
            for item in items:
                title_elem = item.find("div", class_="cassetteitem_content-title")
                title = title_elem.text.strip() if title_elem else ""
                
                b_type_elem = item.find("div", class_="cassetteitem_content-label")
                b_type_raw = b_type_elem.text.strip() if b_type_elem else ""
                if "アパート" in b_type_raw: b_type = "アパート"
                elif "マンション" in b_type_raw: b_type = "マンション"
                else: b_type = "その他"
                
                address_elem = item.find("li", class_="cassetteitem_detail-col1")
                address = address_elem.text.strip() if address_elem else ""
                
                stations = item.find_all("div", class_="cassetteitem_detail-text")
                sta1 = stations[0].text.strip() if len(stations) > 0 else ""
                sta2 = stations[1].text.strip() if len(stations) > 1 else ""
                sta3 = stations[2].text.strip() if len(stations) > 2 else ""
                
                col3 = item.find("li", class_="cassetteitem_detail-col3")
                col3_divs = col3.find_all("div") if col3 else []
                age = col3_divs[0].text.strip() if len(col3_divs) > 0 else ""
                bldg_floors = col3_divs[1].text.strip() if len(col3_divs) > 1 else ""
                
                tbodies = item.find_all("tbody")
                for tbody in tbodies:
                    room_count += 1
                    status_text.text(f"🚀 詳細ページから全項目を精密抽出中... (P{page} : {room_count}/{total_rooms}部屋目)")
                    
                    rent = tbody.find("span", class_="cassetteitem_price cassetteitem_price--rent")
                    admin = tbody.find("span", class_="cassetteitem_price cassetteitem_price--administration")
                    deposit = tbody.find("span", class_="cassetteitem_price cassetteitem_price--deposit")
                    gratuity = tbody.find("span", class_="cassetteitem_price cassetteitem_price--gratuity")
                    layout = tbody.find("span", class_="cassetteitem_madori")
                    area = tbody.find("span", class_="cassetteitem_menseki")
                    
                    tds = tbody.find_all("td")
                    room_floor = ""
                    for td in tds:
                        td_text = td.text.strip()
                        if re.match(r'^\d+階$', td_text) or re.match(r'^B\d+階$', td_text):
                            room_floor = td_text
                            
                    combined_floors = f"{room_floor}/{bldg_floors}" if room_floor and bldg_floors else bldg_floors
                    
                    a_tag = tbody.find("a", href=re.compile(r'/chintai/(jnc|bc)_'))
                    if a_tag:
                        url_href = a_tag.get("href")
                        full_url = f"https://suumo.jp{url_href}" if url_href.startswith('/') else url_href
                        m = re.search(r'/(jnc_\d+|bc_\d+)/', url_href)
                        suumo_code = m.group(1) if m else ""
                    else:
                        full_url = ""
                        suumo_code = ""

                    kouzou = chiku_nengetsu = taiyou = setsubi = shop_name = ""
                    detail_dict = {}

                    if full_url:
                        try:
                            time.sleep(random.uniform(d_min, d_max))
                            d_res = session.get(full_url, headers=headers, timeout=10)
                            
                            if d_res.status_code == 403:
                                error_msg = f"詳細ページの取得中（{page}ページ目）にSUUMOのアクセス制限（403 Forbidden）を検知しました。"
                                break 
                                
                            d_tree = lxml.html.fromstring(d_res.content)
                            
                            kouzou = get_xpath_text(d_tree, '//*[@id="contents"]/div[4]/table/tbody/tr[1]/td[2]')
                            chiku_nengetsu = get_xpath_text(d_tree, '//*[@id="contents"]/div[4]/table/tbody/tr[2]/td[2]')
                            taiyou = get_xpath_text(d_tree, '//*[@id="contents"]/div[4]/table/tbody/tr[6]/td[2]')
                            
                            setsubi_elements = d_tree.xpath('//*[@id="bkdt-option"]/div/ul/li')
                            if setsubi_elements:
                                setsubi = "、".join([el.text_content().strip() for el in setsubi_elements])
                            
                            shop_name = get_xpath_text(d_tree, '//*[@id="contents"]/div[5]/div/div/div[1]/div[2]/div/div[2]/div/div[1]')
                            if not shop_name:
                                shop_name = get_xpath_text(d_tree, '//*[@id="contents"]/div[6]/div/div/p[1]/a')

                            for table in d_tree.xpath('//table'):
                                for tr in table.xpath('.//tr'):
                                    ths = tr.xpath('.//th')
                                    tds_detail = tr.xpath('.//td')
                                    for i in range(min(len(ths), len(tds_detail))):
                                        k = ths[i].text_content().strip()
                                        v = re.sub(r'\s+', ' ', tds_detail[i].text_content()).strip()
                                        detail_dict[k] = v
                                        
                        except requests.exceptions.Timeout:
                            pass 
                        except Exception:
                            pass

                    kouzou = kouzou or detail_dict.get("構造", "")
                    chiku_nengetsu = chiku_nengetsu or detail_dict.get("築年月", "")
                    taiyou = taiyou or detail_dict.get("取引態様", detail_dict.get("態様", ""))
                    setsubi = setsubi or detail_dict.get("部屋の特徴・設備", detail_dict.get("設備", ""))
                    shop_name = shop_name or detail_dict.get("取り扱い店舗", "")

                    all_data.append({
                        "物件名": title,
                        "家賃": rent.text.strip() if rent else "",
                        "共益費": admin.text.strip() if admin else "",
                        "敷金": deposit.text.strip() if deposit else "",
                        "礼金": gratuity.text.strip() if gratuity else "",
                        "間取り": layout.text.strip() if layout else "",
                        "専有面積": area.text.strip() if area else "",
                        "建物種別": b_type,
                        "築年数": age,
                        "最寄駅1": sta1,
                        "最寄駅2": sta2,
                        "最寄駅3": sta3,
                        "住所": address,
                        "階建": detail_dict.get("階建", combined_floors),
                        "構造": kouzou,
                        "築年月": chiku_nengetsu,
                        "設備": setsubi,
                        "損保": detail_dict.get("損保", ""),
                        "駐車場": detail_dict.get("駐車場", ""),
                        "入居時期": detail_dict.get("入居可能日", detail_dict.get("入居", "")),
                        "態様": taiyou,
                        "条件": detail_dict.get("条件", ""),
                        "suumoコード": suumo_code,
                        "情報更新日": detail_dict.get("情報更新日", ""),
                        "契約期間": detail_dict.get("契約期間", ""),
                        "保証会社": detail_dict.get("保証会社", ""),
                        "ほか諸費用": detail_dict.get("ほか諸費用", ""),
                        "備考": detail_dict.get("備考・特記事項", detail_dict.get("備考", "")),
                        "店舗": shop_name,
                        "間取り詳細": detail_dict.get("間取り詳細", ""),
                        "ほか初期費用": detail_dict.get("ほか初期費用", ""),
                        "敷金積み増し": detail_dict.get("敷金積み増し", ""),
                        "バルコニー面積": detail_dict.get("バルコニー面積", ""),
                        "URL": full_url
                    })
                
                if error_msg:
                    break
            
            progress_bar.progress(page / max_pages)
            if error_msg:
                break
                
        except requests.exceptions.Timeout:
            error_msg = f"ページ {page} で通信タイムアウトが発生しました。SUUMOサーバーの応答が遅延しています。"
            break
        except Exception as e:
            error_msg = f"ページ {page} で予期せぬエラーが発生しました: {str(e)}"
            break
            
    progress_bar.empty()
    if error_msg:
        status_text.warning("⚠️ 制限検知のため、取得処理を安全に中断しました。")
    else:
        status_text.success("✅ 全ての詳細データの取得が完了しました！")
    
    df = pd.DataFrame(all_data)
    
    if not df.empty:
        before_count = len(df)
        df = df.drop_duplicates(subset=['物件名', '家賃', '共益費', '間取り', '専有面積', '階建'], keep='first')
        after_count = len(df)
        removed_count = before_count - after_count
        
        if removed_count > 0:
            st.info(f"✨ 自動クレンジング: 複数会社から出稿されていた同一物件の重複を {removed_count} 件 削除しました。（実数: {after_count}件）")
            
    return df, error_msg

# =========================================================
# 3. 前処理・データ読み込みエンジン
# =========================================================
@st.cache_data
def analyze_real_estate_data_v15(raw_df, rules_file):
    df_rules = pd.read_csv(rules_file)
    extracted_rules = {}
    madori_list = ['ワンルーム', '1K・1DK', '1LDK', '2K・2DK', '2LDK', '3K・3DK', '3LDK']
    
    for madori in madori_list:
        rule_dict = {}
        if madori in df_rules.columns:
            for idx, row in df_rules.iterrows():
                item_name = str(row.iloc[0]).strip()
                val = row[madori]
                if pd.notna(val) and str(val).strip() != '-':
                    try:
                        rule_dict[item_name] = float(val)
                    except ValueError:
                        pass
        extracted_rules[madori] = rule_dict

    df_suumo = raw_df.copy()

    rent_col = next((c for c in df_suumo.columns if '家賃' in str(c) or '賃料' in str(c)), None)
    df_suumo['家賃_円'] = df_suumo[rent_col].astype(str).str.extract(r'([\d\.]+)').astype(float) * 10000
    
    kyoeki_col = next((c for c in df_suumo.columns if '共益費' in str(c) or '管理費' in str(c)), None)
    if kyoeki_col:
        df_suumo['共益費_円'] = df_suumo[kyoeki_col].astype(str).replace('-', '0').str.extract(r'([\d\.]+)').astype(float).fillna(0)
    else:
        df_suumo['共益費_円'] = 0

    df_suumo.loc[df_suumo['共益費_円'] < 100, '共益費_円'] = df_suumo['共益費_円'] * 10000
    df_suumo['総家賃'] = df_suumo['家賃_円'] + df_suumo['共益費_円']

    area_col = next((c for c in df_suumo.columns if '面積' in str(c)), None)
    df_suumo['専有面積_m2'] = df_suumo[area_col].astype(str).str.extract(r'([\d\.]+)').astype(float) if area_col else 25.0

    df_suumo['㎡単価_家賃のみ'] = df_suumo['家賃_円'] / df_suumo['専有面積_m2']
    df_suumo['㎡単価_総家賃'] = df_suumo['総家賃'] / df_suumo['専有面積_m2']

    walk_col = next((c for c in df_suumo.columns if str(c) in ['最寄駅1', '駅1', '徒歩1', '徒歩']), None)
    if walk_col:
        df_suumo['徒歩分数'] = df_suumo[walk_col].astype(str).str.extract(r'(?:歩|徒歩)(\d+)分').astype(float).fillna(10)
    else:
        df_suumo['徒歩分数'] = 10

    age_col = next((c for c in df_suumo.columns if '築' in str(c) or '数' in str(c)), None)
    if age_col:
        df_suumo['築年'] = df_suumo[age_col].apply(lambda x: 0 if '新築' in str(x) else float(re.search(r'\d+', str(x)).group()) if pd.notna(x) and re.search(r'\d+', str(x)) else 0)
    else:
        df_suumo['築年'] = 0

    madori_col = next((c for c in df_suumo.columns if '間取' in str(c)), None)
    def map_madori(m):
        m = str(m).upper().replace(' ', '').replace('　', '') 
        import unicodedata
        m = unicodedata.normalize('NFKC', m) 
        if '1R' in m or 'ワンルーム' in m: return 'ワンルーム'
        if any(x in m for x in ['1K', '1DK', '1SK', '1SDK']): return '1K・1DK'
        if any(x in m for x in ['1LDK', '1SLDK']): return '1LDK'
        if any(x in m for x in ['2K', '2DK', '2SK', '2SDK']): return '2K・2DK'
        if any(x in m for x in ['2LDK', '2SLDK']): return '2LDK'
        if any(x in m for x in ['3K', '3DK', '3SK', '3SDK']): return '3K・3DK'
        if '3LDK' in m or '4' in m or '5' in m: return '3LDK'
        return 'その他'
    df_suumo['間取りグループ'] = df_suumo[madori_col].apply(map_madori) if madori_col else '1K・1DK'

    type_col = next((c for c in df_suumo.columns if '建物種別' in str(c) or '種別' in str(c)), None)
    if type_col:
        df_suumo['建物種別_判定用'] = df_suumo[type_col].astype(str)
    else:
        text_cols = df_suumo.select_dtypes(include=[object]).fillna('').agg(' '.join, axis=1)
        df_suumo['建物種別_判定用'] = text_cols

    station_col = next((c for c in df_suumo.columns if '駅1' in str(c) or '最寄駅1' in str(c) or '駅' in str(c)), None)
    def extract_station(text):
        text = str(text).strip()
        if text in ('nan', '', 'None', '-'): return '不明'
        text = re.split(r'歩|徒歩|バス|車|\s|　', text)[0].strip()
        if '/' in text:
            text = text.split('/')[-1]
        if text.endswith('駅'):
            text = text[:-1]
        if text.endswith('線'):
            return '不明'
        return text if text else '不明'

    df_suumo['駅名'] = df_suumo[station_col].apply(extract_station) if station_col else '不明'

    return extracted_rules, df_suumo

# =========================================================
# 4. UIロジック
# =========================================================
tab1, tab2, tab3 = st.tabs(["📂 ①データの取得＆解析", "🤖 ②詳細査定シミュレーター", "🗺️ ③マップ・㎡単価分析"])

# ---------------------------------------------------------
# TAB 1: アップロード / スクレイピング画面
# ---------------------------------------------------------
with tab1:
    st.write("「SUUMOから自動取得」または「お手元のExcelファイルアップロード」のどちらかを選択してください。")
    
    data_source = st.radio("データソースの選択", ["🌐 SUUMOのURLから自動取得 (スクレイピング)", "📁 エクセル/CSVファイルをアップロード"])
    
    df_raw = None
    
    if data_source == "🌐 SUUMOのURLから自動取得 (スクレイピング)":
        target_url = st.text_input("SUUMOの検索結果URLを貼り付けてください", placeholder="https://suumo.jp/jj/chintai/ichiran/...")
        max_pages = st.number_input("取得する最大ページ数", min_value=1, max_value=100, value=3)
        
        with st.expander("⚙️ スクレイピング待機時間の設定（ブロック対策）", expanded=False):
            st.markdown("SUUMOからのロボット検知（アクセスブロック）を避けるための待機時間（秒）です。ページ数が多い場合やブロックされる場合は、秒数を長めに設定してください。")
            col_w1, col_w2 = st.columns(2)
            with col_w1:
                st.markdown("**▼ 1件取得（詳細ページ）ごとの待機**")
                d_min = st.number_input("最短待機 (秒)", min_value=0.1, max_value=10.0, value=1.0, step=0.5)
                d_max = st.number_input("最長待機 (秒)", min_value=0.1, max_value=15.0, value=2.5, step=0.5)
            with col_w2:
                st.markdown("**▼ ページ遷移（次のページへ）の待機**")
                p_min = st.number_input("最短待機 (秒)", min_value=1.0, max_value=30.0, value=3.0, step=1.0)
                p_max = st.number_input("最長待機 (秒)", min_value=1.0, max_value=30.0, value=5.0, step=1.0)
                
            p_min_actual, p_max_actual = min(p_min, p_max), max(p_min, p_max)
            d_min_actual, d_max_actual = min(d_min, d_max), max(d_min, d_max)

        if st.button("🚀 データを取得する"):
            if target_url:
                with st.spinner("SUUMOから全物件の詳細データを自動収集しています（※設定した待機時間に応じて処理に時間がかかります）..."):
                    scraped_df, error_msg = scrape_suumo_list(target_url, max_pages, p_min_actual, p_max_actual, d_min_actual, d_max_actual)
                    
                    if not scraped_df.empty:
                        st.session_state['raw_df'] = scraped_df
                        if error_msg:
                            st.warning(f"⚠️ **取得中断のお知らせ**\n\n{error_msg}\n\nロボット対策による制限がかかりましたが、**そこまでに取得できた {len(scraped_df)} 件のデータ** は安全に保存されました！下のボタンからダウンロード・解析へ進めます。")
                        else:
                            st.success("✅ データの取得と重複クレンジングが完了しました！")
                    else:
                        if error_msg:
                            st.error(f"データの取得に失敗しました。\n原因: {error_msg}")
                        else:
                            st.error("データの取得に失敗しました。URLが正しいか確認してください。")
            else:
                st.warning("URLを入力してください。")
                
        if 'raw_df' in st.session_state:
            st.write("取得したデータプレビュー:")
            st.dataframe(st.session_state['raw_df'].head())
            df_raw = st.session_state['raw_df']
            
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                df_raw.to_excel(writer, index=False)
            st.download_button(label="📥 取得したデータをExcelで保存（重複削除済み）", data=buffer.getvalue(), file_name="suumo_scraped_data_deduplicated.xlsx", mime="application/vnd.ms-excel")

    else:
        uploaded_suumo = st.file_uploader("SUUMO物件データ (Excel/CSV)", type=["xlsx", "csv"])
        if uploaded_suumo:
            try:
                df_raw = pd.read_excel(uploaded_suumo)
            except:
                df_raw = pd.read_csv(uploaded_suumo)
            st.success("✅ ファイルを読み込みました！")

    st.markdown("---")
    st.write("▼ 共通: ルールCSVをアップロードして解析を実行してください")
    uploaded_rules = st.file_uploader("ルールフォーマット (CSV) ※必須", type=["csv"])

    if df_raw is not None and uploaded_rules is not None:
        if st.button("🧠 解析してシミュレーターを起動"):
            with st.spinner("データを解析し、駅ごとの相場とルールを構築しています..."):
                extracted_rules, df_suumo = analyze_real_estate_data_v15(df_raw, uploaded_rules)
                
                st.session_state['rules'] = extracted_rules
                st.session_state['df_suumo'] = df_suumo
                
                st.success("✅ 解析完了！「②詳細査定シミュレーター」や「③マップ・㎡単価分析」タブへお進みください。")

# ---------------------------------------------------------
# TAB 2: シミュレーター画面
# ---------------------------------------------------------
with tab2:
    if 'rules' not in st.session_state or 'df_suumo' not in st.session_state:
        st.warning("⚠️ 先に「①データの取得＆解析」タブでデータを取り込んでください。")
    else:
        st.subheader("🤖 詳細査定シミュレーター")
        
        rules = st.session_state['rules']
        df_suumo = st.session_state['df_suumo']

        calc_mode = st.radio("💰 単価計算の基準（ベース相場に共益費を含めるか）", ["家賃＋共益費（総家賃）で計算", "家賃のみで計算"], horizontal=True)
        tanka_col = '㎡単価_総家賃' if calc_mode == "家賃＋共益費（総家賃）で計算" else '㎡単価_家賃のみ'

        valid_layouts = list(rules.keys())
        default_layout_idx = valid_layouts.index('1K・1DK') if '1K・1DK' in valid_layouts else 0
        
        raw_stations = df_suumo['駅名'].unique()
        station_list = ['指定なし'] + sorted([s for s in raw_stations if pd.notna(s) and str(s).strip() not in ['', 'nan', '不明']])

        st.markdown("**基本スペック**")
        col1, col2, col3, col4, col5 = st.columns(5)
        with col1: target_layout = st.selectbox("間取りタイプ", valid_layouts, index=default_layout_idx)
        with col2: selected_station = st.selectbox("対象駅", station_list)
        with col3: i_area = st.number_input("専有面積 (㎡)", min_value=10.0, max_value=200.0, value=25.0, step=0.5)
        with col4: i_age = st.number_input("築年数 (年) ※新築は0", min_value=0, max_value=100, value=5)
        with col5: i_walk = st.number_input("駅徒歩 (分)", min_value=0, max_value=60, value=8)

        st.markdown("**建物種別 ＆ 設備条件（選択で査定額に反映されます）**")
        i_btype = st.radio("建物種別", ["指定なし", "マンション", "アパート"], horizontal=True)
        
        col5, col6, col7, col8 = st.columns(4)
        with col5:
            i_2f = st.checkbox("2階以上", value=True)
            i_corner = st.checkbox("角部屋", value=False)
            i_south = st.checkbox("南向き", value=False)
        with col6:
            i_bt = st.checkbox("バス・トイレ別", value=True)
            i_sh = st.checkbox("洗面所独立", value=False)
            i_wc = st.checkbox("温水洗浄便座", value=False)
            i_oidaki = st.checkbox("追い焚き風呂", value=False)
        with col7:
            i_sys = st.checkbox("システムキッチン", value=False)
            i_dry = st.checkbox("浴室乾燥機", value=False)
            i_net = st.checkbox("インターネット無料", value=False)
        with col8:
            i_auto = st.checkbox("オートロック", value=True)
            i_box = st.checkbox("宅配ボックス", value=False)
            i_premium = st.number_input("その他・手動プレミアム (円)", value=0, step=1000)

        selected_features = {
            '2階以上': i_2f, '角部屋': i_corner, '南向き': i_south,
            'バス・トイレ別': i_bt, '洗面所独立': i_sh, '温水洗浄便座': i_wc,
            '追い焚き風呂': i_oidaki,
            'システムキッチン': i_sys, '浴室乾燥機': i_dry, 'インターネット無料': i_net,
            'オートロック': i_auto, '宅配ボックス': i_box
        }

        mask_base = (df_suumo['間取りグループ'] == target_layout)
        if selected_station != '指定なし': mask_base &= (df_suumo['駅名'] == selected_station)
        if i_btype == 'マンション': mask_base &= df_suumo['建物種別_判定用'].str.contains('マンション', na=False)
        elif i_btype == 'アパート': mask_base &= df_suumo['建物種別_判定用'].str.contains('アパート', na=False)

        tanka_series_base = df_suumo[mask_base][tanka_col].dropna()
        
        if len(tanka_series_base) > 0:
            tanka_base = tanka_series_base.median()
        else:
            mask_fallback = (df_suumo['間取りグループ'] == target_layout)
            if i_btype in ['マンション', 'アパート']:
                mask_fallback &= df_suumo['建物種別_判定用'].str.contains(i_btype, na=False)
            tanka_series_fb = df_suumo[mask_fallback][tanka_col].dropna()
            if len(tanka_series_fb) > 0:
                tanka_base = tanka_series_fb.median()
                st.warning(f"⚠️ 指定された「{selected_station}駅」には{i_btype}のデータがないため、ベース家賃はエリア全体の{i_btype}相場を代用しています。")
            else:
                tanka_base = df_suumo[df_suumo['間取りグループ'] == target_layout][tanka_col].dropna().median()
                if pd.isna(tanka_base): tanka_base = 4000
                st.warning(f"⚠️ {i_btype}のデータが見つからないため、全体の相場を使用しています。")

        r = rules.get(target_layout, {})
        rent_base = tanka_base * i_area
        rent_rules = 0
        
        tanka_under_10 = r.get('徒歩10分以内単価', 0)
        tanka_over_10 = r.get('徒歩10分超追加単価', 0)
        fixed_penalty = r.get('徒歩10分超固定ペナルティ', 0)

        if i_walk <= 10:
            rent_rules += (i_walk * tanka_under_10) * i_area
        else:
            rent_rules += (10 * tanka_under_10) * i_area
            rent_rules += fixed_penalty
            rent_rules += ((i_walk - 10) * tanka_over_10) * i_area
        
        if i_age == 0: rent_rules += r.get('築年_新築単価', 0) * i_area
        elif 1 <= i_age <= 3: rent_rules += r.get('築年_1_3年単価', 0) * i_area
        elif 4 <= i_age <= 6: rent_rules += r.get('築年_4_6年単価', 0) * i_area
        elif 7 <= i_age <= 10: rent_rules += r.get('築年_7_10年単価', 0) * i_area
        
        for feat_name, is_checked in selected_features.items():
            if is_checked:
                feat_tanka = r.get(feat_name, 0)
                rent_rules += feat_tanka * i_area
        
        predicted_rent = int(rent_base + rent_rules + i_premium)

        station_label = "当該エリア全体" if selected_station == '指定なし' else f"{selected_station}駅周辺"
        if i_btype != '指定なし': station_label += f"（{i_btype}）"
            
        data_count = len(tanka_series_base)
        display_rent = predicted_rent
        cap_message = "" 
        
        if data_count > 0:
            price_min = int(tanka_series_base.min() * i_area)
            price_max = int(tanka_series_base.max() * i_area)
            zone_low = int(tanka_series_base.quantile(0.333) * i_area)
            zone_high = int(tanka_series_base.quantile(0.667) * i_area)

            if predicted_rent > price_max:
                display_rent = price_max 
                cap_message = f"<br><span style='color:#e74c3c; font-size:16px; font-weight:bold;'>※相場上限に達したため最高価格を表示しています（参考理論値: {predicted_rent:,} 円）</span>"
        else:
            price_min = price_max = zone_low = zone_high = 0

        st.markdown(
            f"""
            <div style="background-color:#e8f4f8;padding:20px;border-radius:10px;text-align:center;margin-top:20px;">
                <h3 style="margin:0;color:#333;">設備・条件を反映した推定家賃</h3>
                <h1 style="margin:0;color:#0066cc;font-size:48px;">{display_rent:,} 円</h1>
                <p style="color:#666; margin:0;">
                ({i_btype}のベース相場: {int(rent_base):,}円 ＋ 設備加減点: {int(rent_rules):,}円 ＋ 手動調整: {i_premium}円){cap_message}
                </p>
            </div>
            """, 
            unsafe_allow_html=True
        )

        st.markdown("<br><hr>", unsafe_allow_html=True)
        
        st.subheader(f"📈 面積 {i_area}㎡ の箱に対する、【{station_label}】の純粋な相場帯（データ: {data_count}件）")
        st.caption(f"※設備等を一切考慮せず、同じ間取り・同じ広さの{i_btype}が市場でどう分布しているかを示す「理論値」の目安です。")

        if data_count > 0:
            colA, colB, colC = st.columns(3)
            with colA: st.metric(label="最低価格目安", value=f"{price_min:,} 円")
            with colB: st.metric(label="ボリュームゾーン (中核33%)", value=f"{zone_low:,} 〜 {zone_high:,} 円", delta="市場の中心帯")
            with colC: st.metric(label="最高価格目安", value=f"{price_max:,} 円")

            st.caption(f"▼ 今回の推定家賃（{display_rent:,}円）が、市場全体のどの位置にいるかの目安")
            if price_max > price_min:
                progress_val = (display_rent - price_min) / (price_max - price_min)
                st.progress(min(1.0, max(0.0, progress_val)))
            else:
                st.progress(0.5)

            st.markdown("<br><br>", unsafe_allow_html=True)
            
            rent_col_actual = '総家賃' if calc_mode == "家賃＋共益費（総家賃）で計算" else '家賃_円'
            actual_rent_series = df_suumo[mask_base][rent_col_actual].dropna()
            
            st.subheader(f"📊 【{target_layout}】の実際の家賃分布（面積換算なし / データ: {data_count}件）")
            st.caption(f"※入力された面積({i_area}㎡)に関わらず、指定された条件（{station_label}・{target_layout}）で現在募集されている物件の「実際の価格」の分布です。")
            
            actual_min = int(actual_rent_series.min())
            actual_max = int(actual_rent_series.max())
            actual_zone_low = int(actual_rent_series.quantile(0.333))
            actual_zone_high = int(actual_rent_series.quantile(0.667))
            
            colD, colE, colF = st.columns(3)
            with colD: st.metric(label="実際の最低家賃", value=f"{actual_min:,} 円")
            with colE: st.metric(label="ボリュームゾーン (中核33%)", value=f"{actual_zone_low:,} 〜 {actual_zone_high:,} 円", delta="実際の募集価格の中心帯")
            with colF: st.metric(label="実際の最高家賃", value=f"{actual_max:,} 円")
            
            st.caption(f"▼ 今回の推定家賃（{display_rent:,}円）が、実際に出回っている物件の中でどの位置にいるかの目安")
            if actual_max > actual_min:
                progress_val_actual = (display_rent - actual_min) / (actual_max - actual_min)
                st.progress(min(1.0, max(0.0, progress_val_actual)))
            else:
                st.progress(0.5)
                
        else:
            st.info("条件に一致するデータがないため、相場分布のメーターは表示されません。")

# ---------------------------------------------------------
# TAB 3: マップ・単価分析画面
# ---------------------------------------------------------
with tab3:
    if 'df_suumo' not in st.session_state:
        st.warning("⚠️ 先に「①データの取得＆解析」タブでデータを取り込んでください。")
    else:
        st.subheader("🗺️ 物件マップ ＆ ㎡単価ヒートマップ分析")
        st.write("設定した条件で物件を絞り込み、地図上にプロットして㎡単価を表示します。")
        
        df = st.session_state['df_suumo']
        
        st.markdown("**▼ マップに表示する物件の絞り込み**")
        col_m1, col_m2, col_m3, col_m4 = st.columns(4)
        
        valid_layouts_map = df['間取りグループ'].unique()
        with col_m1:
            map_layout = st.multiselect("間取り", valid_layouts_map, default=valid_layouts_map)
        with col_m2:
            map_max_rent = st.number_input("総家賃の上限 (万円)", value=25.0, step=1.0)
        with col_m3:
            map_max_walk = st.number_input("駅徒歩の上限 (分)", value=15, step=1)
        with col_m4:
            map_max_age = st.number_input("築年数の上限 (年)", value=30, step=1)

        filtered_df = df[
            (df['間取りグループ'].isin(map_layout)) &
            (df['総家賃'] <= map_max_rent * 10000) &
            (df['徒歩分数'] <= map_max_walk) &
            (df['築年'] <= map_max_age)
        ].copy()

        st.info(f"💡 条件に一致する物件: {len(filtered_df)} 件")
        
        if len(filtered_df) > 50:
            st.warning("※件数が多すぎるため、変換負荷を考慮して上位50件のみをマップに表示します。さらに条件を絞り込むことをお勧めします。")
            filtered_df = filtered_df.head(50)

        if st.button("🗺️ マップを描画する (※住所の座標変換に数十秒かかります)"):
            with st.spinner(f"{len(filtered_df)}件の住所を座標に変換しています...少々お待ちください。"):
                
                geolocator = Nominatim(user_agent="suumo_real_estate_analyzer")
                geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1.0)
                
                filtered_df['location'] = filtered_df['住所'].apply(geocode)
                filtered_df['緯度'] = filtered_df['location'].apply(lambda loc: loc.latitude if loc else None)
                filtered_df['経度'] = filtered_df['location'].apply(lambda loc: loc.longitude if loc else None)
                
                map_df = filtered_df.dropna(subset=['緯度', '経度'])
                
                if not map_df.empty:
                    st.success(f"✅ {len(map_df)} 件の物件をマップに配置しました！")
                    
                    center_lat = map_df['緯度'].mean()
                    center_lon = map_df['経度'].mean()
                    
                    m = folium.Map(location=[center_lat, center_lon], zoom_start=15)
                    
                    for idx, row in map_df.iterrows():
                        tanka_m2 = row['㎡単価_総家賃']
                        
                        popup_html = f"""
                        <div style="width:200px;">
                            <h4 style="margin:0; color:#0066cc;">{row['物件名']}</h4>
                            <hr style="margin:5px 0;">
                            <b>総家賃:</b> {row['総家賃']/10000:.1f} 万円<br>
                            <b>間取り:</b> {row['間取り']} ({row['専有面積_m2']}㎡)<br>
                            <b>築年数:</b> {row['築年']}年 / <b>駅徒歩:</b> {row['徒歩分数']}分<br>
                            <div style="background-color:#fff3cd; padding:5px; margin-top:5px; border-radius:3px;">
                                <b style="color:#d35400;">㎡単価: {int(tanka_m2):,} 円/㎡</b>
                            </div>
                        </div>
                        """
                        
                        pin_color = "red" if tanka_m2 >= 4000 else "blue"
                        
                        folium.Marker(
                            location=[row['緯度'], row['経度']],
                            popup=folium.Popup(popup_html, max_width=300),
                            icon=folium.Icon(color=pin_color, icon="home"),
                        ).add_to(m)
                    
                    st_folium(m, width=900, height=600)
                else:
                    st.error("住所の座標変換に失敗しました。取得した住所データの形式が特殊な可能性があります。")