import pandas as pd
import numpy as np
import re
from sklearn.linear_model import Ridge

# ==========================================
# 1. データの読み込み
# ==========================================
# ★修正点: Excelファイルを直接読み込むように変更しました
df_suumo = pd.read_excel("SUUMO.xlsx")
df_rules = pd.read_csv("rules.csv")

# ==========================================
# 2. 前処理関数
# ==========================================
def preprocess_suumo(df):
    df = df.copy()
    
    # --- 数値変換 ---
    # 家賃を円に変換
    df['家賃_円'] = df['家賃'].astype(str).str.extract(r'([\d\.]+)').astype(float) * 10000
    
    # 専有面積を数値化
    df['専有面積_m2'] = df['専有面積'].astype(str).str.extract(r'([\d\.]+)').astype(float)
    
    # 徒歩分数の抽出（最寄駅1から）
    df['徒歩分数'] = df['最寄駅1'].astype(str).str.extract(r'歩(\d+)分').astype(float)
    df['徒歩分数'] = df['徒歩分数'].fillna(df['徒歩分数'].median())
    
    # 築年数の数値化
    df['築年'] = df['築年数'].apply(lambda x: 0 if '新築' in str(x) else float(re.search(r'\d+', str(x)).group()) if re.search(r'\d+', str(x)) else 0)
    
    # 階建から現在の階数と全体階数を抽出
    df['現在階'] = df['階建'].astype(str).str.extract(r'(\d+)階/').astype(float)
    df['全体階'] = df['階建'].astype(str).str.extract(r'/(\d+)階建').astype(float)
    
    # --- 間取りのグルーピング ---
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
    df['間取りグループ'] = df['間取り'].apply(map_madori)
    
    # --- 特徴量（フラグ）の作成 ---
    features = pd.DataFrame(index=df.index)
    
    # 徒歩分数関連
    features['徒歩10分以内単価'] = df['徒歩分数'].apply(lambda x: x if x <= 10 else 10)
    features['徒歩10分超固定ペナルティ'] = df['徒歩分数'].apply(lambda x: 1 if x > 10 else 0)
    features['徒歩10分超追加単価'] = df['徒歩分数'].apply(lambda x: x - 10 if x > 10 else 0)
    
    # 築年数
    features['築年_新築単価'] = (df['築年'] == 0).astype(int)
    features['築年_1_3年単価'] = ((df['築年'] >= 1) & (df['築年'] <= 3)).astype(int)
    features['築年_4_6年単価'] = ((df['築年'] >= 4) & (df['築年'] <= 6)).astype(int)
    features['築年_7_10年単価'] = ((df['築年'] >= 7) & (df['築年'] <= 10)).astype(int)
    features['築年_11_20年単価'] = ((df['築年'] >= 11) & (df['築年'] <= 20)).astype(int)
    features['築年_21_30年単価'] = ((df['築年'] >= 21) & (df['築年'] <= 30)).astype(int)
    features['築年_31年以降'] = (df['築年'] >= 31).astype(int)
    
    # 建物種別
    features['マンション'] = df['建物種別'].str.contains('マンション', na=False).astype(int)
    features['アパート'] = df['建物種別'].str.contains('アパート', na=False).astype(int)
    
    # 構造
    features['鉄筋系'] = df['構造'].str.contains('鉄筋', na=False).astype(int)
    features['鉄骨系'] = df['構造'].str.contains('鉄骨', na=False).astype(int)
    features['木造'] = df['構造'].str.contains('木造', na=False).astype(int)
    features['ブロック・その他'] = ((features['鉄筋系']==0) & (features['鉄骨系']==0) & (features['木造']==0)).astype(int)
    
    # 階数
    features['1階の物件'] = (df['現在階'] == 1).astype(int)
    features['2階以上'] = (df['現在階'] >= 2).astype(int)
    features['最上階'] = (df['現在階'] == df['全体階']).astype(int)
    
    # キーワード抽出関数（設備、条件、備考など全体から探す）
    df['text_all'] = df['設備'].fillna('') + df['条件'].fillna('') + df['備考'].fillna('')
    
    def check_kwd(keywords):
        pattern = '|'.join(keywords)
        return df['text_all'].str.contains(pattern, na=False).astype(int)

    # 設備・条件（ルールCSVの項目に合わせてマッピング）
    kwd_dict = {
        '角部屋': ['角部屋', '角住戸'],
        '南向き': ['南向き', '南面'],
        '室内洗濯機置場': ['室内洗濯機置場', '室内洗濯置'],
        '洗面所独立': ['洗面所独立', '独立洗面'],
        'フローリング': ['フローリング'],
        'メゾネット': ['メゾネット'],
        'ロフト': ['ロフト'],
        '防音室': ['防音室', '楽器相談'],
        '地下室': ['地下室'],
        '家具家電付き': ['家具付', '家電付'],
        'エアコン付き': ['エアコン'],
        '床暖房': ['床暖房'],
        '灯油暖房': ['灯油暖房'],
        'ガス暖房': ['ガス暖房'],
        'バス・トイレ別': ['バストイレ別', 'バス・トイレ別'],
        '温水洗浄便座': ['温水洗浄便座', 'ウォシュレット'],
        '浴室乾燥機': ['浴室乾燥機'],
        '追い焚き風呂': ['追焚機能', '追い焚き'],
        'シャワールーム': ['シャワールーム'],
        'ガスコンロ対応': ['ガスコンロ対応', 'ガスコンロ付'],
        'IHコンロ': ['IHクッキングヒーター', 'IHコンロ'],
        'コンロ2口以上': ['2口コンロ', '3口コンロ', 'コンロ2口', 'コンロ3口'],
        'オール電化': ['オール電化'],
        'システムキッチン': ['システムキッチン'],
        'カウンターキッチン': ['カウンターキッチン', '対面式キッチン'],
        '駐車場あり': ['駐車場あり', '駐車場有', '駐輪場'], 
        '敷地内駐車場': ['敷地内駐車場'],
        '駐輪場あり': ['駐輪場'],
        'バイク置場あり': ['バイク置場'],
        'エレベーター': ['エレベーター'],
        '宅配ボックス': ['宅配ボックス'],
        '敷地内ゴミ置場': ['敷地内ごみ置き場'],
        'バルコニー付': ['バルコニー'],
        'ルーフバルコニー付': ['ルーフバルコニー'],
        '専用庭': ['専用庭'],
        '都市ガス': ['都市ガス'],
        'プロパンガス': ['プロパンガス'],
        'バリアフリー': ['バリアフリー'],
        'オートロック': ['オートロック'],
        '管理人有り': ['管理人', '常駐'],
        'TVモニタ付きインタホン': ['TVインターホン', 'モニター付インターホン'],
        '防犯カメラ': ['防犯カメラ'],
        '即入居可': ['即入居可'],
        '女性限定': ['女性限定'],
        'ペット相談可': ['ペット相談'],
        '楽器相談可': ['楽器相談'],
        '事務所利用可': ['事務所利用可', 'SOHO'],
        'ルームシェア可': ['ルームシェア相談'],
        '高齢者歓迎': ['高齢者歓迎'],
        'LGBTフレンドリー': ['LGBTフレンドリー'],
        'カスタマイズ可': ['カスタマイズ可'],
        'DIY可': ['DIY可'],
        '定期借家': ['定期借家'],
        'インターネット接続可': ['インターネット対応', 'ネット専用回線'],
        'BSアンテナ': ['BS'],
        'CSアンテナ': ['CS'],
        'ケーブルテレビ': ['CATV'],
        'インターネット無料': ['インターネット無料', 'ネット使用料不要'],
        '床下収納': ['床下収納'],
        'シューズボックス': ['シューズボックス'],
        'トランクルーム': ['トランクルーム'],
        'ウォークインクローゼット': ['ウォークインクロゼット', 'ウォークインクローゼット'],
        'デザイナーズ物件': ['デザイナーズ'],
        '分譲賃貸': ['分譲賃貸'],
        '保証人不要': ['保証人不要'],
        'タワーマンション': ['タワーマンション'],
        'リフォーム済み': ['リフォーム済', '内装リフォーム済'],
        'リノベーション物件': ['リノベーション'],
        'フリーレント': ['フリーレント'],
        '特定優良賃貸住宅': ['特定優良賃貸住宅']
    }
    
    for key, words in kwd_dict.items():
        features[key] = check_kwd(words)

    # 「㎡単価への影響」にするために、固定ペナルティ以外は専有面積を掛け算する
    area = df['専有面積_m2']
    features_scaled = pd.DataFrame()
    
    for col in features.columns:
        if col == '徒歩10分超固定ペナルティ':
            features_scaled[col] = features[col] # そのまま
        else:
            features_scaled[col] = features[col] * area # 面積を掛ける
            
    # 基本の㎡単価（切片用）
    features_scaled['基本㎡単価'] = area
    
    return df['家賃_円'], features_scaled, df['間取りグループ']

# 前処理の実行
print("データを読み込み、前処理を開始します...")
y, X, groups = preprocess_suumo(df_suumo)

# ==========================================
# 3. 回帰分析の実行と結果のマッピング
# ==========================================
madori_list = ['ワンルーム', '1K・1DK', '1LDK', '2K・2DK', '2LDK', '3K・3DK', '3LDK']
coef_results = {}

print("回帰分析を実行中...")
for madori in madori_list:
    idx = groups == madori
    
    if idx.sum() < 10:  # データが少なすぎる場合は欠損値扱い
        coef_results[madori] = {col: np.nan for col in X.columns}
        continue
        
    X_sub = X.loc[idx].fillna(0)
    y_sub = y.loc[idx].fillna(0)
    
    model = Ridge(alpha=1.0, fit_intercept=False)
    model.fit(X_sub, y_sub)
    coef_results[madori] = dict(zip(X_sub.columns, model.coef_))

# ==========================================
# 4. rules.csv への出力
# ==========================================
df_output = df_rules.copy()

for i, row in df_output.iterrows():
    item_name = row['間取りグループ'] 
    
    if item_name in X.columns:
        for madori in madori_list:
            val = coef_results[madori].get(item_name, np.nan)
            df_output.at[i, madori] = round(val, 1) if pd.notnull(val) else val

df_output.to_csv("rules_calculated.csv", index=False, encoding="utf-8-sig")
print("計算が完了し、'rules_calculated.csv' が生成されました。")