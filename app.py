import pandas as pd
import numpy as np
import re
import streamlit as st

# =========================================================
# 1. ページ設定
# =========================================================
st.set_page_config(page_title="不動産ハイブリッド査定システム", layout="wide")
st.title("🏡 不動産ハイブリッド査定システム (AI × プロの相場観)")

# =========================================================
# 2. 前処理・データ読み込みエンジン
# =========================================================
@st.cache_data
def analyze_real_estate_data_v4(suumo_file, rules_file):
    """
    どんな形式の不動産データ（列名違い）でも自動で項目を探し出し、
    駅ごとの相場や面積単価を算出する強力なエンジン
    """
    # ---------------------------------------------------------
    # ① ルールCSVから係数を抽出
    # ---------------------------------------------------------
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

    # ---------------------------------------------------------
    # ② SUUMOデータをクレンジング（どんな列名でも対応）
    # ---------------------------------------------------------
    try:
        df_suumo = pd.read_excel(suumo_file)
    except Exception:
        df_suumo = pd.read_csv(suumo_file)

    # --- 家賃 ---
    rent_col = next((c for c in df_suumo.columns if '家賃' in str(c) or '賃料' in str(c)), None)
    if not rent_col:
        st.error("❌ エラー: データに「家賃」または「賃料」の列が見つかりません。")
        st.stop()
    df_suumo['家賃_円'] = df_suumo[rent_col].astype(str).str.extract(r'([\d\.]+)').astype(float) * 10000
    
    # --- 管理費・共益費 ---
    kyoeki_col = next((c for c in df_suumo.columns if '共益費' in str(c) or '管理費' in str(c)), None)
    if kyoeki_col:
        df_suumo['共益費_円'] = df_suumo[kyoeki_col].astype(str).replace('-', '0').str.extract(r'([\d\.]+)').astype(float).fillna(0)
    else:
        df_suumo['共益費_円'] = 0

    df_suumo.loc[df_suumo['共益費_円'] < 100, '共益費_円'] = df_suumo['共益費_円'] * 10000
    df_suumo['総家賃'] = df_suumo['家賃_円'] + df_suumo['共益費_円']

    # --- 専有面積 ---
    area_col = next((c for c in df_suumo.columns if '面積' in str(c)), None)
    if area_col:
        df_suumo['専有面積_m2'] = df_suumo[area_col].astype(str).str.extract(r'([\d\.]+)').astype(float)
    else:
        df_suumo['専有面積_m2'] = 25.0

    df_suumo['㎡単価'] = df_suumo['総家賃'] / df_suumo['専有面積_m2']

    # --- 徒歩分数 ---
    walk_col = next((c for c in df_suumo.columns if str(c) in ['徒歩1', '徒歩', '歩']), None)
    if walk_col:
        df_suumo['徒歩分数'] = df_suumo[walk_col].astype(str).str.extract(r'(\d+)').astype(float).fillna(10)
    else:
        station_info_col = next((c for c in df_suumo.columns if '駅' in str(c)), None)
        if station_info_col:
            df_suumo['徒歩分数'] = df_suumo[station_info_col].astype(str).str.extract(r'(?:歩|徒歩)(\d+)分').astype(float).fillna(10)
        else:
            df_suumo['徒歩分数'] = 10

    # --- 築年数 ---
    age_col = next((c for c in df_suumo.columns if '築' in str(c) or '数' in str(c)), None)
    if age_col:
        df_suumo['築年'] = df_suumo[age_col].apply(lambda x: 0 if '新築' in str(x) else float(re.search(r'\d+', str(x)).group()) if pd.notna(x) and re.search(r'\d+', str(x)) else 0)
    else:
        df_suumo['築年'] = 0

    # --- 間取り ---
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
    
    if madori_col:
        df_suumo['間取りグループ'] = df_suumo[madori_col].apply(map_madori)
    else:
        df_suumo['間取りグループ'] = '1K・1DK'

    # ---------------------------------------------------------
    # ③ 駅名の超強力な自動抽出
    # ---------------------------------------------------------
    target_station_cols = ['駅1', '最寄駅1', '駅', '最寄駅']
    station_col = None
    for c in target_station_cols:
        if c in df_suumo.columns:
            station_col = c
            break
            
    if not station_col:
        for col in df_suumo.columns:
            col_str = str(col).replace(' ', '').replace('　', '')
            if '駅' in col_str and '沿線' not in col_str:
                if '1' in col_str or '１' in col_str:
                    station_col = col
                    break
                if station_col is None:
                    station_col = col

    def extract_station(text):
        text = str(text).strip()
        if text in ('nan', '', 'None', '-'):
            return '不明'
            
        text = re.split(r'歩|徒歩|バス|車', text)[0].strip()
        parts = re.split(r'[/ 　]+', text)
        
        station_name = ""
        for part in reversed(parts):
            if '駅' in part:
                station_name = part.replace('駅', '')
                break
        
        if not station_name:
            if len(parts) > 1:
                station_name = parts[-1] 
            else:
                station_name = parts[0]
                
        station_name = station_name.strip()
        if station_name.endswith('駅'):
            station_name = station_name[:-1]
        if station_name.endswith('線'):
            return '不明'
            
        return station_name if station_name else '不明'

    if station_col:
        df_suumo['駅名'] = df_suumo[station_col].apply(extract_station)
    else:
        df_suumo['駅名'] = '不明'

    return extracted_rules, df_suumo

# =========================================================
# 3. UIロジック
# =========================================================
tab1, tab2 = st.tabs(["📂 ①データのアップロード＆解析", "🤖 ②詳細査定シミュレーター"])

# ---------------------------------------------------------
# TAB 1: アップロード画面
# ---------------------------------------------------------
with tab1:
    st.write("当該エリアのSUUMO物件一覧エクセルと、ルールフォーマットCSVをアップロードしてください。")
    
    colA, colB = st.columns(2)
    with colA:
        uploaded_suumo = st.file_uploader("SUUMO物件データ (Excel/CSV)", type=["xlsx", "csv"])
    with colB:
        uploaded_rules = st.file_uploader("ルールフォーマット (CSV)", type=["csv"])

    if uploaded_suumo is not None and uploaded_rules is not None:
        with st.spinner("データを解析し、駅ごとの相場とルールを構築しています..."):
            extracted_rules, df_suumo = analyze_real_estate_data_v4(uploaded_suumo, uploaded_rules)
            
            st.session_state['rules'] = extracted_rules
            st.session_state['df_suumo'] = df_suumo
            
            st.success("✅ 解析完了！駅名を自動抽出しました。「②詳細査定シミュレーター」タブへお進みください。")

# ---------------------------------------------------------
# TAB 2: シミュレーター画面
# ---------------------------------------------------------
with tab2:
    if 'rules' not in st.session_state:
        st.warning("⚠️ 先に「①データのアップロード＆解析」タブでファイルを取り込んでください。")
    else:
        st.subheader("🤖 詳細査定シミュレーター")
        st.write("アップロードしたデータに基づき、対象駅の相場とルール係数を掛け合わせて適正な賃料を算出します。")
        
        rules = st.session_state['rules']
        df_suumo = st.session_state['df_suumo']

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
        
        # --- 💡追加：建物種別の選択 ---
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
            # --- 💡追加：追い焚き風呂の選択 ---
            i_oidaki = st.checkbox("追い焚き風呂", value=False)
        with col7:
            i_sys = st.checkbox("システムキッチン", value=False)
            i_dry = st.checkbox("浴室乾燥機", value=False)
            i_net = st.checkbox("インターネット無料", value=False)
        with col8:
            i_auto = st.checkbox("オートロック", value=True)
            i_box = st.checkbox("宅配ボックス", value=False)
            i_premium = st.number_input("その他・手動プレミアム (円)", value=0, step=1000)

        # 辞書のキーと画面上の状態を紐付け（ルールCSVの項目名と一致させます）
        selected_features = {
            'マンション': i_btype == 'マンション',
            'アパート': i_btype == 'アパート',
            '2階以上': i_2f, '角部屋': i_corner, '南向き': i_south,
            'バス・トイレ別': i_bt, '洗面所独立': i_sh, '温水洗浄便座': i_wc,
            '追い焚き風呂': i_oidaki,
            'システムキッチン': i_sys, '浴室乾燥機': i_dry, 'インターネット無料': i_net,
            'オートロック': i_auto, '宅配ボックス': i_box
        }

        # ==========================================
        # 査定計算ロジック（駅による相場の絞り込み）
        # ==========================================
        if selected_station == '指定なし':
            df_filtered = df_suumo[df_suumo['間取りグループ'] == target_layout]
            station_label = "当該エリア全体"
        else:
            df_filtered = df_suumo[(df_suumo['間取りグループ'] == target_layout) & (df_suumo['駅名'] == selected_station)]
            station_label = f"{selected_station}駅周辺"

        tanka_series = df_filtered['㎡単価'].dropna()
        data_count = len(tanka_series)
        
        if data_count > 0:
            tanka_base = tanka_series.median()
            layout_stats = {
                'min_tanka': tanka_series.min(),
                'max_tanka': tanka_series.max(),
                'p33_tanka': tanka_series.quantile(0.333),
                'p67_tanka': tanka_series.quantile(0.667)
            }
        else:
            df_all = df_suumo[df_suumo['間取りグループ'] == target_layout]
            tanka_all = df_all['㎡単価'].dropna()
            if len(tanka_all) > 0:
                tanka_base = tanka_all.median()
                st.warning(f"⚠️ 指定された「{selected_station}駅」には「{target_layout}」のデータが存在しないため、ベース家賃はエリア全体の相場を使用しています。")
                layout_stats = None
                data_count = len(tanka_all)
            else:
                tanka_base = 4000
                layout_stats = None
                data_count = 0

        r = rules.get(target_layout, {})
        
        # 1. ハコ自体の家賃
        rent_base = tanka_base * i_area
        
        # 2. 加点・減点の計算
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
        
        # 3. 理論上の推定家賃
        predicted_rent = int(rent_base + rent_rules + i_premium)

        # ==========================================
        # 相場分布の取得と上限（キャップ）処理
        # ==========================================
        display_rent = predicted_rent
        cap_message = "" 

        if layout_stats:
            price_min = int(layout_stats['min_tanka'] * i_area)
            price_max = int(layout_stats['max_tanka'] * i_area)
            zone_low = int(layout_stats['p33_tanka'] * i_area)
            zone_high = int(layout_stats['p67_tanka'] * i_area)

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
                (ベース相場: {int(rent_base):,}円 ＋ 設備加減点: {int(rent_rules):,}円 ＋ 手動調整: {i_premium}円){cap_message}
                </p>
            </div>
            """, 
            unsafe_allow_html=True
        )

        st.markdown("<br><hr>", unsafe_allow_html=True)
        st.subheader(f"📈 面積 {i_area}㎡ の箱に対する、【{station_label}】の純粋な相場帯（データ: {data_count}件）")
        st.caption("※設備等を一切考慮せず、同じ間取り・同じ広さの物件が市場でどう分布しているかを示します。")

        if layout_stats:
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
            st.info("この間取り（または指定された駅）はデータが少なすぎるため、相場分布のメーターは表示されません。")