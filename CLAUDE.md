# CLAUDE.md — personal-health-mcp

> 詳細な要件・API仕様・受け入れ条件は `doc/requirements-personal-health-mcp_tanita.md` を参照。

## プロジェクト概要

タニタ ヘルスプラネット API から体組成データ（体重・体脂肪率）を取得し、MCP ツールとして Claude 等の AI エージェントに提供する。
Claude Desktop から MCP ツールとして呼び出せることを最優先とする。

## 技術スタック

Python 3.12 / FastMCP / httpx（async）/ authlib / SQLite（標準ライブラリ）/ python-dotenv
依存管理は `pyproject.toml` のみ（requirements.txt は作らない）。実行環境は Windows ネイティブ Python。

## 設計上の重要な決定事項

**TokenManager（`auth.py`）**
- トークン更新時は `set_key()` による `.env` 書き戻しと `os.environ` の更新を**同時に**行う（`set_key()` だけでは `os.environ` は更新されない）
- アクセストークン有効期限まで残り30分以内でリフレッシュ

**SQLite 差分同期**
- 一度同期した過去日付は再同期しない
- 当日データは `CACHE_TTL_SECONDS`（デフォルト3600秒）以内の再呼び出しはキャッシュを返す
- プロフィールは TTL なし。`--reset-profile` のみで更新

**その他の意図的な設計**
- `auth.py` が `storage/sqlite.py` に依存する（個人用途・シングルユーザーとして許容）
- `get_latest_body_composition` は直近30日にデータがない場合 `"error": "No data available"` を返す（API仕様）

## 取得対象・コーディング制約

- 取得タグは `6021`（体重）・`6022`（体脂肪率）のみ。タグ 6023〜6029 は廃止済みのため実装しない
- アクセストークン・リフレッシュトークンを SQLite・ログに書き出さない
- プロフィール情報（生年月日・身長・性別）を `.env` にハードコードしない（API レスポンスから取得）
- ログレベルは `LOG_LEVEL` 環境変数で制御する

## Windows / asyncio

Windows では asyncio デフォルトが `ProactorEventLoop`。FastMCP が吸収しない場合は `server.py` に追加：

```python
import asyncio
asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
```

## 初回認証

```bash
python -m health_mcp.tanita.auth
```

## スコープ外

BLE 心拍計 / タグ 6023〜6029 / タニタ API へのデータ書き込み・削除 / Web UI / マルチユーザー / Apple Health・Garmin 等 / 心拍ゾーン計算（LLM 側で計算）
