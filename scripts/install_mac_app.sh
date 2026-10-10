#!/bin/bash
# 在桌面（或 /Applications）生成「OutreachPilot.app」：双击即启动后台服务并打开应用窗口。
# 用法：bash scripts/install_mac_app.sh            → 桌面
#       bash scripts/install_mac_app.sh /Applications
# 程序文件复制到 ~/Library/Application Support/OutreachPilot/app 运行：macOS 不允许从图标启动的进程读取桌面/文稿文件夹。
# 以后用界面里的「检查更新」即可升级这份副本；改了本目录的代码后重新运行本脚本。
set -euo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${1:-$HOME/Desktop}"
APP="$DEST/OutreachPilot.app"
PY="$(command -v python3 || echo /usr/bin/python3)"
LOGDIR="$HOME/Library/Application Support/OutreachPilot"
ROOT="$LOGDIR/app"

mkdir -p "$ROOT"
rsync -a --delete --exclude '.git' --exclude '__pycache__' --exclude '.DS_Store' "$SRC/" "$ROOT/"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources" "$LOGDIR"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>OutreachPilot</string>
  <key>CFBundleDisplayName</key><string>OutreachPilot</string>
  <key>CFBundleIdentifier</key><string>com.outreachpilot.app</string>
  <key>CFBundleExecutable</key><string>OutreachPilot</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>LSUIElement</key><false/>
</dict></plist>
PLIST

cat > "$APP/Contents/MacOS/OutreachPilot" <<LAUNCH
#!/bin/bash
# Starts the background service once (it keeps running after the window closes), then opens the app window.
ROOT="$ROOT"
PY="$PY"
LOG="$LOGDIR/app.log"
PORT=\$("\$PY" -c "import json,os;p=os.path.expanduser('~/Library/Application Support/OutreachPilot/settings.json');print(json.load(open(p)).get('port',18800) if os.path.exists(p) else 18800)" 2>/dev/null || echo 18800)
if ! curl -s -m 1 "http://127.0.0.1:\$PORT/api/ping" >/dev/null 2>&1; then
  cd "\$ROOT" && nohup "\$PY" app.py --no-browser >> "\$LOG" 2>&1 &
  for i in \$(seq 1 50); do curl -s -m 1 "http://127.0.0.1:\$PORT/api/ping" >/dev/null 2>&1 && break; sleep 0.2; done
fi
cd "\$ROOT" && exec "\$PY" app.py
LAUNCH
chmod +x "$APP/Contents/MacOS/OutreachPilot"

# icon
TMP="$(mktemp -d)"
"$PY" "$SRC/scripts/make_icon.py" "$TMP/icon.png" 1024
mkdir -p "$TMP/AppIcon.iconset"
for s in 16 32 128 256 512; do
  sips -z $s $s "$TMP/icon.png" --out "$TMP/AppIcon.iconset/icon_${s}x${s}.png" >/dev/null
  d=$((s*2)); sips -z $d $d "$TMP/icon.png" --out "$TMP/AppIcon.iconset/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$TMP/AppIcon.iconset" -o "$APP/Contents/Resources/AppIcon.icns" 2>/dev/null || cp "$TMP/icon.png" "$APP/Contents/Resources/AppIcon.png"
rm -rf "$TMP"
touch "$APP"
echo "已生成：$APP"
