content = open('index.html', 'r', encoding='utf-8').read()

# To'g'rilash 1: Buzilgan PT va PS konstantalarini to'g'ri shakl bilan almashtirish
# PT va PS qatorlarini topib, to'g'ri qayta tuzamiz
import re

# Eski PT qatori (har qanday ko'rinishda bo'lishi mumkin)
content = re.sub(
    r"const PT = \{[^}]+\}[^;]*;[^\n]*channel[^\n]*\n",
    "    const PT = { animes: 'Animelar', admins: 'Adminlar', stats: 'Statistika', report: 'Shikoyat / Taklif', settings: 'Sozlamalar', game: '🃏 O\\'yinlar', channel: 'Kanal & Chat' };\n",
    content
)

content = re.sub(
    r"const PS = \{[^}]+\}[^;]*;[^\n]*channel[^\n]*\n",
    "    const PS = { animes: 'Barcha anime sarlavhalar', admins: 'Bot boshqaruvchilari', stats: 'Faoliyat ko\\'rsatkichlari', report: 'Xabaringiz adminga yetkaziladi', settings: 'Interfeys sozlamalari', game: 'Google bilan kiring', channel: 'Telegram statistikasi' };\n",
    content
)

# Natijani tekshirish
lines = content.split('\n')
for i, l in enumerate(lines, 1):
    if 'const PT' in l or 'const PS' in l:
        print(f"Line {i}: {l[:200]}")

open('index.html', 'w', encoding='utf-8').write(content)
print("Done!")
