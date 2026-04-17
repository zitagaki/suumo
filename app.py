import pandas as pd
import numpy as np
import re
from sklearn.linear_model import Ridge
import streamlit as st
import io

# =========================================================
# 1. ページ設定
# =========================================================
st.set_page_config(page_title="不動産ハイブリッド査定システム", layout="wide")
st.title("🏡 不動産ハイブリッド査定システム (AI × プロの相場観)")

# =========================================================
# 2. 前処理・AIルール算出エンジン
# =========================================================
@st.cache_data
def analyze_real_estate_data(suumo_file, rules_file):
    """
    アップロードされたSUUMO(Excel)とrules(CSV)から、
    1. 各間取りのベース単価
    2. 設備や条件による加減算ルール
    を算出する。
    """
    # データの読み込み
    try:
        df_suumo = pd.read_excel(suumo_file)
    except Exception:
        df_suumo = pd.read_csv(suumo_file) # CSVだった場合のフォールバック
        
    df_rules = pd.read_csv(rules_file)

    # ⚠️【追加】アップロード間違い防止のエラーチェック
    if '家賃' not in df_suumo.columns and '賃料' not in df_suumo.columns:
        st.error("❌ エラー: SUUMOデータ側に「家賃」の列が見つかりません。ファイルを選択する枠が逆になっていないか確認してください。")
        st.stop()

    # --- 基本的な数値のクレンジング（安全な取得処理） ---
    # 1. 家賃
    rent_col = '家賃' if '家賃' in df_suumo.columns else '賃料'
    df_suumo['家賃_円'] = df_suumo[rent_col].astype(str).str.extract(r'([\d\.]+)').astype(float) * 10000
    
    # 2. 共益費（列が無い場合や「管理費」になっている場合を吸収）
    if '共益費' in df_suumo.columns:
        df_suumo['共益費_円'] = df_suumo['共益費'].astype(str).replace('-', '0').str.extract(r'([\d\.]+)').astype(float).fillna(0)
    elif '管理費' in df_suumo.columns:
        df_suumo['共益費_円'] = df_suumo['管理費'].astype(str).replace('-', '0').str.extract(r'([\d\.]+)').astype(float).fillna(0)
    else:
        df_suumo['共益費_円'] = 0 # どちらも無い場合は0円とする

    # 万単位表記の共益費がある場合の補正（例: 1.5万 -> 15000）
    df_suumo.loc[df_suumo['共益費_円'] < 100, '共益費_円'] = df_suumo['共益費_円'] * 10000
    df_suumo['総家賃'] = df_suumo['家賃_円'] + df_suumo['共益費_円']

    # 3. 専有面積
    area_col = '専有面積' if '専有面積' in df_suumo.columns else '面積' if '面積' in df_suumo.columns else None
    if area_col:
        df_suumo['専有面積_m2'] = df_suumo[area_col].astype(str).str.extract(r'([\d\.]+)').astype(float)
    else:
        st.error("❌ エラー: データ内に「専有面積」の列が見つかりません。")
        st.stop()

    df_suumo['㎡単価'] = df_suumo['総家賃'] / df_suumo['専有面積_m2']

    # 4. 徒歩分数
    if '最寄駅1' in df_suumo.columns:
        df_suumo['徒歩分数'] = df_suumo['最寄駅1'].astype(str).str.extract(r'歩(\d+)分').astype(float).fillna(10)
    else:
        df_suumo['徒歩分数'] = 10 # 取得できない場合は一律10分とする

    # エクセルによって列名が「築年数」か「数」になる場合への対応
    age_col = '築年数' if '築年数' in df_suumo.columns else '数' if '数' in df_suumo.columns else None
    if age_col:
        df_suumo['築年'] = df_suumo[age_col].apply(lambda x: 0 if '新築' in str(x) else float(re.search(r'\d+', str(x)).group()) if re.search(r'\d+', str(x)) else 0)
    else:
        df_suumo['築年'] = 0

    # 間取りのグルーピング
    madori_col = '間取り' if '間取り' in df_suumo.columns else '間取' if '間取' in df_suumo.columns else None
    def map_madori(m):
        m = str(m)
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
        df_suumo['間取りグループ'] = 'ワンルーム'

    # --- 特徴量（フラグ）の作成 ---
    features = pd.DataFrame(index=df_suumo.index)

    features['徒歩10分以内単価'] = df_suumo['徒歩分数'].apply(lambda x: x if x <= 10 else 10)
    features['徒歩10分超固定ペナルティ'] = df_suumo['徒歩分数'].apply(lambda x: 1 if x > 10 else 0)
    features['徒歩10分超追加単価'] = df_suumo['徒歩分数'].apply(lambda x: x - 10 if x > 10 else 0)

    features['築年_新築単価'] = (df_suumo['築年'] == 0).astype(int)
    features['築年_1_3年単価'] = ((df_suumo['築年'] >= 1) & (df_suumo['築年'] <= 3)).astype(int)
    features['築年_4_6年単価'] = ((df_suumo['築年'] >= 4) & (df_suumo['築年'] <= 6)).astype(int)
    features['築年_7_10年単価'] = ((df_suumo['築年'] >= 7) & (df_suumo['築年'] <= 10)).astype(int)

    if '階建' in df_suumo.columns:
        df_suumo['現在階'] = df_suumo['階建'].astype(str).str.extract(r'(\d+)階/').astype(float)
    elif '階' in df_suumo.columns:
        df_suumo['現在階'] = df_suumo['階'].astype(str).str.extract(r'(\d+)').astype(float)
    else:
        df_suumo['現在階'] = 1

    features['2階以上'] = (df_suumo['現在階'] >= 2).astype(int)

    # 設備情報の安全な取得
    equip_text = df_suumo['設備'].fillna('') if '設備' in df_suumo.columns else ""
    cond_text = df_suumo['条件'].fillna('') if '条件' in df_suumo.columns else ""
    note_text = df_suumo['備考'].fillna('') if '備考' in df_suumo.columns else ""
    df_suumo['text_all'] = equip_text + cond_text + note_text
    
    def check_kwd(keywords):
        return df_suumo['text_all'].str.contains('|'.join(keywords), na=False).astype(int)

    kwd_dict = {
        '角部屋': ['角部屋', '角住戸'], '南向き': ['南向き', '南面'],
        '洗面所独立': ['洗面所独立', '独立洗面'], 'バス・トイレ別': ['バストイレ別', 'バス・トイレ別'],
        '温水洗浄便座': ['温水洗浄便座', 'ウォシュレット'], '浴室乾燥機': ['浴室乾燥機'],
        'システムキッチン': ['システムキッチン'], 'オートロック': ['オートロック'],
        '宅配ボックス': ['宅配ボックス'], 'インターネット無料': ['インターネット無料', 'ネット使用料不要']
    }
    for key, words in kwd_dict.items():
        features[key] = check_kwd(words)

    # --- 回帰分析で係数を算出 ---
    madori_list = ['ワンルーム', '1K・1DK', '1LDK', '2K・2DK', '2LDK', '3K・3DK', '3LDK']
    extracted_rules = {}
    base_tanka_dict = {}
    market_stats = {}

    for madori in madori_list:
        df_m = df_suumo[df_suumo['間取りグループ'] == madori]
        
        if len(df_m) < 10:
            extracted_rules[madori] = {}
            base_tanka_dict[madori] = 0
            market_stats[madori] = None
            continue
        
        # 相場の中央値・パーセンタイルを保存
        tanka_series = df_m['㎡単価'].dropna()
        base_tanka_dict[madori] = tanka_series.median()
        
        market_stats[madori] = {
            'min_tanka': tanka_series.min(),
            'max_tanka': tanka_series.max(),
            'p33_tanka': tanka_series.quantile(0.333),
            'p67_tanka': tanka_series.quantile(0.667)
        }

        y = df_m['㎡単価'].fillna(base_tanka_dict[madori])
        X = features.loc[df_m.index].fillna(0)
        
        model = Ridge(alpha=50.0) 
        model.fit(X, y)
        
        madori_results = dict(zip(X.columns, np.round(model.coef_, 0)))
        mean_area = df_m['専有面積_m2'].mean()
        madori_results['徒歩10分超固定ペナルティ'] = round(madori_results['徒歩10分超固定ペナルティ'] * mean_area, 0)
        
        extracted_rules[madori] = madori_results

    return extracted_rules, base_tanka_dict, market_stats

# =========================================================
# 3. UIロジック
# =========================================================
# タブの作成
tab1, tab2 = st.tabs(["📂 ①データのアップロード＆解析", "🤖 ②詳細査定シミュレーター"])

# ---------------------------------------------------------
# TAB 1: アップロード画面
# ---------------------------------------------------------
with tab1:
    st.write("当該エリアのSUUMO物件一覧エクセルと、ルールフォーマットCSVをアップロードしてください。")
    st.write("アップロードすると、AIが自動的にエリアごとの相場と加減算ルールを構築します。")
    
    colA, colB = st.columns(2)
    with colA:
        uploaded_suumo = st.file_uploader("SUUMO物件データ (Excel)", type=["xlsx", "csv"])
    with colB:
        uploaded_rules = st.file_uploader("ルールフォーマット (CSV)", type=["csv"])

    if uploaded_suumo is not None and uploaded_rules is not None:
        with st.spinner("データを解析してエリアの相場・ルールを構築しています..."):
            extracted_rules, base_tanka_dict, market_stats = analyze_real_estate_data(uploaded_suumo, uploaded_rules)
            
            # セッションに保存してTab2で使えるようにする
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
        st.write("解析したエリアデータに基づき、適正な賃料を算出します。")
        
        rules = st.session_state['rules']
        bases = st.session_state['base_tanka']
        stats = st.session_state['market_stats']

        # 有効な間取り（データが10件以上あって解析できたもの）だけを選択肢にする
        valid_layouts = [k for k, v in bases.items() if v > 0]
        
        if not valid_layouts:
            st.error("データが少なすぎて分析可能な間取りがありません。別のデータをお試しください。")
        else:
            # --- 基本スペック入力 ---
            col1, col2, col3, col4 = st.columns(4)
            with col1: target_layout = st.selectbox("間取りタイプ", valid_layouts, index=0)
            with col2: i_area = st.number_input("専有面積 (㎡)", min_value=10.0, max_value=200.0, value=25.0, step=0.5)
            with col3: i_age = st.number_input("築年数 (年) ※新築は0", min_value=0, max_value=100, value=5)
            with col4: i_walk = st.number_input("駅徒歩 (分)", min_value=0, max_value=60, value=8)

            # --- 設備条件の入力 ---
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

            # 選択された設備を辞書にまとめる
            selected_features = {
                '2階以上': i_2f, '角部屋': i_corner, '南向き': i_south,
                'バス・トイレ別': i_bt, '洗面所独立': i_sh, '温水洗浄便座': i_wc,
                'システムキッチン': i_sys, '浴室乾燥機': i_dry, 'インターネット無料': i_net,
                'オートロック': i_auto, '宅配ボックス': i_box
            }

            # ==========================================
            # 査定計算ロジック
            # ==========================================
            r = rules.get(target_layout, {})
            
            # 1. ベース家賃（対象エリアの中央値単価 × 面積）
            tanka_base = bases.get(target_layout, 4000)
            rent_base = tanka_base * i_area
            
            # 2. 加減算ロジック
            rent_rules = 0
            # 徒歩分数
            if i_walk > 10:
                rent_rules += r.get('徒歩10分超固定ペナルティ', 0)
                rent_rules += (i_walk - 10) * r.get('徒歩10分超追加単価', 0) * i_area
            # 築年数
            if i_age == 0: rent_rules += r.get('築年_新築単価', 0) * i_area
            elif 1 <= i_age <= 3: rent_rules += r.get('築年_1_3年単価', 0) * i_area
            elif 4 <= i_age <= 6: rent_rules += r.get('築年_4_6年単価', 0) * i_area
            elif 7 <= i_age <= 10: rent_rules += r.get('築年_7_10年単価', 0) * i_area
            # 設備条件
            for feat_name, is_checked in selected_features.items():
                if is_checked:
                    rent_rules += r.get(feat_name, 0) * i_area
            
            # 3. 最終推定家賃
            predicted_rent = rent_base + rent_rules + i_premium

            # ==========================================
            # 結果表示 (上部：シミュレーター結果)
            # ==========================================
            st.markdown(
                f"""
                <div style="background-color:#e8f4f8;padding:20px;border-radius:10px;text-align:center;margin-top:20px;">
                    <h3 style="margin:0;color:#333;">設備・条件を反映した推定家賃</h3>
                    <h1 style="margin:0;color:#0066cc;font-size:48px;">{int(predicted_rent):,} 円</h1>
                    <p style="color:#666; margin:0;">
                    (エリアベース相場: {int(rent_base):,}円 ＋ AI設備加減点: {int(rent_rules):,}円 ＋ 手動調整: {i_premium}円)
                    </p>
                </div>
                """, 
                unsafe_allow_html=True
            )

            # ==========================================
            # 結果表示 (下部：純粋な相場帯とボリュームゾーン)
            # ==========================================
            st.markdown("<br><hr>", unsafe_allow_html=True)
            st.subheader(f"📈 面積 {i_area}㎡ の箱に対する、当該エリアの純粋な相場帯")
            st.caption("※アップロードされたデータに基づき、設備等を考慮せず、同じ間取り・同じ広さの物件が市場でどう分布しているかを示します。")

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

                # プログレスバーでの視覚化
                st.caption(f"▼ 今回の推定家賃（{int(predicted_rent):,}円）が、市場全体のどの位置にいるかの目安")
                # ゼロ除算エラーなどを防ぐ
                if price_max > price_min:
                    progress_val = (predicted_rent - price_min) / (price_max - price_min)
                    st.progress(min(1.0, max(0.0, progress_val)))
                else:
                    st.progress(0.5)
            else:
                st.info("この間取りの相場分布データは取得できませんでした。")