import pandas as pd
import numpy as np
import re
import requests
from bs4 import BeautifulSoup
import time
import random
import streamlit as st
import io

# =========================================================
# 1. ページ設定
# =========================================================
st.set_page_config(page_title="不動産ハイブリッド査定システム", layout="wide")
st.title("🏡 不動産ハイブリッド査定システム (AI × プロの相場観)")

# =========================================================
# 2. スクレイピングエンジン (SUUMO一覧ページから直接取得)
# =========================================================
def scrape_suumo_list(base_url, max_pages=3):
    """
    SUUMOの検索結果URLから、指定したページ数分の物件情報をスクレイピングする
    ロボット検知を避けるためのステルス機能を実装
    """
    all_data = []
    
    # 💡強化ポイント: 人間のブラウザ（最新のChrome）を完全に偽装
    session = requests.Session()
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'ja,en-US;q=0.9,en;q=0.8',
        'Referer': 'https://suumo.jp/',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1'
    }
    
    # ページネーションパラメータの整理
    base_url = re.sub(r'&page=\d+', '', base_url)
    base_url = re.sub(r'&pn=\d+', '', base_url)
    separator = '&' if '?' in base_url else '?'
    
    progress_bar = st.progress(0)
    status_text = st.empty()

    for page in range(1, max_pages + 1):
        status_text.text(f"SUUMOからデータを取得中... (ページ {page}/{max_pages})")
        
        # SUUMOのURLパターンに対応（pageとpnの両方を付与して安全にめくる）
        url = f"{base_url}{separator}page={page}&pn={page}"
        
        try:
            # 💡強化ポイント: 機械的なアクセスと判定されないよう、1.5〜3.5秒のランダムな待機時間を入れる
            time.sleep(random.uniform(1.5, 3.5))
            
            res = session.get(url, headers=headers, timeout=15)
            res.raise_for_status() 
            
            # 文字化け対策として .text ではなく .content をパースする
            soup = BeautifulSoup(res.content, 'html.parser')
            items = soup.find_all("div", class_="cassetteitem")
            
            if not items:
                st.warning(f"⚠️ ページ {page} から物件データを抽出できませんでした。データが終了したか、SUUMOにロボットとして検知された可能性があります。")
                # 💡強化ポイント: ブロックされた原因を探るためのデバッグ画面
                with st.expander("開発用：サーバーからの返答内容を確認する"):
                    st.write(f"HTTPステータスコード: {res.status_code}")
                    st.code(res.text[:1500]) # 返ってきたHTMLの先頭1500文字を表示
                break
            
            for item in items:
                # 物件の基本情報
                title_elem = item.find("div", class_="cassetteitem_content-title")
                title = title_elem.text.strip() if title_elem else ""
                
                # マンション・アパートの取得
                b_type_elem = item.find("div", class_="cassetteitem_content-label")
                b_type_raw = b_type_elem.text.strip() if b_type_elem else ""
                if "アパート" in b_type_raw: b_type = "アパート"
                elif "マンション" in b_type_raw: b_type = "マンション"
                else: b_type = "その他"
                
                address_elem = item.find("li", class_="cassetteitem_detail-col1")
                address = address_elem.text.strip() if address_elem else ""
                
                # 駅・沿線情報の取得
                stations = item.find_all("div", class_="cassetteitem_detail-text")
                sta1 = stations[0].text.strip() if len(stations) > 0 else ""
                sta2 = stations[1].text.strip() if len(stations) > 1 else ""
                sta3 = stations[2].text.strip() if len(stations) > 2 else ""
                
                col3 = item.find("li", class_="cassetteitem_detail-col3")
                col3_divs = col3.find_all("div") if col3 else []
                age = col3_divs[0].text.strip() if len(col3_divs) > 0 else ""
                floors = col3_divs[1].text.strip() if len(col3_divs) > 1 else ""
                
                # 部屋ごとの情報
                tbodies = item.find_all("tbody")
                for tbody in tbodies:
                    rent = tbody.find("span", class_="cassetteitem_price cassetteitem_price--rent")
                    admin = tbody.find("span", class_="cassetteitem_price cassetteitem_price--administration")
                    deposit = tbody.find("span", class_="cassetteitem_price cassetteitem_price--deposit")
                    gratuity = tbody.find("span", class_="cassetteitem_price cassetteitem_price--gratuity")
                    layout = tbody.find("span", class_="cassetteitem_madori")
                    area = tbody.find("span", class_="cassetteitem_menseki")
                    
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
                        "階建": floors
                    })
            
            progress_bar.progress(page / max_pages)
            
        except Exception as e:
            st.error(f"スクレイピング中にエラーが発生しました: {e}")
            break
            
    progress_bar.empty()
    status_text.empty()
    return pd.DataFrame(all_data)

# =========================================================
# 3. 前処理・データ読み込みエンジン
# =========================================================
@st.cache_data
def analyze_real_estate_data_v7(raw_df, rules_file):
    """
    スクレイピングしたDF、またはアップロードしたDFを受け取り、
    ルールCSVと掛け合わせて分析可能な状態にクレンジングする
    """
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

    # 家賃と共益費の計算
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

    # 徒歩分数の抽出
    walk_col = next((c for c in df_suumo.columns if str(c) in ['最寄駅1', '駅1', '徒歩1', '徒歩']), None)
    if walk_col:
        df_suumo['徒歩分数'] = df_suumo[walk_col].astype(str).str.extract(r'(?:歩|徒歩)(\d+)分').astype(float).fillna(10)
    else:
        df_suumo['徒歩分数'] = 10

    # 築年数
    age_col = next((c for c in df_suumo.columns if '築' in str(c) or '数' in str(c)), None)
    if age_col:
        df_suumo['築年'] = df_suumo[age_col].apply(lambda x: 0 if '新築' in str(x) else float(re.search(r'\d+', str(x)).group()) if pd.notna(x) and re.search(r'\d+', str(x)) else 0)
    else:
        df_suumo['築年'] = 0

    # 間取り
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

    # 建物種別
    type_col = next((c for c in df_suumo.columns if '建物種別' in str(c) or '種別' in str(c)), None)
    if type_col:
        df_suumo['建物種別_判定用'] = df_suumo[type_col].astype(str)
    else:
        text_cols = df_suumo.select_dtypes(include=[object]).fillna('').agg(' '.join, axis=1)
        df_suumo['建物種別_判定用'] = text_cols

    # 駅名の抽出
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
tab1, tab2 = st.tabs(["📂 ①データの取得＆解析 (スクレイピング対応)", "🤖 ②詳細査定シミュレーター"])

# ---------------------------------------------------------
# TAB 1: アップロード / スクレイピング画面
# ---------------------------------------------------------
with tab1:
    st.write("「SUUMOから自動取得」または「お手元のExcelファイルアップロード」のどちらかを選択してください。")
    
    data_source = st.radio("データソースの選択", ["🌐 SUUMOのURLから自動取得 (スクレイピング)", "📁 エクセル/CSVファイルをアップロード"])
    
    df_raw = None
    
    if data_source == "🌐 SUUMOのURLから自動取得 (スクレイピング)":
        target_url = st.text_input("SUUMOの検索結果URLを貼り付けてください", placeholder="https://suumo.jp/jj/chintai/ichiran/...")
        max_pages = st.number_input("取得する最大ページ数", min_value=1, max_value=20, value=3)
        
        if st.button("🚀 データを取得する"):
            if target_url:
                with st.spinner("SUUMOから物件データを自動収集しています。しばらくお待ちください..."):
                    scraped_df = scrape_suumo_list(target_url, max_pages)
                    if not scraped_df.empty:
                        st.session_state['raw_df'] = scraped_df
                        st.success(f"✅ {len(scraped_df)}件の物件データを取得しました！")
                    else:
                        st.error("データの取得に失敗しました。URLが正しいか確認してください。")
            else:
                st.warning("URLを入力してください。")
                
        # 取得済みデータの表示とダウンロード
        if 'raw_df' in st.session_state:
            st.write("取得したデータプレビュー:")
            st.dataframe(st.session_state['raw_df'].head())
            df_raw = st.session_state['raw_df']
            
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                df_raw.to_excel(writer, index=False)
            st.download_button(label="📥 取得したデータをExcelで保存", data=buffer.getvalue(), file_name="suumo_scraped_data.xlsx", mime="application/vnd.ms-excel")

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
                extracted_rules, df_suumo = analyze_real_estate_data_v7(df_raw, uploaded_rules)
                
                st.session_state['rules'] = extracted_rules
                st.session_state['df_suumo'] = df_suumo
                
                st.success("✅ 解析完了！「②詳細査定シミュレーター」タブへお進みください。")

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

        # ==========================================
        # ベース相場の取得
        # ==========================================
        mask_base = (df_suumo['間取りグループ'] == target_layout)
        
        if selected_station != '指定なし':
            mask_base &= (df_suumo['駅名'] == selected_station)

        if i_btype == 'マンション':
            mask_base &= df_suumo['建物種別_判定用'].str.contains('マンション', na=False)
        elif i_btype == 'アパート':
            mask_base &= df_suumo['建物種別_判定用'].str.contains('アパート', na=False)

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

        # ==========================================
        # 計算ロジック
        # ==========================================
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

        # ==========================================
        # 画面下部統計と上限キャップ
        # ==========================================
        station_label = "当該エリア全体" if selected_station == '指定なし' else f"{selected_station}駅周辺"
        if i_btype != '指定なし':
            station_label += f"（{i_btype}）"
            
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

        # ==========================================
        # 結果表示
        # ==========================================
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
        st.caption(f"※設備等を一切考慮せず、同じ間取り・同じ広さの{i_btype}が市場でどう分布しているかを示します。")

        if data_count > 0:
            colA, colB, colC = st.columns(3)
            with colA:
                st.metric(label="最低価格目安", value=f"{price_min:,} 円")
            with colB:
                st.metric(label="ボリュームゾーン (中核33%)", value=f"{zone_low:,} 〜 {zone_high:,} 円", delta="市場の中心帯")
            with colC:
                st.metric(label="最高価格目安", value=f"{price_max:,} 円")

            st.caption(f"▼ 今回の推定家賃（{display_rent:,}円）が、市場全体のどの位置にいるかの目安")
            if price_max > price_min:
                progress_val = (display_rent - price_min) / (price_max - price_min)
                st.progress(min(1.0, max(0.0, progress_val)))
            else:
                st.progress(0.5)
        else:
            st.info("条件に一致するデータがないため、相場分布のメーターは表示されません。")