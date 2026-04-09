# personal-health-mcp

タニタ ヘルスプラネット API から体組成データ（体重・体脂肪率）を取得し、MCP ツールとして Claude Desktop 等の AI エージェントに提供します。

## セットアップ

### 1. インストール

```bash
pip install -e .
```

### 2. .env を作成

```bash
cp .env.example .env
```

`.env` を編集して `HEALTH_PLANET_CLIENT_ID`・`HEALTH_PLANET_CLIENT_SECRET`・`HEALTH_PLANET_REDIRECT_URI` を設定してください。

### 3. 初回認証

```bash
python -m health_mcp.tanita.auth
```

表示された URL をブラウザで開き、「アクセスを許可する」をクリック後、リダイレクト URL を貼り付けると `.env` にトークンが保存されます。

### 4. Claude Desktop に MCP サーバーを登録

`claude_desktop_config.json` に以下を追加してください：

```json
{
  "mcpServers": {
    "personal-health": {
      "command": "health-mcp",
      "cwd": "/path/to/personal-health-mcp"
    }
  }
}
```

## MCP ツール一覧

| ツール | 説明 |
|---|---|
| `get_latest_body_composition` | 最新の体重・体脂肪率を取得（直近30日対象） |
| `get_body_composition` | 指定期間（最大92日）の体組成データを取得 |
| `get_measurements_range` | キャッシュ内データの日付範囲と件数を確認 |
| `get_profile` | 生年月日・身長・性別を取得 |
| `list_available_metrics` | 取得可能なメトリクス一覧を表示 |

## プロフィールの再取得

タニタアプリでプロフィール情報を変更した場合：

```bash
python -m health_mcp.tanita.auth --reset-profile
```

## 開発

```bash
pip install -e ".[dev]"
pytest          # テスト
mypy src        # 型チェック
ruff check src  # リント
```
