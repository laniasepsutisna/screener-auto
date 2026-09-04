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

1. Push repo ke GitHub (sudah: `laniasepsutisna/screener-auto`)
2. Buka [vercel.com/new](https://vercel.com/new) → Import repo
3. **Root Directory:** `web`
4. Framework: Next.js (otomatis)
5. Deploy

URL contoh: `https://screener-auto.vercel.app`

Setiap push report baru ke `main` akan rebuild otomatis.

## Catatan

- Data dibaca dari `../reports/*/latest.md` saat build
- Filter/sort di browser (client-side)
- Bukan saran investasi
