#!/bin/sh
# bidr sarmalayıcısı: sandbox'lı ajan ortamı (Codex, Claude Code sandbox; yalnız çalışma klasörüne
# yazılabilir, `export X=…` / `X=… komut` biçimi izin ister). Geçici klasörü ve paket önbelleklerini
# repo içindeki git dışı `_tmp/`'ye alıp komutu çalıştırır; ortam değişkenini ajanın kendisi
# vermek zorunda kalmaz. Gerçek veri buraya yazılmaz: çalışma alanı yine repo dışındadır.
#
#   sh tools/sandbox.sh kur                 # .venv + bidr (uv varsa uv, yoksa python3 -m venv + pip)
#   sh tools/sandbox.sh pytest -q           # test paketi
#   sh tools/sandbox.sh next -w <alan>      # her bidr komutu: sh tools/sandbox.sh <bidr argümanları>
#
# Windows PowerShell'de karşılığı README "Sandbox'lı ajan ortamı" bölümündedir.
set -eu

REPO=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
T="$REPO/_tmp"
mkdir -p "$T/tmp" "$T/uv-cache" "$T/pip-cache"
TMPDIR="$T/tmp"
UV_CACHE_DIR="$T/uv-cache"
PIP_CACHE_DIR="$T/pip-cache"
export TMPDIR UV_CACHE_DIR PIP_CACHE_DIR

case "${1:-}" in
  ""|-h|--help|yardim)
    sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'
    ;;
  kur)
    cd "$REPO"
    if command -v uv >/dev/null 2>&1; then
      uv venv && uv pip install -e '.[dev]'
    else
      python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
    fi
    .venv/bin/bidr --help >/dev/null && echo "kuruldu: $REPO/.venv (bidr komutu: sh $REPO/tools/sandbox.sh)"
    ;;
  pytest)
    shift
    cd "$REPO"
    [ -x .venv/bin/python ] || { echo "bidr kurulu değil: önce sh tools/sandbox.sh kur" >&2; exit 2; }
    exec .venv/bin/python -m pytest "$@"
    ;;
  *)
    # `bidr next` / AGENTS.md komutları da bu sarmalayıcıyla yazılsın (bidr.pipeline.state.bidr_command)
    BIDR_SARMALAYICI="$REPO/tools/sandbox.sh"
    export BIDR_SARMALAYICI
    [ -x "$REPO/.venv/bin/bidr" ] || { echo "bidr kurulu değil: önce sh tools/sandbox.sh kur" >&2; exit 2; }
    exec "$REPO/.venv/bin/bidr" "$@"
    ;;
esac
