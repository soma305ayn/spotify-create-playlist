# setlist2spotify

ライブのセットリスト画像から曲名・アーティスト名を読み取り、Spotify で検索して新しいプレイリストを自動作成する Python ツールです。

```
画像 ──(前処理 + OCR)──▶ テキスト ──(パーサ)──▶ 曲リスト ──(Spotify 検索 + スコアリング)──▶ プレイリスト
```

## 構成

| ファイル | 役割 |
|---|---|
| `setlist2spotify/ocr.py` | 画像前処理（拡大・反転・大津二値化）と OCR バックエンド（Tesseract / Claude Vision） |
| `setlist2spotify/parser.py` | OCR テキストから曲番号（`M1` `01.` `EN1` `⑤` など）・MC 等の除外・曲名/アーティスト分割 |
| `setlist2spotify/matcher.py` | 複数クエリで Spotify を検索し、曲名・アーティスト名の類似度で最適なトラックを選択 |
| `setlist2spotify/spotify.py` | Spotify Web API クライアント（PKCE 認証・トークン自動更新・429 リトライ） |
| `setlist2spotify/cli.py` | 一連のワークフローを実行する CLI |

## セットアップ

```bash
# Tesseract 本体と日本語データ（--ocr tesseract の場合）
sudo apt install tesseract-ocr tesseract-ocr-jpn   # macOS: brew install tesseract tesseract-lang

cd setlist2spotify
pip install -r requirements.txt
```

### Spotify アプリの登録

1. <https://developer.spotify.com/dashboard> でアプリを作成
2. Redirect URI に `http://127.0.0.1:8888/callback` を追加（`localhost` は不可）
3. Web API を有効化し、Client ID を控える（PKCE を使うため Client Secret は不要）

```bash
export SPOTIFY_CLIENT_ID=xxxxxxxxxxxxxxxx
```

初回実行時にブラウザが開き、Spotify へのアクセス許可を求められます。トークンは `~/.cache/setlist2spotify/token.json` に保存され、以降は自動更新されます。

## 使い方

```bash
# 基本: 抽出結果を確認・修正 → 検索 → 曖昧な曲は候補から選択 → 作成
python -m setlist2spotify setlist.jpg --artist 櫻坂46 --name "5th YEAR ANNIVERSARY LIVE"

# 抽出結果だけ確認（Spotify 不要）
python -m setlist2spotify setlist.jpg --extract-only --show-ocr

# 検索結果だけ確認（プレイリストは作らない）
python -m setlist2spotify setlist.jpg --artist 日向坂46 --dry-run

# 装飾の多い画像・縦書きなどは Claude Vision で抽出（要 ANTHROPIC_API_KEY）
python -m setlist2spotify setlist.jpg --ocr claude

# テキストから（OCR 済み・手入力のセットリスト）、確認なしで全自動
python -m setlist2spotify --text setlist.txt --artist 櫻坂46 --yes --public
```

主なオプション:

| オプション | 説明 |
|---|---|
| `--artist` | 曲ごとにアーティスト表記がない場合の既定アーティスト（検索精度が大きく上がります） |
| `--ocr tesseract\|claude` | OCR バックエンド（既定: tesseract） |
| `--threshold 0.75` | 自動採用する一致スコア。未満の曲は候補から手動選択（`--yes` 時はスキップ） |
| `--market JP` | 検索対象の国 |
| `--psm 6` / `--no-preprocess` | Tesseract の調整用 |

## 精度を上げる工夫

**OCR**
- EXIF 回転補正、小さい画像の拡大、暗い背景（告知画像に多い白文字）の自動反転、大津法による二値化
- Tesseract が日本語の文字間に挿入する余分な空白を除去
- 全角英数字・丸数字を NFKC で正規化
- `--ocr claude` では Claude のビジョン + JSON スキーマ指定の構造化出力で、曲名・アーティスト・本編/アンコールを直接取得

**パース**
- `M1` `01.` `3)` `⑤` `EN1` `W-EN1` などの曲番号表記に対応。`2人セゾン` のような数字始まりの曲名は番号と誤認しない
- 番号付き行が 3 行以上あれば、番号のない行（公演名・日付・会場）はノイズとして除外
- `MC` `VTR` `影ナレ` などの進行項目を除外
- `曲名 / アーティスト`、`曲名 - アーティスト`、`「曲名」アーティスト` を分割

**Spotify 照合**
- `track:"曲名" artist:"アーティスト"` → フリーワード → バージョン表記除去 → 曲名のみ、の順に検索
- カタカナ/ひらがな・全角/半角・記号の違いを吸収した類似度（曲名 70% + アーティスト 30%）
- `(off vocal)` `カラオケ` `オルゴール` `cover` などの音源は減点
- 高スコアの一致が見つかった時点で追加検索を打ち切り、API 呼び出しを節約

## Spotify Web API について

2026 年 2 月の Web API 変更に対応しています（プレイリスト作成は `POST /me/playlists`、曲追加は `POST /playlists/{id}/items`、検索の `limit` 上限は 10）。Development Mode のアプリでは、ダッシュボードで許可したユーザーのみ利用できます。

## テスト

```bash
pip install -r requirements-dev.txt
python -m pytest
```

Tesseract と日本語フォントがある環境では、生成した画像を実際に OCR する E2E テストも実行されます。
