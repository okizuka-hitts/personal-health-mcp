# 要件定義書

> **このドキュメントはClaude Codeへの指示書を兼ねます。**
> AIが実装判断に必要なコンテキストをすべてこのドキュメントに集約してください。

**バージョン:** v1.4
**更新日:** 2026-04-08

---

## 1. プロジェクト概要

| 項目 | 内容 |
|------|------|
| プロジェクト名 | personal-health-mcp（タニタ体組成データ取得モジュール） |
| 作成日 | 2026-04-08 |
| 担当者 | Hiromichi（HITTS Labs） |
| 想定期間 | 2026 Q2 中旬まで |

### 背景・目的

`personal-health-mcp` は、個人の健康データを AI エージェントが自然言語で参照できるようにする MCP サーバーである。本ドキュメントは、そのうち **タニタ ヘルスプラネット API 経由の体組成データ取得** に関するモジュールの要件を定義する。

タニタ ヘルスプラネット API の OAuth 2.0 認証および体組成データ取得は、PoC（`health-planet-cli`）で動作確認済みである。本モジュールはその検証成果を MCP サーバーとして実用化する。

### ゴール（1文で）

タニタ ヘルスプラネット API から体組成データ（体重・体脂肪率）を取得し、MCP ツールとして Claude 等の AI エージェントに提供できる状態にする。

---

## 2. AIへのコンテキスト（Claude Code用）

### このプロジェクトで大切にすること

- **優先順位**: 動作の確実さ > コードの洗練さ。Claude Desktop から MCP ツールとして呼び出せることが最優先。
- **避けたいこと**: 不要な依存ライブラリの追加、過度な抽象化。シングルパッケージ構成を維持する（モノレポ化しない）。
- **コードスタイル**: 型ヒント必須、docstring は公開メソッドのみ、`async/await` で I/O 処理を統一する。
- **OSS 公開前提**: README・CLAUDE.md を整備できる品質・構成にする。MIT ライセンス。
- **個人用途**: 収益化・マルチユーザー対応は対象外。自分のデータを AI が参照できることだけを目指す。

### アーキテクチャ上の制約（なぜこの設計か）

本モジュールは `personal-health-mcp` リポジトリ内の一部として実装する。BLE 心拍計収集処理（別プロセス）と MCP サーバーはプロセスを分離する設計になっており、タニタ API はプロセス分離の必要がないため MCP サーバープロセス内で直接呼び出す。

SQLite キャッシュは Phase 1 要件（後述）であり、省略しない。API レスポンスをそのつど外部 API に投げる構成は採用しない。

`auth.py` は `--reset-profile` フラグ経由で `storage/sqlite.py` の `profile` テーブル削除を呼び出す。個人用途のシングルユーザー設計として意図的に許容する依存関係であり、将来的な分離は不要と判断している。

### 既存コードベースの状況

- 新規リポジトリ（既存コードなし）
- HITTS Labs GitHub organization 配下に作成予定
- BLE 心拍計モジュール（`ble-hr-monitor` の Python + Bleak 実装）と同一リポジトリ内に共存する予定
- タニタ API の OAuth 2.0 フローおよびレスポンス構造は PoC で確認済み

---

## 3. 技術スタック・制約

### 使用技術

| カテゴリ | 技術 |
|----------|------|
| 言語 | Python 3.12 |
| MCP フレームワーク | FastMCP |
| HTTP クライアント | httpx（async 対応） |
| OAuth 2.0 | authlib |
| データ永続化 | SQLite（標準ライブラリ `sqlite3`） |
| 設定管理 | python-dotenv（`.env` 読み込み・書き戻し） |
| 依存管理 | pyproject.toml（requirements.txt は作成しない） |
| 実行環境 | Windows ネイティブ Python |

### 制約事項

- **認証情報の管理**: クライアント ID・シークレット・リフレッシュトークン等は `.env` ファイルで管理する。コードおよびコミット履歴に含めない。
- **プロフィール情報の管理**: 生年月日・身長・性別は `.env` ではなく、タニタ ヘルスプラネット API のレスポンス（`/status` エンドポイント）から取得する。ハードコードおよび `.env` への記載を禁止する。
- **MCP サーバーは読み取り専用**: タニタ API への書き込み操作（データ削除等）は実装しない。
- **シングルユーザー前提**: マルチユーザー対応・認証分離は対象外。
- **WSL2 での BLE 不可**: 実行環境は Windows ネイティブ Python。タニタモジュール単体は WSL2 でも動作可能だが、リポジトリ全体の実行環境は Windows を前提とする。

---

## 4. タニタ ヘルスプラネット API 仕様（実装に必要な情報）

### 認証フロー

OAuth 2.0 Authorization Code Flow。以下のエンドポイントを使用する。

| エンドポイント | 用途 |
|---|---|
| `https://www.healthplanet.jp/oauth/auth` | 認可エンドポイント |
| `https://www.healthplanet.jp/oauth/token` | トークンエンドポイント |

- アクセストークンの有効期限: **3時間**
- リフレッシュトークンの有効期限: **30日間**
- リフレッシュトークンは `.env` に保存し、期限切れ前に自動更新する。

### 初回認証フロー（ワンショット認証 CLI）

MCP サーバーとは別に、初回認証を完結させるための CLI スクリプトをスコープに含める。

```
python -m health_mcp.tanita.auth
```

**実行フロー：**

1. `.env` から `CLIENT_ID`・`CLIENT_SECRET`・`REDIRECT_URI` を読み込む
2. 認可 URL を生成してターミナルに出力する
3. ユーザーがブラウザで認可 URL を開き、「アクセスを許可」をクリックする
4. リダイレクト先の URL に含まれる `code` パラメータをターミナルに貼り付ける
5. スクリプトがトークンエンドポイントを呼び出し、`ACCESS_TOKEN`・`REFRESH_TOKEN`・`TOKEN_EXPIRES_AT` を取得する
6. 取得したトークンを **`.env` ファイルに直接書き込む**

**README の「初回認証手順」にこのスクリプトの実行手順を記載する。**

### トークン自動更新と `.env` 書き戻し

個人用途のシングルユーザー設計のため、トークン更新後は **`.env` ファイルを直接上書き** する方針とする。別途 `.tokens` ファイルを用意しない。

- MCP サーバー起動時・および各ツール呼び出し時にアクセストークンの有効期限（`TOKEN_EXPIRES_AT`）を確認する
- 有効期限まで残り**30分以内**の場合、リフレッシュトークンで自動更新し、新しいトークンを `.env` に書き戻す
- `.env` の書き戻しは `python-dotenv` の `set_key()` を使用する（ファイル全体の再生成ではなく対象キーのみ更新）
- リフレッシュトークン自体も更新された場合は同様に `.env` を更新する

### データ取得エンドポイント

```
GET https://www.healthplanet.jp/status/innerscan.json
```

**主要クエリパラメータ**

| パラメータ | 説明 |
|---|---|
| `access_token` | アクセストークン |
| `date` | 日付タイプ（`0`=登録日, `1`=測定日） |
| `from` | 取得開始日時（`yyyyMMddHHmmss` 形式、例: `20260401000000`） |
| `to` | 取得終了日時（`yyyyMMddHHmmss` 形式、例: `20260407235959`） |
| `tag` | 取得するデータ種別（複数指定可、カンマ区切り） |

**取得対象タグ**

| タグ | データ種別 |
|---|---|
| `6021` | 体重（kg） |
| `6022` | 体脂肪率（%） |

> **注意**: タグ 6023〜6029（筋肉量・基礎代謝・BMI 等）は廃止済み（Discontinued）のため取得対象外とする。

**レスポンス例**

```json
{
  "birth_date": "19860101",
  "height": "175.0",
  "sex": "male",
  "data": [
    {
      "date": "202604071230",
      "keydata": "70.5",
      "model": "BC-705N",
      "tag": "6021"
    },
    {
      "date": "202604071230",
      "keydata": "18.2",
      "model": "BC-705N",
      "tag": "6022"
    }
  ]
}
```

- `birth_date`・`height`・`sex` はレスポンスのトップレベルに含まれる。これをプロフィール情報のソースとして使用する。
- `date` は `yyyyMMddHHmm` 形式の12桁文字列（例: `"202604071230"`）。リクエストの `from`・`to` は秒まで含む14桁だが、レスポンスの `date` は分までの12桁である点に注意。
- 取得範囲は最大 **3ヶ月**（API 制限）。

---

## 5. SQLite キャッシュ設計

### 目的

- タニタ API のレート制限回避
- MCP ツール呼び出しのレスポンス高速化
- オフライン時の参照継続

### テーブル設計

**`profile` テーブル**

| カラム名 | 型 | 説明 |
|---|---|---|
| `id` | INTEGER (PK) | 常に1件のみ保持（`id=1` 固定） |
| `birth_date` | TEXT | 生年月日（`YYYYMMDD` 形式） |
| `height_cm` | REAL | 身長（cm） |
| `sex` | TEXT | 性別（`male` / `female`） |
| `fetched_at` | TEXT | 取得日時（ISO 8601形式） |

**`body_composition` テーブル**

| カラム名 | 型 | 説明 |
|---|---|---|
| `measured_at` | TEXT (PK) | 測定日時（ISO 8601形式、例: `2026-04-07T12:30:00`） |
| `weight_kg` | REAL | 体重（kg）。未取得の場合は NULL |
| `body_fat_pct` | REAL | 体脂肪率（%）。未取得の場合は NULL |
| `created_at` | TEXT | レコード挿入日時 |

**`sync_log` テーブル**

| カラム名 | 型 | 説明 |
|---|---|---|
| `id` | INTEGER (PK, AUTOINCREMENT) | |
| `synced_at` | TEXT | 同期実行日時（ISO 8601形式） |
| `from_date` | TEXT | 取得対象の開始日 |
| `to_date` | TEXT | 取得対象の終了日 |
| `record_count` | INTEGER | 取得・挿入したレコード数 |

### キャッシュ更新方針

- `get_body_composition`・`get_latest_body_composition` 呼び出し時、**リクエストの `start_date`〜`end_date` の範囲**のうち、`sync_log` に記録がない期間のみ API を呼び出す（差分同期）。全期間を毎回取得し直さない。
- `end_date` が今日を含む場合、当日分は `sync_log` の最終同期時刻から **`CACHE_TTL_SECONDS`（デフォルト: 3600秒）以上** 経過している場合のみ再同期する。同日中に複数回呼び出されても TTL 内であればキャッシュを返す。
- キャッシュが存在しない場合（初回起動時等）は即座に API を呼び出す。
- `UPSERT`（INSERT OR REPLACE）を使用し、同一 `measured_at` のデータは上書きする。

**`CACHE_TTL_SECONDS` の役割まとめ**

| 対象 | 動作 |
|---|---|
| 過去日付のデータ（今日より前） | 一度同期したら再同期しない（TTL 不適用） |
| 当日のデータ | `CACHE_TTL_SECONDS` 以内の再呼び出しはキャッシュを返す |
| プロフィール（`profile` テーブル） | TTL なし・`--reset-profile` のみで更新 |

### Windows 環境での asyncio に関する注意

Windows では `asyncio` のデフォルトイベントループが `ProactorEventLoop` になるため、`httpx` の非同期クライアントと干渉する場合がある。FastMCP がこれを透過的に処理するか確認する（受け入れ条件の実機確認 DoD として記載）。FastMCP が吸収しない場合は `server.py` で以下を設定する。

```python
import asyncio
asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
```

---

## 6. 機能要件（MCP ツール仕様）

### 提供する MCP ツール一覧

| ツール名 | 概要 | 優先度 |
|---|---|---|
| `get_latest_body_composition` | 最新の体組成データを1件取得 | Must |
| `get_body_composition` | 指定日付範囲の体組成データを取得 | Must |
| `get_measurements_range` | データが存在する日付範囲を返す | Must |
| `get_profile` | ユーザーの基本プロフィール（生年月日・身長・性別）を取得 | Must |
| `list_available_metrics` | 取得可能なメトリクスの一覧と説明を返す | Must |

> **注意**: 心拍数関連ツール（`get_latest_heart_rate`・`get_heart_rate`）は別モジュール（BLE 収集プロセス）が担当するため本ドキュメントのスコープ外。

---

### T-01: `get_latest_body_composition`

**目的**

最新の体組成データ（体重・体脂肪率）を1件返す。「最近の体重は？」という AI からの問いに答える。

**入力（引数なし）**

**出力（JSON）**

```json
{
  "measured_at": "2026-04-07T12:30:00",
  "weight_kg": 70.5,
  "body_fat_pct": 18.2
}
```

**エラー時**

```json
{
  "error": "No data available"
}
```

**処理フロー**

1. 差分同期ロジックに従いキャッシュ更新を判定する（セクション5「キャッシュ更新方針」参照）。`get_latest_body_composition` の場合、直近30日を対象範囲として差分同期を実行する。
2. SQLite から `measured_at` が最新の1件を返す。

> **仕様上の制限**: 直近30日に測定データが存在しない場合は `"error": "No data available"` を返す。30日以上前のデータを取得したい場合は `get_body_composition(start_date=...)` で明示的に範囲を指定すること。

---

### T-02: `get_body_composition`

**目的**

指定した日付範囲の体組成データを返す。「先月の体重の推移を教えて」という問いに答える。

**入力**

| パラメータ | 型 | 必須 | デフォルト | 説明 |
|---|---|---|---|---|
| `start_date` | string | No | 30日前 | 取得開始日（`YYYY-MM-DD` 形式） |
| `end_date` | string | No | 今日 | 取得終了日（`YYYY-MM-DD` 形式） |

**制約**

- 指定可能な最大範囲は **92日間（約3ヶ月）**。超過する場合はエラーを返す。
- `start_date` > `end_date` の場合はエラーを返す。

**出力（JSON）**

```json
{
  "start_date": "2026-03-08",
  "end_date": "2026-04-07",
  "count": 8,
  "data": [
    {
      "measured_at": "2026-04-07T12:30:00",
      "weight_kg": 70.5,
      "body_fat_pct": 18.2
    }
  ]
}
```

- `data` は `measured_at` の降順（新しい順）で返す。

**処理フロー**

1. パラメータのバリデーション
2. キャッシュ更新判定
3. SQLite から指定範囲のレコードを返す

---

### T-03: `get_measurements_range`

**目的**

SQLite に保存されているデータの日付範囲（最古・最新）と総件数を返す。AI が「どの期間のデータがあるか」を把握するために使う。

**入力（引数なし）**

**出力（JSON）**

```json
{
  "oldest_measurement": "2026-01-10T08:15:00",
  "latest_measurement": "2026-04-07T12:30:00",
  "total_count": 42
}
```

**データが存在しない場合**

```json
{
  "oldest_measurement": null,
  "latest_measurement": null,
  "total_count": 0,
  "message": "No data in cache. Please call get_body_composition to sync data first."
}
```

> `get_measurements_range` は SQLite を直接参照するのみで API 呼び出しを行わない。初回起動時等でキャッシュが空の場合は上記のように `message` フィールドで同期を促す。

---

### T-04: `get_profile`

**目的**

ユーザーの基本プロフィール（生年月日・身長・性別）を返す。LLM が BMI 計算・年齢計算・心拍ゾーン推定（最大心拍数の算出等）などを行う際の前提情報として使う。

**入力（引数なし）**

**出力（JSON）**

```json
{
  "birth_date": "19860101",
  "height_cm": 175.0,
  "sex": "male"
}
```

- `birth_date` は `YYYYMMDD` 形式の文字列。年齢への変換は LLM 側で行う。
- `height_cm` は数値（float）。API レスポンスの文字列 `"175.0"` をパースして返す。
- `sex` は API レスポンスの値をそのまま返す（`"male"` / `"female"`）。

**処理フロー**

1. SQLite の `profile` テーブルにキャッシュが存在する場合はそれを返す。
2. キャッシュがない場合は `innerscan` エンドポイントを、**当日の `00:00:00`〜`23:59:59`** を `from`・`to` として呼び出す。測定データが0件でもレスポンスのトップレベルにプロフィール情報（`birth_date`・`height`・`sex`）は返るという前提で実装する（実機確認 DoD として後述）。
3. レスポンスのトップレベルから `birth_date`・`height`・`sex` を取得してキャッシュに保存する。
4. プロフィール情報はユーザーが変更しない限り不変のため、TTL は設けず手動リフレッシュ（後述）でのみ更新する。

**プロフィールキャッシュの手動リフレッシュ**

プロフィール情報（身長・性別等）を更新した場合は、以下のコマンドでキャッシュをクリアする。次回 `get_profile` 呼び出し時に自動で再取得される。README に手順を明記する。

```bash
python -m health_mcp.tanita.auth --reset-profile
```

> **注意**: プロフィール情報を取得するための専用エンドポイントはない。`innerscan` エンドポイントのレスポンストップレベルに含まれる値を流用する。

---

### T-05: `list_available_metrics`

**目的**

このMCPサーバーが提供するメトリクスの一覧と説明を返す。AI がどのツールを呼び出すべきかを判断するためのメタ情報として機能する。

**入力（引数なし）**

**出力（JSON）**

```json
{
  "metrics": [
    {
      "name": "weight_kg",
      "description": "体重（kg）",
      "source": "Tanita Health Planet API",
      "tool": "get_latest_body_composition / get_body_composition"
    },
    {
      "name": "body_fat_pct",
      "description": "体脂肪率（%）",
      "source": "Tanita Health Planet API",
      "tool": "get_latest_body_composition / get_body_composition"
    },
    {
      "name": "profile",
      "description": "生年月日・身長・性別（BMI計算・年齢計算・心拍ゾーン推定の前提情報）",
      "source": "Tanita Health Planet API",
      "tool": "get_profile"
    }
  ]
}
```

---

## 7. 非機能要件

| 項目 | 要件 |
|------|------|
| パフォーマンス | キャッシュが有効な場合、MCP ツール呼び出しから応答まで **1秒以内** |
| エラーハンドリング | API エラー（認証失敗・タイムアウト等）は JSON エラーオブジェクトを返し、MCP サーバープロセスをクラッシュさせない |
| ログ | 通常動作時は最小限のログのみ。`LOG_LEVEL=DEBUG` を `.env` に設定することで API リクエスト/レスポンスの詳細を出力する（MCP サーバーは Claude Desktop から起動されるため CLI フラグより環境変数が適切） |
| セキュリティ | アクセストークン・リフレッシュトークンを SQLite・ログに永続化しない。`.env` のみに保持する |
| 可観測性 | `sync_log` テーブルへの記録により、AI から「最後にデータを同期したのはいつか」を確認できる |

---

## 8. 設定ファイル（`.env`）

`.env` に記載する項目と意味を以下に示す。Claude Code は `.env.example` をコードに含め、実際の値を含む `.env` は `.gitignore` で除外する。

```dotenv
# タニタ ヘルスプラネット API
HEALTH_PLANET_CLIENT_ID=your_client_id
HEALTH_PLANET_CLIENT_SECRET=your_client_secret
HEALTH_PLANET_REDIRECT_URI=http://localhost:8080/callback

# OAuth トークン（python -m health_mcp.tanita.auth 実行後に自動設定）
HEALTH_PLANET_ACCESS_TOKEN=
HEALTH_PLANET_REFRESH_TOKEN=
HEALTH_PLANET_TOKEN_EXPIRES_AT=

# SQLite キャッシュ
SQLITE_DB_PATH=./data/health.db

# キャッシュ更新間隔（秒）
CACHE_TTL_SECONDS=3600

# ログレベル（DEBUG にすると API リクエスト/レスポンスの詳細を出力）
LOG_LEVEL=INFO
```

> **プロフィール情報（生年月日・身長・性別）はここに記載しない。** タニタ API のレスポンスから取得する。

**使用ライブラリへの補足：** `.env` の読み込みには `python-dotenv` を使用する。トークン自動更新時の書き戻しには `python-dotenv` の `set_key()` を使用し、ファイル全体を再生成しない。`python-dotenv` を `pyproject.toml` の依存ライブラリに追加すること。

---

## 9. ディレクトリ構成（想定）

```
personal-health-mcp/
├── pyproject.toml
├── .env.example
├── .gitignore
├── README.md
├── CLAUDE.md
├── LICENSE
├── data/                        # SQLite DB（.gitignore で除外）
│   └── health.db
└── src/
    └── health_mcp/
        ├── __init__.py
        ├── server.py            # FastMCP エントリーポイント
        ├── tanita/
        │   ├── __init__.py
        │   ├── auth.py          # OAuth 2.0 認証・トークン管理・初回認証CLI（python -m health_mcp.tanita.auth）
        │   │                    # ※ TokenManager クラスでインメモリのトークン状態を一元管理する。
        │   │                    #    .env 書き戻し（set_key）とメモリ上の状態更新を同時に行い、
        │   │                    #    プロセス再起動なしにトークンが有効な状態を維持する。
        │   ├── client.py        # ヘルスプラネット API クライアント
        │   └── models.py        # データモデル（dataclass）
        └── storage/
            ├── __init__.py
            └── sqlite.py        # SQLite 読み書き
```

---

## 10. 受け入れ条件・完了定義

> **Done の定義**: 以下をすべて満たした状態を「完了」とする。

### 機能面

- [ ] 初回認証: `python -m health_mcp.tanita.auth` を実行すると認可 URL が表示され、コード入力後に `.env` にトークンが書き込まれる
- [ ] トークン自動更新: アクセストークン期限切れ時にリフレッシュトークンで自動更新され、新しいトークンが `.env` に書き戻されるとともにメモリ上の TokenManager 状態も更新される
- [ ] T-01: Claude Desktop から `get_latest_body_composition` を呼び出すと最新の体重・体脂肪率が返る
- [ ] T-02: `get_body_composition` に `start_date`・`end_date` を渡すと該当期間のデータ一覧が返る
- [ ] T-02: 92日超の範囲を指定するとエラーが返る
- [ ] T-02: 未同期の日付範囲のみ API を呼び出し、既同期範囲は SQLite から返す（差分同期）
- [ ] T-02: `end_date` が今日の場合、`CACHE_TTL_SECONDS` 以内の再呼び出しはキャッシュを返し、API を呼ばない
- [ ] T-03: `get_measurements_range` がデータの最古・最新日時と件数を返す
- [ ] T-03: キャッシュが空の場合、`message` フィールドで同期を促すレスポンスが返る
- [ ] T-04: `get_profile` が生年月日・身長・性別を返す
- [ ] T-04: プロフィールが SQLite にキャッシュされ、2回目以降は API を呼ばない
- [ ] T-04: `--reset-profile` フラグでプロフィールキャッシュがクリアされる
- [ ] T-05: `list_available_metrics` がメトリクス一覧を返す

### 実機確認による仕様確定

- [ ] `data` が空配列のレスポンスでもトップレベルの `birth_date`・`height`・`sex` が返ることを実機確認し、T-04 のプロフィール取得前提を確定している
- [ ] Windows 環境で FastMCP が `asyncio` のイベントループポリシーを透過的に処理するか確認し、必要であれば `server.py` に `WindowsSelectorEventLoopPolicy` を追加している

### 品質面

- [ ] `README.md` にインストール手順・初回認証手順・Claude Desktop への登録方法が記載されている
- [ ] `CLAUDE.md` にリポジトリ構成・開発上の注意点が記載されている
- [ ] `.env.example` が含まれており、実際の値を含む `.env` は `.gitignore` で除外されている
- [ ] MIT ライセンス（`LICENSE` ファイル）が含まれている
- [ ] タニタ API クライアントの単体テストが `httpx` のモックで整備されている
- [ ] SQLite 読み書きの単体テストが in-memory DB（`:memory:`）で整備されている
- [ ] GitHub Actions（ubuntu-latest）で Lint（ruff）・型チェック（mypy）・モックテストが自動実行される

### Claude Codeへの確認事項

- [ ] `health_mcp/tanita/__main__.py`（または `auth.py` の `if __name__ == "__main__"` ブロック）が存在し、`python -m health_mcp.tanita.auth` で起動できるか（`[project.scripts]` は名前付き CLI コマンド用であり、`python -m` 形式とは別）
- [ ] `TokenManager` クラス（またはそれに相当する設計）でインメモリのトークン状態を一元管理し、`.env` 書き戻しとメモリ上の状態更新を同時に行っているか（`set_key()` だけでは `os.environ` は更新されないため）
- [ ] トークン書き戻しに `python-dotenv` の `set_key()` を使用し、`.env` 全体を再生成していないか
- [ ] トークン有効期限のチェックが残り30分以内をトリガーとしているか
- [ ] タニタ API レスポンスのプロフィール情報（`birth_date`・`height`・`sex`）を `.env` ではなくレスポンスから取得しているか
- [ ] `get_profile` のプロフィールキャッシュ（`profile` テーブル）に TTL を設けず、`--reset-profile` のみで更新する設計になっているか
- [ ] T-04 のプロフィール取得時の `innerscan` リクエストが当日の `00:00:00`〜`23:59:59` 範囲になっているか
- [ ] `height_cm` が API レスポンスの文字列 `"175.0"` から float にパースされているか
- [ ] `get_body_composition` のキャッシュ更新が差分同期（未同期範囲のみ API 呼び出し）になっているか
- [ ] `end_date` が今日を含む場合に、`CACHE_TTL_SECONDS` 経過後のみ当日分を再同期しているか（毎回 API を叩いていないか）
- [ ] `LOG_LEVEL` 環境変数でログレベルを制御しており、`--verbose` フラグを使っていないか
- [ ] Windows での `asyncio` イベントループポリシー問題を考慮しているか（FastMCP が吸収しない場合の対応を確認）
- [ ] タグ 6023〜6029（筋肉量・基礎代謝・BMI 等）の取得を実装していないか（廃止済みタグ）
- [ ] アクセストークン・リフレッシュトークンが SQLite・ログに書き出されていないか
- [ ] `get_body_composition` の範囲上限（92日）チェックが実装されているか
- [ ] `data/` ディレクトリが `.gitignore` に含まれているか
- [ ] FastMCP の MCP サーバーとして `pyproject.toml` に `[project.scripts]` エントリーポイントが定義されているか
- [ ] 心拍数関連の処理を本モジュールに混入させていないか（BLE モジュールと責務を分離する）

---

## 11. スコープ外（今回やらないこと）

- BLE 心拍計（COOSPO H9Z）の接続・取得（別モジュールが担当）
- タグ 6023〜6029（筋肉量・基礎代謝・BMI 等）の取得（廃止済み）
- タニタ API へのデータ書き込み・削除
- Web UI・ダッシュボード
- クラウドホスティング（Supabase 等への移行は将来フェーズ）
- マルチユーザー対応
- Apple Health・Garmin 等の追加データソース
- 心拍ゾーン計算等の派生指標（LLM 側で計算する）

---

## 12. 参考情報・リンク

- タニタ ヘルスプラネット API ドキュメント: https://www.healthplanet.jp/apis/api.html
- FastMCP ドキュメント: https://gofastmcp.com/
- httpx ドキュメント: https://www.python-httpx.org/
- authlib ドキュメント: https://docs.authlib.org/
- 関連リポジトリ（BLE CLI 版）: `ble-hr-monitor`
- MCP サーバー企画書: `健康データ MCP サーバー — 企画書`

---

## 13. 変更履歴

| バージョン | 更新日 | 主な変更内容 |
|---|---|---|
| v1.0 | 2026-04-08 | 初版 |
| v1.1 | 2026-04-08 | `get_profile` ツール追加・`profile` テーブル追加・`list_available_metrics` のメトリクス一覧更新 |
| v1.2 | 2026-04-08 | レビュー対応: 初回認証 CLI 追加・トークン書き戻し設計明記・差分同期設計・T-04 プロフィール取得の from/to 範囲明記・T-03 未同期時メッセージ追加・LOG_LEVEL 環境変数化・asyncio ポリシー注記・python-dotenv 追加 |
| v1.3 | 2026-04-08 | レビュー対応: T-01 処理フローを差分同期設計に統一・CACHE_TTL_SECONDS の役割を当日再同期間隔として明確化・TokenManager によるインメモリトークン管理を設計方針に追記・python -m 形式は __main__.py で実現する旨を確認事項に修正 |
| v1.4 | 2026-04-08 | レビュー対応: T-01 の30日制限を仕様として明記（案B採用）・auth.py → sqlite.py の依存を設計方針に明記 |
