# Ai-clipper
AI-powered automatic video clipping system that converts livestreams into engaging short-form videos for YouTube Shorts, Instagram Reels, and TikTok, with AI-selected highlights, captions, subtitles, and 9:16 formatting.

## How to use
- **Start a clipping job:** see [START_HERE.md](START_HERE.md) for the message to paste into a new Claude Code session.
- **Full playbook for Claude:** [CLAUDE.md](CLAUDE.md) (loaded automatically in sessions on this repo).
- **Setup on a Linux cloud session:** `bash setup_linux.sh`
- **Find a Kick streamer's past streams:** `python3 tools/kick_vods.py <channel> [--gta]`

Clipping skills are based on the MIT-licensed `gta6-clipper` skills (see `skills/LICENSE-gta6-clipper`),
with our own 4K editor (`skills/gta6-clipper/scripts/pro_render.py`) and download-page tools (`web/`).
