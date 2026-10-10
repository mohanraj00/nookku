#!/bin/sh
# The command hook of the nookku plugin, for Claude Code and for Codex. The argument is the hook
# event. The hook runs `nookku hook` from PATH, which holds each rule (SPEC.md section 5).
#
# If nookku is not on PATH, this script fails closed. In relay mode or during a test, it blocks
# the prompt and denies the tool call. With no state folder, it does nothing.

event=$1
# Codex sets PLUGIN_ROOT for a plugin hook, and Claude Code does not
# (proofs/spikes/codex-plugin.json, proofs/plugin/load.json).
if [ -n "${PLUGIN_ROOT:-}" ]; then
  harness=codex
else
  harness=claude-code
fi
if command -v nookku >/dev/null 2>&1; then
  exec nookku hook --harness "$harness"
fi

cat >/dev/null
root=.
# A Codex hook can inherit CLAUDE_PROJECT_DIR from a Claude Code session of another project.
if [ "$harness" = claude-code ] && [ -n "${CLAUDE_PROJECT_DIR:-}" ]; then
  root=$CLAUDE_PROJECT_DIR
fi
state="$root/.nookku"
[ -d "$state" ] || exit 0
on=no
[ -e "$state/current.json" ] && on=yes
if [ -e "$state/mode" ]; then
  # A mode file that cannot be read, or that does not say off, counts as relay mode on.
  mode=$(tr -d ' \t\r\n' <"$state/mode" 2>/dev/null) || mode=unknown
  [ "$mode" = off ] || on=yes
fi
[ "$on" = yes ] || exit 0

missing="nookku: relay mode is on, but the nookku command is not on PATH. Install it with: uv tool install nookku."
case "$event" in
  UserPromptSubmit)
    printf '{"decision": "block", "reason": "%s Nothing was sent."}\n' "$missing"
    ;;
  PreToolUse)
    printf '{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "%s The tool call did not run."}}\n' "$missing"
    ;;
esac
exit 0
