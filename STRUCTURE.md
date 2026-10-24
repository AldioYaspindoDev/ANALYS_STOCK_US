Kamu adalah senior Python engineer. Tugasmu: merapikan struktur folder dan me-refactor
kode proyek ini mengikuti best practice, TANPA mengubah perilaku API yang sudah jalan.

## Konteks proyek
- FastAPI yang menyediakan endpoint GET /info/{ticker} dan GET /health.
- /info/{ticker} mengembalikan harga terakhir + perubahan persen (yfinance) dan sentimen
  berita (FinBERT, model ProsusAI/finbert). Berita diambil dari yfinance, dengan cadangan
  Google News RSS jika kosong.
- API ini nanti dipanggil oleh n8n (Docker) lewat http://host.docker.internal:8000
  untuk bot Telegram, jadi format JSON respons TIDAK BOLEH berubah:
  ticker, price, change_pct, sentiment_label, sentiment_score, news_count,
  news_source, top_headlines.
- OS: Linux. Virtual environment ada di .venv.

## Langkah 0 - Audit dulu, jangan langsung ubah
1. Tampilkan struktur folder saat ini (abaikan .venv, .git, __pycache__).
2. Baca semua file kode, docker-compose.yml, .gitignore, requirements.txt.
3. Buat daftar:
   a. file/folder yang TIDAK dibutuhkan (kosong, sisa percobaan, scratch_*.py,
      folder rencana yang belum dipakai seperti ingestion/transform/sql/data/docs
      bila kosong, __pycache__, dll.)
   b. file yang perlu dipindah atau di-rename
   c. masalah kualitas kode di main.py
4. BERHENTI dan minta konfirmasi saya sebelum menghapus apa pun.
   Jangan hapus: .git, .venv, .env, .env.example, docker-compose.yml, dan file yang
   berisi kode yang masih dipakai. Folder yang tidak kosong harus disebutkan isinya
   dan saya yang memutuskan.

## Langkah 1 - Struktur target
Gunakan struktur ini (sesuaikan hanya jika ada alasan kuat, dan jelaskan alasannya):

stock-pipeline/
├── src/
│   └── stock_api/
│       ├── __init__.py
│       ├── main.py          # hanya membuat app FastAPI, lifespan, include router
│       ├── config.py        # pengaturan dari environment (pydantic-settings)
│       ├── schemas.py       # model Pydantic untuk respons
│       ├── routers/
│       │   ├── __init__.py
│       │   └── info.py      # endpoint /info/{ticker} dan /health
│       └── services/
│           ├── __init__.py
│           ├── market.py    # ambil harga dari yfinance
│           ├── news.py      # ambil berita (yfinance + Google News) + dedupe
│           └── sentiment.py # FinBERT, skor, label
├── tests/
│   ├── test_sentiment.py
│   ├── test_news.py
│   └── test_api.py
├── docker-compose.yml
├── .env.example
├── .gitignore
├── pyproject.toml           # metadata, konfigurasi ruff dan pytest
├── requirements.txt
├── requirements-dev.txt     # pytest, ruff, httpx
└── README.md

## Langkah 2 - Refactor kode (best practice)
- Pisahkan tanggung jawab: router hanya mengurus HTTP, logika ada di services.
  Fungsi di services tidak boleh bergantung pada FastAPI.
- Model FinBERT dimuat sekali lewat lifespan FastAPI (bukan global variable mutable
  dengan lazy load manual). Pertimbangkan opsi untuk memuat saat startup agar request
  pertama tidak lambat, dan jelaskan trade-off-nya singkat.
- Gunakan Pydantic response_model untuk respons /info agar kontrak JSON eksplisit
  dan terdokumentasi di /docs.
- Semua konstanta (ambang batas label 0.15, jumlah berita maksimum 10, timeout HTTP,
  nama model, User-Agent) pindah ke config.py dan bisa diubah lewat environment.
- Pakai logging modul standar (bukan print). Log sumber berita yang dipakai dan
  kegagalan jaringan, tanpa membocorkan data sensitif.
- Error handling: jangan gunakan `except Exception: pass` yang menelan error tanpa jejak.
  Tangkap exception yang spesifik, catat di log, lalu kembalikan hasil fallback yang jelas.
- Validasi ticker pakai regex yang jelas (huruf, boleh titik dan tanda hubung
  seperti BRK-B, panjang maksimum wajar), dengan pesan error yang konsisten.
- Endpoint bersifat blocking (yfinance, requests, FinBERT), jadi gunakan `def` biasa
  agar dijalankan di threadpool, bukan `async def` yang memblokir event loop.
- Tambahkan cache sederhana dengan TTL (misalnya 5 menit per ticker) agar tidak
  memanggil yfinance dan FinBERT berulang-ulang. Implementasi in-memory tanpa library
  berat sudah cukup; buat TTL bisa diatur dari config.
- Type hints lengkap, docstring singkat untuk fungsi publik, tidak ada kode duplikat.
- Jangan menambah fitur baru dan jangan over-engineering. Tidak perlu database,
  Docker untuk API, atau autentikasi pada tahap ini.

## Langkah 3 - Tes
- Tulis tes pytest untuk: label_from_score (termasuk batas nilai dan None),
  dedupe, parsing dua format berita yfinance, parsing RSS Google News,
  dan endpoint /health serta /info dengan semua dependensi eksternal di-mock
  (yfinance, requests, FinBERT). Tes tidak boleh memanggil internet atau mengunduh model.
- Jalankan `pytest` dan pastikan lulus.

## Langkah 4 - Tooling dan dokumentasi
- Isi pyproject.toml dengan konfigurasi ruff (lint + format) dan pytest.
- Jalankan `ruff check` dan `ruff format`, perbaiki semua temuan.
- Rapikan requirements.txt: hanya dependensi yang benar-benar dipakai, versi di-pin,
  dan pisahkan dependensi dev ke requirements-dev.txt.
- Rapikan .gitignore (.venv, __pycache__, .env, .pytest_cache, .ruff_cache, dan sejenisnya).
- Perbarui .env.example dengan semua variabel yang dipakai (tanpa nilai rahasia).
- Tulis README.md singkat: deskripsi, cara setup di Linux, cara menjalankan
  (uvicorn src.stock_api.main:app --reload --host 0.0.0.0), cara menjalankan tes,
  contoh respons /info/STX, dan catatan bahwa yfinance dan Google News bukan sumber resmi.

## Langkah 5 - Verifikasi
1. Jalankan API dan uji dengan curl: /health, /info/STX, /info/AAPL, /info/ZZZZZ (harus 404),
   dan ticker tidak valid (harus 400).
2. Bandingkan bentuk JSON /info/STX dengan daftar field di bagian Konteks. Harus identik.
3. Tampilkan ringkasan: file yang dihapus, dipindah, dan dibuat; keputusan desain penting;
   perintah baru untuk menjalankan API; hal yang sengaja tidak dikerjakan.

## Aturan umum
- Kerjakan bertahap dan commit per tahap dengan pesan commit yang jelas
  (contoh: "refactor: pisahkan services", "test: tambah unit test").
- Jangan menjalankan perintah destruktif (rm -rf, git reset --hard, git clean)
  tanpa konfirmasi saya.
- Jangan membaca, mencetak, atau meng-commit isi file .env.
- Jika ada keputusan yang ambigu, pilih opsi paling sederhana dan catat alasannya.
- Jelaskan dalam bahasa Indonesia, kode dan komentar boleh dalam bahasa Inggris.