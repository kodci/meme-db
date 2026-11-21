#!/usr/bin/env python3
"""YouTube playlist'lerindeki videoları index.json'a tek tek kart olarak ekler.

Videolar indirilmez; sadece video kimliği, başlık ve tarih kaydedilir. Oynatma
uygulamada YouTube'un resmi gömülü oynatıcısıyla yapılır.

Kullanım:
    export YOUTUBE_API_KEY=...            # Windows PowerShell: $env:YOUTUBE_API_KEY="..."
    python tools/sync_youtube.py          # playlists.txt dosyasındaki listeleri eşitler
    python tools/sync_youtube.py "https://www.youtube.com/playlist?list=PLxxxx" --tag komik
    python tools/sync_youtube.py --no-prune

playlists.txt (satır başına bir playlist; # ile yorum; satır sonuna #etiket yazılabilir):
    https://www.youtube.com/playlist?list=PLxxxxxxxx   #komik #kedi

Davranış:
  * Yeni videolar eklenir (id: "yt-<videoId>"). Var olan kayıtlara dokunulmaz,
    elle yaptığın başlık/etiket düzenlemeleri korunur.
  * Playlist'ten kaldırılan videolar index.json'dan da silinir (sadece bu script
    tarafından eklenenler; "playlist" alanı olanlar). --no-prune ile kapatılır.
  * Özel/silinmiş videolar atlanır. Bir playlist boş dönerse silme yapılmaz.
Tarih: videonun YouTube'a yüklenme tarihi (createdAt). --date added dersen
playlist'e eklenme tarihi kullanılır.
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://www.googleapis.com/youtube/v3/playlistItems"
SKIP_TITLES = {"private video", "deleted video"}


def parse_playlist_id(text: str):
    """URL ya da çıplak ID'den playlist kimliğini çıkarır."""
    text = text.strip()
    m = re.search(r"[?&]list=([A-Za-z0-9_-]+)", text)
    if m:
        return m.group(1)
    if re.fullmatch(r"(PL|UU|LL|FL|OL|RD)[A-Za-z0-9_-]{8,}", text):
        return text
    return None


def read_playlists(path: Path):
    """playlists.txt -> [(playlistId, [etiketler])]"""
    out = []
    if not path.exists():
        return out
    for raw in path.read_text("utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        tags = [t.lstrip("#") for t in re.findall(r"(?:^|\s)(#[^\s#]+)", line)]
        url = re.sub(r"(?:^|\s)#[^\s#]+", "", line).strip()
        pid = parse_playlist_id(url)
        if pid is None:
            print(f"UYARI: playlist anlaşılamadı, atlandı: {line}", file=sys.stderr)
            continue
        out.append((pid, tags))
    return out


def http_get_json(url: str) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            msg = json.load(e)["error"]["message"]
        except Exception:
            msg = e.reason
        raise SystemExit(f"YouTube API hatası ({e.code}): {msg}")
    except urllib.error.URLError as e:
        raise SystemExit(f"Ağ hatası: {e.reason}")


def fetch_playlist(playlist_id: str, api_key: str, get=http_get_json):
    """Playlist'teki tüm videoları sayfa sayfa getirir."""
    items, token = [], None
    while True:
        q = {
            "part": "snippet,contentDetails",
            "playlistId": playlist_id,
            "maxResults": 50,
            "key": api_key,
        }
        if token:
            q["pageToken"] = token
        data = get(API + "?" + urllib.parse.urlencode(q))
        items.extend(data.get("items", []))
        token = data.get("nextPageToken")
        if not token:
            return items


def to_entry(item: dict, playlist_id: str, tags, date_mode: str):
    sn = item.get("snippet", {})
    cd = item.get("contentDetails", {})
    vid = cd.get("videoId") or sn.get("resourceId", {}).get("videoId")
    title = (sn.get("title") or "").strip()
    if not vid or title.lower() in SKIP_TITLES:
        return None
    if date_mode == "added":
        created = sn.get("publishedAt") or cd.get("videoPublishedAt")
    else:
        created = cd.get("videoPublishedAt") or sn.get("publishedAt")
    return {
        "id": f"yt-{vid}",
        "title": title,
        "type": "youtube",
        "videoId": vid,
        "tags": list(tags),
        "author": (sn.get("videoOwnerChannelTitle") or "YouTube").replace(" - Topic", ""),
        "createdAt": created or "1970-01-01T00:00:00Z",
        "playlist": playlist_id,
    }


def sync(doc: dict, fetched: dict, tags_by_playlist: dict, prune=True, date_mode="published"):
    """doc'u yerinde günceller. fetched: {playlistId: [api item, ...]}"""
    items = doc.setdefault("memes", [])
    existing = {m.get("videoId") for m in items if m.get("videoId")}
    added = removed = 0

    for pid, api_items in fetched.items():
        live = set()
        for it in api_items:
            e = to_entry(it, pid, tags_by_playlist.get(pid, []), date_mode)
            if e is None:
                continue
            live.add(e["videoId"])
            if e["videoId"] not in existing:
                items.append(e)
                existing.add(e["videoId"])
                added += 1
        if prune and live:  # boş dönen listede silme yapma
            before = len(items)
            items[:] = [
                m for m in items
                if not (m.get("playlist") == pid and m.get("videoId") not in live)
            ]
            removed += before - len(items)

    items.sort(key=lambda m: m.get("createdAt", ""), reverse=True)
    return added, removed


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("playlist", nargs="*", help="playlist URL'si ya da ID (boşsa playlists.txt)")
    ap.add_argument("--root", default=None, help="depo kökü (varsayılan: scriptin üst klasörü)")
    ap.add_argument("--tag", action="append", default=[], help="komut satırından verilen listeler için etiket")
    ap.add_argument("--no-prune", action="store_true", help="playlist'ten kalkan videoları silme")
    ap.add_argument("--date", choices=["published", "added"], default="published")
    args = ap.parse_args()

    key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not key:
        sys.exit("YOUTUBE_API_KEY ortam değişkeni yok. README'deki adımlara bak.")

    root = Path(args.root) if args.root else Path(__file__).resolve().parent.parent

    targets = []
    for p in args.playlist:
        pid = parse_playlist_id(p)
        if pid is None:
            sys.exit(f"Playlist anlaşılamadı: {p}")
        targets.append((pid, args.tag))
    if not targets:
        targets = read_playlists(root / "playlists.txt")
    if not targets:
        sys.exit("Playlist yok. playlists.txt'ye ekle ya da URL ver.")

    index_path = root / "index.json"
    doc = {"version": 1, "memes": []}
    if index_path.exists() and index_path.read_text("utf-8").strip():
        doc = json.loads(index_path.read_text("utf-8"))
        if isinstance(doc, list):
            doc = {"version": 1, "memes": doc}

    fetched, tags_by = {}, {}
    for pid, tags in targets:
        print(f"Playlist {pid} okunuyor…")
        fetched[pid] = fetch_playlist(pid, key)
        tags_by[pid] = tags
        print(f"  {len(fetched[pid])} öğe")

    added, removed = sync(doc, fetched, tags_by, prune=not args.no_prune, date_mode=args.date)
    index_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{added} eklendi, {removed} silindi, toplam {len(doc['memes'])} meme -> {index_path}")


if __name__ == "__main__":
    main()
