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
        df_suumo['専有面積