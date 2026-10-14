#!/bin/bash
# 在桌面（或 /Applications）生成「Outsearch Pilot.app」：双击即启动后台服务并打开应用窗口。
# 用法：bash scripts/install_mac_app.sh            → 桌面
#       bash scripts/install_mac_app.sh /Applications
# 程序文件复制到 ~/Library/Application Support/OutreachPilot/app 运行：macOS 不允许从图标启动的进程读取桌面/文稿文件夹。
# 以后用界面里的「检查更新」即可升级这份副本；改了本目录的代码后重新运行本脚本。
set -euo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${1:-$HOME/Desktop}"
APP="$DEST/Outsearch Pilot.app"
PY="${OUTREACH_PYTHON:-$HOME/.local/share/outreachpilot-python/bin/python3}"
if [ ! -x "$PY" ]; then echo "设置 OUTREACH_PYTHON 为已安装的 Python 3 路径" >&2; exit 1; fi
LOGDIR="$HOME/Library/Application Support/OutreachPilot"
ROOT="$LOGDIR/app"

mkdir -p "$ROOT"
rsync -a --delete --exclude '.git' --exclude '__pycache__' --exclude '.DS_Store' "$SRC/" "$ROOT/"

# Preserve the previous desktop entry for rollback; never replace it silently.
if [ -e "$APP" ]; then
  BACKUP="$HOME/Library/Application Support/OutreachPilot Backups/launchers/$(date +%Y%m%d-%H%M%S)-$$"
  mkdir -p "$BACKUP"
  chmod 700 "$BACKUP"
  mv "$APP" "$BACKUP/Outsearch Pilot.app"
fi
"$PY" "$SRC/scripts/build_mac_launcher.py" "$APP" --python "$PY" --root "$ROOT" --logdir "$LOGDIR"

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
/usr/bin/codesign --force --sign - "$APP"
/usr/bin/codesign --verify "$APP"
touch "$APP"
echo "已生成：$APP"

# Global command for terminals and AI agents (Codex / Claude Code / any shell): `outreach go`
BIN="$HOME/.local/bin"
mkdir -p "$BIN"
cat > "$BIN/outreach" <<SHIM
#!/bin/bash
exec "$PY" "$ROOT/app.py" "\$@"
SHIM
chmod +x "$BIN/outreach"
echo "已安装命令：$BIN/outreach   （查看状态：outreach status；打开界面：outreach open）"
case ":$PATH:" in *":$BIN:"*) ;; *) echo "提示：把 $BIN 加入 PATH，例如 echo 'export PATH=\"$BIN:\$PATH\"' >> ~/.zshrc";; esac

# Skill for Codex and Claude Code
"$PY" "$SRC/scripts/install_skill.py" --root "$ROOT" || true
