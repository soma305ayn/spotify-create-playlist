# setlist2spotify

ライブのセットリスト（曲名の一覧）を貼り付けるだけで、Spotify で曲を探して新しいプレイリストを自動作成するツールです。

```
セットリストを貼り付け ──▶ 曲名・アーティスト名を読み取り ──▶ Spotify で検索 ──▶ プレイリスト作成
```

## セットリストの文字を用意する

画像のセットリストは、スマホの文字認識で文字にしてからコピーするのが手軽で正確です。

- **iPhone**: 写真アプリで画像を開き、右下の「テキスト認識」ボタン（または文字を長押し）→ すべてを選択 → コピー
- **Android**: Google フォトで画像を開き「レンズ」→「テキスト」→ すべてを選択 → コピー
- **Web のセットリスト**: そのまま範囲選択してコピー

コピーした文字は、LINE の Keep メモやメールなどで自分の PC に送ってください。

多少ゴミが混ざっていても大丈夫です。次のような行は自動で除きます。

- `M1` `01.` `EN1` などの曲番号（曲名から外します）
- MC、VTR、影ナレなどの進行項目
- 公演名・日付・会場の行（曲番号付きの行が 3 行以上ある場合）

`曲名 / アーティスト` の形なら、アーティスト名も読み取ります。

## はじめての準備（1 回だけ）

1. **Python** を https://www.python.org/downloads/ から入れる（インストール画面で「Add python.exe to PATH」にチェック）
2. このリポジトリを「Code」→「Download ZIP」でダウンロードして展開
3. 展開したフォルダ（`README.md` がある場所）で右クリック →「ターミナルで開く」→ 次を実行

   ```powershell
   python -m pip install -r requirements.txt
   ```

4. **Spotify アプリを登録**して Client ID を取得
   1. <https://developer.spotify.com/dashboard> で「Create app」（Spotify Premium が必要です）
   2. Redirect URIs に `http://127.0.0.1:8888/callback` を追加（`localhost` は不可）
   3. 「Web API」にチェックして保存し、Settings の **Client ID** を控える

## 使い方

1. フォルダ内の **`setlist2spotify.bat` をダブルクリック**（またはターミナルで `python -m setlist2spotify`）
2. 入力方法を選ぶ
   - **1: まとめて貼り付ける** … 右クリックまたは Ctrl+V で貼り付け、最後に新しい行で `end` と入力して Enter
   - **2: 1 曲ずつ手で入力する** … 「1 曲目:」「2 曲目:」と聞かれるので曲名を入力。全部入れたら何も入力せずに Enter
3. 聞かれたらアーティスト名を入力（例: `AKB48`。検索精度が上がります）
4. 読み取った曲の一覧を確認
   - `a` … 曲を追加（1 曲ずつ入力）
   - `d 3` … 3 曲目を削除
   - `e 3` … 3 曲目を修正
   - 何も入力せず Enter … 次へ
5. 初回だけ Client ID を聞かれるので入力（以降は保存されます）
6. 初回だけブラウザが開くので、Spotify で「同意する」を押す
7. 自信のない曲は候補が表示されるので番号で選ぶ（Enter でスキップ）
8. プレイリスト名を入力し、「作成しますか？」で Enter
9. 「完成しました！」と URL が表示され、ブラウザでプレイリストが開きます

> `--dry-run` を付けて実行した場合は、検索結果の確認だけでプレイリストは作成されません。

### その他の使い方

```powershell
# 検索結果だけ確認（プレイリストは作らない）
python -m setlist2spotify --dry-run

# 最初から手入力モードで始める
python -m setlist2spotify --type --artist AKB48

# コピーした内容をそのまま使う（貼り付け不要）
python -m setlist2spotify --clipboard --artist AKB48

# テキストファイルから読み込む
python -m setlist2spotify setlist.txt --artist AKB48 --name "春コンサート2026"
```

| オプション | 説明 |
|---|---|
| `--artist` | アーティスト名（指定すると入力を聞かれません） |
| `--name` | プレイリスト名 |
| `--public` | 公開プレイリストとして作成（既定は非公開） |
| `--dry-run` | 検索だけしてプレイリストは作らない |
| `--yes` | 確認や候補選択をせず自動で進める |
| `--threshold 0.75` | 自動で採用する一致度（0〜1）。下げると候補選択が減る |
| `--client-id` | Client ID を指定（一度指定すると保存されます） |

## Spotify での曲の探し方

- 「曲名＋アーティスト名」→「フリーワード」→「曲名だけ」の順に検索します
- カタカナ/ひらがな・全角/半角・記号の違いを吸収して、曲名とアーティスト名の近さを点数にします
- カラオケ・オフボーカル・オルゴール・カバーなどの音源は点数を下げます
- 見つからなかった曲は、プレイリストの説明欄に「未収録」として書き残します

## 補足

- Spotify の 2026 年 2 月の Web API 変更に対応しています（`POST /me/playlists`、`POST /playlists/{id}/items`、検索 `limit` 上限 10）
- 開発者モードのアプリは、登録者本人と「User Management」に追加した最大 5 人まで使えます
- Client ID とログイン情報は `C:\Users\<ユーザー名>\.cache\setlist2spotify\` に保存されます

## テスト

```bash
python -m pip install -r requirements-dev.txt
python -m pytest
```
