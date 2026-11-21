#!/usr/bin/env python3
"""YouTube playlist'lerindeki videoları index.json'a tek tek kart olarak ekler.

Videolar indirilmez; sadece video kimliği, başlık ve tarih kaydedilir. Oynatma
uygulamada YouTube'un resmi gömülü oynatıcısıyla yapılır.

Kullanım:
    export YOUTUBE_API_KEY=...            # Windows PowerShell: $env:YOUTUBE_API_KEY="..."
    python tools/sync_youtube.py          # playlists.txt dosyasındaki listeleri eşitler
    python tools/sync_youtube.py "https://www.youtube.com/playlist?list=PLxxxx" --tag komik
    python tools/sync_youtube.py --no-prune
    python tools/sync_youtube.py --recheck   # var olan videoların dikey (Shorts) bilgisini yenile

playlists.txt (satır başına bir playlist; # ile yorum; satır sonuna #etiket yazılabilir):
    https://www.youtube.com/playlist?list=PLxxxxxxxx   #komik #kedi

Davranış:
  * Yeni videolar eklenir (id: "yt-<videoId>"). Var olan kayıtlara dokunulmaz,
    elle yaptığın başlık/etiket düzenlemeleri korunur.
  * Playlist'ten kaldırılan videolar index.json'dan da silinir (sadece bu script
    tarafından eklenenler; "playlist" alanı olanlar). --no-prune ile kapatılır.
  * Özel/silinmiş ve GÖMMEYE KAPALI videolar atlanır (uygulamada oynamazlar);
    daha önce eklenmişlerse bir sonraki eşitlemede silinir.
  * Shorts (dikey) videolar "vertical": true ile işaretlenir; Reels'te ekranı doldurur.
  * Bir playlist boş dönerse silme yapılmaz.
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
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

API = "https://www.googleapis.com/youtube/v3/playlistItems"
VIDEOS_API = "https://www.googleapis.com/youtube/v3/videos"
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


def fetch_embeddable(ids, api_key, get=http_get_json):
    """{videoId: gömülebilir mi}. API'de dönmeyen video özel/silinmiştir (False)."""
    ids = list(dict.fromkeys(ids))
    out = {i: False for i in ids}
    for k in range(0, len(ids), 50):
        chunk = ids[k:k + 50]
        q = {"part": "status", "id": ",".join(chunk), "key": api_key}
        data = get(VIDEOS_API + "?" + urllib.parse.urlencode(q))
        for it in data.get("items", []):
            out[it["id"]] = bool(it.get("status", {}).get("embeddable", False))
    return out


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def is_short(video_id: str) -> bool:
    """youtube.com/shorts/ID Shorts için 200 döner, diğer videolarda yönlendirir.
    Resmi bir API değildir; başarısız olursa dikey sayılmaz."""
    req = urllib.request.Request(
        f"https://www.youtube.com/shorts/{video_id}",
        method="HEAD",
        headers={"User-Agent": "Mozilla/5.0"},
    )
    try:
        with urllib.request.build_opener(_NoRedirect).open(req, timeout=15) as r:
            return r.status == 200
    except Exception:
        return False


def detect_vertical(ids, check=is_short):
    ids = list(ids)
    if not ids:
        return {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        return dict(zip(ids, ex.map(check, ids)))


def to_entry(item: dict, playlist_id: str, tags, date_mode: str, vertical=None):
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
    entry = {
        "id": f"yt-{vid}",
        "title": title,
        "type": "youtube",
        "videoId": vid,
        "tags": list(tags),
        "author": (sn.get("videoOwnerChannelTitle") or "YouTube").replace(" - Topic", ""),
        "createdAt": created or "1970-01-01T00:00:00Z",
        "playlist": playlist_id,
    }
    if vertical and vertical.get(vid):
        entry["vertical"] = True
    return entry


def sync(doc: dict, fetched: dict, tags_by_playlist: dict, prune=True, date_mode="published", vertical=None):
    """doc'u yerinde günceller. fetched: {playlistId: [api item, ...]}"""
    items = doc.setdefault("memes", [])
    existing = {m.get("videoId") for m in items if m.get("videoId")}
    added = removed = 0

    for pid, api_items in fetched.items():
        live = set()
        for it in api_items:
            e = to_entry(it, pid, tags_by_playlist.get(pid, []), date_mode, vertical)
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
    ap.add_argument("--recheck", action="store_true", help="mevcut videolar için de dikey (Shorts) kontrolünü yeniden yap")
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

    def vid_of(it):
        return it.get("contentDetails", {}).get("videoId") or it.get("snippet", {}).get("resourceId", {}).get("videoId")

    all_ids = [vid_of(it) for items in fetched.values() for it in items if vid_of(it)]
    emb = fetch_embeddable(all_ids, key)
    skipped = sum(1 for v in set(all_ids) if not emb.get(v))
    for pid in fetched:
        fetched[pid] = [it for it in fetched[pid] if emb.get(vid_of(it))]
    print(f"{skipped} video atlandı (özel/silinmiş/gömmeye kapalı)")

    known = {m.get("videoId") for m in doc.get("memes", []) if m.get("videoId")}
    new_ids = [v for v in dict.fromkeys(all_ids) if emb.get(v) and (args.recheck or v not in known)]
    vertical = detect_vertical(new_ids)
    print(f"{sum(vertical.values())} dikey (Shorts) video bulundu")

    added, removed = sync(doc, fetched, tags_by, prune=not args.no_prune, date_mode=args.date, vertical=vertical)
    if args.recheck:
        for m in doc["memes"]:
            v = m.get("videoId")
            if v in vertical:
                if vertical[v]:
                    m["vertical"] = True
                else:
                    m.pop("vertical", None)
    index_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{added} eklendi, {removed} silindi, toplam {len(doc['memes'])} meme -> {index_path}")


if __name__ == "__main__":
    main()
