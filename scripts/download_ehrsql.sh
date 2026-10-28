#!/usr/bin/env bash
# Downloads EHRSQL 2024 (CC BY 4.0) and its preprocessed MIMIC-IV demo database (ODbL 1.0) into data/ehrsql.
set -euo pipefail

DEST="data/ehrsql"
COMMIT="f9e1aa02160d39e3f8df52bf5c69c5cf2e472499"
BASE="https://raw.githubusercontent.com/glee4810/ehrsql-2024/$COMMIT/data/mimic_iv"

mkdir -p "$DEST/valid" "$DEST/test"
fetch() { curl -fSL --retry 5 -o "$DEST/$1" "$BASE/$1"; }

echo "Downloading the MIMIC-IV demo database (37 MB) and the valid and test splits..."
fetch mimic_iv.sqlite
for split in valid test; do
  fetch "$split/data.json"
  fetch "$split/label.json"
done

(cd "$DEST" && sha256sum -c - <<'SUMS'
a26a60261d7e3bbf1869ffd92efe1803abdbce3eb256a2883fc0439c63427796  mimic_iv.sqlite
eeccae3bd8ec96b1bf5ae7a1cb0e723c971a015a17ab57467bf9b027a24c3e62  valid/data.json
9addafb996119b0e4a1b05928a6d4d42f33c073fa6d72edbdf8273faa40a6db0  valid/label.json
b141da1fd5fa7e7ba8179ce87528653daa8eaa68d5510662e7a65b51cc626b42  test/data.json
307d8666440e45d35aa7852e19d32160844025592352f47a2aa0325178005450  test/label.json
SUMS
)
echo "Done."
