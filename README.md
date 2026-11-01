<div align="center">

# Frameora

**Telegram bot that prepares your videos for high frame-rate upload on TikTok.**

[العربية](README.ar.md) · English

<a href="https://github.com/zt-tb/Frameora/actions/workflows/tests.yml"><img src="https://github.com/zt-tb/Frameora/actions/workflows/tests.yml/badge.svg" alt="Tests" /></a>
<a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT%20%2B%20Attribution-2ea44f?style=flat" alt="License" /></a>
<img src="https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white" alt="Python" />
<img src="https://img.shields.io/badge/Telegram-Bot%20(Kurigram)-26A5E4?logo=telegram&logoColor=white" alt="Telegram Bot" />
<img src="https://img.shields.io/badge/PostgreSQL-asyncpg-4169E1?logo=postgresql&logoColor=white" alt="PostgreSQL" />
<img src="https://img.shields.io/badge/Redis-optional-DC382D?logo=redis&logoColor=white" alt="Redis" />
<img src="https://img.shields.io/badge/FFmpeg-required-007808?logo=ffmpeg&logoColor=white" alt="FFmpeg" />
<img src="https://img.shields.io/badge/languages-Arabic%20%7C%20English-green" alt="Languages" />

<a href="https://t.me/K0_MG"><img src="https://img.shields.io/badge/Telegram-@K0__MG-26A5E4?logo=telegram&logoColor=white" alt="Telegram @K0_MG" /></a>
<a href="https://instagram.com/z0_28"><img src="https://img.shields.io/badge/Instagram-z0__28-E4405F?logo=instagram&logoColor=white" alt="Instagram z0_28" /></a>
<a href="https://www.tiktok.com/@zt_tb"><img src="https://img.shields.io/badge/TikTok-@zt__tb-000000?logo=tiktok&logoColor=white" alt="TikTok @zt_tb" /></a>
<a href="https://youtube.com/@M7JN"><img src="https://img.shields.io/badge/YouTube-@M7JN-FF0000?logo=youtube&logoColor=white" alt="YouTube @M7JN" /></a>
<a href="https://github.com/zt-tb"><img src="https://img.shields.io/badge/GitHub-zt--tb-181717?logo=github&logoColor=white" alt="GitHub zt-tb" /></a>

</div>

> **Open source with attribution.** Frameora is released under the MIT License with an attribution requirement. You may use, modify and share it, but you must keep the [NOTICE](NOTICE) file and the copyright headers, and credit the original author, **Mohsen Al-Taie (@K0_MG)**. See [LICENSE](LICENSE).

## What it does

You send a video to the bot, pick a method, and receive a prepared MP4 file. By default the picture and audio are not re-encoded, and the bot checks the file's integrity before sending it back.

| Feature | Description |
|---|---|
| **Spark** | Fast, light method. Try this first. Works with any frame rate. |
| **Blaze** | Alternative if Spark does not give a suitable result. |
| **Pulse** | For constant frame-rate clips (60 or 120 FPS works best). |
| **MOV to MP4** | Converts MOV to MP4 without re-encoding. |
| **Compression** | Optional per-user "compress first" mode (H.264, up to 1080p). It re-encodes, so quality may drop. |
| **`/analyze`** | Shows codec, resolution, frame rate, bitrate and audio details without changing the file. |
| **`/check`** | Compares your original with the video published on TikTok (SSIM or VMAF). |
| **Languages** | Iraqi Arabic and English, switchable with `/lang`. |

## How to use it

1. Open the bot on Telegram and send `/start`.
2. Send your video **as a file** (not as a normal video) so Telegram does not compress it. MP4 and MOV are supported.
3. Choose a method: Spark, Blaze or Pulse.
4. Wait for the bot to process the video, then download the returned file.
5. Open **TikTok Studio** in your phone or computer browser and upload the file from your downloads.
6. In TikTok Studio, turn on **Allow high quality uploads**. Without it, playback can fall back to 30 FPS.
7. After publishing, send the link to `/check` to compare the result with your original.

## Commands

| Command | Purpose |
|---|---|
| `/start` | Main menu |
| `/help` | Usage guide |
| `/analyze` | Inspect a video without modifying it |
| `/check` | Compare a published TikTok video with the original |
| `/lang` | Change language |
| `/terms` | Terms of use and payment |
| `/paysupport` | Help with Telegram Stars payments |
| `/cancel` | Cancel the current operation |

## Access and payment

- **Subscribers** get full access, including `/analyze` and `/check`.
- **Everyone else** can pay with Telegram Stars (250 Stars by default) to process one video. The payment is consumed only when the finished file is delivered. If processing fails, the bot refunds the Stars automatically.
- For payment problems, use `/paysupport`.

## Important notes

- This is an unofficial tool. It is not affiliated with or endorsed by TikTok or ByteDance.
- TikTok can re-encode uploads or change its pipeline at any time, so no frame rate or quality is guaranteed after publishing.
- Send only content you own or have the right to use.
- Uploaded videos are processed in temporary storage and deleted after the job finishes. The original is kept as a short reference clip (first 30 seconds by default) for `/check` and removed after 48 hours.

## For the operator

Frameora runs on Python 3.11+, FFmpeg, PostgreSQL and optionally Redis. Configuration is read from environment variables; see [`.env.example`](.env.example) for the full list.

Required: `API_ID`, `API_HASH`, `BOT_TOKEN`, `OWNER_ID`, `DATABASE_URL`.

For Railway: add PostgreSQL (and Redis), mount a persistent volume at `/app/data`, and set `REF_DIR=/app/data/tfps_refs`. Run only one instance per database.

Tests: `pip install -r requirements.txt -r requirements-dev.txt && pytest -q` (needs ffmpeg).

## Credit

If you use Frameora or build on it, please credit the author in your README or bot description, for example: *Based on Frameora by Mohsen Al-Taie (@K0_MG)*. Redistributions must keep the `NOTICE` file.

To cite it in research or documentation, use [CITATION.cff](CITATION.cff) (GitHub shows a "Cite this repository" button).

## Author

**Mohsen Al-Taie**

<div align="center">

<img src="assets/divider.svg" width="100%" alt="" />

### 📱 Follow Me | تابعني

<div dir="ltr">

<a href="https://t.me/K0_MG"><img src="assets/social/telegram.svg" width="72" alt="Telegram @K0_MG" /></a>
<a href="https://instagram.com/z0_28"><img src="assets/social/instagram.svg" width="72" alt="Instagram z0_28" /></a>
<a href="https://www.tiktok.com/@zt_tb"><img src="assets/social/tiktok.svg" width="72" alt="TikTok @zt_tb" /></a>
<a href="https://youtube.com/@M7JN"><img src="assets/social/youtube.svg" width="72" alt="YouTube @M7JN" /></a>
<a href="https://github.com/zt-tb"><img src="assets/social/github.svg" width="72" alt="GitHub zt-tb" /></a>

</div>

[Telegram @K0_MG](https://t.me/K0_MG) · [Instagram z0_28](https://instagram.com/z0_28) · [TikTok @zt_tb](https://www.tiktok.com/@zt_tb) · [YouTube @M7JN](https://youtube.com/@M7JN) · [GitHub zt-tb](https://github.com/zt-tb)

<img src="assets/divider.svg" width="100%" alt="" />

</div>

Copyright (c) 2026 Mohsen Al-Taie. Licensed under the MIT License with an attribution requirement.
