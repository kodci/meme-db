# Meme DB

Memefeed uygulamasının okuduğu meme veritabanı. **Herkese açık (public)** bir GitHub reposu olmalı.

```
index.json          # tüm memelerin listesi (uygulama bunu okur)
memes/              # görsel ve videolar
tools/build_index.py
```

## index.json

```json
{
  "version": 1,
  "memes": [
    {
      "id": "benzersiz-id",
      "title": "Başlık",
      "type": "image",
      "file": "memes/2026/11/abc.jpg",
      "tags": ["etiket"],
      "author": "kullanici",
      "createdAt": "2026-11-20T09:00:00Z"
    }
  ]
}
```

| Alan | Açıklama |
|---|---|
| `type` | `image`, `video` veya `text` (yoksa dosya uzantısından anlaşılır) |
| `file` | Depodaki yol. Görsel/video için zorunlu |
| `text` | Sadece `type: text` için, memenin metni |
| `createdAt` | ISO 8601, UTC. "Yeni/Eski" sıralaması buna göre |
| `id`, `title`, `tags`, `author` | İsteğe bağlı ama `id` önerilir |

## Meme eklemenin 3 yolu

1. **Uygulamadan**: Ayarlar'a GitHub token gir, Yükle sekmesinden ekle (dosya + index.json otomatik güncellenir).
2. **Elle**: Dosyayı `memes/` altına koy, `index.json`'a kayıt ekle, commit et.
3. **Toplu (eski memeler)**: Dosyaları `memes/` altına at, `python tools/build_index.py` çalıştır, commit et. Alt klasör adları etiket olur. Eski memelerin gerçek tarihlerini `createdAt` alanından düzelt.

## Token

GitHub → Settings → Developer settings → Fine-grained tokens → bu repo için **Contents: Read and write**. Sadece sana ait cihazlarda kullan.

## Sınırlar

- Uygulamadan yükleme dosya başına 20 MB ile sınırlı.
- GitHub reposu şişer: çok video yüklenecekse ileride Releases/CDN düşün.
- `raw.githubusercontent.com` önbelleği birkaç dakika sürebilir. Uygulama bunu aşmak için tazeleme isteğine zaman damgası ekler.
