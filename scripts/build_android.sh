#!/bin/sh
set -eu
PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
TOOLS_DIR="$PROJECT_ROOT/build/toolchains"
JAVA_HOME=$(find "$TOOLS_DIR" -type d -path '*/Contents/Home' -maxdepth 4 -print -quit)
if [ -z "$JAVA_HOME" ]; then
  echo '请先运行 python3 scripts/prepare_android_tools.py，或使用 Android Studio。' >&2
  exit 1
fi
export JAVA_HOME
export ANDROID_HOME="$TOOLS_DIR/sdk"
export GRADLE_USER_HOME="$PROJECT_ROOT/build/gradle-home"
exec "$TOOLS_DIR/gradle-8.11.1/bin/gradle" -p "$PROJECT_ROOT/android" --no-daemon :app:assembleDebug "$@"
