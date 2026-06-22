# النشر السحابي بالكامل — بدون جهازك الشخصي 🌩️

## الخيار الموصى به: DigitalOcean **App Platform** (كله من المتصفّح)
لا SSH، لا سيرفر تديره، لا ملفّات على جهازك — تربط GitHub وتحط المفاتيح في
المتصفّح، ويعمل البوت 24/7 ويعيد النشر تلقائيًا عند كل تحديث.

1. فعّل رصيد الطلاب: <https://education.github.com/pack> → DigitalOcean → 200$.
2. <https://cloud.digitalocean.com/apps> → **Create App → GitHub** → اختر
   `salem0557/cloude`، الفرع `main`، وفعّل **Autodeploy**.
3. يكتشف الإعداد من `.do/app.yaml` تلقائيًا (خدمة ويب تشغّل البوت على `/health`).
4. **Environment Variables** (في المتصفّح) — اضبط القيم وميّز السرّية كـ
   *Encrypted*:
   ```
   BOT_MODE=live
   CONFIRM_LIVE=I_UNDERSTAND_THE_RISK
   BINANCE_API_KEY=...           (Encrypted)
   BINANCE_API_SECRET=...        (Encrypted)
   PUBLISH_DASHBOARD=true
   GITHUB_TOKEN=github_pat_...   (Encrypted)   ← لحفظ الحالة على GitHub
   GH_REPO=salem0557/cloude
   PUBLISH_BRANCH=bot-live
   ```
5. **Create Resources**. بعد البناء تحصل على رابط `https://<اسم>.ondigitalocean.app`
   يفتح لوحة المراقبة من أي جهاز.

> 💾 App Platform بلا قرص دائم، لذلك فعّلنا حفظ الحالة على GitHub
> (`PUBLISH_DASHBOARD=true` + `GITHUB_TOKEN`): يحفظ `state.json` على فرع
> `bot-live` ويستعيده عند كل إقلاع، فتبقى صفقاتك محفوظة. **مهم للوضع الحقيقي.**

> 🔄 كل تحديث أدفعه إلى `main` يعيد App Platform النشر تلقائيًا — بدون أي تدخّل.

---

# بديل: DigitalOcean Droplet (تحكّم كامل + قرص دائم) ☁️

البوت يشتغل 24/7 على خادم DigitalOcean، **ويُحدّث نفسه تلقائيًا** كل ما يُدفع
تحديث إلى فرع `main` (سحب + إعادة بناء خلال ~3 دقائق). تتابعه من جوالك عبر رابط
`http://<عنوان-الخادم>:8000` (لوحة + سجلّ مباشر).

## 1) فعّل رصيد الطلاب (200$)
1. ادخل <https://education.github.com/pack> وفعّل الحزمة بحساب الطالب.
2. ابحث عن **DigitalOcean** داخل الحزمة → احصل على كود الـ200$ وفعّله في حسابك
   على <https://www.digitalocean.com>.

## 2) أنشئ خادمًا (Droplet)
- **Create → Droplets**.
- الصورة: **Ubuntu 24.04 LTS**.
- الحجم: **Basic → Regular → 1GB/1CPU (~6$/شهر)** يكفي تمامًا.
- المنطقة: الأقرب لك (مثلًا Frankfurt).
- المصادقة: **SSH key** (أأمن) أو كلمة مرور.
- أنشئه، واحفظ عنوان **IP**.

## 3) ادخل الخادم وشغّل الإعداد بأمر واحد
من جهازك:
```bash
ssh root@<عنوان-IP>
```
ثم على الخادم:
```bash
curl -fsSL https://raw.githubusercontent.com/salem0557/cloude/main/deploy/setup.sh -o setup.sh
bash setup.sh
```
هذا يثبّت Docker و git، يستنسخ المشروع في `/opt/cloude`، ويفعّل التحديث التلقائي.

## 4) ضع مفاتيحك وشغّل البوت
```bash
nano /opt/cloude/bot/.env
```
عدّل (للتداول الحقيقي):
```
BOT_MODE=live
CONFIRM_LIVE=I_UNDERSTAND_THE_RISK
BINANCE_API_KEY=مفتاحك
BINANCE_API_SECRET=سرّك
QUOTE_PER_TRADE=15
DAILY_LOSS_LIMIT=20
```
احفظ (Ctrl+O ثم Ctrl+X)، ثم:
```bash
cd /opt/cloude
docker compose -f bot/docker-compose.yml up -d --build
```

## 5) افتح بوّابة الجدار للمنفذ 8000 (للوحة)
```bash
ufw allow 8000/tcp || true
```
ثم افتح من جوالك: `http://<عنوان-IP>:8000`

## أوامر مفيدة
```bash
# السجلّ المباشر
docker compose -f /opt/cloude/bot/docker-compose.yml logs -f
# حالة التحديث التلقائي
systemctl status cryptobot-autodeploy.timer
journalctl -u cryptobot-autodeploy.service -n 30
# إيقاف البوت
docker compose -f /opt/cloude/bot/docker-compose.yml down
```

## كيف أحدّثه لك بعدها
أي تعديل تطلبه أكتبه وأدفعه إلى `main`، والخادم **يسحبه ويعيد بناءه تلقائيًا**
خلال دقائق — بدون أي تدخّل منك.

> 🔒 مفاتيح Binance تبقى في `bot/.env` على الخادم فقط، غير مرفوعة لـ GitHub.
> لوحة المنفذ 8000 تعرض **حالة عامة فقط** (بلا مفاتيح). اربط مفتاح Binance
> بصلاحية **تداول فقط + السحب معطّل + تقييد IP** بعنوان خادمك.
