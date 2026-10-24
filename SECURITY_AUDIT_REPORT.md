# Xavfsizlik tekshiruvi hisoboti — animebot (web_server.py va boshqalar)

Tekshiruv turi: **statik kod tahlili** (kod diqqat bilan o'qib chiqildi + maqsadli grep
qidiruvlar; jonli hujum/ekspluatatsiya ishlatilmadi). Loyiha: Telegram bot + unga
biriktirilgan veb-ilova (aiohttp, `web_server.py`, ~3800 qator).

## Topilgan va tuzatilgan zaifliklar

### 1. `X-Forwarded-For` spoofing → barcha IP-asosli himoyani chetlab o'tish
**Joyi:** `web_server.py`, `_client_ip()` funksiyasi (SSEqadar ~306-qator)
**Darajasi:** Yuqori

So'rov yuboruvchi `X-Forwarded-For` header'ini o'zi xohlagancha o'rnata olardi, va
kod uni **hech qanday tekshiruvsiz** ishonib qabul qilardi (headerdagi birinchi
qiymatni olib). Bu header esa butun loyihadagi barcha rate-limit va bruteforce
himoyasining kaliti edi:

- `/api/admin/login` (admin login+parol urinishlari)
- AI chat kunlik kvota (`AI_IP_DAILY_GUARD`)
- Google/Spotify OAuth, Telegram link so'rovlari, report/shikoyat spam himoyasi

Har bir so'rovda `X-Forwarded-For: <random>` yuborib, bitta hujumchi har safar
"yangi IP" sifatida ko'rinib, limitsiz urinishlar qila olardi — masalan admin
login/parolni cheksiz bruteforce qilish mumkin edi (nginx/caddy konfiguratsiyasi
ham headerni **almashtirmay, qo'shib** uzatadi — `$proxy_add_x_forwarded_for` —
bu muammoni yanada kuchaytiradi, chunki kod headerning birinchi, ya'ni
hujumchi qo'shgan qiymatini olardi).

**Tuzatish:** `X-Forwarded-For` endi faqat so'rov ishonchli proksidan (localhost,
`127.0.0.1`/`::1` — nginx/caddy shu yerga proksi qiladi) kelganda hisobga
olinadi, va undan proksi qo'shgan **eng o'ngdagi** qiymat olinadi, header
qiymatining o'zi emas.

### 2. Open redirect — `/media/{file_id}`
**Joyi:** `web_server.py`, `media_proxy()` (~740-qator)
**Darajasi:** O'rta

```python
file_id = request.match_info["file_id"]
if file_id.startswith("http"):
    raise web.HTTPFound(file_id)
```

`file_id` to'g'ridan-to'g'ri URL manzilidan (hech qanday autentifikatsiyasiz,
har qanday tashrif buyuruvchi uchun) olinadi. Agar u `http`/`https` bilan
boshlansa, server **har qanday** tashqi manzilga 302 redirect qilib yuborardi:

```
https://sizning-sayt.uz/media/https://phishing-sayt.com/login
```

Bu klassik **open redirect** — fishing, ishonchni suiiste'mol qilish (haqiqiy
domen ko'rinib, boshqa saytga olib ketish), OAuth redirect hujumlari uchun
ishlatilishi mumkin edi.

**Tuzatish:** Redirect endi faqat oldindan belgilangan, ishonchli host'larga
(`anilist.co`, `kitsu.io` va ularning subdomenlari, faqat `https`) ruxsat
beradi; boshqa holatda `404` qaytaradi.

### 3. `device_id` — kriptografik jihatdan zaif, taxmin qilinishi mumkin bo'lgan identifikator
**Joyi:** `script.js`, `_getDeviceId()` (~1185-qator)
**Darajasi:** Past/O'rta

```js
id = 'dev_' + Math.random().toString(36).slice(2) + Date.now().toString(36);
```

`device_id` — bu web-profil (saqlangan animelar ro'yxati, Telegram profiliga
ulanish so'rovlari) uchun yagona identifikator bo'lib, amalda bearer-token
vazifasini bajaradi (`/api/profile/saved`, `/api/telegram/profile`,
`/api/telegram/link/*` shu orqali ishlaydi). Ammo u:
- `Math.random()` — kriptografik jihatdan ishonchli emas (CSPRNG emas);
- `Date.now()` qismi esa — foydalanuvchi saytga kirgan vaqtga yaqin qiymat,
  demak qidiruv maydoni ancha qisqaradi.

Nazariy jihatdan boshqa foydalanuvchining `device_id`'sini taxmin qilib,
uning saqlangan ro'yxatini o'qish/o'zgartirish imkoniyati mavjud edi.

**Tuzatish:** Endi `crypto.randomUUID()` (yoki `crypto.getRandomValues()`)
orqali kriptografik jihatdan ishonchli, taxmin qilib bo'lmaydigan qiymat
generatsiya qilinadi.

**Qoldiq tavsiya (hozircha qo'llanilmadi, kengroq API o'zgarishi talab qiladi):**
`device_id` ba'zi endpointlarda GET query-parametr sifatida yuboriladi
(`?device_id=...`), bu esa server/proksi loglarida, brauzer tarixida qolishi
mumkin. Kelajakda buni `POST` body yoki maxsus header orqali yuborishga
o'tkazish tavsiya etiladi.

## Qayta tekshirish (ikkinchi aylanma)

Tuzatishlardan so'ng kod yana statik tarzda qayta ko'rib chiqildi:
- `_client_ip()` — ishonchsiz proksi/to'g'ridan-to'g'ri ulanishda header
  butunlay e'tiborga olinmasligi, faqat `127.0.0.1`/`::1` orqali kelganda
  ishlatilishi tasdiqlandi.
- `media_proxy()` — ixtiyoriy tashqi URL (masalan `evil.com`) endi `404`
  qaytarishi, faqat ruxsat etilgan host'lar redirect qilinishi tasdiqlandi.
- `script.js` sintaksisi va `_getDeviceId()` mantiqi tekshirildi — endi
  `crypto.randomUUID()` ishlatiladi (qo'llab-quvvatlamaydigan muhitlarda
  `getRandomValues()` fallback bilan).

Uchala joyda ham dastlabki zaiflik qayta paydo bo'lmadi (Python/JS sintaksis
xatosiz, mantiq kutilganidek ishlaydi).

## Doirasi va cheklovlar

Bu — **kodni qo'lda va grep orqali statik ko'rib chiqish**, jonli/deploy
qilingan muhitga qarshi penetration test emas. Qo'shimcha tekshirilgan,
ammo muammo topilmagan joylar: SQL so'rovlaridagi f-string'lar (barchasi
ichki/qattiq kodlangan ustun nomlaridan, foydalanuvchi kiritmasidan emas),
`eval`/`exec`/`pickle`, `shell=True`, git tarixidagi maxfiy kalitlar, admin
login + 2FA (Telegram orqali tasdiqlash) oqimi, AniList poster yuklab olish
funksiyasi (SSRF'dan himoyalangan — faqat `anilist.co`, faqat `https`).

To'liq ishonch uchun tavsiya: `bandit`/`semgrep` kabi statik skanerlarni
loyihaga qarshi ishga tushirish, va **faqat o'zingizga tegishli/ruxsat
etilgan** muhitda avtorizatsiyalangan penetration test o'tkazish.
