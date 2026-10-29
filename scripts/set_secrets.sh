#!/usr/bin/env bash
# .env의 OPENAI_API_KEY·DISCORD_WEBHOOK_URL을 GitHub Actions Secrets로 등록한다.
# 어느 폴더에서 실행해도 이 스크립트 옆 폴더의 .env를 읽고, 값은 화면에 찍지 않는다.
# 상대 경로로 실행했다가 .env를 못 찾아 빈 값이 등록된 일이 있어서, 없거나 비면 아무것도 등록하지 않고 멈춘다.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$ROOT/.env"
REPO="Lightnine999/my-newsletter-agent"

if [ ! -f "$ENV_FILE" ]; then
  echo "중단: $ENV_FILE 가 없어요." >&2
  exit 1
fi

for KEY in OPENAI_API_KEY DISCORD_WEBHOOK_URL; do
  VALUE="$(grep "^${KEY}=" "$ENV_FILE" | head -1 | cut -d= -f2- || true)"
  if [ -z "$VALUE" ]; then
    echo "중단: .env에 ${KEY} 값이 비어 있어요. 아무것도 등록하지 않았어요." >&2
    exit 1
  fi
done

for KEY in OPENAI_API_KEY DISCORD_WEBHOOK_URL; do
  grep "^${KEY}=" "$ENV_FILE" | head -1 | cut -d= -f2- | gh secret set "$KEY" -R "$REPO"
  echo "  ${KEY}: $(grep "^${KEY}=" "$ENV_FILE" | head -1 | cut -d= -f2- | wc -c | tr -d ' ')자 등록"
done
echo "완료: Secrets 두 개를 등록했어요."
