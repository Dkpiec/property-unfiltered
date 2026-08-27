# Property Unfiltered — YouTube Automation Pipeline

**Faceless, data-driven Delhi NCR real estate channel — fully automated from topic ideation to YouTube upload, with two human approval gates.**

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  GitHub Actions (public repo, free minutes)                      │
│                                                                  │
│  generate_topics.yml  →  pending_topics.json   (Gate 1)         │
│         ↓ (Hermes triggers via GH API)                           │
│  generate_video.yml   →  pending_video_review.json + MP4 (Gate 2)│
│         ↓ (Hermes triggers via GH API)                           │
│  publish_approved_video.yml  →  YouTube upload                  │
└─────────────────────────────────────────────────────────────────┘
         ↓ artifacts        ↓ approval events
┌─────────────────────────────────────────────────────────────────┐
│  Hermes (on VPS, connected Telegram bot)                         │
│  - Polls GH API for completed runs                               │
│  - Downloads manifests as artifacts                              │
│  - Sends all Telegram notifications via the connected bot         │
│  - Funnels your approval replies → triggers next workflow        │
│  - Monitors failure streaks, sends weekly performance summaries   │
└─────────────────────────────────────────────────────────────────┘
```

## Repository Structure

```
property-unfiltered/
├── .github/workflows/
│   ├── generate_topics.yml           # schedule + dispatch
│   ├── generate_video.yml            # dispatch (after Gate 1)
│   └── publish_approved_video.yml    # dispatch (after Gate 2)
├── config/
│   ├── prompts/                      # LLM prompt templates
│   ├── settings.yaml                 # channel, content, topic weights
│   ├── llm.yaml                      # per-task model/provider config
│   └── tts.yaml                      # voiceover provider config
├── src/
│   ├── utils.py                      # logging, config, redaction, Telegram
│   ├── llm_client.py                 # Gemini + Groq/Llama failover
│   ├── research.py                   # non-fatal news enrichment
│   ├── topic_generator.py            # 10-15 candidates → ranked top 5
│   ├── scriptwriter.py               # script + 5 titles + desc + tags + thumbnails
│   ├── voiceover.py                  # Coqui XTTS-v2 / edge-tts
│   ├── video_builder.py              # FFmpeg: Ken Burns, subtitles, encode
│   ├── generate_video.py             # orchestrator
│   └── youtube_upload.py             # YouTube Data API v3 upload
├── scripts/
│   ├── setup_youtube_oauth.py        # one-time OAuth setup
│   └── configure_repo.sh             # optional gh CLI helper
├── assets/                           # stock mappings, templates, fonts
├── output/                           # gitignored — generated videos
├── logs/                             # gitignored
├── requirements.txt
└── .gitignore
```

## How the Two Approval Gates Work

### Gate 1: Topics
1. `generate_topics.yml` runs (schedule or manual) → produces 5 candidate topics → artifact uploaded.
2. Hermes detects the completed run, downloads the artifact, sends you a Telegram message with a numbered list (type + rationale).
3. You reply with numbers (e.g. `1,3,5`).
4. Hermes triggers `generate_video.yml` with those topic ids.

### Gate 2: Final Video
1. `generate_video.yml` runs for each approved topic → produces MP4 + review manifest → artifact uploaded.
2. Hermes sends you a Telegram message with: topic, type, duration, full script, 5 title options, description, tags, thumbnail ideas, and a download link.
3. You reply `APPROVE 2` (to pick title #2) or `APPROVE WITH CHANGES <notes>`.
4. Hermes triggers `publish_approved_video.yml` with the approved metadata.

**Both gates are mandatory. Nothing gets uploaded without your explicit approval.**

## Setup

### 1. Create the GitHub repository

Create a **public** repository on GitHub (required for free Actions minutes). Then push this code:

```bash
cd /path/to/property-unfiltered
git remote add origin https://github.com/YOUR_USER/property-unfiltered.git
git push -u origin main
```

### 2. Add GitHub Secrets

Go to repo **Settings → Secrets and variables → Actions → New repository secret** and add:

| Secret | Description | Required |
|--------|-------------|----------|
| `GOOGLE_API_KEY` | Gemini API key (free tier, [makersuite.google.com](https://makersuite.google.com)) | Yes |
| `GROQ_API_KEY` | Groq API key (free tier, [console.groq.com](https://console.groq.com)) | Optional fallback |
| `PEXELS_API_KEY` | Pexels API key (free tier, [pexels.com/api](https://www.pexels.com/api)) | Optional (stock footage) |
| `YOUTUBE_CLIENT_SECRETS` | OAuth client secrets JSON (single-line string) | Yes (for upload) |
| `YOUTUBE_REFRESH_TOKEN` | YouTube OAuth refresh token | Yes (for upload) |

Also set **Variables** (Settings → Secrets → Actions → Variables):
- `TTS_PROVIDER` = `coqui` or `edge` (default: coqui)
- `YOUTUBE_CATEGORY_ID` = `27` (Education) or `26` (Howto & Style)

### 3. YouTube OAuth Setup

Run on your **local machine** (not on GitHub Actions):

```bash
pip install google-api-python-client google-auth-oauthlib
python scripts/setup_youtube_oauth.py /path/to/client_secret_XXXX.json
```

This opens a browser for OAuth consent, then prints the `YOUTUBE_CLIENT_SECRETS` JSON and `YOUTUBE_REFRESH_TOKEN` values. Paste both into GitHub Secrets.

### 4. LLM Configuration

The pipeline uses **Google Gemini free tier** by default (requires `GOOGLE_API_KEY`). If Gemini fails or hits rate limits, it automatically falls back to **Groq** (Llama 3.3 70B, requires `GROQ_API_KEY`).

Per-task models and temperatures are in `config/llm.yaml`. Override at runtime:
```bash
export LLM_PROVIDER=openai_compatible  # force provider
export LLM_MODEL=llama-3.3-70b-versatile  # force model
```

### 5. TTS Configuration

Default: **Coqui XTTS-v2** (open-source, CPU, multilingual English). Falls back to **edge-tts** `en-IN-PrabhatNeural` (fast, Indian male English).

Set `TTS_PROVIDER=edge` in GitHub Variables to use edge-tts (faster, but uses Microsoft's cloud). For monetized videos, Coqui is recommended (full open-source, commercial use allowed).

Config in `config/tts.yaml`.

### 6. Telegram in Hermes

The Hermes monitor on your VPS uses the **connected Telegram bot** (the same one Hermes uses for your daily chat). No extra setup needed — the bot token and chat ID are already in `/opt/data/.env`.

If you want to run Hermes-side monitoring from scratch, you need:
- `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in your environment
- `GH_PAT` (fine-grained GitHub PAT with `actions: read/write` + `contents: read`)
- `GH_REPO` set to `owner/property-unfiltered`

### 7. Run Workflows Manually

1. Go to **Actions → Generate Topics → Run workflow** (or wait for the cron schedule).
2. After receiving topics via Telegram, reply with your choices.
3. Hermes triggers **Generate Video** → you receive the video for review.
4. Reply `APPROVE N` → Hermes triggers **Publish Approved Video** → done.

## Hermes Monitoring

Hermes runs two cron jobs on the VPS:

| Job | Schedule | What it does |
|-----|----------|-------------|
| `property-unfiltered-monitor` | Every 30 min | Polls GH API for completed runs, downloads artifacts, sends Telegram for Gate 1 / Gate 2 / failure alerts |
| `property-unfiltered-weekly` | Monday 09:00 UTC | Fetches YouTube Analytics, aggregates views/CTR/retention, sends top/bottom video summary + suggestions |

Both use the connected Telegram bot. No Telegram credentials are stored in GitHub.

## Tech Stack

- **LLM**: Google Gemini (free tier) + Groq/Llama fallback
- **TTS**: Coqui XTTS-v2 (primary, CPU) / edge-tts en-IN male (fallback)
- **Video**: FFmpeg (Ken Burns, subtitles, YouTube encode)
- **Upload**: YouTube Data API v3 (OAuth2 refresh token)
- **CI/CD**: GitHub Actions (public repo, free minutes)
- **Orchestration**: Hermes (Telegram gateway, VPS cron)

## License

MIT