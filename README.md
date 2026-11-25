# Shartnoma bot

## Railway

Repo ildizidagi `Dockerfile` LibreOffice (PDF), Poppler, Tesseract (eng/rus/uzb) va Times New Roman/Calibri o‘rnini bosuvchi shriftlarni o‘rnatadi; `railway.json` Railway’ga shu Dockerfile’ni ishlatishni aytadi.

1. Railway → Variables: `BOT_TOKEN`, `ALLOWED_USER_IDS` (vergul bilan, masalan `1573757720,123456789`).
2. Railway → service → Volume qo‘shing, mount path: `/app/data`. Baza, sotuvchilar, raqamlash, yuklangan shablonlar va tayyor shartnomalar (`/app/contracts` → `data/contracts`) shu yerda saqlanadi. Volume bo‘lmasa har deploy’da ular o‘chadi.
3. Replica faqat 1 ta bo‘lsin va bot boshqa joyda (kompyuter, boshqa server) ishlamasin — aks holda Telegram 409 beradi.
4. Deploy log’ida `LibreOffice ...` versiyasi chiqadi (build vaqtida tekshiriladi).

## Doimiy ishlash

Desktopdagi bot `shartnoma-bot.service` foydalanuvchi systemd xizmati bilan ishlaydi. Avtomatik ishga tushish va sessiyadan chiqqanda ishlash (`linger`) yoqilgan. Jarayon to'xtasa, 10 soniyadan so'ng qayta ishga tushadi. Internet uzilsa, bot qayta ulanishga urinadi. Kompyuter o'chirilgan yoki uyqu holatida bo'lsa bot ishlamaydi.

```bash
systemctl --user status shartnoma-bot
systemctl --user restart shartnoma-bot
systemctl --user stop shartnoma-bot
journalctl --user -u shartnoma-bot -n 50 --no-pager
```

Doimiy xizmat yoqilganida ikkinchi nusxani `start.sh` bilan ishga tushirmang. Yangilangan kodni yuklash uchun `systemctl --user restart shartnoma-bot` ishlating.

Python 3.11+ uchun Telegram bot. `requests` kutubxonasi talab qilinadi (`requirements.txt`). Joriy kompyuterda o'rnatilgan.

## Ishga tushirish

1. BotFather orqali bot yarating va token oling.
2. `.env.example` faylini `.env` nomiga ko'chiring. `BOT_TOKEN` va `ALLOWED_USER_IDS`ni to'ldiring. `/id` faqat ruxsat berilgan foydalanuvchilarga javob beradi. Qolganlarga @azamjonbro ga murojaat qilish xabari chiqadi.
3. Botga `/sozlash` yuborib sotuvchi rekvizitlarini matn, rasm yoki PDF orqali kiriting va tasdiqlang. Yoki `company.example.json`ni `company.json` nomiga ko'chirib to'ldiring.
4. Terminalda: `bash start.sh`
5. Botga `/start` yuboring.

Tokenni kodga yozmang. `.env` fayli kompyuteringizda qoladi.

## Ishlaydigan jarayon

Birinchi kirishda namuna va shablon tanlovi → sotuvchini STIR orqali bir marta sozlash. Keyingi shartnomalarda: hamkor STIR → Orginfo → yetishmagan rekvizitlar → tasdiq → QQS stavkasi va narx turi → tovar nomi → birlik → miqdor → bir birlik narxi → yana tovar yoki davom etish → tasdiq → Word va PDF.

Orginfo’dan korxona nomi, STIR, rahbar va manzil olinadi. Bank nomi, hisob raqami va MFO rasm/PDF yoki matndan olinadi. Topilgan ma’lumotni tuzatish ham mumkin. Har safar tayyor rekvizitlar tasdiqlash uchun ko‘rsatiladi.

Orginfo ulanishini Telegram tokensiz sinash:

```bash
python3 orginfo.py 310514454
```

Modul Orginfo ochiq qidiruv va korxona HTML sahifalarini o‘qiydi; rasmiy API ishlatilmaydi. HTTP ulanishlar qayta ishlatiladi. Vaqtinchalik tarmoq yoki server xatosida bitta qayta urinish bor; 403/429 javoblarida qayta urinmaydi.

Muvaffaqiyatli natijalar `data/orginfo-cache.json` faylida, eng ko'pi bilan 128 ta STIR uchun saqlanadi. 6 soatgacha keshdan tez javob beriladi. Tarmoq/server ishlamasa, 7 kungacha bo'lgan eski ma'lumot sanasi va ogohlantirish bilan ko'rsatilishi mumkin. Sana hech qachon kesh o'qilgani uchun yangilanmaydi. Sahifa formati o'zgarsa yoki STIR mos kelmasa eski ma'lumot bilan yashirilmaydi. Kesh yo'q bo'lsa bot qo'lda kiritishga o'tadi. Orginfo’dagi ma’lumotlar norasmiy: tasdiqlashda rekvizitlarni tekshiring. Mahalliy `data/companies.json` ro‘yxatidagi to‘liq yozuvlar ustun turadi.

Rekvizitlar namunasi:

```text
Nomi: MISOL MCHJ
STIR: 123456789
Direktor: Ism Familiya
Manzil: Toshkent shahri
Bank: Bank nomi
Hisob: 20208000000000000001
MFO: 00450
```

Rekvizitlar kiritilgan STIR bilan solishtiriladi. Summa tiyingacha aniq hisoblanadi. Suhbatlar va shartnoma raqamlari SQLite bazasida saqlanadi, bot qayta ishga tushirilganda tiklanadi. Tayyor fayllar `contracts/` ichida qoladi. `/bekor` suhbatni bekor qiladi, `/oxirgi` oxirgi faylni qayta yuboradi.

## Rasm va PDF o'qish

Tezlik: Telegram ulanishlari `requests.Session` bilan qayta ishlatiladi. Fayl yuklash va oddiy API so'rovlarida ulanish uchun 4, javob uchun 12 soniya timeout bor. Qo'shimcha holat xabari rasmni yuklashni bloklamaydi. Oxirgi 8 ta fayl (jami 32 MB gacha) va 16 ta OCR natijasi 15 daqiqagacha faqat xotirada saqlanadi. Takroriy fayl qayta yuklanmaydi, aynan bir xil rasm qayta OCR qilinmaydi. Bot qayta ishga tushsa kesh tozalanadi.

Jurnalda `file download=... ocr=... total=...` va `response_total=...` soniyalarda yoziladi. Token, rekvizitlar va rasm matni tezlik jurnaliga yozilmaydi. Internet sifati umumiy vaqtga ta'sir qiladi.

`ocr.py` Tesseract orqali o'zbek, rus va ingliz matnini lokal o'qiydi. Ma'lumot tashqi AI xizmatiga yuborilmaydi. `runtime/` papkasida Ubuntu 26.04 x86_64 uchun OCR dasturi, kerakli kutubxonalar, til modellari va litsenziyalar bor. Boshqa tizimda Tesseract (eng, rus, uzb tillari) va Poppler o'rnatilishi kerak.

JPG/PNG/WEBP/TIFF va PDF qo'llanadi. Hajm 10 MB, PDF 5 betgacha. Matnli PDF matn qatlamidan, skanerlangan PDF esa OCR orqali o'qiladi. Noaniq yoki yetishmagan maydonlarni bot qo'lda to'ldirishni so'raydi. Turli STIR yoki bir maydon uchun bir nechta qiymat bo'lsa, davom etish to'xtatiladi. O'qilgan bank raqamlarini tasdiqlashdan oldin tekshiring.

## Word shablon

`/shablon` yuborib o'zingiz tekshirgan `.docx` faylini yuklang. Faylda quyidagi matn maydonlari bo'lishi kerak:

- `{{number}}`, `{{date}}`, `{{items}}`, `{{total}}`
- `{{seller_name}}`, `{{seller_stir}}`, `{{seller_director}}`, `{{seller_address}}`, `{{seller_bank}}`, `{{seller_account}}`, `{{seller_mfo}}`
- Xaridor uchun yuqoridagilarda `seller` o'rniga `buyer` yoziladi.

Majburiylari: number, date, seller_name, buyer_name, items, total. Qolganlari ixtiyoriy. Word matnni alohida format bo'laklariga ajratgan bo'lsa ham maydonlar to'ldiriladi. Shablon o'zgarganda oldingi tayyor hujjatlar o'zgarmaydi.

Shablonsiz bot rekvizitlar va tovarlar ro'yxatidan **LOYIHA** tayyorlaydi. Bu to'liq yuridik shartnoma emas; narxlar, yetkazib berish, to'lov, javobgarlik va boshqa kelishilgan shartlar foydalanuvchi shablonidan keladi.

## Buyruqlar

- `/start` — yangi shartnoma
- `/settings` — sotuvchi rekvizitlarini birma-bir kiritish va o'zgartirish
- `/sozlash` — sotuvchi rekvizitlarini saqlash (tasdiqlash bilan)
- `/shablon` — Word shablon yuklash
- `/namuna` — xayoliy rekvizitlar bilan SINOV hujjati; haqiqiy sozlamalarni o'zgartirmaydi
- `/holat` — sotuvchi va shablon holati
- `/oxirgi` — oxirgi tayyor fayl
- `/bekor` — joriy jarayonni bekor qilish
- `/yordam` — buyruqlar

## Har bir adminning sotuvchisi

`/settings` avval STIRni so‘rab Orginfo orqali ma’lumot qidiradi, keyin nom, direktor, manzil, bank, 20 xonali hisob, MFO va ixtiyoriy telefon va OKEDni so'raydi. Xaridor telefoni rekvizitlardagi «Тел:» qatoridan olinadi. Mavjud qiymatni tugma bilan qoldirish mumkin. Yakuniy tasdiqlashsiz o'zgarish saqlanmaydi; `/bekor` oldingi sozlamani saqlab qoladi.

Rekvizitlar `data/sellers/TELEGRAM_ID.json` faylida har bir admin uchun alohida saqlanadi. Bir admin o'zgartirgan sotuvchi boshqasiga ta'sir qilmaydi. Avvalgi `company.json` mavjud bo'lsa eski o'rnatishlar uchun boshlang'ich qiymat sifatida o'qiladi. Yangi shartnoma boshlangan paytdagi sotuvchi nusxasi hujjat tugaguncha saqlanadi.

Javohir yuborgan bo‘sh `дог.doc` asosidagi `template.docx` ishlatiladi. Barcha bandlar saqlangan, jumladan manbadagi amal qilish muddati — 2027-yil. Faqat tomonlar, raqam/sana, summalar, tovar jadvali hamda tanlangan QQS yozuvi almashtiriladi. Spetsifikatsiya alohida sahifadan boshlanadi.

Tayyor shablon birlik, miqdor va bir birlik narxini alohida so‘raydi. QQS 12%, QQSsiz yoki boshqa stavka; narx QQS bilan yoki QQSsiz tanlanadi. QQSli narxdan `narx*100/(100+stavka)` orqali sof narx chiqariladi. Hisob Decimal bilan oraliq narxni yaxlitlamasdan bajariladi; satr summalari tiyingacha ROUND_HALF_UP, QQS yakuniy summa va sof summa farqi. Jadvaldagi birlik narxi ikki kasrda ko‘rsatilgani uchun ko‘rinadigan narx × miqdor bilan bir tiyin yaxlitlash farqi bo‘lishi mumkin.

`/shablon` orqali maydonli Word fayllarini yuklang. Bot har birini fayl nomi bilan `data/templates/TELEGRAM_ID/` papkasiga saqlaydi va takroriy nomga tartib raqami qo‘shadi. Avval ulangan shaxsiy shablon ham tanlovda chiqadi. Oddiy Word hujjatini yuklashdan avval bot maydonlarini qo‘ying. `{{items}}` ishlatadigan shablonlarda jami-summa oqimi saqlangan.

PDF aynan saqlangan Word fayldan LibreOffice orqali olinadi. Bot `SOFFICE_PATH`, PATHdagi `soffice`/`libreoffice`, `/opt/libreoffice*` va bundled nusxani ketma-ket sinaydi, har birini ikki marta. Har aylantirish uchun alohida profil, 120 soniya chegara va atomar fayl yozish bor. Xato sababi (stderr) jurnalga yoziladi. Serverda: `sudo apt install libreoffice-writer poppler-utils fonts-liberation`.

Sahifaga moslash: tayyor shablonda shartnomaning asosiy qismi 2 betdan, spetsifikatsiya 1 betdan oshmasligi kerak. Word yaratilgach LibreOffice bilan sahifalar sanaladi; oshsa shrift 0,5 pt dan kichraytiriladi (asosiy matn kamida 7,5 pt, spetsifikatsiya 7 pt), ko‘p tovarda jadval qatorlari zichlanadi. Spetsifikatsiya chegarasi — `pageBreakBefore` bo‘lgan paragraf. Bunday chegarasi yo‘q shaxsiy shablonlar o‘zgartirilmaydi. LibreOffice bo‘lmasa hujjat asl ko‘rinishida beriladi. Word avval yuboriladi. PDF xatosida `/pdf`, barcha fayllar uchun `/oxirgi`; tasdiqni qayta bosish shartnoma raqamini ko‘paytirmaydi.

Rekvizitlar bosqichidagi har bir rasm/PDF `data/uploads/TELEGRAM_ID/` ichida OCR xato bersa ham saqlanadi. Fayl yonida STIR va SHA256 yozilgan mahalliy JSON bor. MongoDB ulanishi o‘zgartirilmagan, unga yangi yozish qo‘shilmagan. Didox integratsiyasi yo‘q: hujjatlar Telegramga yuboriladi.

## Hozirgi chegaralar

- Haqiqiy sotuvchi rekvizitlari foydalanuvchidan olinadi. Bo'sh sozlamalar o'rniga o'ylab topilgan ma'lumot kiritilmaydi.
- STIR qidiruvi Orginfo ochiq sahifalaridan ishlaydi. Sayt tuzilishi o‘zgarsa, modulni yangilash kerak bo‘lishi mumkin. Orginfo — davlat reyestri emas.
- OCR har qanday sifatsiz rasmni to'g'ri o'qishi kafolatlanmaydi. Har bir rekvizit tasdiqlash oynasida tekshiriladi.
- Bot faqat ruxsat etilgan foydalanuvchilarning shaxsiy chatida ishlaydi.
- Telegramga ulanish va real fayl yuborish uchun token va internet kerak.

## Tekshirish

```bash
python3 -m unittest discover -s tests -v
```

Telegram API: https://core.telegram.org/bots/api

## Shartnoma namunalari

`template.docx` — umumiy shartnoma. Bir nechta shablon mavjud bo‘lsa, `/start` umumiy, Discover Invest va shu chatga tegishli shaxsiy shablonlardan tanlashni so‘raydi. Discover Invest shablonini admin `/discover` orqali maydonli `.docx` sifatida yuklaydi. Bitta sotuvchi STIRiga tegishli barcha shartnomalar shablondan qat’i nazar bitta raqam ketma-ketligidan foydalanadi.

## Xodim qo‘shish

Yangi xodimning Telegram ID raqamini (xodim uni @userinfobot orqali bilib oladi) `.env`dagi `ALLOWED_USER_IDS`ga vergul bilan qo‘shing va botni qayta ishga tushiring. Xodim birinchi `/start`da sotuvchi korxonani STIR orqali sozlaydi.

## Shartnoma raqami va sanasi

`/settings` ichida «🔢 Raqamlash sozlamalari» tugmasi yoki `/raqamlash`: navbatdagi raqamni kiriting va tasdiqlang. Masalan, oxirgi ishlatilgan raqam 283 bo‘lsa 284 kiritiladi. Raqamlash sotuvchi korxona (STIR) bo‘yicha barcha xodimlar uchun umumiy, mahalliy SQLite ichida saqlanadi: bir korxonaning ikki xodimi bir xil № bermaydi. Sotuvchi almashsa uning ketma-ketligi aralashmaydi. Eski admin bo‘yicha ketma-ketliklar ishga tushishda eng kattasi bilan birlashtiriladi.

Tasdiqlash oynasi raqam va sanani ko‘rsatadi; «Raqamni o‘zgartirish» va «Sanani o‘zgartirish» tugmalari bor. Birinchi raqam sozlanmagan bo‘lsa bot uni alohida so‘raydi. Sana Toshkent bo‘yicha bugungi kun sifatida taklif etiladi yoki KK.OO.YYYY shaklida kiritiladi. Tasdiqlangan qiymatlar shartnoma va spetsifikatsiyada ishlatiladi. Fayl nomidagi ID ichki yozuv identifikatori, hujjatdagi biznes raqamidan mustaqil.

Raqam shartnoma yozuvi yaratilganda oshadi. Bekor qilish oshirmaydi. Telegram/PDF qayta yuborishda yozuv va raqam takror yaratilmaydi. Avval ishlatilgan raqam qayta qabul qilinmaydi. Navbatdan kichik bo‘sh raqamni bir martalik qo‘yish umumiy hisoblagichni orqaga surmaydi; yuqori raqam qo‘yish ketma-ketlikni undan keyin davom ettiradi. Boshlang‘ich raqam yoki ketma-ketlikni qayta sozlash faqat alohida tasdiq bilan amalga oshadi. Eski berilgan raqamlar sotuvchi nusxasi mavjud yozuvlardan avtomatik ko‘chiriladi. Sana yil almashtirganda raqamlash o‘z-o‘zidan nolga qaytmaydi.
# shartnomabot
# shartnomabot
# shartnomabot
