#!/usr/bin/env bash
# PreToolUse hook (Bash/PowerShell): before Claude runs `git push`, make sure
# CLAUDE.md was updated in the commits being pushed, so the shared project
# context stays current across PCs. If it wasn't, the push is refused with
# instructions; Claude updates CLAUDE.md, commits, and pushes again. Escape
# hatch when CLAUDE.md genuinely needs no change: append the comment
# `# claude-md-reviewed` to the push command.
input=$(cat)

case "$input" in *"git push"*) ;; *) exit 0 ;; esac
case "$input" in *claude-md-reviewed*) exit 0 ;; esac

cd "${CLAUDE_PROJECT_DIR:-.}" 2>/dev/null || exit 0
upstream=$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null) || exit 0

if git diff --name-only "$upstream"..HEAD 2>/dev/null | grep -qx 'CLAUDE.md'; then
    exit 0
fi

printf '%s\n' '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"CLAUDE.md is not updated in the commits being pushed. Before pushing: update CLAUDE.md (Current status, Day 1 next steps, Waiting on Steve, Parked, Gotchas) to reflect what these commits change, commit it, then push again. If CLAUDE.md genuinely needs no change for these commits, re-run the push with the comment  # claude-md-reviewed  appended to the command."}}'
exit 0
