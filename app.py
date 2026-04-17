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
def analyze_real_estate_data(suumo_file, rules_file):
    """
    1. ルールCSVから、加減算の係数を直接読み込む（再計算しない）
    2. SUUMOデータ(Excel/CSV)から、ベースとなる㎡単価と相場帯のみを算出する
    """
    # ---------------------------------------------------------
    # ① ルールCSVから係数を抽出（ユーザーがアップロードした数値をそのまま使う）
    # ---------------------------------------------------------
    df_rules = pd.read_csv(rules_file)
    extracted_rules = {}
    madori_list = ['ワンルーム', '1K・1DK', '1LDK', '2K・2DK', '2LDK', '3K・3DK', '3LDK']
    
    for madori in madori_list:
        rule_dict = {}
        if madori in df_rules.columns:
            for idx, row in df_rules.iterrows():
                item_name = str(row.iloc[0]).strip() # A列の項目名（「オートロック」など）を取得
                val = row[madori]
                # 欠損値やハイフンでなければ数値に変換して辞書に格納
                if pd.notna(val) and str(val).strip() != '-':
                    try:
                        rule_dict[item_name] = float(val)
                    except ValueError:
                        pass
        extracted_rules[madori] = rule_dict

    # ---------------------------------------------------------
    # ② SUUMOデータから相場帯（ベース単価・ボリュームゾーン）を算出
    # ---------------------------------------------------------
    try:
        df_suumo = pd.read_excel(suumo_file)
    except Exception:
        df_suumo = pd.read_csv(suumo_file)

    if '家賃' not in df_suumo.columns and '賃料' not in df_suumo.columns:
        st.error("❌ エラー: SUUMOデータ側に「家賃」の列が見つかりません。ファイルを選択する枠が逆になっていないか確認してください。")
        st.stop()

    # 家賃と共益費の合算
    rent_col = '家賃' if '家賃' in df_suumo.columns else '賃料'
    df_suumo['家賃_円'] = df_suumo[rent_col].astype(str).str.extract(r'([\d\.]+)').astype(float) * 10000
    
    if '共益費' in df_suumo.columns:
        df_suumo['共益費_円'] = df_suumo['共益費'].astype(str).replace('-', '0').str.extract(r'([\d\.]+)').astype(float).fillna(0)
    elif '管理費' in df_suumo.columns:
        df_suumo['共益費_円'] = df_suumo['管理費'].astype(str).replace('-', '0').str.extract(r'([\d\.]+)').astype(float).fillna(0)
    else:
        df_suumo['共益費_円'] = 0

    df_suumo.loc[df_suumo['共益費_円'] < 100, '共益費_円'] = df_suumo['共益費_円'] * 10000
    df_suumo['総家賃'] = df_suumo['家賃_円'] + df_suumo['共益費_円']

    # 専有面積と㎡単価
    area_col = '専有面積' if '専有面積' in df_suumo.columns else '面積' if '面積' in df_suumo.columns else None
    if area_col:
        df_suumo['専有面積_m2'] = df_suumo[area_col].astype(str).str.extract(r'([\d\.]+)').astype(float)
    else:
        df_suumo['専有面積_m2'] = 25.0 # 安全対策のデフォルト

    df_suumo['㎡単価'] = df_suumo['総家賃'] / df_suumo['専有面積_m2']

    # 間取りのグルーピング
    madori_col = '間取り' if '間取り' in df_suumo.columns else '間取' if '間取' in df_suumo.columns else None
    def map_madori(m):
        m = str(m).upper().replace(' ', '').replace('　', '') 
        import unicodedata
        m = unicodedata.normalize('NFKC', m) 
        
        if '1R' in m or 'ワンルーム' in m: return 'ワンルーム'
        if m in ['1K', '1DK', '1SK', '1SDK']: return '1K・1DK'
        if m in ['1LDK', '1SLDK']: return '1LDK'
        if m in ['2K', '2DK', '2SK', '2SDK']: return '2K・2DK'
        if m in ['2LDK', '2SLDK']: return '2LDK'
        if m in ['3K', '3DK', '3SK', '3SDK']: return '3K・3DK'
        if '3LDK' in m or '4' in m or '5' in m: return '3LDK'
        return 'その他'
    
    if madori_col:
        df_suumo['間取りグループ'] = df_suumo[madori_col].apply(map_madori)
    else:
        df_suumo['間取りグループ'] = '1K・1DK'

    # 間取りごとのベース単価と相場分布を計算
    base_tanka_dict = {}
    market_stats = {}

    for madori in madori_list:
        df_m = df_suumo[df_suumo['間取りグループ'] == madori]
        tanka_series = df_m['㎡単価'].dropna()
        
        # データが1件以上あれば相場を算出、なければデフォルト値
        if len(tanka_series) > 0:
            base_tanka_dict[madori] = tanka_series.median()
            market_stats[madori] = {
                'min_tanka': tanka_series.min(),
                'max_tanka': tanka_series.max(),
                'p33_tanka': tanka_series.quantile(0.333),
                'p67_tanka': tanka_series.quantile(0.667)
            }
        else:
            base_tanka_dict[madori] = 4000 # デフォルト相場
            market_stats[madori] = None

    return extracted_rules, base_tanka_dict, market_stats

# =========================================================
# 3. UIロジック
# =========================================================
tab1, tab2 = st.tabs(["📂 ①データのアップロード＆解析", "🤖 ②詳細査定シミュレーター"])

# ---------------------------------------------------------
# TAB 1: アップロード画面
# ---------------------------------------------------------
with tab1:
    st.write("当該エリアのSUUMO物件一覧エクセルと、ルールフォーマットCSVをアップロードしてください。")
    st.write("※ルールCSVに記載された加減算金額が、そのままシミュレーターの設備に反映されます。")
    
    colA, colB = st.columns(2)
    with colA:
        uploaded_suumo = st.file_uploader("SUUMO物件データ (Excel/CSV)", type=["xlsx", "csv"])
    with colB:
        uploaded_rules = st.file_uploader("ルールフォーマット (CSV)", type=["csv"])

    if uploaded_suumo is not None and uploaded_rules is not None:
        with st.spinner("データを解析してエリアの相場・ルールを構築しています..."):
            extracted_rules, base_tanka_dict, market_stats = analyze_real_estate_data(uploaded_suumo, uploaded_rules)
            
            st.session_state['rules'] = extracted_rules
            st.session_state['base_tanka'] = base_tanka_dict
            st.session_state['market_stats'] = market_stats
            
            st.success("✅ データの解析が完了しました！「②詳細査定シミュレーター」タブに移動して査定を行ってください。")

# ---------------------------------------------------------
# TAB 2: シミュレーター画面
# ---------------------------------------------------------
with tab2:
    if 'rules' not in st.session_state:
        st.warning("⚠️ 先に「①データのアップロード＆解析」タブでファイルを取り込んでください。")
    else:
        st.subheader("🤖 詳細査定シミュレーター")
        st.write("アップロードしたルールCSVの係数に基づき、適正な賃料を算出します。")
        
        rules = st.session_state['rules']
        bases = st.session_state['base_tanka']
        stats = st.session_state['market_stats']

        # 全ての間取りを選択可能にする
        valid_layouts = list(rules.keys())
        
        col1, col2, col3, col4 = st.columns(4)
        with col1: target_layout = st.selectbox("間取りタイプ", valid_layouts, index=1) # デフォルトを1Kに
        with col2: i_area = st.number_input("専有面積 (㎡)", min_value=10.0, max_value=200.0, value=25.0, step=0.5)
        with col3: i_age = st.number_input("築年数 (年) ※新築は0", min_value=0, max_value=100, value=5)
        with col4: i_walk = st.number_input("駅徒歩 (分)", min_value=0, max_value=60, value=8)

        st.markdown("**付加価値・設備条件（チェックで査定額に反映されます）**")
        col5, col6, col7, col8 = st.columns(4)
        with col5:
            i_2f = st.checkbox("2階以上", value=True)
            i_corner = st.checkbox("角部屋", value=False)
            i_south = st.checkbox("南向き", value=False)
        with col6:
            i_bt = st.checkbox("バス・トイレ別", value=True)
            i_sh = st.checkbox("洗面所独立", value=False)
            i_wc = st.checkbox("温水洗浄便座", value=False)
        with col7:
            i_sys = st.checkbox("システムキッチン", value=False)
            i_dry = st.checkbox("浴室乾燥機", value=False)
            i_net = st.checkbox("インターネット無料", value=False)
        with col8:
            i_auto = st.checkbox("オートロック", value=True)
            i_box = st.checkbox("宅配ボックス", value=False)
            i_premium = st.number_input("その他・手動プレミアム (円)", value=0, step=1000)

        # 辞書のキーと、画面上のラベルを一致させる
        selected_features = {
            '2階以上': i_2f, '角部屋': i_corner, '南向き': i_south,
            'バス・トイレ別': i_bt, '洗面所独立': i_sh, '温水洗浄便座': i_wc,
            'システムキッチン': i_sys, '浴室乾燥機': i_dry, 'インターネット無料': i_net,
            'オートロック': i_auto, '宅配ボックス': i_box
        }

        # ==========================================
        # 査定計算ロジック
        # ==========================================
        # アップロードされたCSVから該当間取りのルールを取得
        r = rules.get(target_layout, {})
        
        # 1. ハコ自体の家賃（ベース単価 × 面積）
        tanka_base = bases.get(target_layout, 4000)
        rent_base = tanka_base * i_area
        
        # 2. 設備や条件による加点・減点の計算
        rent_rules = 0
        
        # ⚠️修正箇所：徒歩分数の加減算（10分以内も加味する）
        tanka_under_10 = r.get('徒歩10分以内単価', 0)
        tanka_over_10 = r.get('徒歩10分超追加単価', 0)
        fixed_penalty = r.get('徒歩10分超固定ペナルティ', 0)

        if i_walk <= 10:
            # 10分以内の場合： (徒歩分数 × 徒歩10分以内単価) × 面積
            rent_rules += (i_walk * tanka_under_10) * i_area
        else:
            # 10分超の場合： まず10分までの影響を加算
            rent_rules += (10 * tanka_under_10) * i_area
            # 10分超えの固定ペナルティを加算（これは「固定」なので面積を掛けない）
            rent_rules += fixed_penalty
            # 10分を超えた1分ごとの影響を加算
            rent_rules += ((i_walk - 10) * tanka_over_10) * i_area
        
        # 築年ペナルティ
        if i_age == 0: rent_rules += r.get('築年_新築単価', 0) * i_area
        elif 1 <= i_age <= 3: rent_rules += r.get('築年_1_3年単価', 0) * i_area
        elif 4 <= i_age <= 6: rent_rules += r.get('築年_4_6年単価', 0) * i_area
        elif 7 <= i_age <= 10: rent_rules += r.get('築年_7_10年単価', 0) * i_area
        
        # 設備の加点・減点
        for feat_name, is_checked in selected_features.items():
            if is_checked:
                # 該当設備の係数を取得し、面積を掛けて家賃に反映する
                feat_tanka = r.get(feat_name, 0)
                rent_rules += feat_tanka * i_area
        
        # 3. 最終的な推定家賃
        predicted_rent = rent_base + rent_rules + i_premium

        # ==========================================
        # 結果表示
        # ==========================================
        st.markdown(
            f"""
            <div style="background-color:#e8f4f8;padding:20px;border-radius:10px;text-align:center;margin-top:20px;">
                <h3 style="margin:0;color:#333;">設備・条件を反映した推定家賃</h3>
                <h1 style="margin:0;color:#0066cc;font-size:48px;">{int(predicted_rent):,} 円</h1>
                <p style="color:#666; margin:0;">
                (エリアベース相場: {int(rent_base):,}円 ＋ 設備・条件加点/減点: {int(rent_rules):,}円 ＋ 手動調整: {i_premium}円)
                </p>
            </div>
            """, 
            unsafe_allow_html=True
        )

        st.markdown("<br><hr>", unsafe_allow_html=True)
        st.subheader(f"📈 面積 {i_area}㎡ の箱に対する、当該エリアの純粋な相場帯")
        st.caption("※設備や徒歩分数を一切考慮せず、同じ間取り・同じ広さの物件が市場でどう分布しているかを示します。")

        layout_stats = stats.get(target_layout)
        if layout_stats:
            price_min = int(layout_stats['min_tanka'] * i_area)
            price_max = int(layout_stats['max_tanka'] * i_area)
            zone_low = int(layout_stats['p33_tanka'] * i_area)
            zone_high = int(layout_stats['p67_tanka'] * i_area)

            colA, colB, colC = st.columns(3)
            with colA:
                st.metric(label="最低価格目安", value=f"{price_min:,} 円")
            with colB:
                st.metric(label="ボリュームゾーン (中核33%)", value=f"{zone_low:,} 〜 {zone_high:,} 円", delta="市場の中心帯")
            with colC:
                st.metric(label="最高価格目安", value=f"{price_max:,} 円")

            st.caption(f"▼ 今回の推定家賃（{int(predicted_rent):,}円）が、市場全体のどの位置にいるかの目安")
            if price_max > price_min:
                progress_val = (predicted_rent - price_min) / (price_max - price_min)
                st.progress(min(1.0, max(0.0, progress_val)))
            else:
                st.progress(0.5)
        else:
            st.info("この間取りはSUUMOデータに存在しなかったため、相場分布のメーターは表示されません。")