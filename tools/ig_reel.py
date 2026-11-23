#!/usr/bin/env python3
"""ig_reel.py - publish a vertical clip as an Instagram Reel via the official Instagram API.

    python3 tools/ig_reel.py whoami
    python3 tools/ig_reel.py prep  clip.mp4 out.mp4          # transcode only, no network
    python3 tools/ig_reel.py post  clip.mp4 --caption-file caption.txt --expect avyukt_tx [--dry-run]

Uses "Instagram API with Instagram Login" (graph.instagram.com). The access token is read from
IG_TOKEN; when it is unset a placeholder is sent and the session's network proxy, which holds the
real token, replaces it. Never commit a token.

Flow: transcode to Instagram's Reels spec (1080x1920 H.264, <=25 Mbps, AAC) -> create a REELS
container with upload_type=resumable -> upload the bytes to rupload.facebook.com -> poll until the
container is FINISHED -> media_publish -> print the permalink.
"""
import argparse, json, os, subprocess, sys, time
import requests

API = "https://graph.instagram.com/v23.0"
TOKEN = os.environ.get("IG_TOKEN", "proxy-injected")
HDR = {"Authorization": f"Bearer {TOKEN}"}


def die(msg, resp=None):
    if resp is not None:
        msg += f"\n  HTTP {resp.status_code}: {resp.text[:600]}"
    sys.exit(f"error: {msg}")


def api(method, path, **kw):
    r = requests.request(method, f"{API}/{path}", headers=HDR, timeout=60, **kw)
    if r.status_code >= 400:
        die(f"{method} {path} failed", r)
    return r.json()


def whoami():
    return api("GET", "me", params={"fields": "user_id,username,account_type"})


def prep(src, dst):
    """Re-encode to 1080x1920, 30fps, capped bitrate, moov atom first."""
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", src,
           "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,"
                  "pad=1080:1920:(ow-iw)/2:(oh-ih)/2,fps=30,format=yuv420p",
           "-c:v", "libx264", "-profile:v", "high", "-preset", "medium", "-crf", "20",
           "-maxrate", "12M", "-bufsize", "24M",
           "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
           "-movflags", "+faststart", dst]
    subprocess.run(cmd, check=True)
    return dst


def post(path, caption, expect=None, dry_run=False, share_to_feed=True):
    me = whoami()
    if expect and me.get("username", "").lower() != expect.lower():
        die(f"token belongs to @{me.get('username')}, expected @{expect}. Nothing posted.")
    if me.get("account_type") not in ("BUSINESS", "MEDIA_CREATOR", "CREATOR"):
        print(f"warning: account_type is {me.get('account_type')}; Reels publishing needs a professional account")
    print(f"account: @{me.get('username')} ({me.get('account_type')})")

    work = path.rsplit(".", 1)[0] + ".ig.mp4"
    prep(path, work)
    size = os.path.getsize(work)
    print(f"transcoded: {work} ({size / 1e6:.1f} MB)")
    if dry_run:
        print("dry run: stopping before upload")
        return None

    c = api("POST", "me/media", data={"media_type": "REELS", "upload_type": "resumable",
                                      "caption": caption,
                                      "share_to_feed": "true" if share_to_feed else "false"})
    cid, uri = c["id"], c["uri"]
    print(f"container: {cid}")

    with open(work, "rb") as fh:
        r = requests.post(uri, data=fh, timeout=600, headers={
            "Authorization": f"OAuth {TOKEN}", "offset": "0", "file_size": str(size)})
    if r.status_code >= 400:
        die("video upload failed", r)
    print("uploaded")

    for _ in range(60):  # up to ~10 minutes of processing
        s = api("GET", cid, params={"fields": "status_code,status"})
        if s.get("status_code") == "FINISHED":
            break
        if s.get("status_code") in ("ERROR", "EXPIRED"):
            die(f"Instagram could not process the video: {s}")
        time.sleep(10)
    else:
        die("timed out waiting for Instagram to process the video")

    m = api("POST", "me/media_publish", data={"creation_id": cid})
    link = api("GET", m["id"], params={"fields": "permalink"}).get("permalink")
    print(f"published: {link}")
    return {"media_id": m["id"], "permalink": link}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("whoami")
    pp = sub.add_parser("prep"); pp.add_argument("src"); pp.add_argument("dst")
    po = sub.add_parser("post"); po.add_argument("video")
    po.add_argument("--caption-file", required=True)
    po.add_argument("--expect", help="refuse to post unless the token's username matches")
    po.add_argument("--dry-run", action="store_true")
    po.add_argument("--no-feed", action="store_true", help="Reels tab only, not the main grid")
    a = p.parse_args()
    if a.cmd == "whoami":
        print(json.dumps(whoami(), indent=1))
    elif a.cmd == "prep":
        prep(a.src, a.dst)
    else:
        caption = open(a.caption_file, encoding="utf-8").read().strip()
        out = post(a.video, caption, a.expect, a.dry_run, not a.no_feed)
        if out:
            print(json.dumps(out))


if __name__ == "__main__":
    main()
