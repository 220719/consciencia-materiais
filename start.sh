#!/usr/bin/env bash
# Sobe a Rede de Materiais e relança o Streamlit se o processo cair.
set -u
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
PORT="${PORT:-8502}"

parar() {
  echo
  echo "Encerrando Rede de Materiais."
  exit 0
}
trap parar INT TERM

if command -v fuser >/dev/null 2>&1; then
  fuser -k "${PORT}/tcp" >/dev/null 2>&1 || true
  sleep 1
fi

echo "Rede de Materiais — http://localhost:${PORT}"
echo "Ctrl+C para parar. Se o Streamlit cair, ele reinicia sozinho."

while true; do
  uv run streamlit run app.py \
    --server.headless true \
    --server.port "$PORT" \
    --server.address 0.0.0.0 \
    --server.fileWatcherType poll \
    --browser.gatherUsageStats false
  echo "Streamlit saiu. Reiniciando em 3s..."
  sleep 3
done
