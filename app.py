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
# 1. ページ設定と記憶領域（セッション）の初期化
# =========================================================
st.set_page_config(page_title="不動産ハイブリッド査定システム", layout="wide")

if 'raw_df' not in st.session_state:
    st.session_state['raw_df'] = pd.DataFrame()
if 'scraping_log' not in st.session_state:
    st.session_state['scraping_log'] = ""
# 💡 自動再開のための記憶領域を追加
if 'current_target_url' not in st.session_state:
    st.session_state['current_target_url'] = ""
if 'next_start_page' not in st.session_state:
    st.session_state['next_start_page'] = 1
if 'remaining_pages' not in st.session_state:
    st.session_state['remaining_pages'] = 30
if 'auto_resume_mode' not in st.session_state:
    st.session_state['auto_resume_mode'] = False

st.title("🏡 不動産ハイブリッド査定システム (AI × プロの相場観)")

# =========================================================
# 2. スクレイピングエンジン (自動再開ナビゲーション搭載)
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

def scrape_suumo_list_incremental(base_url, start_page, max_pages, p_min, p_max, d_min, d_max):
    session = requests.Session()
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'ja,en-US;q=0.9,en;q=0.8',
        'Referer': 'https://suumo.jp/',
        'Connection': 'keep-alive'
    }
    
    base_url = base_url.replace('FR301FC005', 'FR301FC001').replace('FR301FC006', 'FR301FC001').replace('FR301FC007', 'FR301FC001')
    base_url = re.sub(r'&pn=\d+', '', base_url)
    base_url = re.sub(r'&page=\d+', '', base_url)
    separator = '&' if '?' in base_url else '?'
    
    tracker_box = st.empty()
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    new_data = []
    end_page = start_page + max_pages
    current_progress = 0
    interrupted = False

    for page in range(start_page, end_page):
        # 💡 通信を行う前に、もしここで止まった場合の「次の開始位置」を記憶しておく
        st.session_state['next_start_page'] = page
        st.session_state['remaining_pages'] = end_page - page
        
        st.session_state['scraping_log'] = f"⚠️ 【中断検知】前回の取得は【 {page} 】ページ目の途中で通信が強制切断されました。"
        tracker_box.info(f"🔄 **現在【 {page} 】ページ目を処理しています...**\n\n※もしここで突然画面が初期状態に戻った場合は、裏で強制切断が起きています。")
        
        url = f"{base_url}{separator}pn={page}"
        try:
            wait_time = random.uniform(p_min, p_max)
            status_text.text(f"⏳ {page}ページ目へ遷移中... ({wait_time:.1f}秒待機)")
            time.sleep(wait_time)
            
            res = session.get(url, headers=headers, timeout=15)
            if res.status_code == 403:
                st.session_state['scraping_log'] = f"❌ 【 {page} 】ページ目でSUUMOのブロック(403)を検知しました！"
                tracker_box.error(st.session_state['scraping_log'])
                interrupted = True
                break
                
            res.raise_for_status() 
            res.encoding = res.apparent_encoding 
            soup = BeautifulSoup(res.content, 'html.parser')
            items = soup.find_all("div", class_="cassetteitem")
            
            if not items:
                st.session_state['scraping_log'] = f"⚠️ {page}ページ目からデータが見つかりませんでした（最終ページの可能性があります）。"
                tracker_box.warning(st.session_state['scraping_log'])
                interrupted = True # これ以上進む必要がないので再開フラグは立てない
                st.session_state['auto_resume_mode'] = False
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
                    status_text.text(f"🚀 詳細データ取得中... (P{page} : {room_count}/{total_rooms}部屋目)")
                    
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
                                st.session_state['scraping_log'] = f"❌ 【 {page} 】ページ目の物件詳細取得中にブロックされました！"
                                tracker_box.error(st.session_state['scraping_log'])
                                temp_df = pd.DataFrame(new_data)
                                if not temp_df.empty:
                                    st.session_state['raw_df'] = pd.concat([st.session_state['raw_df'], temp_df]).drop_duplicates(subset=['物件名', '家賃', '共益費', '間取り', '専有面積', '階建'], keep='first')
                                interrupted = True
                                return # ここで関数を抜けるが、外側で再開処理をキャッチする
                                
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

                    new_data.append({
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
            
            temp_df = pd.DataFrame(new_data)
            if not temp_df.empty:
                st.session_state['raw_df'] = pd.concat([st.session_state['raw_df'], temp_df]).drop_duplicates(subset=['物件名', '家賃', '共益費', '間取り', '専有面積', '階建'], keep='first')
            new_data = [] 
            
            current_progress += 1
            progress_bar.progress(current_progress / max_pages)
                
        except requests.exceptions.Timeout:
            st.session_state['scraping_log'] = f"❌ 【 {page} 】ページ目で通信タイムアウトが発生しました。"
            tracker_box.error(st.session_state['scraping_log'])
            interrupted = True
            break
        except Exception as e:
            st.session_state['scraping_log'] = f"⚠️ 予期せぬエラーが発生しました。"
            tracker_box.error(st.session_state['scraping_log'])
            interrupted = True
            break
            
    if not interrupted:
        st.session_state['scraping_log'] = f"✅ 指定された {start_page} ページ 〜 {end_page - 1} ページの処理がすべて完了しました！"
        tracker_box.success(st.session_state['scraping_log'])
        st.session_state['auto_resume_mode'] = False # 完走したら再開モードをオフ
    else:
        # 💡 中断された場合、再開モードをオンにして画面にボタンを出す準備をする
        st.session_state['auto_resume_mode'] = True
        
    status_text.empty()
    progress_bar.empty()

# =========================================================
# 3. 前処理・データ読み込みエンジン
# =========================================================
@st.cache_data
def analyze_real_estate_data_final(raw_df, rules_file):
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
tab1, tab2, tab3 = st.tabs(["📂 ①データの取得＆解析", "🤖 ②詳細査定シミュレーター", "🏘️ ③エリア別相場ヒートマップ"])

# ---------------------------------------------------------
# TAB 1: アップロード / スクレイピング画面
# ---------------------------------------------------------
with tab1:
    st.write("「SUUMOから自動取得」または「お手元のExcelファイルアップロード」のどちらかを選択してください。")
    
    data_source = st.radio("データソースの選択", ["🌐 SUUMOのURLから自動取得 (スクレイピング)", "📁 エクセル/CSVファイルをアップロード"])
    
    df_raw = None
    
    if data_source == "🌐 SUUMOのURLから自動取得 (スクレイピング)":
        target_url = st.text_input("SUUMOの検索結果URLを貼り付けてください", placeholder="https://suumo.jp/jj/chintai/ichiran/...")
        
        # URLが入力されたら記憶しておく
        if target_url:
            st.session_state['current_target_url'] = target_url
            
        # 💡 自動再開モードがONの時は、目立つように警告と再開ボタンを出す
        if st.session_state['auto_resume_mode']:
            st.markdown(
                f"""
                <div style="background-color:#ffebee;padding:20px;border-radius:10px;border: 2px solid #f44336;margin-bottom:20px;">
                    <h3 style="margin:0;color:#d32f2f;">⚠️ スクレイピングが中断されました</h3>
                    <p style="color:#333;font-size:16px;">
                        前回の処理は <b>{st.session_state['next_start_page']} ページ目</b> でストップしました。<br>
                        ネットワークを切り替えるか、少し時間を置いてから下のボタンを押すと、<b>残りの {st.session_state['remaining_pages']} ページ分</b> を自動的に再開します。
                    </p>
                </div>
                """, 
                unsafe_allow_html=True
            )
            
            # 再開専用の巨大ボタン
            if st.button(f"🔄 【開始ページ: {st.session_state['next_start_page']}】から即座に再開する", type="primary", use_container_width=True):
                st.session_state['scraping_log'] = ""
                with st.spinner(f"{st.session_state['next_start_page']}ページ目から再開しています..."):
                    scrape_suumo_list_incremental(
                        st.session_state['current_target_url'], 
                        st.session_state['next_start_page'], 
                        st.session_state['remaining_pages'], 
                        1.0, 2.5, 3.0, 5.0 # ※ここは固定の安全値で再開
                    )
                st.rerun() # 処理が終わったら画面をリロード
        
        st.markdown("---")
        
        col_p1, col_p2 = st.columns(2)
        with col_p1:
            start_page = st.number_input("スクレイピング開始ページ（通常は1）", min_value=1, max_value=999, value=1)
        with col_p2:
            max_pages = st.number_input("取得するページ数", min_value=1, max_value=200, value=30)
        
        with st.expander("⚙️ スクレイピング待機時間の設定（ブロック対策）", expanded=False):
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

        col_btn, col_res = st.columns([1, 1])
        
        with col_btn:
            if st.button("🚀 新規データを取得する（最初から）"):
                if target_url:
                    if start_page == 1:
                        st.session_state['raw_df'] = pd.DataFrame()
                    st.session_state['auto_resume_mode'] = False # 手動でスタートしたら再開モードはリセット
                    st.session_state['scraping_log'] = ""
                    with st.spinner("SUUMOから全物件の詳細データを自動収集しています..."):
                        # ※タイマー機能は削除し、シンプルな進行に戻しました
                        scrape_suumo_list_incremental(target_url, start_page, max_pages, p_min_actual, p_max_actual, d_min_actual, d_max_actual)
                    st.rerun() # 処理後に画面をリロード
                else:
                    st.warning("URLを入力してください。")

        with col_res:
            if 'raw_df' in st.session_state and not st.session_state['raw_df'].empty:
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                    st.session_state['raw_df'].to_excel(writer, index=False)
                st.download_button(
                    label=f"📥 取得済みデータ ({len(st.session_state['raw_df'])}件) を保存（中断時用）",
                    data=buffer.getvalue(),
                    file_name="suumo_rescue_data.xlsx",
                    mime="application/vnd.ms-excel"
                )

        if 'scraping_log' in st.session_state and st.session_state['scraping_log']:
            if "❌" in st.session_state['scraping_log'] or "⚠️" in st.session_state['scraping_log']:
                pass # 再開モードの赤いボックスが出ているのでここはスルー
            else:
                st.success(st.session_state['scraping_log'])

        if 'raw_df' in st.session_state and not st.session_state['raw_df'].empty:
            st.write("取得したデータプレビュー:")
            st.dataframe(st.session_state['raw_df'].head())
            df_raw = st.session_state['raw_df']

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
                extracted_rules, df_suumo = analyze_real_estate_data_final(df_raw, uploaded_rules)
                st.session_state['rules'] = extracted_rules
                st.session_state['df_suumo'] = df_suumo
                st.success("✅ 解析完了！「②詳細査定シミュレーター」や「③エリア別相場ヒートマップ」タブへお進みください。")

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
            else:
                tanka_base = df_suumo[df_suumo['間取りグループ'] == target_layout][tanka_col].dropna().median()
                if pd.isna(tanka_base): tanka_base = 4000

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
            
            actual_min = int(actual_rent_series.min())
            actual_max = int(actual_rent_series.max())
            actual_zone_low = int(actual_rent_series.quantile(0.333))
            actual_zone_high = int(actual_rent_series.quantile(0.667))
            
            colD, colE, colF = st.columns(3)
            with colD: st.metric(label="実際の最低家賃", value=f"{actual_min:,} 円")
            with colE: st.metric(label="ボリュームゾーン (中核33%)", value=f"{actual_zone_low:,} 〜 {actual_zone_high:,} 円", delta="実際の募集価格の中心帯")
            with colF: st.metric(label="実際の最高家賃", value=f"{actual_max:,} 円")
            
            if actual_max > actual_min:
                progress_val_actual = (display_rent - actual_min) / (actual_max - actual_min)
                st.progress(min(1.0, max(0.0, progress_val_actual)))
            else:
                st.progress(0.5)
                
        else:
            st.info("条件に一致するデータがないため、相場分布のメーターは表示されません。")

# ---------------------------------------------------------
# 💡 TAB 3: 町丁目ごとの相場ヒートマップ＆リスト化エンジン
# ---------------------------------------------------------
with tab3:
    if 'df_suumo' not in st.session_state:
        st.warning("⚠️ 先に「①データの取得＆解析」タブでデータを取り込んでください。")
    else:
        st.subheader("🏘️ エリア（町丁目）別 相場ヒートマップ＆物件リスト")
        st.write("「下高井戸１」などの住所ごとにデータを自動グループ化し、相場水準やボリュームゾーンをリスト化します。")
        
        df = st.session_state['df_suumo']
        
        calc_mode_map = st.radio("💰 単価計算の基準（ヒートマップ用）", ["家賃＋共益費（総家賃）で計算", "家賃のみで計算"], horizontal=True, key="map_calc_mode")
        rent_col_map = '総家賃' if calc_mode_map == "家賃＋共益費（総家賃）で計算" else '家賃_円'
        tanka_col_map = '㎡単価_総家賃' if calc_mode_map == "家賃＋共益費（総家賃）で計算" else '㎡単価_家賃のみ'
        
        st.markdown("**▼ データの絞り込み条件**")
        col_m1, col_m2 = st.columns(2)
        
        valid_layouts_map = df['間取りグループ'].unique()
        raw_stations_map = df['駅名'].unique()
        station_list_map = sorted([s for s in raw_stations_map if pd.notna(s) and str(s).strip() not in ['', 'nan', '不明']])
        
        with col_m1: map_layouts = st.multiselect("間取りタイプ", valid_layouts_map, default=valid_layouts_map)
        with col_m2: map_stations = st.multiselect("対象駅（複数選択可 / 空欄で全駅対象）", station_list_map)
        
        st.markdown("**▼ スペックの範囲指定（左右の丸をつまんで下限〜上限を設定）**")
        col_m3, col_m4, col_m5 = st.columns(3)
        with col_m3: map_area = st.slider("専有面積 (㎡)", min_value=0.0, max_value=200.0, value=(10.0, 100.0), step=1.0)
        with col_m4: map_age = st.slider("築年数 (年)", min_value=0, max_value=100, value=(0, 40))
        with col_m5: map_walk = st.slider("駅徒歩 (分)", min_value=0, max_value=60, value=(0, 20))

        map_btype = st.radio("建物種別 (集計用)", ["指定なし", "マンション", "アパート"], horizontal=True)
        
        with st.expander("➕ 詳細な設備条件で絞り込む"):
            col_m6, col_m7, col_m8, col_m9 = st.columns(4)
            with col_m6:
                m_2f = st.checkbox("2階以上", value=False, key='m2f')
                m_corner = st.checkbox("角部屋", value=False, key='mcorn')
                m_south = st.checkbox("南向き", value=False, key='msou')
            with col_m7:
                m_bt = st.checkbox("バス・トイレ別", value=False, key='mbt')
                m_sh = st.checkbox("洗面所独立", value=False, key='msh')
                m_wc = st.checkbox("温水洗浄便座", value=False, key='mwc')
                m_oidaki = st.checkbox("追い焚き風呂", value=False, key='moid')
            with col_m8:
                m_sys = st.checkbox("システムキッチン", value=False, key='msys')
                m_dry = st.checkbox("浴室乾燥機", value=False, key='mdry')
                m_net = st.checkbox("インターネット無料", value=False, key='mnet')
            with col_m9:
                m_auto = st.checkbox("オートロック", value=False, key='mauto')
                m_box = st.checkbox("宅配ボックス", value=False, key='mbox')

        filtered_df = df[
            (df['間取りグループ'].isin(map_layouts)) &
            (df['専有面積_m2'] >= map_area[0]) & (df['専有面積_m2'] <= map_area[1]) &
            (df['徒歩分数'] >= map_walk[0]) & (df['徒歩分数'] <= map_walk[1]) &
            (df['築年'] >= map_age[0]) & (df['築年'] <= map_age[1])
        ].copy()
        
        if map_stations: filtered_df = filtered_df[filtered_df['駅名'].isin(map_stations)]
        if map_btype != '指定なし': filtered_df = filtered_df[filtered_df['建物種別_判定用'].str.contains(map_btype, na=False)]
        
        if m_2f: filtered_df = filtered_df[~filtered_df['階建'].str.match(r'^1階/|^1階$|地下', na=False)]
        if m_corner: filtered_df = filtered_df[filtered_df['設備'].str.contains('角住戸|角部屋', na=False) | filtered_df['備考'].str.contains('角住戸|角部屋', na=False)]
        if m_south: filtered_df = filtered_df[filtered_df['設備'].str.contains('南向き', na=False) | filtered_df['備考'].str.contains('南向き', na=False)]
        if m_bt: filtered_df = filtered_df[filtered_df['設備'].str.contains('バストイレ別|バス・トイレ別', na=False)]
        if m_sh: filtered_df = filtered_df[filtered_df['設備'].str.contains('洗面所独立|独立洗面台', na=False)]
        if m_wc: filtered_df = filtered_df[filtered_df['設備'].str.contains('温水洗浄便座', na=False)]
        if m_oidaki: filtered_df = filtered_df[filtered_df['設備'].str.contains('追焚|追い焚き', na=False)]
        if m_sys: filtered_df = filtered_df[filtered_df['設備'].str.contains('システムキッチン', na=False)]
        if m_dry: filtered_df = filtered_df[filtered_df['設備'].str.contains('浴室乾燥', na=False)]
        if m_net: filtered_df = filtered_df[filtered_df['設備'].str.contains('ネット無料|インターネット無料', na=False)]
        if m_auto: filtered_df = filtered_df[filtered_df['設備'].str.contains('オートロック', na=False)]
        if m_box: filtered_df = filtered_df[filtered_df['設備'].str.contains('宅配ボックス', na=False)]

        st.info(f"💡 条件に一致する物件: {len(filtered_df)} 件")
        
        if not filtered_df.empty:
            st.markdown("### 📊 町丁目エリア別の平均相場＆ボリュームゾーン")
            
            def calc_price_vz(x):
                if len(x) < 3: return "-"
                return f"{(x.quantile(0.333)/10000):.1f} 〜 {(x.quantile(0.667)/10000):.1f}"
                
            def calc_tanka_vz(x):
                if len(x) < 3: return "-"
                return f"{int(x.quantile(0.333)):,} 〜 {int(x.quantile(0.667)):,}"

            area_stats = filtered_df.groupby('住所').agg(
                物件数=('物件名', 'count'),
                平均価格_万円=(rent_col_map, lambda x: x.mean() / 10000),
                価格ボリューム帯_万円=(rent_col_map, calc_price_vz),
                平均平米単価_円=(tanka_col_map, 'mean'),
                単価ボリューム帯_円=(tanka_col_map, calc_tanka_vz),
                平均専有面積_m2=('専有面積_m2', 'mean'),
                平均築年数_年=('築年', 'mean'),
                平均駅徒歩_分=('徒歩分数', 'mean')
            ).reset_index()
            
            area_stats = area_stats.rename(columns={'平均平米単価_円': '平均㎡単価_円'})
            area_stats = area_stats.sort_values('平均㎡単価_円', ascending=False)
            
            try:
                styled_stats = area_stats.style.background_gradient(
                    cmap='coolwarm',
                    subset=['平均㎡単価_円']
                ).format({
                    "平均価格_万円": "{:.1f}",
                    "平均㎡単価_円": "{:,.0f}",
                    "平均専有面積_m2": "{:.1f}",
                    "平均築年数_年": "{:.1f}",
                    "平均駅徒歩_分": "{:.1f}"
                })
                st.dataframe(styled_stats, use_container_width=True, height=400)
            except ImportError:
                styled_stats = area_stats.style.format({
                    "平均価格_万円": "{:.1f}",
                    "平均㎡単価_円": "{:,.0f}",
                    "平均専有面積_m2": "{:.1f}",
                    "平均築年数_年": "{:.1f}",
                    "平均駅徒歩_分": "{:.1f}"
                })
                st.dataframe(styled_stats, use_container_width=True, height=400)

            st.markdown("<br><hr>", unsafe_allow_html=True)
            st.markdown("### 📋 指定エリアの物件詳細リスト")
            
            selected_area_for_list = st.selectbox("詳細を確認したい町丁目を選択してください", ['すべて表示'] + list(area_stats['住所']))
            
            if selected_area_for_list == 'すべて表示':
                display_df = filtered_df.copy()
            else:
                display_df = filtered_df[filtered_df['住所'] == selected_area_for_list].copy()
            
            url_cols = [c for c in display_df.columns if 'URL' in str(c).upper() or 'リンク' in str(c)]
            if url_cols and 'URL' not in display_df.columns:
                display_df = display_df.rename(columns={url_cols[0]: 'URL'})
            
            display_df = display_df.sort_values(rent_col_map)
            
            display_df_clean = display_df.copy()
            price_col_label = '総家賃(万円)' if rent_col_map == '総家賃' else '家賃(万円)'
            
            if rent_col_map in display_df_clean.columns:
                display_df_clean[price_col_label] = (display_df_clean[rent_col_map] / 10000).round(1)
            if tanka_col_map in display_df_clean.columns:
                display_df_clean['㎡単価(円)'] = display_df_clean[tanka_col_map].astype(int).apply(lambda x: f"{x:,}")
            
            final_cols = ['物件名', 'URL', '住所', '間取り', '専有面積_m2', price_col_label, '㎡単価(円)', '階建', '築年', '徒歩分数']
            valid_final_cols = [c for c in final_cols if c in display_df_clean.columns]
            
            display_df_view = display_df_clean[valid_final_cols].copy()
            
            col_config = {}
            if "URL" in valid_final_cols:
                display_df_view['URL'] = display_df_view['URL'].fillna("")
                col_config["URL"] = st.column_config.LinkColumn("物件リンク", display_text="🔗 詳細を見る")
                
            st.dataframe(
                display_df_view,
                column_config=col_config,
                use_container_width=True
            )

            st.markdown("<br>#### 🕵️ リンク切れ対策：物件の詳細カルテ", unsafe_allow_html=True)
            st.write("※SUUMOの掲載が終了してURLが見られなくなっても、取得時の全データをここで確認・ダウンロードできます。")
            
            display_df['セレクト用ラベル'] = display_df['物件名'] + "（" + display_df['階建'].astype(str) + " / " + display_df[rent_col_map].astype(str) + "円）"
            prop_options = ["選択してください"] + display_df['セレクト用ラベル'].tolist()
            
            col_d1, col_d2 = st.columns([2, 1])
            with col_d1:
                selected_prop_label = st.selectbox("詳細を確認したい物件を上のリストから選んでください", prop_options)
            with col_d2:
                buffer_area = io.BytesIO()
                with pd.ExcelWriter(buffer_area, engine='xlsxwriter') as writer:
                    display_df.drop(columns=['セレクト用ラベル']).to_excel(writer, index=False)
                st.download_button(
                    label="📥 表示中リストの【全項目データ】をExcel保存",
                    data=buffer_area.getvalue(),
                    file_name=f"suumo_detail_{selected_area_for_list}.xlsx",
                    mime="application/vnd.ms-excel"
                )
                
            if selected_prop_label != "選択してください":
                prop_data = display_df[display_df['セレクト用ラベル'] == selected_prop_label].iloc[0]
                
                st.markdown(f"<div style='background-color:#f8f9fa; padding:20px; border-radius:10px; border: 1px solid #ddd;'>", unsafe_allow_html=True)
                st.markdown(f"<h5 style='color:#0066cc;'>🏢 {prop_data.get('物件名', '不明')}</h5>", unsafe_allow_html=True)
                
                c1, c2, c3 = st.columns(3)
                with c1:
                    st.markdown(f"**💰 家賃 / 共益費:**<br>{prop_data.get('家賃', '-')} / {prop_data.get('共益費', '-')}", unsafe_allow_html=True)
                    st.markdown(f"**🪙 敷金 / 礼金:**<br>{prop_data.get('敷金', '-')} / {prop_data.get('礼金', '-')}", unsafe_allow_html=True)
                    st.markdown(f"**📐 間取り / 面積:**<br>{prop_data.get('間取り', '-')} / {prop_data.get('専有面積', '-')}", unsafe_allow_html=True)
                with c2:
                    st.markdown(f"**🏢 構造 / 階建:**<br>{prop_data.get('構造', '-')} / {prop_data.get('階建', '-')}", unsafe_allow_html=True)
                    st.markdown(f"**📅 築年月 / 入居:**<br>{prop_data.get('築年月', '-')} / {prop_data.get('入居時期', '-')}", unsafe_allow_html=True)
                    st.markdown(f"**🚉 最寄駅:**<br>{prop_data.get('最寄駅1', '-')}", unsafe_allow_html=True)
                with c3:
                    st.markdown(f"**🤝 態様 / 条件:**<br>{prop_data.get('態様', '-')} / {prop_data.get('条件', '-')}", unsafe_allow_html=True)
                    st.markdown(f"**🏪 取扱店舗:**<br>{prop_data.get('店舗', '-')}", unsafe_allow_html=True)
                    st.markdown(f"**🔄 情報更新日:**<br>{prop_data.get('情報更新日', '-')}", unsafe_allow_html=True)
                    
                st.markdown("---")
                st.markdown(f"**🛁 設備:**<br><span style='color:#555;'>{prop_data.get('設備', '-')}</span>", unsafe_allow_html=True)
                st.markdown(f"**📝 備考:**<br><span style='color:#555;'>{prop_data.get('備考', '-')}</span>", unsafe_allow_html=True)
                st.markdown("</div>", unsafe_allow_html=True)