販売伝票明細(49) 取込マッピング仕様
更新日: 2026-02-14

**Source**
- 入力ファイル: `docs/templates/販売伝票明細 (49).csv`
- 形式: CSV
- 参照期間: 最低1年、最大3年（前年必須）
- 例: 2026年計画時は2025年を必須、必要に応じて2024年・2023年を追加
- 年次重み（標準）
- 1年参照: 2025=1.0
- 2年参照: 2025=0.7, 2024=0.3
- 3年参照: 2025=0.6, 2024=0.3, 2023=0.1
- 例外: 前年データ不足の店舗は、取得可能な期間のみで算出し不足フラグを付与

**Column Mapping**
- A列: 伝票番号
- D列: 営業日付
- F列: 店舗コード
- G列: 店舗名
- I列: 商品コード
- K列: 商品名
- T列: 販売金額
- V列: 数量
- AL列: 登録日時
- 実装では列文字または固定インデックス参照を推奨
- A=1, D=4, F=6, G=7, I=9, K=11, T=20, V=22, AL=38

**Transform Rules**
- `product_code_10` = 商品コード(I列)の左10桁
- `color_cd` = 商品コード(I列)の11〜12桁目
- `size_cd` = 商品コード(I列)の13桁目以降
- `item_category_cd` = `product_code_10` の3〜4桁目
- `item_category_name` は以下で判定
- 01: ワンピース
- 02: カーデ
- 03: ジャケット
- 04: ニット
- 05: カットソー
- 06: コート
- 07: ブラウス
- 08: スカート
- 09: パンツ
- 10: トレーナー
- 11: インナー
- 12: セットアップ
- 13: アクセサリー
- 15: シューズ

**Product Display Rule**
- 商品コード表示: `product_code_10` を表示
- 商品名表示: K列を表示
- 例
- 商品コード: `1103120055`
- 商品名: `247217ﾌｧｰﾂｷFﾚｻﾞｰJK`

**Time Slot Aggregation**
- 集計基準時刻: AL列 `登録日時`
- 集計粒度: 30分
- バケット例: 10:00-10:29, 10:30-10:59
- `slot_sales_amount` = 同一店舗・同一営業日・同一30分帯の販売金額(T列)合計
- `slot_qty` = 同一帯の数量(V列)合計
- `slot_ticket_count` = 同一帯の伝票番号(A列)件数（必要なら重複排除）
- `slot_sales_ratio` = `slot_sales_amount / 店舗日次売上合計`
- 年次統合時は、年ごとの `slot_sales_ratio` を重み付き平均で合成
- `final_slot_sales_ratio` = Σ(年次重み × 年次slot_sales_ratio)
- ピーク帯は `final_slot_sales_ratio` 上位の時間帯として判定

**Data Quality and Accuracy**
- 外れ値対策: 店舗別・時間帯別で販売金額の上位1%/下位1%を除外可能（設定でON/OFF）
- 曜日整合: 曜日別パターンを保持し、平日/土日祝で別集計
- 信頼度指標: 参照期間内の有効営業日カバー率を算出
- `coverage_rate` = 有効営業日数 / 想定営業日数
- `coverage_rate` が0.8未満の場合は低信頼フラグを付与

**Output Fields (Recommended)**
- business_date
- store_code
- store_name
- slot_start_datetime
- slot_end_datetime
- slot_sales_amount
- slot_sales_ratio
- slot_qty
- slot_ticket_count
- product_code_10
- color_cd
- size_cd
- item_category_cd
- item_category_name
- product_name

**Validation**
- 必須欠損チェック: D, F, I, T, V, AL
- 型チェック: T, Vは数値
- 日時チェック: ALは日時変換可能
- 不正商品コード: 10桁未満はエラー行として隔離
- 注意: CSVライブラリによってはヘッダー解釈で失敗するケースがあるため、列番号基準の取込にしておくと安全
