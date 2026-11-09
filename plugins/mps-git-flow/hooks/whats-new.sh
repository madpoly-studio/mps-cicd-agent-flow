#!/usr/bin/env bash
# SessionStart hook of mps-git-flow: once per new version on this machine, shows what changed. Reads
# RELEASE_NOTES.md shipped with the plugin (no network) and never fails the session.
# State: the last version shown, in ${CLAUDE_CONFIG_DIR:-~/.claude}/mps-git-flow/last_seen_version.
# Last version unknown (first run with this hook, or a downgrade): only the installed version's notes. Otherwise
# every version newer than the last one shown, at most max_versions of them.

max_versions=5
notes_url="https://github.com/madpoly-studio/mps-cicd-agent-flow/blob/main/plugins/mps-git-flow/RELEASE_NOTES.md"

root="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." 2>/dev/null && pwd)}"
notes="$root/RELEASE_NOTES.md"
manifest="$root/.claude-plugin/plugin.json"
[ -f "$notes" ] && [ -f "$manifest" ] || exit 0
version=$(tr -d '\r' < "$manifest" | sed -n 's/^[[:space:]]*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1)
[ -n "$version" ] || exit 0

state_dir="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/mps-git-flow"
state="$state_dir/last_seen_version"
last=""
[ -f "$state" ] && last=$(head -n 1 "$state" | tr -d '\r[:space:]')
[ "$last" = "$version" ] && exit 0
# Recorded before printing: a broken notes file must not show a message at every start.
mkdir -p "$state_dir" 2>/dev/null && printf '%s\n' "$version" > "$state" 2>/dev/null

clean=$(tr -d '\r' < "$notes")
body=$(printf '%s\n' "$clean" | awk -v current="$version" -v last="$last" -v max="$max_versions" '
  function heading(line,   v) {
    if (line !~ /^## /) return ""
    v = substr(line, 4); sub(/[ \t].*$/, "", v); return v
  }
  { lines[NR] = $0; if (last != "" && heading($0) == last) found = 1 }
  END {
    out = ""; on = 0; count = 0
    for (i = 1; i <= NR; i++) {
      v = heading(lines[i])
      if (v != "") {
        if (found) {
          if (v == current) started = 1
          if (!started) { on = 0; continue }  # newer than the installed version: not installed yet
          if (v == last || ++count > max) break
          on = 1
        } else if (v == current) {
          on = 1
        } else if (on) {
          break
        }
        if (on) out = out (out == "" ? "" : "\n") "Bản " v ":"
        continue
      }
      if (!on || lines[i] !~ /[^ \t]/) continue
      if (lines[i] ~ /^[ \t]/) {  # a wrapped bullet: joined to its first line
        t = lines[i]; sub(/^[ \t]+/, "", t); out = out " " t
      } else {
        out = out "\n" lines[i]
      }
    }
    printf "%s", out
  }')
[ -n "$body" ] || exit 0

json_escape() {
  # tr for the tab: BSD sed (macOS) does not know \t.
  printf '%s' "$1" | tr '\t' ' ' | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' | awk '{ printf "%s%s", (NR > 1 ? "\\n" : ""), $0 }'
}

user_msg="mps-git-flow bản $version - có gì mới:
$body
Xem đầy đủ: $notes_url"
claude_ctx="The mps-git-flow plugin on this machine is now version $version. The user was just shown these release notes (Vietnamese): $body
Do not repeat them unprompted; use them to answer questions about what changed."

printf '{"systemMessage": "%s", "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "%s"}}\n' \
  "$(json_escape "$user_msg")" "$(json_escape "$claude_ctx")"
exit 0
