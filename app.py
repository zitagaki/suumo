import time
import random
import re
import pandas as pd
import numpy as np
import streamlit as st

# =========================================================
# 1. 査定ルール辞書（機械学習で抽出した各間取りの加減算係数）
# =========================================================
# ※値は「㎡単価（円）」への影響額。固定ペナルティのみ「総額（円）」への影響額。
RULES_DICT = {
    'ワンルーム': {
        '徒歩10分超固定ペナルティ': -1233, '徒歩10分超追加単価': -29, 
        '築年_新築単価': -101, '築年_1_3年単価': 88, '築年_4_6年単価': -2, '築年_7_10年単価': 16,
        '2階以上': 51, '角部屋': 135, '南向き': -95, '洗面所独立': -176, 'バス・トイレ別': -210,
        '温水洗浄便座': 107, '浴室乾燥機': -116, 'システムキッチン': -65, 'オートロック': -85,
        '宅配ボックス': -174, 'インターネット無料': 127
    },
    '1K・1DK': {
        '徒歩10分超固定ペナルティ': -1792, '徒歩10分超追加単価': -101, 
        '築年_新築単価': -127, '築年_1_3年単価': 261, '築年_4_6年単価': 91, '築年_7_10年単価': -225,
        '2階以上': 13, '角部屋': -83, '南向き': -86, '洗面所独立': -102, 'バス・トイレ別': -37,
        '温水洗浄便座': 175, '浴室乾燥機': -7, 'システムキッチン': 90, 'オートロック': 137,
        '宅配ボックス': 126, 'インターネット無料': -85
    },
    '1LDK': {
        '徒歩10分超固定ペナルティ': 1295, '徒歩10分超追加単価': -58, 
        '築年_新築単価': 277, '築年_1_3年単価': 42, '築年_4_6年単価': -228, '築年_7_10年単価': -91,
        '2階以上': 26, '角部屋': -23, '南向き': -26, '洗面所独立': -26, 'バス・トイレ別': 12,
        '温水洗浄便座': 112, '浴室乾燥機': 22, 'システムキッチン': -1, 'オートロック': 205,
        '宅配ボックス': 143, 'インターネット無料': -46
    },
    '2K・2DK': {
        '徒歩10分超固定ペナルティ': 52, '徒歩10分超追加単価': 1, 
        '築年_新築単価': 2, '築年_1_3年単価': 21, '築年_4_6年単価': 34, '築年_7_10年単価': -58,
        '2階以上': -24, '角部屋': 11, '南向き': 0, '洗面所独立': 13, 'バス・トイレ別': 0,
        '温水洗浄便座': 0, '浴室乾燥機': 0, 'システムキッチン': 0, 'オートロック': 75,
        '宅配ボックス': 75, 'インターネット無料': -17
    },
    '2LDK': {
        '徒歩10分超固定ペナルティ': -1292, '徒歩10分超追加単価': -37, 
        '築年_新築単価': 248, '築年_1_3年単価': -29, '築年_4_6年単価': -80, '築年_7_10年単価': -139,
        '2階以上': 87, '角部屋': 17, '南向き': 8, '洗面所独立': -70, 'バス・トイレ別': -6,
        '温水洗浄便座': 33, '浴室乾燥機': -45, 'システムキッチン': 24, 'オートロック': 128,
        '宅配ボックス': 140, 'インターネット無料': -90
    },
    '3LDK': {
        '徒歩10分超固定ペナルティ': 293, '徒歩10分超追加単価': 2, 
        '築年_新築単価': 4, '築年_1_3年単価': -3, '築年_4_6年単価': 22, '築年_7_10年単価': -23,
        '2階以上': -25, '角部屋': -62, '南向き': 30, '洗面所独立': 27, 'バス・トイレ別': -10,
        '温水洗浄便座': 4, '浴室乾燥機': -11, 'システムキッチン': 3, 'オートロック': 63,
        '宅配ボックス': 12, 'インターネット無料': 37
    }
}

# =========================================================
# 2. 査定計算エンジン
# =========================================================
def calc_rule_adjustments(area, walk, age, features, layout):
    """設備の加減算ロジックを計算して総額を返す"""
    r = RULES_DICT.get(layout, RULES_DICT.get('1K・1DK', {}))
    adj = 0
    
    # --- 徒歩分数の計算 ---
    if walk > 10:
        # 固定ペナルティ（総額への直接マイナス）
        adj += r.get('徒歩10分超固定ペナルティ', 0)
        # 10分を超えた1分ごとの追加ペナルティ（㎡単価 × 面積）
        adj += (walk - 10) * r.get('徒歩10分超追加単価', 0) * area

    # --- 築年数の計算（㎡単価 × 面積） ---
    if age == 0: adj += r.get('築年_新築単価', 0) * area
    elif 1 <= age <= 3: adj += r.get('築年_1_3年単価', 0) * area
    elif 4 <= age <= 6: adj += r.get('築年_4_6年単価', 0) * area
    elif 7 <= age <= 10: adj += r.get('築年_7_10年単価', 0) * area
    # 11年以上は今回はベース家賃に吸収される前提で0加算とする

    # --- 設備・条件の計算（㎡単価 × 面積） ---
    for feat_name, is_checked in features.items():
        if is_checked:
            adj += r.get(feat_name, 0) * area
            
    return adj


# =========================================================
# 3. Streamlit メインアプリ画面
# =========================================================
def main():
    st.set_page_config(page_title="不動産ハイブリッド査定システム", layout="wide")
    st.title("🏡 不動産ハイブリッド査定システム (AI × プロの相場観)")
    
    tab1, tab2 = st.tabs(["📊 ①対象エリアのデータ収集", "🤖 ②ハイブリッド詳細査定"])

    # ---------------------------------------------------------
    # TAB 1: スクレイピング画面（お手元の既存ロジックを配置する場所）
    # ---------------------------------------------------------
    with tab1:
        st.write("対象としたい駅やエリアのSUUMO一覧URLを入力し、相場の基準となるデータを収集します。")
        
        col1, col2 = st.columns([3, 1])
        with col1:
            target_list_url = st.text_input("SUUMOの一覧ページのURL:", placeholder="https://suumo.jp/...")
        with col2:
            max_pages = st.number_input("取得する最大ページ数", min_value=1, max_value=50, value=5)

        if st.button("スクレイピングを実行する"):
            st.info("※ここにSelenium等を用いたスクレイピング処理が走ります。取得したデータをセッションステート等に保存してください。")
            # 実際にはここに、抽出したデータからベースとなる㎡単価を算出する処理を入れます
            # 例: st.session_state['base_price_per_sqm'] = 4500

    # ---------------------------------------------------------
    # TAB 2: 詳細査定シミュレーター
    # ---------------------------------------------------------
    with tab2:
        st.subheader("🤖 詳細査定シミュレーター")
        st.write("物件の基本スペックと設備を選択し、適正な賃料を算出します。")
        
        # --- 基本スペック入力 ---
        col1, col2, col3, col4 = st.columns(4)
        with col1: target_layout = st.selectbox("間取りタイプ", list(RULES_DICT.keys()), index=1)
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
        # 本来はTab1のスクレイピング結果から取得するベース単価（ハコ単価）。
        # データがない場合のための仮のデフォルト相場（東京標準）を設定
        default_base_tanka = {
            'ワンルーム': 4000, '1K・1DK': 4500, '1LDK': 4200, 
            '2K・2DK': 3800, '2LDK': 3500, '3LDK': 3300
        }
        
        # 面積 × ベース単価 で基本家賃を計算
        base_tanka = default_base_tanka.get(target_layout, 4000)
        rent_base = base_tanka * i_area
        
        # 設備・ルールの加減算を計算
        rent_rules = calc_rule_adjustments(i_area, i_walk, i_age, selected_features, target_layout)
        
        # 最終推定家賃
        predicted_rent = rent_base + rent_rules + i_premium

        # ==========================================
        # 相場帯・ボリュームゾーンの算出（設備を考慮しない純粋な面積の幅）
        # ==========================================
        # 本来は実際のSUUMOデータから算出。ここでは統計的なブレ幅から擬似計算
        price_median = int(base_tanka * i_area)
        price_min = int(price_median * 0.65) # 下限（約35%安）
        price_max = int(price_median * 1.50) # 上限（約50%高）
        zone_low = int(price_median * 0.90)  # ボリュームゾーン下限
        zone_high = int(price_median * 1.15) # ボリュームゾーン上限

        # ==========================================
        # 結果表示
        # ==========================================
        st.markdown(
            f"""
            <div style="background-color:#e8f4f8;padding:20px;border-radius:10px;text-align:center;margin-top:20px;">
                <h3 style="margin:0;color:#333;">設備・条件を反映した推定家賃</h3>
                <h1 style="margin:0;color:#0066cc;font-size:48px;">{int(predicted_rent):,} 円</h1>
                <p style="color:#666; margin:0;">
                (ベース家賃: {int(rent_base):,}円 ＋ AI設備加点/減点: {int(rent_rules):,}円 ＋ 手動調整: {i_premium}円)
                </p>
            </div>
            """, 
            unsafe_allow_html=True
        )

        st.markdown("<br><hr>", unsafe_allow_html=True)
        st.subheader("📈 この物件の「面積（ハコ）」に対する純粋な相場帯")
        st.caption("※設備や築年数を一切考慮せず、同じ間取り・同じ広さの物件が市場でどの価格帯で取引されているかを示します。")

        colA, colB, colC = st.columns(3)
        with colA:
            st.metric(label="最低価格目安", value=f"{price_min:,} 円")
        with colB:
            st.metric(label="ボリュームゾーン (上位33%〜66%)", value=f"{zone_low:,} 〜 {zone_high:,} 円", delta="相場の中核")
        with colC:
            st.metric(label="最高価格目安", value=f"{price_max:,} 円")

        # 相場の中での立ち位置をプログレスバーで視覚化
        st.caption(f"▼ 今回の推定家賃（{int(predicted_rent):,}円）が、市場全体のどの位置にいるかの目安")
        progress_val = (predicted_rent - price_min) / (price_max - price_min)
        # バーがエラーを起こさないように0.0〜1.0の範囲に収める
        st.progress(min(1.0, max(0.0, progress_val)))


if __name__ == "__main__":
    main()