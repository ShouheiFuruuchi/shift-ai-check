POS参照期間設計（最低1年〜最大3年）
更新日: 2026-02-14

**目的**
- 時間帯売上構成比とピーク帯推定の精度向上
- 新しい傾向を優先しつつ、年次変動を吸収

**基本方針**
- 参照期間は最低1年、最大3年
- 前年データは必須
- 前々年・3年前は任意追加
- 年次ごとの重み付き平均で30分帯構成比を算出

**年次選択ルール**
- 対象年を `target_year` とする
- 必須: `target_year - 1`
- 任意: `target_year - 2`, `target_year - 3`
- 管理画面で参照年数を1/2/3から選択

**標準重み**
- 1年: [1.0]
- 2年: [0.7, 0.3]
- 3年: [0.6, 0.3, 0.1]
- 不足年がある場合は利用可能年で再正規化

**集計手順（店舗別）**
1. 年ごとに30分帯売上構成比 `year_slot_ratio` を計算
2. 曜日区分（平日/土日祝）を分けて同様に計算
3. 重み付き平均で `final_slot_ratio` を算出
4. `final_slot_ratio` 上位帯をピーク帯として抽出

**式**
- `year_slot_ratio(y, s) = slot_sales(y, s) / day_sales_total(y)`
- `final_slot_ratio(s) = Σ weight(y) * year_slot_ratio(y, s)`

**品質補正**
- 外れ値除外（任意）: 店舗×時間帯で販売金額の上位1%/下位1%を除外
- カバー率: `coverage_rate = valid_business_days / expected_business_days`
- `coverage_rate < 0.8` で低信頼フラグ

**不足データ時のフォールバック**
- 前年データ不足: 利用可能データで算出 + 不足フラグ
- 新店: 同エリア平均または同業態平均の時間帯比率を暫定適用

**保存推奨項目**
- store_code
- target_year
- reference_years
- weights
- slot_start
- final_slot_ratio
- coverage_rate
- low_confidence_flag
- calculated_at

**受け入れ条件**
- 参照年数を1〜3で切替可能
- 重み設定をUIから変更可能
- 店舗ごとに信頼度フラグが出る
- 低信頼時は自動作成結果画面に警告表示
