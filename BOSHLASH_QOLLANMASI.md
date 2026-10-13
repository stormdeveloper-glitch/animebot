# 🤖 BITTA BOT — tayyor qo'llanma (0 → ishlaydigan bot)

Bu qo'llanma **bitta Telegram bot** orqali hamma narsani ishga tushiradi:
user panel + admin panel + web app. Yon qo'shimcha bot kerak emas
(`SUPPORT_BOT_TOKEN` bo'sh qoldirilsa, support bot avtomatik o'chadi).

Vaqt: ~20 daqiqa. Barcha xizmatlar bepul.

---

## 0. Nima kerak (hammasi bepul)

| Narsa | Manzil | Nega |
|---|---|---|
| Telegram akkaunt | t.me | bot yaratish uchun |
| **BotFather** | t.me/BotFather | bitta bot + token |
| GitHub | github.com | kodni saqlash |
| Railway | railway.app | bot ishga tushirish (Python) |
| 000webapp | 000webhost.com / 000webapp.com | statik veb-sahifa (ixtiyoriy, 5-bosqich) |

---

## 1. Bitta Telegram bot yaratish (BotFather)

1. `t.me/BotFather` → `/start`
2. `/newbot`
3. Nom: `AnimeUz Bot` (istalgan)
4. Username: `animeuz_bot_2026` (noyob bo'lishi shart; Mos emas deganda boshqasini yozing)
5. BotFather sizga **TOKEN** beradi:
   `8123456789:AAFxxxxxxxxxxxxxxxxxxxxxxxxxxxx` — **bu bitta token butun botni boshqaradi.**
   Uni nusxalang va hech qayerga (kod, GitHub, HTML) **yozmang**.
6. Botga buyruqlar ro'yxatini bering:

```
/setcommands
```
shu matnni yuboring:
```
Bosh menyu — Asosiy menyu
Qidiruv — Anime izlash
Web — Web appni ochish
Yordam — Qo'llanma
Panel — Admin paneli
```
7. (ixtiyoriy) `/setuserpic`, `/setdescription`, `/setabouttext`.

✅ Natija: **1 ta bot, 1 ta token** — boshqa bot yaratish shart emas.

---

## 2. 📁 Kodni GitHub'ga yuklash

1. `github.com` → **New repository** → nom: `animebu-bot` → Private
2. Bu papkadagi (`animebot-main`) **hamma faylni** yuklang.
   `data/` papkasini ham yuklang (ichida `.gitkeep` bor).
3. **`.env` faylini KIRMANG** — token u yerda emas, Railway'ga keyin qo'yiladi (6-bosqich).

> Agar xohlasangiz, men Git'ni o'zim sozlab, commit + push qilib beraman — ayting kifoya.

---

## 3. 🔑 Telegram ID'ni o'zingizni topish

1. `t.me/userinfobot` ga `/start` yuboring.
2. Bot sizga **raqam** beradi (masalan `123456789`). Bu sizning Telegram ID'ngiz —
   6-bosqichda `SUPER_ADMIN_ID` ga yoziladi.

---

## 4. 🚂 Botni Railway'da ishga tushirish (asosiy qadam)

1. `railway.app` → **GitHub bilan** kirish
2. **+ New Project** → **Deploy from GitHub repo** → yuqoridagi reponi tanlang
3. **Settings** → *Root Directory*: `animebot-main` (repo ichida papka bo'lsa)
4. **Settings** → **Variables** → quyidagilarni qo'shing:

```
BOT_TOKEN            = 8123456789:AAFxxxxxxxxxxxxxxxxxxxxxxxxxxxx
BOT_USERNAME         = animeuz_bot_2026
SUPER_ADMIN_ID       = 123456789
ADMIN_IDS            = 123456789
CUSTOM_EMOJI_ENABLED = 0
```

> ⚠️ `DATABASE_URL`, `MYSQL_URL` — **qo'shmang** (ularni qo'shsangiz, bot bazani
> e'tiborsiz qoldiradi va hamma so'rov yiqiladi).

5. **Volume qo'shing** (bazani o'chirib yubormaslik uchun — juda muhim):
   Settings → **+ New** → **Volume**
   - Mount path: `/app/data`
   - Size: `1 GB`
6. **Deploy** (avtomatik boshlanadi) → build ~3–5 daqiqa.
7. Settings → **Domains** → *Generate Domain* → beriladi manzil:
   `https://animebot-xxxx.up.railway.app`
8. O'sha manzilni **brauzerda oching** — "AnimeUz" sayti ko'rinsa hammasi tayyor.

---

## 5. 🌐 Web App (Mini App) — 000webapp va haqiqat

**Muhim texnik haqiqat:** `000webapp.com` / `000webhost.com` **faqat statik sahifalarni**
(HTML/CSS/JS) qabul qiladi. Bu loyihaning web app'i (`index.html`) `https://.../api/animes`
kabi **Python backend'iga** murojaat qiladi. 000webapp'da Python yo'q, shuning uchun
o'sha manzilda sayt ochiladi, lekin anime ma'lumotlari yuklanmaydi.

**Shuning uchun 2 ta variant:**

### Variant A — TAVSIYA (000webapp kerak emas, hammasi bitta manzilda)
Web app **Railway'dagi bot bilan birga** ishlaydi: `https://animebot-xxxx.up.railway.app`
sayti ham, API ham bir yerda. Bot sozlamalarida shu manzilni `web_app_url` qilib qo'ysangiz
bo'ldi — "🌐 Web App" tugmasi darhol ishlaydi.

### Variant B — 000webapp'da alohida sahifa (faqat ko'rish uchun)
1. `000webhost.com` → **Get Started** → email + parol bilan ro'yxatdan o'ting
2. **Build a Website** → **Upload your site**
3. **Upload files** → `index.html`, `style.css`, `script.js`, `privacy.html`, `terms.html` ni yuklang
4. Beriladi manzil: `https://sizningism.000webhostapp.com` (SSL avtomatik)
5. Bu manzilni `web_app_url` ga **qo'ymang** (API ishlamaydi) — `web_app_url` ga
   Railway manzilini qo'ying (Variant A dagidek).

---

## 6. 🎛 Web app manzilini botga ulash

Telegram'da botni oching:

1. `🗄 Boshqarish`
2. `*️⃣ Birlamchi sozlamalar`
3. `web_app_url` ni tanlang → `https://animebot-xxxx.up.railway.app` yozing (https:// bilan, oxirida / **bo'lmasin**) → **Saqlash**
4. Endi `🏠 Asosiy menyu` yoki `/menu` → user menyusida `🌐 Web App` tugmasi paydo bo'ladi.

---

## 7. 🧰 Birinchi sozlamalar (faqat boshlovchi uchun)

| Qadam | Qayerda | Nima qilinadi |
|---|---|---|
| Admin qo'shish | `/panel` → `📋 Adminlar` | foydalanuvchi ID sini yuboring |
| Kanallar | `/panel` → `📢 Kanallar` | obuna majburiy bo'lsa; bot kanalda **admin** bo'lishi shart |
| Anime qo'shish | `/panel` → `🎥 Animelar sozlash` → `➕ Anime qo'shish` | nom, kod, status |
| Qism qo'shish | web: `https://animebot-xxxx.up.railway.app/admin` | "Qism qo'shish" → botga havola keladi |
| Xush kelish matni | `/panel` → `📃 Matnlar` | `{name}` joyiga ism qo'yiladi |
| To'lov kartasi | `/panel` → `💳 Hamyonlar` | foydalanuvchilarga ko'rinadi |
| Matnli tugmalar | `/panel` → `🎛 Tugmalar` | anime kartasiga havola qo'shish |
| Bot rejimi | `/panel` → `🤖 Bot holati` | "O'chirilgan" bo'lsa oddiy userlar faqat "tamirlanmoqda" ko'radi |

---

## ✅ 8. Yakuniy tekshirish ro'yxati

- [ ] Oddiy (admin emas) akkaunt bilan `/start` → **menyu chiqadi**
- [ ] `🔎 Anime izlash` → `🏷 Anime nomi orqali` → nom yozing → anime kartasi
- [ ] Kartada `📥 Yuklash` / `▶️ 1-qismdan boshlash` ishlaydi
- [ ] `🌐 Web App` → sahifa ochiladi va animelar ro'yxati chiqadi
- [ ] `/panel` → `📊 Statistika` → raqamlar
- [ ] Telefonda ham, kompyuterda ham menyu **almashadi**
- [ ] `◀️ Orqaga` → `🏠 Asosiy menyu` → user panel qaytadi
- [ ] Railway → Logs → qizil xato yo'q

---

## ❗ 9. Ko'p uchraydigan xatolar

| Xato / alomat | Sabab | Yechim |
|---|---|---|
| Bot **umuman javob bermayapti** | Railway'da xato yoki token noto'g'ri | Railway → Logs → birinchi qizil xatoni o'qing |
| `Conflict: terminated by other getUpdates request` | **Ikkita joyda** ishlab turibdi (kompyuteringizda `run.bat` + Railway) | kompyuterdagi botni to'xtating, faqat Railway qolsin |
| `can't parse entities` / `Unsupported start tag "tg-emoji"` | custom emoji yoki HTML | `CUSTOM_EMOJI_ENABLED=0` (hozir shunday qilingan; eskicha kodda esa xabar umuman ketmas edi — endi fallback tufayli baribir ketadi) |
| Web App ochilmaydi | manzil `https://` emas yoki oxirida `/` bor | `https://...up.railway.app` (so'ng `/` yo'q) |
| Bazani yo'qotish | Volume qo'shilmagan | Settings → Volume → `/app/data` |
| Web app'da animelar bo'sh (000webapp variantida) | 000webapp'da Python API yo'q | Variant A (Railway) ni ishlating |
| `Database closed` / `no such table` | boshqa DB yo'li | `DATABASE_URL` ni **o'chiring** |
| Oddiy userlar faqat "tamirlanmoqda" ko'radi | Bot rejimi o'chirilgan | `/panel` → `🤖 Bot holati` → `✅ Botni Yoqish` |

---

## 🔐 10. Xavfsizlik qoidalari (qisqa)

1. `BOT_TOKEN` — faqat **Railway Variables** da. Kod ichiga, GitHub'ga, HTML'ga **yozilmaydi**.
2. GitHub repo **Private** bo'lsin.
3. Web admin (`/admin`) uchun `ADMIN_LOGIN` / `ADMIN_PASSWORD` kiritsangiz, ularni ham Railway'ga qo'ying.
4. Railway'da `*.env` faylini qo'ymang — faqat Variables.
5. Web app'da `web_app_url` faqat `https://` bilan.

---

## 📌 Xulosa: nima qayerda turadi

```
Telegram (1 ta bot, 1 ta token)
   ├── Bot serveri  → Railway (Python, main.py, /app/data volume)
   └── Web app      → Railway (index.html + API, bir xil manzil)
                      (000webapp faqat statik nusxa uchun, Variant B)

Boshqaruv: /panel (Telegram) + https://...up.railway.app/admin (web)
```

Hammasi shu. Keyingi qadam — **GitHub'ga yuklash va Railway deploy**;
xohlasangiz, men shu ikki qadamni ham qilib beraman.
