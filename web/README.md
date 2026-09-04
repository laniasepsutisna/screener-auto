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

## Catatan

- Data dibaca dari `../reports/*/latest.md` saat build
- Filter/sort di browser (client-side)
- Bukan saran investasi
