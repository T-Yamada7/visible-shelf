# VisibleShelf — AI可視性診断ツール (Phase 0)

日本酒D2C蔵向けに「自社の商品がAIの推薦回答に出るか」を診断するスクリプト。  
ChatGPT / Gemini / Perplexity に代表クエリ20本を投げ、登場有無・順位・競合・引用URLをCSVに出力する。

## セットアップ

```bash
pip install -r requirements.txt
cp .env.example .env
# .env に各APIキーを記入
```

## 使い方

```bash
# Perplexity だけで全20クエリを実行
python main.py --engines perplexity

# 実行前に叩くクエリ一覧だけ確認（APIは呼ばない）
python main.py --dry-run --engines perplexity

# raw/ の既存レスポンスから抽出・スコアリングだけ再実行
python main.py --skip-api

# 診断対象蔵を切り替える
python main.py --target config/targets_other_brewery.yaml
```

## 出力

| ファイル | 内容 |
|---|---|
| `raw/{engine}_{query_id}_{timestamp}.json` | 生レスポンス（全文）|
| `out/results.csv` | 明細（1行 = 1クエリ×エンジン） |
| `out/summary.json` | 総合スコア・競合ランキング |
| `out/manual_check.txt` | Web版との乖離確認用プロンプト（q07/q08/q16） |

## 設定ファイル

| ファイル | 用途 |
|---|---|
| `config/targets.yaml` | 診断対象蔵（蔵名・銘柄・サイトURL） |
| `config/queries.yaml` | 代表クエリ20本（Tier 1〜3） |
| `config/engines.yaml` | 使用エンジンとモデル名 |
| `config/scoring.yaml` | スコア重み（hit/mention/rank_bonus等） |

## 実装状況

- [x] Step 1: Perplexity エンジン疎通・raw保存
- [x] Step 2: runner（全クエリ×エンジン一括実行・リトライ・エラースキップ）
- [ ] Step 3: extractor（登場有無・順位・競合・引用抽出）
- [ ] Step 4: LLM二次判定（hit/mention分類）
- [ ] Step 5: scorer・CSV/JSON出力
- [ ] Step 6: ChatGPT / Gemini エンジン追加

## ディレクトリ構成

```
visible-shelf/
  config/          設定ファイル（targets, queries, engines, scoring）
  src/
    runner.py      API呼び出し・raw保存
    extractor.py   抽出（未実装）
    scorer.py      スコアリング（未実装）
    engines/
      perplexity.py
      chatgpt.py   （未実装）
      gemini.py    （未実装）
  raw/             生レスポンス（.gitignore対象）
  out/             results.csv, summary.json, manual_check.txt
  main.py          エントリーポイント
  .env.example     APIキーのテンプレート
```
