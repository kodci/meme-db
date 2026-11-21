#!/usr/bin/env python3
"""memes/ klasöründeki yeni görsel/video dosyalarını index.json'a ekler.

Eski memeleri toplu aktarmak için: dosyaları memes/ altına at (alt klasör
adları etiket olur), sonra bu scripti çalıştır. index.json'daki mevcut
kayıtlara dokunmaz, sadece henüz kayıtlı olmayan dosyaları ekler.

Kullanım:
    python tools/build_index.py                 # depo kökü = scriptin üst klasörü
    python tools/build_index.py /yol/repo       # farklı bir kök
    python tools/build_index.py --author canberk

Not: tarih olarak dosyanın değiştirilme zamanı kullanılır. git clone sonrası
bu zaman klonlama anı olur; eski memelerin gerçek tarihleri için index.json'daki
"createdAt" alanlarını elle düzelt.
"""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

IMAGE = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
VIDEO = {".mp4", ".webm", ".mov", ".m4v"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?", default=None)
    ap.add_argument("--author", default="arşiv")
    args = ap.parse_args()

    root = Path(args.root) if args.root else Path(__file__).resolve().parent.parent
    index_path = root / "index.json"
    memes_dir = root / "memes"

    doc = {"version": 1, "memes": []}
    if index_path.exists() and index_path.read_text("utf-8").strip():
        doc = json.loads(index_path.read_text("utf-8"))
        if isinstance(doc, list):
            doc = {"version": 1, "memes": doc}
    items = doc.setdefault("memes", [])
    known = {m.get("file") for m in items if m.get("file")}

    added = 0
    for p in sorted(memes_dir.rglob("*")):
        ext = p.suffix.lower()
        if not p.is_file() or ext not in IMAGE | VIDEO:
            continue
        rel = p.relative_to(root).as_posix()
        if rel in known:
            continue
        mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
        folders = p.relative_to(memes_dir).parts[:-1]
        items.append(
            {
                "id": hashlib.sha1(rel.encode("utf-8")).hexdigest()[:10],
                "title": p.stem.replace("_", " ").replace("-", " ").strip(),
                "type": "video" if ext in VIDEO else "image",
                "file": rel,
                "tags": [f for f in folders if not f.isdigit()],
                "author": args.author,
                "createdAt": mtime.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        )
        added += 1

    items.sort(key=lambda m: m.get("createdAt", ""), reverse=True)
    index_path.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"{added} yeni kayıt eklendi, toplam {len(items)} meme -> {index_path}")


if __name__ == "__main__":
    main()
