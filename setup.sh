#!/usr/bin/env bash
# One-command installer for SupoClip (https://github.com/FujiwaraChoki/supoclip)
# Usage: ./setup.sh            -> clone, configure .env, start with Docker
#        ./setup.sh --no-start -> clone and configure only
set -euo pipefail

cd "$(dirname "$0")"
DIR="supoclip"

command -v git >/dev/null || { echo "git is required: https://git-scm.com/downloads"; exit 1; }
command -v docker >/dev/null || { echo "Docker is required: https://docs.docker.com/get-docker/"; exit 1; }
docker info >/dev/null 2>&1 || { echo "Docker is installed but not running. Start Docker Desktop and retry."; exit 1; }
if docker compose version >/dev/null 2>&1; then COMPOSE="docker compose"; else COMPOSE="docker-compose"; fi

if [ -d "$DIR/.git" ]; then
  echo "Updating existing SupoClip checkout..."
  git -C "$DIR" pull --ff-only || true
else
  git clone --depth 1 https://github.com/FujiwaraChoki/supoclip.git "$DIR"
fi

ENV_FILE="$DIR/.env"
[ -f "$ENV_FILE" ] || cp "$DIR/.env.example" "$ENV_FILE"

# set_env KEY VALUE: replace KEY=... in .env (or append it)
set_env() {
  local tmp; tmp="$(mktemp)"
  grep -v "^$1=" "$ENV_FILE" > "$tmp" || true
  printf '%s=%s\n' "$1" "$2" >> "$tmp"
  mv "$tmp" "$ENV_FILE"
}
get_env() { grep "^$1=" "$ENV_FILE" | tail -1 | cut -d= -f2- || true; }
ask() { # ask VAR "Prompt" -> keeps current value if Enter is pressed
  local cur val; cur="$(get_env "$1")"
  if [ -n "$cur" ]; then read -r -s -p "$2 [already set, Enter to keep]: " val; else read -r -s -p "$2: " val; fi
  echo
  [ -n "$val" ] && set_env "$1" "$val"
  return 0
}
rand() { LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 48; }

echo
echo "== API keys (input is hidden; press Enter to skip one) =="
ask ASSEMBLY_AI_API_KEY "AssemblyAI API key (transcription)"
ask GOOGLE_API_KEY      "Google Gemini API key"
ask OPENAI_API_KEY      "OpenAI API key"
ask ANTHROPIC_API_KEY   "Anthropic API key"

# Transcription: AssemblyAI if a key is set, otherwise local Whisper
if [ -n "$(get_env ASSEMBLY_AI_API_KEY)" ]; then
  set_env TRANSCRIPTION_PROVIDER assemblyai
else
  echo "No AssemblyAI key: using local Whisper (slower, no key needed)."
  set_env TRANSCRIPTION_PROVIDER whisper
fi

# Pick the AI model for clip selection
echo
echo "Which AI model should pick the clips?"
echo "  1) Google Gemini 3 Flash  (fast, cheap - recommended)"
echo "  2) OpenAI GPT-5.2"
echo "  3) Anthropic Claude Sonnet"
read -r -p "Choose 1-3 [1]: " choice
case "${choice:-1}" in
  2) set_env LLM "openai:gpt-5.2" ;;
  3) set_env LLM "anthropic:claude-sonnet-5-5" ;;
  *) set_env LLM "google-gla:gemini-3-flash-preview" ;;
esac

# Replace default dev secrets with random ones
[ "$(get_env BETTER_AUTH_SECRET)" = "supoclip_dev_secret_change_in_production" ] && set_env BETTER_AUTH_SECRET "$(rand)"
[ "$(get_env BACKEND_AUTH_SECRET)" = "change_me_backend_auth_secret" ] && set_env BACKEND_AUTH_SECRET "$(rand)"
set_env SELF_HOST true

echo
echo "Config written to $ENV_FILE"
[ "${1:-}" = "--no-start" ] && exit 0

echo "Building and starting SupoClip (first run takes several minutes)..."
(cd "$DIR" && $COMPOSE up -d --build)

PORT="$(get_env FRONTEND_PORT)"; PORT="${PORT:-3107}"
echo
echo "SupoClip is starting up."
echo "  App:      http://localhost:$PORT   (create an account, then paste a YouTube link)"
echo "  API docs: http://localhost:8000/docs"
echo "  Logs:     cd $DIR && $COMPOSE logs -f"
echo "  Stop:     cd $DIR && $COMPOSE down"
