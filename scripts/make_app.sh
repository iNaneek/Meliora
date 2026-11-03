#!/bin/zsh
# Build a thin Meliora.app launcher in ~/Applications.
# It runs the live code in this repo, so edits show up on the next launch with no rebuild.
# Re-run this script only if you move the repo or change the icon.
set -euo pipefail

REPO="${0:A:h:h}"
APP="$HOME/Applications/Meliora.app"
UV="${UV:-$(command -v uv || echo "$HOME/.local/bin/uv")}"

"$UV" sync --project "$REPO" --quiet

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

"$REPO/.venv/bin/python" "$REPO/scripts/make_icon.py" "$APP/Contents/Resources/Meliora.icns"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Meliora</string>
  <key>CFBundleDisplayName</key><string>Meliora</string>
  <key>CFBundleIdentifier</key><string>com.keenan.meliora</string>
  <key>CFBundleExecutable</key><string>Meliora</string>
  <key>CFBundleIconFile</key><string>Meliora</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.1.0</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSCalendarsFullAccessUsageDescription</key><string>Meliora reads your calendar to plan your day around classes, work and training.</string>
  <key>NSCalendarsUsageDescription</key><string>Meliora reads your calendar to plan your day around classes, work and training.</string>
  <key>NSRemindersFullAccessUsageDescription</key><string>Meliora reads and adds reminders so plans reach your phone.</string>
  <key>NSRemindersUsageDescription</key><string>Meliora reads and adds reminders so plans reach your phone.</string>
</dict></plist>
PLIST

# exec (not `uv run`) so the Python process *is* the app: one Dock icon, not two.
cat > "$APP/Contents/MacOS/Meliora" <<LAUNCH
#!/bin/zsh
mkdir -p "$REPO/data"
cd "$REPO"
exec "$REPO/.venv/bin/python" -m meliora >> "$REPO/data/app.log" 2>&1
LAUNCH
chmod +x "$APP/Contents/MacOS/Meliora"

# Ad-hoc signature: gives macOS a stable identity to attach permission grants (Calendar,
# Reminders) to. Rebuilding changes it, so macOS may ask again after a rebuild.
codesign --force --sign - "$APP"

touch "$APP"  # nudge Finder/Dock to pick up the icon
echo "Built $APP"
