# AI可視性診断スクリプト 仕様書（Phase 0）

VisibleShelf（AEO最適化ツール）のPhase 0プロトタイプ。
日本酒D2C蔵を対象に、「自社の商品がAIの推薦回答に出るか」を診断する最小スクリプト。
この仕様書はClaude Codeに渡して実装してもらう前提で書いている。

---

## 0. ゴールと非ゴール

**ゴール**
- 代表クエリ（20本）を ChatGPT / Gemini / Perplexity に投げる
- 各回答から「対象蔵・銘柄が登場したか」「順位」「競合」「引用URL」を抽出
- 結果を1枚のCSV（兼スプレッドシート）に吐く
- 同じ診断を後日また回せる（再現性）ようにする

**非ゴール（Phase 0ではやらない）**
- 最適化案の生成（直す機能）
- フィード配信（届ける機能）
- Web UI / ダッシュボード（出力はCSVで十分）
- DB永続化（ファイル出力でよい。後で差し替え可能な構造にだけしておく）

---

## 1. 全体フロー

```
queries.yaml + targets.yaml
        │
        ▼
  [1] クエリ × エンジン の総当たりでAPI呼び出し
        │   （生レスポンスはすべて raw/ に保存）
        ▼
  [2] 各回答テキストから登場・順位・競合・引用を抽出（抽出器）
        │
        ▼
  [3] スコアリング（クエリ単位 → エンジン単位 → 総合）
        │
        ▼
  results.csv  +  summary.json  +  raw/*.json
```

3ステップは別関数・別モジュールに分離すること。特に「API呼び出し」と「抽出」は
疎結合にする（生レスポンスを保存しておき、抽出だけ後から何度も再実行できるように）。

---

## 2. 入力ファイル

### 2.1 `targets.yaml` — 診断対象の蔵
```yaml
brand_name: "○○酒造"          # 蔵の正式名
aliases:                        # 表記ゆれ・英語表記など
  - "マルマル酒造"
  - "Maru Maru Sake Brewery"
products:                       # 主力銘柄
  - name: "△△ 純米大吟醸"
    aliases: ["△△", "Maru Junmai Daiginjo"]
  - name: "□□ 特別純米"
    aliases: ["□□"]
prefecture: "新潟県"
website: "https://example-sake.jp"   # 引用判定で「自社サイトか」を見るため
```

### 2.2 `queries.yaml` — 代表クエリ20本
tier と狙いをメタ情報として持たせる。`{brand}` `{product}` `{prefecture}` を
プレースホルダにして targets.yaml から差し込む。

```yaml
queries:
  # Tier 1: 曖昧・潜在ニーズ型
  - id: q01
    tier: 1
    text: "日本酒が好きな父の還暦祝いに、特別感のある一本を贈りたい"
  - id: q02
    tier: 1
    text: "普段ワインしか飲まない人でも飲みやすい、おしゃれな日本酒を探している"
  - id: q03
    tier: 1
    text: "自宅でゆっくり晩酌したい。クセが少なくて毎日飲み飽きしない日本酒は？"
  - id: q04
    tier: 1
    text: "日本酒に入門してみたい初心者。失敗しない最初の一本を教えて"
  - id: q05
    tier: 1
    text: "海外の友人へのお土産にしたい、見た目も味も日本らしい日本酒"
  - id: q06
    tier: 1
    text: "寒い夜に燗でほっとできる、しみじみ美味しい日本酒が飲みたい"
  # Tier 2: 条件指定型（主戦場）
  - id: q07
    tier: 2
    text: "辛口でキレのある純米酒、3000円以内のギフト向け"
  - id: q08
    tier: 2
    text: "フルーティーで香り高い純米大吟醸、5000円前後のおすすめ"
  - id: q09
    tier: 2
    text: "甘口で飲みやすい日本酒、720mlで2000円台"
  - id: q10
    tier: 2
    text: "結婚祝いにふさわしい高級な日本酒、一升瓶で華やかなラベルのもの"
  - id: q11
    tier: 2
    text: "食事に合わせやすい淡麗辛口の日本酒、和食とのペアリング向け"
  - id: q12
    tier: 2
    text: "無濾過生原酒で旨味の強い日本酒、冷やして飲むタイプ"
  - id: q13
    tier: 2
    text: "飲み比べセットで楽しめる日本酒ギフト、4000〜6000円"
  - id: q14
    tier: 2
    text: "お燗にして美味しい熟成タイプの日本酒、コクのあるもの"
  - id: q15
    tier: 2
    text: "低アルコールで軽く飲めるスパークリング日本酒"
  # Tier 3: 指名・近接・産地型
  - id: q16
    tier: 3
    text: "{brand}の代表銘柄は？どんな味わい？"
  - id: q17
    tier: 3
    text: "{prefecture}のおすすめ地酒、小さな酒蔵のもの"
  - id: q18
    tier: 3
    text: "{product}に似た味わいの日本酒は他にある？"
  - id: q19
    tier: 3
    text: "山田錦を使った純米大吟醸で、知る人ぞ知る蔵のもの"
  - id: q20
    tier: 3
    text: "クラフトサケ・新しいスタイルの日本酒を造る注目の若手蔵は？"
```

### 2.3 `engines.yaml` — 叩くエンジン設定
```yaml
engines:
  - id: chatgpt
    enabled: true
    # Web検索を有効にしたモードで叩く（ショッピング的な推薦に近づけるため）
    model: "gpt-4o-search-preview"   # 実装時に利用可能な検索対応モデルへ要調整
  - id: perplexity
    enabled: true
    model: "sonar"                    # 検索一体型。引用URLが取りやすい
  - id: gemini
    enabled: true
    model: "gemini-2.5-flash"         # grounding(検索) を有効化して叩く
```

APIキーは `.env` から読む（`OPENAI_API_KEY` / `PERPLEXITY_API_KEY` / `GEMINI_API_KEY`）。
キーが無いエンジンは自動スキップしてログに残す。

---

## 3. ステップ1：API呼び出し

- 各 (query, engine) の組について1回ずつ呼ぶ（計 20 × 有効エンジン数）。
- **検索/groundingを必ず有効化する。** これがPhase 0の肝。学習データのみの回答では
  リアルタイムのAI推薦を再現できない。
- 各エンジンへ共通の前置きプロンプトを付ける：
  ```
  あなたは日本酒に詳しいショッピングアシスタントです。
  ユーザーの相談に対し、具体的な銘柄・蔵名を3〜5件、理由とともに挙げてください。
  可能なら購入できるサイトのURLも示してください。
  ```
  そのあとにユーザークエリ本文を入れる。
- レート制限対策：エンジンごとに逐次実行＋指数バックオフのリトライ（最大3回）。
- **生レスポンスを必ず保存**：`raw/{engine}_{query_id}_{timestamp}.json`
  （リクエスト本文・モデル名・全文応答・引用/citation構造をそのまま）。
- 1本失敗しても全体は止めず、エラーを記録して次へ進む。

### 重要：APIと実画面の乖離チェック
ChatGPT/Geminiは、Web版のショッピング推薦とAPI応答が一致しない可能性がある。
**最初の検証として q07・q08・q16 の3本だけ、API結果と「実際にWeb版に同じ質問を入れた結果」を
人が見比べられるよう、その3本のプロンプトを `manual_check.txt` に書き出す処理を入れる。**
（自動でWeb版は叩かない。手動確認用のテキストを吐くだけ）

---

## 4. ステップ2：抽出器（回答テキスト → 構造化）

回答テキストと targets.yaml を入力に、以下を判定する。
判定は「ルールベースを一次、LLMを二次」のハイブリッド。

### 4.1 登場有無 `appearance`
- `brand_name` / `aliases` / 各 `product.name` / `product.aliases` を
  正規化（全角半角・スペース・株式会社等の法人格を除去）して部分一致検索。
- 結果を3値で返す：
  - `hit` … 銘柄名または蔵名がはっきり推薦として登場
  - `mention` … 名前は出るが推薦ではない（例：「○○もありますが…」と退ける文脈）
  - `miss` … 登場しない
- hit/mention の切り分けは曖昧なので、**該当箇所の前後文をLLMに渡して
  「これは推薦か、単なる言及か」を分類させる**（二次判定）。

### 4.2 順位 `rank`
- 回答内で銘柄・蔵が列挙されている場合、対象が何番目か（1始まり）。
- リスト構造でない散文の場合は登場順で代用。出ないなら null。

### 4.3 競合 `competitors`
- 回答に登場した「対象以外の」蔵名・銘柄名を抽出（最大10件）。
- 固有名詞抽出はLLMに任せてよい（「この回答に出てくる日本酒の銘柄名と蔵名をJSON配列で」）。
- これが「誰に負けているか」の基礎データになる。

### 4.4 引用 `citations`
- レスポンスの citation / grounding メタdata からURL一覧を取得。
- 各URLを「自社サイト（targets.websiteのドメイン一致）/ モール（rakuten,amazon,yahoo等）/
  第三者メディア / その他」に分類。
- 自社サイトが引用されているか（`self_cited: true/false`）を必ず記録。

---

## 5. ステップ3：スコアリング

### 5.1 クエリ×エンジン単位スコア（0〜100）
```
appearance: hit=60 / mention=20 / miss=0
rank_bonus: 1位=+25, 2位=+18, 3位=+12, 4位=+6, 5位以下=+3, 出ない=0
self_cited: +15 / されてない=0
合計を0〜100にクリップ
```
重みは設定ファイルで変えられるようにする（マジックナンバー禁止）。

### 5.2 集計
- エンジン別平均スコア
- tier別平均スコア（Tier1/2/3で傾向が違うはず＝洞察になる）
- 総合スコア（全クエリ×全エンジンの平均）
- **競合ランキング**：全クエリ横断で competitors に出た回数を集計。
  「自社より頻繁にAIに推薦されている蔵トップ10」を出す。これが一番効く出力。

---

## 6. 出力

### 6.1 `results.csv`（明細／1行 = 1 query×engine）
列：
```
query_id, tier, query_text, engine, appearance, rank,
self_cited, citation_domains, competitors, score, raw_file
```

### 6.2 `summary.json`（集計）
```json
{
  "target": "○○酒造",
  "run_at": "2026-06-05T12:00:00+09:00",
  "overall_score": 0,
  "by_engine": {"chatgpt": 0, "perplexity": 0, "gemini": 0},
  "by_tier": {"1": 0, "2": 0, "3": 0},
  "self_citation_rate": 0.0,
  "top_competitors": [{"name": "□□酒造", "count": 12}],
  "queries_missed": ["q03", "q09"]
}
```

### 6.3 コンソール出力
実行後、要点を人が読める形で出す：総合スコア、出なかったクエリ数、
最頻競合トップ3、自社引用率。

---

## 7. 技術スタック・構成

- 言語：Python 3.11+
- 依存：`openai`, `google-genai`, `requests`(Perplexity), `pyyaml`, `python-dotenv`, `pandas`
- 構成：
  ```
  visibleshelf/
    config/        engines.yaml, queries.yaml, targets.yaml, scoring.yaml
    src/
      runner.py        # ステップ1：API呼び出し
      extractor.py     # ステップ2：抽出
      scorer.py        # ステップ3：スコアリング
      engines/         # chatgpt.py, perplexity.py, gemini.py（共通IFで実装）
    raw/             # 生レスポンス
    out/             # results.csv, summary.json, manual_check.txt
    main.py          # オーケストレーション（--target, --skip-api 等のフラグ）
    .env.example
    README.md
  ```
- 各エンジンは共通インターフェース `ask(prompt) -> {text, citations, model, raw}` で実装し、
  追加・差し替えしやすくする。

### CLIフラグ
- `--target config/targets.yaml`
- `--skip-api` … raw/ の既存レスポンスだけで抽出・スコアリングを再実行（抽出ロジック調整用）
- `--engines chatgpt,perplexity` … 一部エンジンだけ実行
- `--dry-run` … 呼び出すクエリ一覧を表示するだけ

---

## 8. Phase 0で人が手でやること（スクリプト範囲外・申し送り）

- `manual_check.txt` の3本を実際にWeb版ChatGPT/Geminiに入れ、API結果と乖離がないか確認
- `miss` だったクエリの「なぜ出ないか」仮説立て（情報薄／レビュー無／構造化無／未インデックス）
- 検証対象の実在D2C蔵を3〜5件選ぶ（targets.yamlを複数用意して回す）

---

## 9. 実装順序の推奨

1. engines/ の1エンジン（まず Perplexity：引用が取りやすく検索一体型）だけで疎通
2. runner で1クエリ→raw保存まで通す
3. extractor をルールベースのみで実装 → `--skip-api` で回して調整
4. LLM二次判定（hit/mention分類・競合抽出）を追加
5. scorer と出力
6. 残り2エンジン（ChatGPT, Gemini）を共通IFに乗せる
7. targets を複数蔵に増やして実走

まず1エンジン×数クエリで「生レスポンスが取れて抽出できる」ことを最優先で通すこと。
20本×3エンジンの完全自動化は最後でよい。