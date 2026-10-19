[app]
title = Whispering House
package.name = baytalhams
package.domain = org.baytalhams
source.dir = .
source.include_exts = py,png,jpg,ttf,wav,json,txt
source.include_patterns = assets/*
source.exclude_dirs = bin, .buildozer, .github, dist, build, __pycache__, p4a-recipes/__pycache__
version = 1.0

# pygame-ce من الـ recipe المحلي (p4a-recipes) + pyjnius علشان نطق الاسم بمحرك أندرويد
requirements = python3,pygame-ce,pyjnius
p4a.local_recipes = ./p4a-recipes

orientation = landscape
fullscreen = 1

# الأيقونة + شاشة البداية (اللوجو بتاعك)
icon.filename = %(source.dir)s/assets/icon_512.png
icon.adaptive_foreground.filename = %(source.dir)s/assets/icon_fg.png
icon.adaptive_background.filename = %(source.dir)s/assets/icon_bg.png
presplash.filename = %(source.dir)s/assets/presplash.png
android.presplash_color = #000000

android.api = 34
android.minapi = 21
android.ndk_api = 21
android.archs = arm64-v8a, armeabi-v7a
android.accept_sdk_license = True
android.permissions = WAKE_LOCK, INTERNET, ACCESS_NETWORK_STATE, ACCESS_WIFI_STATE, CHANGE_WIFI_MULTICAST_STATE
android.wakelock = True
android.extra_manifest_xml = ./src/android/extra_manifest.xml

[buildozer]
log_level = 2
warn_on_root = 1
