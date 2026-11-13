[app]
title = Hamrah Dars
package.name = hamrahdars
package.domain = org.studycompanion

source.dir = .
source.include_exts = py,json,png,jpg,kv,ttf

version = 1.4

# قفل کردن هر دو نسخه پایتون (هاست و اندروید) روی 3.11.5 برای جلوگیری از تداخل
requirements = python3==3.11.5,hostpython3==3.11.5,kivy==2.3.0,plyer,pyjnius==1.5.0,arabic-reshaper,python-bidi

orientation = portrait
fullscreen = 0

android.permissions = POST_NOTIFICATIONS,VIBRATE,WRITE_EXTERNAL_STORAGE,INTERNET
android.api = 33
android.minapi = 23
android.archs = arm64-v8a
android.accept_sdk_license = True
android.ndk = 25b

# استفاده از شاخه پایدار ابزار ساخت
p4a.branch = master
android.useandroidx = true

[buildozer]
log_level = 2
warn_on_root = 1
