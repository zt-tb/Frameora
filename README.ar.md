<div align="center" dir="rtl">

# Frameora

**بوت تيليغرام يجهّز فيديوهاتك للرفع بإطارات عالية على تيك توك.**

العربية · [English](README.md)

<a href="https://github.com/zt-tb/Frameora/actions/workflows/tests.yml"><img src="https://github.com/zt-tb/Frameora/actions/workflows/tests.yml/badge.svg" alt="Tests" /></a>
<a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT%20%2B%20Attribution-2ea44f?style=flat" alt="License" /></a>
<img src="https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white" alt="Python" />
<img src="https://img.shields.io/badge/Telegram-Bot%20(Kurigram)-26A5E4?logo=telegram&logoColor=white" alt="Telegram Bot" />
<img src="https://img.shields.io/badge/PostgreSQL-asyncpg-4169E1?logo=postgresql&logoColor=white" alt="PostgreSQL" />
<img src="https://img.shields.io/badge/Redis-optional-DC382D?logo=redis&logoColor=white" alt="Redis" />
<img src="https://img.shields.io/badge/FFmpeg-required-007808?logo=ffmpeg&logoColor=white" alt="FFmpeg" />
<img src="https://img.shields.io/badge/languages-Arabic%20%7C%20English-green" alt="Languages" />

<a href="https://t.me/K0_MG"><img src="https://img.shields.io/badge/Telegram-@K0__MG-26A5E4?logo=telegram&logoColor=white" alt="Telegram @K0_MG" /></a>
<a href="https://instagram.com/z0_28"><img src="https://img.shields.io/badge/Instagram-z0__28-E4405F?logo=instagram&logoColor=white" alt="Instagram z0_28" /></a>
<a href="https://www.tiktok.com/@zt_tb"><img src="https://img.shields.io/badge/TikTok-@zt__tb-000000?logo=tiktok&logoColor=white" alt="TikTok @zt_tb" /></a>
<a href="https://youtube.com/@M7JN"><img src="https://img.shields.io/badge/YouTube-@M7JN-FF0000?logo=youtube&logoColor=white" alt="YouTube @M7JN" /></a>
<a href="https://github.com/zt-tb"><img src="https://img.shields.io/badge/GitHub-zt--tb-181717?logo=github&logoColor=white" alt="GitHub zt-tb" /></a>

</div>

<div dir="rtl">

> **مفتوح المصدر مع ذكر صاحب المشروع.** Frameora منشور برخصة MIT مع شرط ذكر الاسم. تقدر تستخدمه وتعدّل عليه وتشاركه، بس لازم تخلي ملف [NOTICE](NOTICE) وترويسات الحقوق، وتذكر اسم صاحب المشروع الأصلي **Mohsen Al-Taie (@K0_MG)**. التفاصيل بملف [LICENSE](LICENSE).

## شنو يسوي البوت

ترسل الفيديو للبوت، تختار الطريقة، ويرجعلك ملف MP4 مجهّز. افتراضياً الصورة والصوت ما ينعاد ترميزهم، والبوت يفحص سلامة الملف قبل ما يرجعه.

| الميزة | الشرح |
|---|---|
| **Spark** | الطريقة السريعة والخفيفة. جرّبها أول شي. تقبل أي معدل إطارات. |
| **Blaze** | بديل إذا Spark ما أعطت نتيجة مناسبة. |
| **Pulse** | للمقاطع ذات معدل إطارات ثابت (الأفضل 60 أو 120 FPS). |
| **MOV إلى MP4** | يحوّل MOV إلى MP4 بدون إعادة ترميز. |
| **الضغط** | خيار "اضغط أول" لكل مستخدم (H.264 لحد 1080p). يعيد الترميز فممكن تقل الجودة. |
| **`/analyze`** | يعرض الكودك والدقة والإطارات والبت ريت والصوت بدون ما يغيّر الملف. |
| **`/check`** | يقارن الأصل ويا الفيديو المنشور على تيك توك (SSIM أو VMAF). |
| **اللغات** | عراقي وإنجليزي، تغيّرها بـ `/lang`. |

## شلون تستخدمه

1. افتح البوت بتيليغرام: `https://t.me/YOUR_BOT_USERNAME` وأرسل `/start`.
2. أرسل الفيديو **كملف** (مو كفيديو عادي) حتى تيليغرام ما يضغطه. يدعم MP4 وMOV.
3. اختار الطريقة: Spark أو Blaze أو Pulse.
4. انتظر البوت يخلص المعالجة، وبعدها نزّل الملف الراجع.
5. افتح **TikTok Studio** من متصفح الموبايل أو الكمبيوتر وارفع الملف من التنزيلات.
6. داخل TikTok Studio فعّل خيار **السماح بالرفع بجودة عالية**. بدونه الفيديو ممكن يرجع 30 إطار عند التشغيل.
7. بعد النشر أرسل الرابط لأمر `/check` حتى تقارن النتيجة ويا الأصل.

## الأوامر

| الأمر | وظيفته |
|---|---|
| `/start` | القائمة الرئيسية |
| `/help` | دليل الاستخدام |
| `/analyze` | فحص الفيديو بدون تعديله |
| `/check` | مقارنة فيديو تيك توك المنشور ويا الأصل |
| `/lang` | تغيير اللغة |
| `/terms` | شروط الاستخدام والدفع |
| `/paysupport` | مساعدة بخصوص الدفع بالنجوم |
| `/cancel` | إلغاء العملية الحالية |

## الوصول والدفع

- **المشتركين** عندهم وصول كامل، ويشمل `/analyze` و`/check`.
- **باقي المستخدمين** يقدرون يدفعون بنجوم تيليغرام (250 نجمة افتراضياً) لمعالجة فيديو واحد. الدفعة تُستهلك فقط بعد ما يوصلك الملف النهائي. إذا فشلت المعالجة، البوت يرجّع النجوم تلقائياً.
- إذا صارت مشكلة بالدفع استخدم `/paysupport`.

## ملاحظات مهمة

- هذي أداة غير رسمية وما إلها علاقة بتيك توك أو ByteDance.
- تيك توك ممكن يعيد ترميز الفيديو أو يغيّر نظامه بأي وقت، فما في ضمان لمعدل الإطارات أو الجودة بعد النشر.
- ارفع فقط محتوى تملكه أو عندك حق استخدامه.
- الفيديوهات تنعالج بتخزين مؤقت وتنحذف بعد انتهاء المهمة. الأصل يُحفظ كمقطع مرجعي قصير (أول 30 ثانية افتراضياً) لأمر `/check` وينحذف بعد 48 ساعة.

## للمشغّل

يشتغل Frameora على Python 3.11+ وFFmpeg وPostgreSQL، وRedis اختياري. الإعدادات تنقرأ من متغيرات البيئة، والقائمة الكاملة بملف [`.env.example`](.env.example).

المتغيرات المطلوبة: `API_ID` و`API_HASH` و`BOT_TOKEN` و`OWNER_ID` و`DATABASE_URL`.

على Railway: أضف PostgreSQL (وRedis)، وركّب Volume دائم على `/app/data`، واضبط `REF_DIR=/app/data/tfps_refs`. شغّل نسخة واحدة فقط لكل قاعدة بيانات.

الاختبارات: `pip install -r requirements.txt -r requirements-dev.txt && pytest -q` (يحتاج ffmpeg).

## الشكر والإشارة

إذا استخدمت Frameora أو بنيت عليه مشروعك، يرجى ذكر صاحبه بالـREADME أو بوصف البوت، مثلاً: *مبني على Frameora من تطوير Mohsen Al-Taie (@K0_MG)*. وأي إعادة نشر لازم تحتفظ بملف `NOTICE`.

للاقتباس أو التوثيق استخدم ملف [CITATION.cff](CITATION.cff) (غيت هاب يعرض زر "Cite this repository").

## صاحب المشروع

**محسن الطائي (Mohsen Al-Taie)**

<div align="center">

<img src="assets/divider.svg" width="100%" alt="" />

### 📱 تابعني | Follow Me

<div dir="ltr">

<a href="https://t.me/K0_MG"><img src="assets/social/telegram.svg" width="72" alt="Telegram @K0_MG" /></a>
<a href="https://instagram.com/z0_28"><img src="assets/social/instagram.svg" width="72" alt="Instagram z0_28" /></a>
<a href="https://www.tiktok.com/@zt_tb"><img src="assets/social/tiktok.svg" width="72" alt="TikTok @zt_tb" /></a>
<a href="https://youtube.com/@M7JN"><img src="assets/social/youtube.svg" width="72" alt="YouTube @M7JN" /></a>
<a href="https://github.com/zt-tb"><img src="assets/social/github.svg" width="72" alt="GitHub zt-tb" /></a>

</div>

[تيليغرام @K0_MG](https://t.me/K0_MG) · [إنستغرام z0_28](https://instagram.com/z0_28) · [تيك توك @zt_tb](https://www.tiktok.com/@zt_tb) · [يوتيوب @M7JN](https://youtube.com/@M7JN) · [غيت هاب zt-tb](https://github.com/zt-tb)

<img src="assets/divider.svg" width="100%" alt="" />

</div>

حقوق النشر © 2026 Mohsen Al-Taie. مرخّص برخصة MIT مع شرط ذكر الاسم.

</div>
