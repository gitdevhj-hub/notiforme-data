#!/usr/bin/env bash
# 관리자에게 알리는 이슈를 만든다. 같은 제목의 열린 이슈가 있으면 새로 만들지 않고 댓글만 단다.
# 사용: bash .github/notify.sh "제목" < 본문파일   (본문은 표준입력, GH_TOKEN 필요, 권한 issues: write)
# 이슈가 생기면 저장소 주인에게 GitHub 알림(기본 설정이면 메일, GitHub 앱이면 휴대폰 알림)이 간다.
set -euo pipefail
title="$1"
body="$(cat)"
number=$(gh issue list --state open --limit 100 --json number,title \
  --jq ".[] | select(.title == \"$title\") | .number" | head -n 1)
if [ -n "$number" ]; then
  gh issue comment "$number" --body "$body"
  echo "이슈 #$number 에 댓글을 달았어요."
else
  gh issue create --title "$title" --body "$body"
fi
