#!/usr/bin/env bash
# Downloads BIRD Mini-Dev (CC BY-SA 4.0) into data/bird_minidev.
# - SQLite databases: the official 2024 package (800 MB zip, MD5 checked)
# - Questions: the July 2025 update from Hugging Face (500 questions)
set -euo pipefail

DEST="data/bird_minidev"
ZIP_URL="https://bird-bench.oss-cn-beijing.aliyuncs.com/minidev.zip"
ZIP_MD5="7beb6dab11e65f0fde563e644a1ea319"
HF="https://huggingface.co/datasets/birdsql/bird_mini_dev/resolve/main/data"

mkdir -p "$DEST"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "Downloading databases (800 MB, resumable)..."
for attempt in 1 2 3 4 5 6 7 8; do
  if curl -fSL -C - --retry 5 --retry-all-errors -o "$TMP/minidev.zip" "$ZIP_URL"; then break; fi
  echo "Retrying ($attempt)..."
done
echo "$ZIP_MD5  $TMP/minidev.zip" | md5sum -c -

unzip -q "$TMP/minidev.zip" -d "$TMP/x"
rm -rf "$DEST/dev_databases"
mv "$TMP/x/minidev/MINIDEV/dev_databases" "$DEST/"
cp "$TMP/x/minidev/MINIDEV/mini_dev_sqlite.json" "$DEST/mini_dev_sqlite_2024.json"

echo "Downloading questions..."
curl -fSL -o "$DEST/mini_dev_sqlite_2025.json" "$HF/mini_dev_sqlite-00000-of-00001.json"

echo "Caching gold results (takes about 7 minutes; two gold queries are slow)..."
uv run sqlagent cache-gold
echo "Done."
