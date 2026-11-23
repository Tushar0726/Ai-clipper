# Ai-clipper
AI-powered automatic video clipping system that converts livestreams into engaging short-form videos for YouTube Shorts, Instagram Reels, and TikTok, with AI-selected highlights, captions, subtitles, and 9:16 formatting.

## Setup (powered by SupoClip)

This project runs [SupoClip](https://github.com/FujiwaraChoki/supoclip) locally with Docker.

**You need:** [Docker Desktop](https://docs.docker.com/get-docker/) (running), git, and API keys:
an [AssemblyAI](https://www.assemblyai.com/) key for transcription (optional — falls back to local Whisper)
and at least one of Google Gemini / OpenAI / Anthropic for clip selection.

```bash
# macOS / Linux
./setup.sh

# Windows (PowerShell)
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

The script clones SupoClip into `supoclip/`, asks for your keys (saved only in `supoclip/.env`, which is git-ignored),
picks the AI model, generates auth secrets, and runs `docker compose up -d --build`.

Then open <http://localhost:3107>, create an account, and paste a YouTube link, e.g.
`https://www.youtube.com/watch?v=FjmYmD4hGfY`.

> **Livestreams:** SupoClip can't clip a stream while it is still live. Wait until it ends and YouTube has
> processed the replay (VOD), then paste the link. Use the `watch?v=` form if the `/live/` link is rejected.

Useful commands (run inside `supoclip/`): `docker compose logs -f` (watch progress), `docker compose down` (stop).
