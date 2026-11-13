[app]
title = Hamrah Dars
package.name = hamrahdars
package.domain = org.studycompanion

source.dir = .
source.include_exts = py,json,png,jpg,kv,ttf

version = 1.4

requirements = python3,kivy==2.3.0,plyer,pyjnius,arabic-reshaper,python-bidi

orientation = portrait
fullscreen = 0

android.permissions = POST_NOTIFICATIONS,VIBRATE,WRITE_EXTERNAL_STORAGE,INTERNET
android.api = 33
android.minapi = 23
android.archs = arm64-v8a
android.accept_sdk_license = True
android.ndk = 25b

# این دو خط مشکل AAB و پایتون را حل می‌کنند
p4a.branch = master
android.useandroidx = true

[buildozer]
log_level = 2
warn_on_root = 1
