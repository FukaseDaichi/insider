# AGENTS.md

## Python は uv で扱う

Python の実行と依存の管理はすべて uv で行う。`pip` やシステムの `python` は直接使わない。

- 実行: `uv run python ...`、テスト: `uv run pytest`
- `.env` が要るときは `uv run --env-file .env ...`
- 依存の追加・削除は `uv add` / `uv remove`（`pyproject.toml` と `uv.lock` は手で書き換えない）
