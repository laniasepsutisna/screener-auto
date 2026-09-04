# Screener Web (Vercel)

Dashboard interaktif untuk laporan di `reports/` (IDX · US · Crypto).

## Local

```bash
cd web
npm install
npm run dev
```

Buka [http://localhost:3000](http://localhost:3000).

## Deploy Vercel (gratis `*.vercel.app`)

Production: https://screener-auto.vercel.app  
Project Vercel: `screener-dashboard` · **Root Directory:** `web`

### Auto-rebuild saat push (wajib sekali)

1. Install **Vercel GitHub App**: https://github.com/apps/vercel/installations/new  
   - Pilih akun `laniasepsutisna`  
   - Beri akses ke repo `screener-auto` (atau All repositories)
2. Di folder `web/`, jalankan:

```powershell
./scripts/connect-github.ps1
```

Setelah itu, setiap push ke `main` (termasuk update `reports/`) akan rebuild otomatis.

### Manual deploy

```bash
cd web
npx vercel --prod
```

Data laporan di-load dari `reports/` (lokal) atau GitHub raw saat build di Vercel.

### Update Portfolio otomatis

Dari skill `portfolio-review`:

```powershell
# Review + copy ke repo + push (Vercel rebuild)
& "$env:USERPROFILE\.cursor\skills\portfolio-review\portfolio_review.ps1" -PushWeb

# Atau sync saja tanpa push:
.\scripts\sync-portfolio.ps1
.\scripts\sync-portfolio.ps1 -Push

# Sync entry snapshot saja (untuk live price)
.\scripts\sync-positions.ps1
.\scripts\sync-positions.ps1 -Push
```

### Portfolio LIVE

Tab **Portfolio** memanggil `/api/portfolio/live` setiap ~20 detik:

- IDX / US harga: Yahoo Finance (`.JK` / ticker US)
- Crypto: CoinGecko
- Entry & weight dari `public/data/positions.json` (bukan markdown statis)
- Kolom **Hari ini** = fluktuasi vs previous close; **Return** = vs harga entry

Markdown `reports/portfolio/latest.md` tetap ada sebagai fallback/arsip.
### Security headers

Production mengirim: `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, `Content-Security-Policy` (+ HSTS dari Vercel).

## Catatan

- Data dibaca dari `../reports/*/latest.md` saat build
- Filter/sort di browser (client-side)
- Bukan saran investasi
