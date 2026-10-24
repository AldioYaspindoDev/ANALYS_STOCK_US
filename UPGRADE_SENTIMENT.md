# UPGRADE_SENTIMEN.md
 
Instruksi untuk AI coding agent. Baca seluruh file ini sebelum mengubah apa pun.
 
## 1. Tujuan
 
Naikkan kualitas sentimen pada endpoint `GET /info/{ticker}`: dari ±10 judul berita
menjadi **minimal 100 artikel unik** yang dikumpulkan dari beberapa sumber gratis,
didedupe, disaring relevansinya, lalu dinilai dengan FinBERT dan diagregasi
(dengan bobot waktu) menjadi satu label + sebaran persentase.
 
Pemilik proyek hanya akan menyiapkan API key. Semua kode, tes, dan dokumentasi
adalah tugasmu.
 
## 2. Konteks proyek (jangan ditebak, verifikasi dulu)
 
- FastAPI, Python 3.10+, Linux, virtualenv di `.venv`.
- Endpoint: `GET /info/{ticker}` dan `GET /health`.
- Harga dari `yfinance`, sentimen dari FinBERT (`ProsusAI/finbert`).
- Berita saat ini: yfinance, dengan cadangan Google News RSS. Hanya ±10 judul.
- API dipanggil oleh **n8n di Docker** lewat `http://host.docker.internal:8000/info/{ticker}`
  untuk bot Telegram. Respons ditampilkan di Telegram dengan Parse Mode Markdown.
- Struktur kode bisa berupa satu file `src/api/main.py` ATAU hasil refactor
  `src/stock_api/...` (routers/services). **Deteksi dulu struktur yang ada**,
  lalu sesuaikan. Jika masih satu file, pecah seperlunya ke modul `news/` dan `sentiment`
  tanpa merombak bagian lain.
## 3. Kontrak API: kompatibel ke belakang (WAJIB)
 
Field lama TIDAK BOLEH berubah nama, tipe, atau arti:
 
```
ticker, price, change_pct, sentiment_label, sentiment_score,
news_count, news_source, top_headlines
```
 
Aturan field lama setelah upgrade:
- `news_count`: jumlah artikel unik yang benar-benar dinilai.
- `news_source`: string ringkas nama sumber yang berkontribusi, dipisah koma,
  **TANPA karakter `_`, `*`, `[`, `` ` ``** (Telegram Markdown akan error).
  Contoh: `finnhub, googlenews, gdelt`.
- `top_headlines`: tetap list string, maksimal 3 judul. Bersihkan karakter
  `_ * [ ] ``` ` ``` dari judul (ganti `_` dan `*` dengan spasi, `[` `]` dengan `(` `)`).
- `sentiment_label`: tetap salah satu dari `bagus`, `netral`, `buruk`, `tidak ada data`.
  Tambahkan nilai baru `data terbatas` HANYA saat artikel unik < `MIN_ARTICLES_FOR_LABEL`.
Field baru (boleh ditambah, semua opsional bagi klien lama):
 
```
positive_pct, neutral_pct, negative_pct   # float 0-100, total ±100
sources_breakdown                          # {"finnhub": 52, "googlenews": 40, "gdelt": 18}
articles_fetched                           # jumlah mentah sebelum dedupe/filter
articles_after_dedupe
articles_scored
window_days                                # rentang waktu berita
cached                                     # bool
```
 
Jika memakai Pydantic `response_model`, definisikan semua field ini secara eksplisit.
 
## 4. Sumber berita
 
Semua sumber ada di modul terpisah, **satu fungsi per sumber**, mengembalikan format
yang sama (lihat bagian 5). Kegagalan satu sumber TIDAK boleh menggagalkan request:
tangkap exception spesifik, catat di log (level WARNING), lanjut ke sumber lain.
 
| Sumber | Wajib? | Key |
|---|---|---|
| Finnhub `company-news` | Ya (aktif jika key ada) | `FINNHUB_API_KEY` |
| Google News RSS | Ya | tidak perlu |
| GDELT DOC 2.0 API | Ya | tidak perlu |
| yfinance `Ticker.news` | Ya (sumber tambahan) | tidak perlu |
 
Jika `FINNHUB_API_KEY` kosong: lewati Finnhub, log satu peringatan, API tetap jalan.
 
### 4.1 Finnhub
- Endpoint: `GET https://finnhub.io/api/v1/company-news?symbol={T}&from={YYYY-MM-DD}&to={YYYY-MM-DD}&token={KEY}`
- Rentang: `NEWS_WINDOW_DAYS` hari terakhir.
- Field yang dipakai: `headline`, `summary`, `source`, `url`, `datetime` (epoch detik).
- Respons bisa berisi ratusan item: ambil maksimal `MAX_ARTICLES_PER_SOURCE`.
- Tangani HTTP 429 (rate limit) dan 401/403 (key salah): log, jangan retry tanpa batas.
- JANGAN mencetak atau me-log token. Pastikan token tidak muncul di pesan error/log
  (URL di log harus disamarkan).
### 4.2 Google News RSS
- Base: `https://news.google.com/rss/search?q={QUERY}+when:{N}d&hl=en-US&gl=US&ceid=US:en`
- Jalankan **2-3 query berbeda** per ticker, misalnya: `"{nama perusahaan}" stock`,
  `{TICKER} stock`, `"{nama perusahaan}" earnings OR guidance`.
- Parse XML dengan `xml.etree.ElementTree`. Ambil `title`, `link`, `pubDate`
  (format RFC 822, parse dengan `email.utils.parsedate_to_datetime`), dan `source`.
- Buang akhiran ` - Nama Sumber` dari judul.
- Atur User-Agent lewat config. Timeout dari config.
### 4.3 GDELT DOC 2.0
- Endpoint: `https://api.gdeltproject.org/api/v2/doc/doc`
- Parameter: `query="{nama perusahaan}"` (tanda kutip untuk frasa), `mode=artlist`,
  `format=json`, `maxrecords=250`, `sort=datedesc`, `timespan={N}d`.
- Batasi ke bahasa Inggris (`sourcelang:english` di query).
- Field: `title`, `url`, `seendate` (format `YYYYMMDDTHHMMSSZ`), `domain`.
- GDELT membatasi laju permintaan dan kadang mengembalikan teks non-JSON saat error:
  cek `Content-Type`/parse dengan try-except, tangani HTTP 429 dengan satu retry
  setelah jeda singkat (sleep tetap, maks 1 kali), lalu menyerah dan log WARNING.
- Tidak ada ringkasan di GDELT: `summary` dikosongkan.
### 4.4 yfinance
- Pertahankan parsing dua bentuk struktur (`title` langsung atau `content.title`),
  juga `content.summary` bila ada. Bungkus dengan try-except.
### 4.5 Aturan umum sumber
- Pakai satu `requests.Session` dengan timeout dan header dari config.
- Ambil sumber **secara paralel** dengan `concurrent.futures.ThreadPoolExecutor`
  (endpoint adalah `def` biasa, bukan `async def`). Total waktu pengambilan harus
  dibatasi (`FETCH_TIMEOUT_SECONDS`).
- JANGAN scraping isi artikel dari situs berita. Hanya judul + ringkasan dari API/RSS.
## 5. Model data internal
 
Buat dataclass/Pydantic model `Article`:
 
```
title: str
summary: str          # boleh kosong
source: str           # nama sumber data: finnhub | googlenews | gdelt | yfinance
publisher: str        # nama media bila ada
url: str
published_at: datetime | None   # timezone-aware (UTC)
```
 
Semua fungsi sumber mengembalikan `list[Article]`. Pecahan logika (normalisasi,
dedupe, relevansi, scoring) ada di fungsi murni tanpa ketergantungan FastAPI,
supaya mudah dites.
 
## 6. Pipeline
 
```
fetch paralel → normalisasi → filter rentang waktu → filter relevansi
→ dedupe → batasi jumlah → FinBERT batch → bobot waktu → agregasi → respons
```
 
### 6.1 Normalisasi
- Bersihkan entitas HTML dan spasi berlebih. Potong `summary` ke `SUMMARY_MAX_CHARS`.
- Artikel tanpa judul dibuang. Artikel tanpa tanggal: boleh dipakai dengan bobot
  waktu terendah, dan catat jumlahnya di log.
### 6.2 Filter relevansi
Artikel dipertahankan hanya jika judul ATAU ringkasan menyebut nama perusahaan
(versi pendek, tanpa "Inc.", "Corp.", "Ltd.") atau ticker sebagai **kata utuh**.
- Nama perusahaan dari `yfinance` (`shortName`), dengan fallback ke ticker saja.
- Ticker pendek/ambigu (≤ 3 huruf, misalnya `STX`, `MU`) harus cocok sebagai kata utuh
  huruf besar DAN, bila memungkinkan, muncul bersama nama perusahaan atau kata kunci
  finansial (stock, shares, earnings, dll.) agar tidak menangkap singkatan lain.
- Artikel dari Finnhub `company-news` dianggap sudah relevan oleh sumbernya,
  tapi tetap dicek ringan.
### 6.3 Dedupe (dua lapis)
1. Eksak: kunci dari `url` yang dinormalisasi (hapus parameter `utm_*`, fragment,
   trailing slash) dan dari judul yang dinormalisasi (huruf kecil, tanpa tanda baca).
2. Mirip: judul yang rasio kemiripannya ≥ `DEDUPE_SIMILARITY` dianggap duplikat
   (pakai `difflib.SequenceMatcher` atau `rapidfuzz` bila ditambahkan ke requirements).
   Jaga kompleksitas tetap wajar (bandingkan hanya dalam batch ≤ beberapa ratus
   artikel atau pakai pengelompokan awal berdasar kata kunci).
Saat ada duplikat, pertahankan versi yang punya ringkasan dan tanggal terbaru.
### 6.4 Scoring FinBERT
- Teks input: `judul` + `. ` + `summary` (jika ada), dipotong (`truncation=True`,
  `max_length` dari config, default 256).
- Jalankan dalam **batch** (`batch_size` dari config, default 16), bukan satu per satu.
- Skor artikel = `P(positive) - P(negative)` (rentang -1..1).
- Klasifikasi per artikel: positif bila skor > `ARTICLE_POS_THRESHOLD` (default 0.15),
  negatif bila < `-ARTICLE_POS_THRESHOLD`, selain itu netral.
- Model dimuat sekali (lifespan atau lazy singleton aman thread). Lindungi
  inferensi dengan lock bila perlu.
### 6.5 Agregasi
- Bobot waktu: `w = 0.5 ** (umur_hari / HALF_LIFE_DAYS)` (default half-life 3 hari).
  Artikel tanpa tanggal memakai bobot minimum (`0.1`).
- `sentiment_score` = rata-rata tertimbang skor artikel, dibulatkan 3 desimal.
- `positive_pct / neutral_pct / negative_pct`: persentase tertimbang per klasifikasi
  artikel, dibulatkan 1 desimal.
- Label (ambang dari config, default sama seperti sebelumnya):
  - skor > 0.15 → `bagus`
  - skor < -0.15 → `buruk`
  - selain itu → `netral`
  - artikel terskor 0 → `tidak ada data`
  - artikel terskor < `MIN_ARTICLES_FOR_LABEL` (default 30) → `data terbatas`
    (skor dan persentase tetap dikembalikan).
- `top_headlines`: 3 judul dengan |skor × bobot| terbesar (sudah dibersihkan, lihat bagian 3).
### 6.6 Cache
- Cache in-memory dengan TTL per ticker (`CACHE_TTL_SECONDS`, default 900) dan
  batas jumlah entri (`CACHE_MAX_ENTRIES`, default 200). Aman thread (gunakan lock).
- Hasil gagal/kosong karena error jaringan **tidak** di-cache (atau di-cache sangat
  singkat) agar tidak membeku pada hasil buruk.
- Respons memuat `cached: true/false`.
## 7. Konfigurasi (`.env.example`)
 
Tambahkan variabel berikut ke `.env.example` (tanpa nilai rahasia) dan baca lewat
modul config yang ada (jangan hardcode):
 
```
FINNHUB_API_KEY=
NEWS_WINDOW_DAYS=7
MAX_ARTICLES_PER_SOURCE=150
MAX_ARTICLES_TOTAL=200
MIN_ARTICLES_FOR_LABEL=30
FETCH_TIMEOUT_SECONDS=20
HTTP_TIMEOUT_SECONDS=10
HTTP_USER_AGENT=Mozilla/5.0
DEDUPE_SIMILARITY=0.9
ARTICLE_POS_THRESHOLD=0.15
LABEL_THRESHOLD=0.15
HALF_LIFE_DAYS=3
FINBERT_MODEL=ProsusAI/finbert
FINBERT_MAX_LENGTH=256
FINBERT_BATCH_SIZE=16
CACHE_TTL_SECONDS=900
CACHE_MAX_ENTRIES=200
```
 
Pastikan `.env` ada di `.gitignore`. Jika perlu pustaka baru (misalnya
`python-dotenv`, `pydantic-settings`, `rapidfuzz`), tambahkan ke `requirements.txt`
dengan versi di-pin.
 
## 8. Logging dan error handling
 
- Gunakan modul `logging` standar. Log per request: jumlah artikel per sumber,
  setelah dedupe, setelah filter, durasi tiap tahap.
- Dilarang `except Exception: pass`. Tangkap exception spesifik
  (`requests.RequestException`, `ET.ParseError`, `ValueError`, `KeyError`), log,
  lalu lanjut dengan hasil kosong untuk sumber itu.
- Jangan pernah mencetak token, isi `.env`, atau URL yang memuat token.
- Jika SEMUA sumber gagal: respons tetap 200 dengan harga, `sentiment_label =
  "tidak ada data"`, `news_count = 0`.
## 9. Tes (pytest, tanpa internet, tanpa unduh model)
 
Mock semua panggilan eksternal (`requests`, `yfinance`, FinBERT). Tes minimal:
 
1. Parser tiap sumber: Finnhub (JSON), Google News (XML contoh), GDELT (JSON contoh,
   format tanggal `YYYYMMDDTHHMMSSZ`), yfinance (dua bentuk struktur).
2. Dedupe: URL sama dengan parameter `utm_*`, judul sama beda huruf/tanda baca,
   judul mirip, dan judul benar-benar berbeda (tidak boleh terbuang).
3. Filter relevansi: ticker pendek sebagai kata utuh vs bagian kata lain
   (contoh: `MU` tidak boleh cocok di kata `Museum`).
4. Pembersihan karakter Markdown pada `top_headlines` dan `news_source`.
5. Pembobotan waktu dan agregasi: hasil deterministik dengan data buatan,
   termasuk kasus artikel tanpa tanggal.
6. Label: batas nilai (0.15, -0.15), kasus `data terbatas` dan `tidak ada data`.
7. Cache: hit, miss, kedaluwarsa TTL, tidak meng-cache hasil gagal.
8. Satu sumber gagal (exception) → sumber lain tetap menghasilkan respons.
9. Endpoint `/info/{ticker}`: semua field lama ada dengan tipe yang sama,
   dan field baru terisi.
Jalankan `pytest` dan `ruff check`/`ruff format` bila tersedia. Semua harus lulus.
 
## 10. Verifikasi manual (jalankan dan laporkan hasilnya)
 
```bash
uvicorn <modul-app>:app --host 0.0.0.0
curl -s http://localhost:8000/health
curl -s http://localhost:8000/info/STX
curl -s http://localhost:8000/info/AAPL
curl -s http://localhost:8000/info/aapl     # huruf kecil harus tetap bekerja
curl -i  http://localhost:8000/info/ZZZZZ   # harus 404
```
 
Jika `FINNHUB_API_KEY` belum diisi, uji tanpa key dan konfirmasi API tetap jalan.
Laporkan untuk AAPL dan STX: `articles_fetched`, `articles_after_dedupe`,
`articles_scored`, `sources_breakdown`, serta waktu respons pertama (dingin)
dan kedua (cache). Target: `articles_scored ≥ 100` untuk saham besar seperti AAPL
bila sumber tersedia. Jika tidak tercapai, jelaskan penyebabnya (jangan memalsukan angka).
 
## 11. Yang dikerjakan pemilik proyek (jangan dikerjakan agent)
 
- Mendaftar dan mengisi `FINNHUB_API_KEY` di `.env`.
- Memperbarui template pesan di node Telegram n8n dan menaikkan timeout node
  HTTP Request ke 60-90 detik. Agent cukup menyediakan contoh template di README.
Contoh template pesan untuk README (n8n, mode Expression):
 
```
📊 {{ $json.ticker }}: ${{ $json.price }} ({{ $json.change_pct }}%)
Sentimen: {{ $json.sentiment_label }} (skor {{ $json.sentiment_score }})
Positif {{ $json.positive_pct }}% | Netral {{ $json.neutral_pct }}% | Negatif {{ $json.negative_pct }}%
Berdasarkan {{ $json.news_count }} berita ({{ $json.window_days }} hari)
Sumber: {{ $json.news_source }}
```
 
## 12. Batasan dan aturan kerja
 
- Jangan menambah fitur di luar dokumen ini (tanpa database, autentikasi, atau Docker
  untuk API pada tahap ini).
- Jangan membaca, mencetak, atau meng-commit isi `.env`.
- Jangan menjalankan perintah destruktif (`rm -rf`, `git reset --hard`, `git clean`)
  tanpa konfirmasi.
- Kerjakan di cabang baru (`feature/multi-source-sentiment`), commit per tahap
  dengan pesan jelas (contoh: `feat: add finnhub source`, `feat: dedupe and relevance filter`,
  `test: cover aggregation`).
- Jika ada keputusan yang ambigu, pilih opsi paling sederhana dan catat alasannya
  di README bagian "Keputusan desain".
- Catat di README: semua sumber berita adalah layanan gratis pihak ketiga dengan batas
  penggunaan yang bisa berubah, hasil sentimen adalah sinyal kasar dan bukan saran
  investasi, dan key Finnhub gratis ditujukan untuk penggunaan pribadi non-komersial.
## 13. Ringkasan akhir yang harus kamu berikan
 
1. Daftar file yang dibuat, diubah, dan dihapus.
2. Hasil `pytest` dan lint.
3. Hasil verifikasi manual (bagian 10), termasuk angka artikel per sumber.
4. Variabel `.env` yang harus diisi pemilik proyek.
5. Hal yang sengaja tidak dikerjakan dan alasannya.
 
Claude finished the response
