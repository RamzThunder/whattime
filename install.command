#!/bin/bash
APP="/Applications/WhatTime.app"

if [ ! -e "$APP" ]; then
    osascript -e 'display alert "WhatTime.app를 먼저 Applications 폴더에 드래그해 주세요." as warning'
    exit 1
fi

xattr -dr com.apple.quarantine "$APP"
open "$APP"
