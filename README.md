# Top Picks Today (cloud / local)

Pipeline harian: **IDX + US + Crypto** → filter ketat → `reports/top-picks/`.

> Heuristik Tuntun-style. **Bukan saran investasi.**

## Quick start

```bash
pip install -r requirements.txt
chmod +x run_top_picks.sh run_screener.sh
./run_top_picks.sh
```

Env opsional:

| Var | Default | Ket |
|-----|---------|-----|
| `STRICTNESS` | `balanced` | `loose` / `balanced` / `strict` |
| `LIMIT` | `5` | max picks per pasar |
| `SKIP_IDX` / `SKIP_US` / `SKIP_CRYPTO` | `0` | set `1` untuk skip |

Output: `reports/top-picks/YYYY-MM-DD.md` + `latest.md`

## Screener terpisah (legacy)

```bash
./run_screener.sh all   # atau idx | crypto | us
```

## Web dashboard (Vercel)

UI interaktif ada di folder [`web/`](web/) — dua mode:

1. **Top Picks** — tab IDX / US / Crypto (screener undervalued)
2. **Portfolio** — review paper trade lintas pasar (dari skill `portfolio-review`)

Deploy gratis ke `*.vercel.app`:

1. Import repo di [vercel.com/new](https://vercel.com/new)
2. Set **Root Directory** = `web`
3. Deploy

Update portfolio di web: copy `~/.cursor/skills/portfolio-review/reports/latest.md` → `reports/portfolio/`, lalu push `main` (auto-rebuild Vercel).

Detail: [`web/README.md`](web/README.md)

## Cursor Automation (cloud)

1. Repo: `laniasepsutisna/screener-auto` · branch `main`
2. Trigger: Senin–Jumat **08:00 WIB** (`0 1 * * 1-5` UTC)
3. Agent: jalankan `./run_top_picks.sh`, lalu commit & push laporan di `reports/`

Lihat instruksi lengkap di draft Automation di Cursor.

## Local Windows (skill)

Skill lokal tetap ada di `~/.cursor/skills/top-picks-today/` (PowerShell).
Repo ini = versi cloud-portable yang sama.
