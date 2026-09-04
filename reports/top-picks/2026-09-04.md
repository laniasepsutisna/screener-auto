# Top Picks Today
**Tanggal:** 2026-09-04  |  **UTC:** 2026-09-04T03:12:49Z  |  **Strictness:** balanced  |  **Limit/pasar:** 5

> Screener + QC otomatis. **Bukan saran investasi.** Paper/heuristik saja.

---

## Ringkasan entry

| Pasar | Status | Gate |
|-------|--------|------|
| IDX | OK (tanpa QC) | UV≥15% · kualitas≥Bagus · QC (Yahoo) |
| US | OK | UV≥15% · kualitas≥Bagus |
| Crypto | OK | UV≥15% · kualitas≥Best · --safe-only --ta-confirm --macro-filter |

**Prioritas modal:** IDX (core) → US (defensif) → Crypto (sizing kecil)

### Matriks cepat

| Kondisi | Aksi |
|---------|------|
| Lolos filter + QC/TA OK | **Entry kandidat** |
| UV tinggi tapi QC/TA gagal / caveat | **Tunggu / Skip** |
| 0 lolos di semua pasar | **Cash** — jangan dipaksa beli |

---

## IDX — boleh entry (QC)

~~~
# Top Undervalued

**5 saham dalam daftar** · Filter: Undervalued (%) ≥ 15% · Kualitas ≥ Bagus · Universe: liquid (80 fetched) · Sumber: Yahoo Finance · Median PER 8.7

| Saham | Kualitas | Undervalued (%) | Tanpa Posisi | Ada Posisi | Harga | Harga Wajar | PER | PBV | PEG |
|-------|----------|-----------------|--------------|------------|-------|-------------|-----|-----|-----|
| **BUKA** Bukalapak.com Tbk. | Bagus | 72% | Beli | Hold | 115 | 318 - 489 | 6.16 | 0.43 | - |
| **KBLI** KMI Wire & Cable T… | Bagus | 70% | Beli | Hold | 332 | 869 - 1,340 | 6.04 | 0.46 | - |
| **SIMP** Salim Ivomas Prata… | Bagus | 69% | Beli | Hold | 645 | 1,619 - 2,496 | 4.61 | 0.48 | 0.87 |
| **CTRA** Ciputra Developmen… | Bagus | 68% | Beli | Hold | 640 | 1,586 - 2,445 | 4.56 | 0.48 | 0.44 |
| **JSMR** Jasa Marga (Perser… | Bagus | 62% | Beli | Hold | 3,000 | 6,140 - 9,466 | 5.9 | 0.59 | 1.36 |

_Tuntun Guidance: Tanpa Posisi = belum punya · Ada Posisi = sudah hold_

_Data: Yahoo Finance (.JK) · Metodologi: Tuntun-style (PBV/PER/PEG band + kualitas heuristik)_
_Tanpa token Stockbit. Angka UV%/kualitas bisa beda dari app Tuntun._
_Bukan saran investasi._
~~~

---

## US — boleh entry

~~~
# Top Undervalued US

**5 saham dalam daftar** · Filter: Undervalued (%) ≥ 15% · Kualitas ≥ Bagus · Universe: liquid (91 fetched) · Median PER 22.8

| Saham | Kualitas | Undervalued (%) | Tanpa Posisi | Ada Posisi | Harga | Harga Wajar | PER | FwdPE | PBV | Yield |
|-------|----------|-----------------|--------------|------------|-------|-------------|-----|-------|-----|-------|
| **MU** Micron Technology, Inc. | Best | 65% | Beli | Hold | 958.16 | 2,325.38 - 3,100.50 | 21.6 | 6.2 | 10.74 | 6.0% |
| **T** AT&T Inc. | Bagus | 42% | Beli | Hold | 26.19 | 38.46 - 51.27 | 8.6 | 10.2 | 1.63 | 4.3% |
| **PYPL** PayPal Holdings, Inc. | Bagus | 35% | Beli selektif | Hold | 56.82 | 77.00 - 99.00 | 10.3 | 9.8 | 2.47 | 1.0% |
| **INTU** Intuit Inc. | Best | 28% | Beli | Hold | 344.30 | 409.96 - 546.61 | 20.8 | 12.6 | 4.93 | 1.6% |
| **UPS** United Parcel Service,… | Bagus | 27% | Beli selektif | Hold | 103.50 | 121.12 - 161.50 | 19.2 | 12.8 | 5.85 | 6.4% |

### Catatan

- **MU**: Forward EPS jauh di atas trailing — sensitif ke revisi analis

_Tuntun Guidance: Tanpa Posisi = belum punya · Ada Posisi = sudah hold_

_Data: Yahoo Finance · Metodologi: Tuntun-style (PE/PBV band + kualitas heuristik)_
_Bukan saran investasi. Belum ada eksekusi broker US dari skill ini._
~~~

---

## Crypto — boleh entry (safe)

~~~
# Top Undervalued Crypto

**1 coin dalam daftar** · Filter: Undervalued (%) ≥ 15% · Kualitas ≥ Best · Risk: value trap excluded · Grade A/B only · TA: Entry OK / Selektif · Macro filter on

## Kondisi Makro

**BTC.D:** 59.28% (Tinggi (alt underperform risk)) · **Regime:** Neutral  
**BTC 7d:** +0.4% · **Alt median 7d:** +0.0% · **MCap 24j:** +1.1% · **Fear & Greed:** 74 (Greed)

| Coin | Grade | Undervalued | TA | RSI | Dist S | Unlock | Guidance | Harga | Stop Loss | R:R |
|------|-------|-------------|----|-----|--------|--------|----------|-------|-----------|-----|
| **SOL** | A | 47% | Selektif | 67 | 0.9% | — | Beli | 104.0000 | 92.0070 | 7.84 |

## Rekomendasi Alokasi Portofolio (risk-adjusted)

| Coin | Grade | Alokasi | USD | Stop Loss | Take Profit | R:R |
|------|-------|---------|-----|-----------|-------------|-----|
| **SOL** | A | 5.0% | $500 | 92.0070 | 197.9843 | 7.84 |

**Kandidat teraman (Grade A/B):** SOL (A, R:R 7.84)

**TA timing:** Selektif: SOL


_Tuntun Guidance: Tanpa Posisi = belum punya coin · Ada Posisi = sudah hold_
_Risk: Grade A=aman · B=moderat · C=agresif · D=tolak · Stop loss = 2×ATR atau support 14d_
_TA: RSI(14) + jarak ke support 14d · Entry OK / Selektif / Tunggu / Hindari_
_Macro: BTC.D + regime (BTC/Alt/Neutral) + Fear & Greed — filter alt saat BTC season_
_Data: CoinGecko · MVRV/NVT = proxy heuristik · Whale = volume+momentum proxy_
_Bukan saran investasi. Crypto sangat volatil — selalu gunakan stop loss._
~~~

---

## Skip list hari ini

- Caveat forward EPS agresif (US growth menyamar value)
- IDX PBV ekstrem / PER one-off earning
- Crypto unlock risk Tinggi / value trap / alt di BTC season ekstrem
- UV ekstrem tanpa konfirmasi kualitas + QC/TA

_Generated by `run_top_picks.sh` · reports/top-picks/2026-09-04.md_
