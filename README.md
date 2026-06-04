# 🎬 Anime Telegram Bot

> **O'zbek tilidagi anime Telegram boti** — foydalanuvchilar anime qidirishi, VIP obuna olishi va qismlarni ko'rishi mumkin bo'lgan to'liq funksiyali bot.

---

## 📋 Mundarija

- [Xususiyatlar](#-xususiyatlar)
- [Texnologiyalar](#-texnologiyalar)
- [Loyiha tuzilishi](#-loyiha-tuzilishi)
- [Ma'lumotlar bazasi](#-malumotlar-bazasi)
- [O'rnatish va ishga tushirish](#-ornatish-va-ishga-tushirish)
- [Muhit o'zgaruvchilari](#-muhit-ozgaruvchilari)
- [Admin funksiyalari](#-admin-funksiyalari)
- [Foydalanuvchi funksiyalari](#-foydalanuvchi-funksiyalari)
- [Kanal turlari](#-kanal-turlari)
- [VIP tizimi](#-vip-tizimi)
- [Referal tizimi](#-referal-tizimi)
- [Web App va Dashboard](#-web-app-va-dashboard)
- [Deploy (Railway)](#-deploy-railway)
- [AI sozlamalari](#ai-sozlamalari)
- [Litsenziya](#litsenziya)

---

## ✨ Xususiyatlar

###  Foydalanuvchilar uchun
| Funksiya | Tavsif |
|---|---|
| 🔎 Anime qidirish | Nom, janr, yoki ID orqali qidirish |
| 📺 Qismlarni ko'rish | Paginatsiyali navigatsiya (24 ta/sahifa) |
| 💎 VIP obuna | 30/60/90 kunlik rejalash |
| 💰 Hisobim | Balans va pul o'tkazmasi |
| 👥 Referal | Referal havolasi orqali bonus olish |
| 🎁 Cashback | Xaridlarda foiz qaytarish |
| 👍 Like/Dislike | Anime baholash tizimi |
| 🌐 Web App | Mini App orqali ko'rish |

### 🗄 Adminlar uchun
| Funksiya | Tavsif |
|---|---|
| 📊 Statistika | Foydalanuvchilar, VIP, anime soni |
| ✉ Broadcast | Barcha foydalanuvchilarga xabar |
| 🎥 Anime boshqarish | Qo'shish, tahrirlash, o'chirish |
| 📢 Kanal boshqarish | 5 turdagi kanal (majburiy, social va b.) |
| 🔎 User boshqarish | Ban/unban, profilni ko'rish |
| 📬 Post tayyorlash | Media + inline tugmali post |
| � To'lovlarni tasdiqlash | VIP to'lovlarni qabul/rad etish |
| 🤖 Bot holati | Texnik ish rejimini yoqish/o'chirish |
| 📋 Admin boshqarish | JSON admin qo'shish/o'chirish (super admin) |
| 📋 Jurnallar | Admin harakatlari tarixi |

---

## 🛠 Texnologiyalar

| Kutubxona | Versiya | Maqsad |
|---|---|---|
| `aiogram` | ≥ 3.0.0 | Telegram Bot Framework |
| `aiosqlite` | latest | Asinxron SQLite baza |
| `python-dotenv` | latest | `.env` faylidan sozlamalar |
| `aiohttp` | ≥ 3.9.0 | Web server va HTTP so'rovlar |

## AI sozlamalari

Bot AI chaqiruvlari OpenAI-compatible `chat/completions` endpoint orqali ishlaydi.
Hozircha ChatGPT/OpenAI API ishlatiladi:

```env
AI_BASE_URL=https://api.openai.com/v1
AI_API_KEY=your_api_key
AI_MODEL=gpt-4o-mini
```

`OPENAI_API_KEY` ham ishlaydi, lekin yangi sozlashlarda `AI_API_KEY` ishlatish
tavsiya etiladi.

## Litsenziya

Ushbu botning o'z kodi Apache License 2.0 ostida tarqatiladi. Batafsil: `LICENSE`.
Copyright va attribution ma'lumotlari: `NOTICE`.

Uchinchi tomon kutubxonalari, AI modellari, API xizmatlari va assetlar o'z
litsenziyalariga ega bo'lishi mumkin. Batafsil: `THIRD_PARTY_NOTICES.md`.

**Python versiyasi:** 3.10+

---

## 📁 Loyiha tuzilishi

```
bot-main/
├── main.py              # Asosiy ishga tushirish fayli
├── config.py            # Sozlamalar (.env dan o'qiydi)
├── database.py          # DB initsializatsiyasi (barcha jadvallar)
├── keyboards.py         # Reply va Inline klaviaturalar
├── states.py            # FSM holatlari
├── web_server.py        # aiohttp web server + real-time dashboard
│
├── handlers/
│   ├── __init__.py
│   ├── admin_handlers.py    # Admin paneli barcha handlerlar (~2200 qator)
│   ├── user_handlers.py     # Foydalanuvchi handlerlar (~1530 qator)
│   └── inline_handlers.py   # Inline callback handlerlar
│
├── utils/
│   ├── __init__.py          # is_admin, check_subscription, cache tizimi
│   ├── admin_manager.py     # JSON admin qo'shish/o'chirish
│   └── logger.py            # Admin harakatlari jurnali
│
├── data/                # SQLite bazasi saqlanadigan papka
│   └── bot.db
│
├── .env.example         # Muhit o'zgaruvchilari namunasi
├── requirements.txt     # Python kutubxonalari
├── Procfile             # Railway/Heroku uchun
├── railway.toml         # Railway deploy sozlamalari
├── runtime.txt          # Python versiyasi
├── run.bat              # Windows uchun ishga tushirish
└── index.html           # Web dashboard sahifasi
```

---

## 🗄 Ma'lumotlar bazasi

Bot **SQLite** (`data/bot.db`) dan foydalanadi. Jadvallar `init_db()` funksiyasida avtomatik yaratiladi.

### `users` — Foydalanuvchilar
| Ustun | Tur | Tavsif |
|---|---|---|
| `user_id` | INTEGER | Telegram ID (unique) |
| `status` | TEXT | Status (`Oddiy`, `VIP`) |
| `pul` | INTEGER | Asosiy balans (so'm) |
| `pul2` | INTEGER | Referal bonuslari |
| `odam` | INTEGER | Taklif qilganlar soni |
| `ban` | TEXT | `unban` yoki `ban` |
| `refid` | INTEGER | Kim orqali kelgani (referrer ID) |
| `joined_at` | DATETIME | Ro'yxatdan o'tgan sana |

### `animelar` — Animalar katalogi
| Ustun | Tavsif |
|---|---|
| `nom` | Anime nomi |
| `rams` | Muqova (Telegram file_id — rasm yoki video) |
| `qismi` | Jami rejalangan qismlar soni |
| `davlat` | Ishlab chiqaruvchi mamlakat |
| `tili` | Til |
| `yili` | Chiqarilgan yili |
| `janri` | Janrlar (vergul bilan ajratilgan) |
| `qidiruv` | Ko'rishlar soni (view counter) |
| `aniType` | Holati (`🔸 OnGoing`, `✅ Yakunlangan`) |
| `fandub` | Ovoz bergan studio/kanal |
| `kanal` | Anime kanali (oxirgi qismda ko'rinadi) |
| `liklar` | Ijobiy ovozlar |
| `desliklar` | Salbiy ovozlar |

### `anime_datas` — Qismlar
| Ustun | Tavsif |
|---|---|
| `id` | Anime ID ga bog'liq |
| `file_id` | Telegram video file_id |
| `qism` | Qism raqami |
| `msg_id` | Yuborilgan xabar ID si |
| `chat_id` | Yuborilgan chat ID si |

### `channels` — Kanallar
```
channelId, channelType, channelLink, channelName
```

### `vip_status` — VIP obunalar
```
user_id, kun (qolgan kunlar), date (tugash sanasi)
```

### `admins` — JSON adminlar (DB orqali)
```
user_id, added_by
```

### `bot_texts` — Sozlanuvchi matnlar
| Key | Default tavsif |
|---|---|
| `guide` | Qo'llanma matni |
| `ads` | Reklama matni |
| `wallet` | Karta raqami |

### `bot_settings` — Bot sozlamalari
| Key | Default | Tavsif |
|---|---|---|
| `vip_price` | `5000` | VIP narxi (30 kun) |
| `vip_currency` | `so'm` | Valyuta |
| `referral_bonus` | `500` | Referal bonus miqdori |
| `cashback_percent` | `5` | Cashback foizi |
| `bot_maintenance` | `0` | Texnik ish rejimi (1=yoqilgan) |
| `web_app_url` | `""` | Mini App URL si |

### `payments` — To'lovlar
```
user_id, amount, purpose, status (pending/approved/rejected), check_file_id
```

### `custom_buttons` — Maxsus tugmalar
```
text, url
```

---

## ⚙️ O'rnatish va ishga tushirish

### 1. Repozitoriyani yuklab oling
```bash
git clone https://github.com/stormdeveloper-glitch/bot.git
cd bot
```

### 2. Virtual muhit yarating
```bash
python -m venv venv

# Windows:
venv\Scripts\activate

# Linux/Mac:
source venv/bin/activate
```

### 3. Kutubxonalarni o'rnating
```bash
pip install -r requirements.txt
```

### 4. Muhit o'zgaruvchilarini sozlang
```bash
cp .env.example .env
# .env ni tahrirlang
```

### 5. Botni ishga tushiring
```bash
python main.py

# Windows da:
run.bat
```

---

## 🔐 Muhit o'zgaruvchilari

`.env` faylini `.env.example` asosida to'ldiring:

```env
# Botfather dan oling
BOT_TOKEN=1234567890:AABBCCDDEEFFaabbccddeeff

# Bot username (@si z)
BOT_USERNAME=my_anime_bot

# Super admin Telegram ID (siz)
SUPER_ADMIN_ID=123456789

# Qo'shimcha adminlar (vergul bilan)
ADMIN_IDS=123456789,987654321

# Asosiy kanal ID
MAIN_CHANNEL_ID=-1001234567890

# Asosiy kanal username
MAIN_CHANNEL_USERNAME=@anime_movie_uz
```

> **Eslatma:** `SUPER_ADMIN_ID` va `ADMIN_IDS` `.env` orqali beriladi va DB dan mustaqil ishlaydi.

---

## 🗄 Admin funksiyalari

### Admin panelga kirish
Faqat adminlar uchun: `/panel` komandasi yoki `🗄 Boshqarish` tugmasi.

### Admin darajalari
| Daraja | Qanday boshqariladi | Huquqlar |
|---|---|---|
| **Super Admin** | `.env` → `SUPER_ADMIN_ID` | Hammasi + admin qo'shish, jurnal ko'rish |
| **Admin** | `.env` → `ADMIN_IDS` | Super admin huquqlari bilan teng (env da) |
| **JSON Admin** | DB → `admins` jadvali | Faqat panel funksiyalari |

### Anime qo'shish jarayoni
Admin paneldan `🎥 Animelar sozlash` → `➕ Anime qo'shish` bosib, ketma-ket:
1. Anime nomini kiriting
2. Jami qismlar sonini kiriting
3. Davlat (ishlab chiqaruvchi mamlakat)
4. Tili
5. Chiqarilgan yili
6. Janrlari (vergul bilan)
7. Fandub studio nomi
8. Holatini kiriting (`🔸 OnGoing` yoki `✅ Yakunlangan`)
9. Muqova rasm yoki video yuboring

Anime muvaffaqiyatli qo'shilgandan so'ng **Anime kodi (ID)** beriladi.

### Qism qo'shish
`➕ Qism qo'shish` → Anime kodini kiriting → Qism faylini (video) yuboring.

### VIP to'lovlarini tasdiqlash
```
/approve_USER_ID_DAYS   — misol: /approve_123456789_30
/reject_USER_ID         — misol: /reject_123456789
```

---

## 👤 Foydalanuvchi funksiyalari

### Start komandasi — `/start`
- Majburiy kanallarga obuna tekshiriladi
- Referral parametrini qabul qiladi (`/start ANIME_ID` yoki `/start REF_ID`)
- Foydalanuvchi DB ga saqlangan bo'lmasa, yangi yozuv yaratiladi

### Anime qidirish (`🔎 Anime izlash`)
| Tur | Tavsif |
|---|---|
| 🏷 Nom orqali | Qismli qidiruv (LIKE %) |
| 📌 Kod orqali | Aniq ID orqali |
| 💬 Janr orqali | Janr bo'yicha filterlash |
| ⏱ So'nggi yuklangan | Oxirgi 10 ta anime |
| �️ Eng ko'p ko'rilgan | Top 10 ta view count bo'yicha |
| � Barcha animelar | Alifbo tartibida 20 ta |

### Qismlar navigatsiyasi
- Har sahifada 24 ta qism tugmasi (5 x 4 grid)
- Oldingi/keyingi sahifa navigatsiyasi
- Joriy qism `[ N ]` ko'rinishida belgilanadi

---

## 📢 Kanal turlari

| Tur | Kod | Tavsif |
|---|---|---|
| Majburiy ochiq | `public` | Obunasiz botdan foydalanib bo'lmaydi |
| Zayavka (yopiq) | `request` | Join request avtomatik tasdiqlanadi |
| Ijtimoiy tarmoq | `social` | Instagram, YouTube va b. (faqat havola) |
| Anime kanali | `anime` | Anime tegishli kanal |
| Ongoing kanali | `ongoing` | Yangi qismlar e'lon qilinadigan kanal |

---

## 💎 VIP tizimi

### Rejalar
| Muddat | Narx |
|---|---|
| 30 kun | Asosiy narx (`vip_price`) |
| 60 kun | Narx × 2 |
| 90 kun | Narx × 3 |

### To'lov jarayoni
1. Foydalanuvchi `💎 VIP` tugmasini bosadi
2. Reja tanlaydi
3. Karta raqamiga o'tkazma chekini yuboradi
4. Admin `/approve_USER_ID_DAYS` buyrug'i bilan tasdiqlaydi
5. Foydalanuvchiga bildirishnoma yuboriladi

---

## � Referal tizimi

- Har foydalanuvchining o'z referal havolasi bor: `https://t.me/BOT_USERNAME?start=USER_ID`
- Yangi foydalanuvchi havola orqali kelganda:
  - **Taklif etuvchi:** `referral_bonus` miqdorida `pul` (asosiy balans) + 1 odam
  - **Yangi foydalanuvchi:** `referral_bonus` miqdorida `pul2` (referal balans)
- Default bonus: **500 so'm** (bot sozlamalarida o'zgartirish mumkin)

---

## 🌐 Web App va Dashboard

Bot bilan birga **aiohttp** web server ishga tushadi:
- Real-time admin dashboard (`index.html` orqali)
- Server-Sent Events (SSE) orqali yangi foydalanuvchi va hodisalar
- URL: Bot ishga tushgandan so'ng konsol logda ko'rinadi

Web App URL ni `bot_settings` → `web_app_url` orqali sozlash mumkin. Sozlanganda asosiy menyuda `🌐 Web App` tugmasi paydo bo'ladi.

---

## � Deploy (Railway)

### Avtomatik deploy
Loyihada `railway.toml` va `Procfile` mavjud:

```
worker: python main.py
```

### Qadamlar
1. [Railway.app](https://railway.app) da hisob oching
2. Repozitoriyani ulang
3. **Environment Variables** bo'limiga `.env` qiymatlarini kiriting
4. Deploy qiling — Railway avtomatik ishga tushiradi

### Volume (ma'lumotlar saqlash)
Railway da `/app/data` papkasi mavjud bo'lsa, SQLite bazasi shu yerda saqlanadi. Aks holda loyiha papkasidagi `data/` papkasi ishlatiladi.

---

## 🔧 Ishlash arxitekturasi

```
main.py
  ├── init_db()                    — DB jadvallarini yaratadi
  ├── Bot + Dispatcher             — Aiogram 3.x
  ├── admin_handlers.router        — Admin panel routerlari
  ├── user_handlers.router         — Foydalanuvchi routerlari
  ├── inline_handlers.router       — Inline callbacklar
  └── start_web_server()           — aiohttp web server (parallel)

utils/__init__.py
  ├── is_admin()                   — TTL cache (60s) bilan admin tekshirish
  ├── is_super_admin()            — Super admin tekshirish
  ├── is_maintenance()             — Texnik ish rejimi (5s cache)
  ├── check_subscription()         — Parallel kanal obuna tekshirish
  └── get_subscription_keyboard()  — Obuna tug xonalari
```

---

## 📝 Litsenziya

Ushbu botning o'z kodi Apache License 2.0 ostida tarqatiladi. Batafsil: `LICENSE`.
Copyright va attribution ma'lumotlari: `NOTICE`.
Uchinchi tomon kodlari va xizmatlari o'z litsenziyalariga ega bo'lishi mumkin.
Batafsil: `THIRD_PARTY_NOTICES.md`.

---

<div align="center">
  Made with ❤️ for O'zbek Anime Community
</div>
