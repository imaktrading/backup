#!/bin/sh
# 新規環境セットアップ用: tools/hooks/* を .git/hooks/ にコピー
set -e
cd "$(dirname "$0")/.."
cp tools/hooks/pre-commit .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
echo "[install_hooks] pre-commit installed."
