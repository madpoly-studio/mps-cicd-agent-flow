---
name: mps-git-flow
description: >-
  Commit and push code to the MPS self-hosted GitLab (git-gst.mto.zing.vn) with Jira (jira-mps.mto.zing.vn)
  ticket discipline - look up or create the Jira ticket (any board, e.g. MPS or the artist board), create the
  branch named after it, review that the changes match the ticket scope and follow the team's and the
  project's code review rules (.mps/review.md), commit only the in-scope files, push,
  open the merge request (MR) back into the branch the work came from, and update the Jira status. Use when
  the user wants to commit, push code, create a merge request / MR, create a branch for a Jira ticket, or follow
  the MPS project git flow. Vietnamese triggers - "commit code", "đẩy code", "push code lên GitLab", "đưa code
  lên", "gửi code", "tạo merge request", "tạo MR", "tạo nhánh/branch theo ticket Jira", "quy trình git MPS".
---

# MPS git flow

You help a team member (often NOT a developer) get their changes from the working tree into a GitLab merge
request that is linked to a Jira ticket, following the team's branch rules. The user's work is precious: never
lose it, never rewrite shared history, never commit what was not meant for this ticket, and stop to ask
whenever something is unusual.
Before anything is committed, the changes are also checked against code review rules: the team's baseline, rules
for the detected stack (Unity C#, Python, web) and the project's own rules in `.mps/review.md` on the base branch.
Only a rule the project itself marks `blocker` can stop a commit; everything else is a warning shown to the user
and written into the merge request.

## Talking to the user

- Speak Vietnamese (or the user's language if they write in another one). Short sentences, plain words.
- Avoid git jargon. When a term is unavoidable, explain it once in brackets, e.g. "nhánh (branch - một bản làm
  việc riêng của bạn)", "merge request (MR - yêu cầu gộp code để người khác duyệt)".
- Every script result has a Vietnamese `message`: relay it in your own friendly words, never dump raw JSON.
- Never ask the user to paste a token into the chat. If they paste one anyway: do not repeat it, tell them to
  revoke it and create a new one, and to put the new one into `.env` themselves.

## The helper script

Claude Code shows "Base directory for this skill: <dir>" when this skill loads. Call that `SKILL_DIR`.
The CLI is `"<SKILL_DIR>/scripts/mps.py"`; references are in `<SKILL_DIR>/references/`.

- Run it with the Python from step 0 (`PY` below = the quoted absolute `python_cmd`), from inside the user's
  project folder (it finds the git root itself): `PY "<SKILL_DIR>/scripts/mps.py" <group> <command> ...`
- ALWAYS pass option values in the equals form and quoted, e.g. `--summary="..."`, `--message="..."`,
  `--title="..."`, `--description="..."`, `--body="..."`, `--name="..."`, so values that start with `-` still parse.
- Each call prints ONE JSON object: `{"ok": true, ...}` or `{"ok": false, "error": "<code>", "message": "..."}`
  (non-zero exit). Branch on `error`, not on text.
- Temp files (Jira description, comments, the reviewers' replies): write them ONLY inside `tmp_dir` from
  `env check` (a folder inside `.git`, never committed), never in the working tree.
- File paths given to `git commit --files` are relative to the project root (as listed by `git preflight`).
- Error codes and fixes: `references/troubleshooting.md`; environment / bootstrap codes:
  `references/setup-environment.md`. Branch rules and examples: `references/branch-rules.md`.

| Command | Purpose |
|---|---|
| `env init [--open]` | create `.env` from the template (never overwrites), make sure git ignores it; gives `fill_guide` |
| `env check` | validate `.env`, Jira + GitLab tokens, GitLab project, access level, Jira project; gives `tmp_dir`; reports `plugin_outdated` when a newer plugin version exists |
| `env set KEY VALUE` | save a NON-secret setting (refuses `*_PAT`) |
| `project setup [--review-rules]` | (lead) add the plugin + auto-update to `.claude/settings.json`, make sure `.env` is git-ignored; report / scaffold `.mps/review.md` |
| `jira get KEY` | read a ticket from ANY Jira project |
| `jira projects` | list Jira projects (boards) the user can see, plus the configured default |
| `jira sprints [--project=KEY]` | active sprints of the board a new ticket goes to (to ask before creating a story) |
| `jira create --type=story\|bug --summary=S --description-file=F [--project=KEY] [--field=...] [--sprint=active\|backlog\|ID]` | create a ticket; a bug goes into the running sprint by default, a story needs `--sprint` (ask the user) |
| `jira transition KEY --to=done\|resolved` / `jira comment KEY --body-file=F` | update a ticket |
| `naming build --key=K --type=story\|bug\|hotfix --title=T` | branch, commit message, MR title/description |
| `flow plan --type=story\|bug --key=K [--phase=dev\|beta\|production]` | phase from the branch holding the work; base = target |
| `git preflight --base=B --branch=N` | status, branch role + `blockers` (must stop) + `warnings` |
| `git set-identity --name=N --email=E` | set the repo-local git name/email (only with the user's consent) |
| `git prepare-branch --base=B --branch=N --key=K [--leave-commits]` | fetch, switch to / create the ticket branch, record its base |
| `git diff-for-review --base=B --to-file` | write the scope bundle and the code-review bundle (same `Bundle-ID`) + the rules snapshot |
| `review classify --base=B --result-file=F` | check the scope reviewer's `FILES:` block, derive commit / exclude lists, save them |
| `review findings --base=B --result-file=F` | check the code reviewer's `FINDINGS:` block against the bundle and the rules, save the result |
| `git commit --message=M --files f1 f2 ... [--include-out-of-scope f ...]` | commit exactly those reviewed files |
| `git push --branch=N --base=B --message=M [--amend-confirmed]` | make the branch ONE commit (message M) rebased on origin/B, check it for .env/secrets, push (lease-protected force only on the own ticket branch) |
| `mr ensure --source=S --target=T --title=X --description=D --key=K --type=story\|bug [--code-review]` | verify target = recorded base, reuse / create the MR (assigned to the user, labelled Enhancement / Bug), add the code-review report |

## Workflow

### 0. Prepare the environment (automatic, no questions)

The helper needs git and Python 3.8+. Missing tools are installed automatically: do NOT ask for permission, but
tell the user in one plain line what you install and why.

1. Detect: Windows -> `powershell.exe -NoProfile -ExecutionPolicy Bypass -File "<SKILL_DIR>/scripts/bootstrap.ps1" -DetectOnly`;
   macOS / Linux -> `sh "<SKILL_DIR>/scripts/bootstrap.sh" --detect-only`. It prints one JSON line.
2. `ok: true` -> `PY` = `"<python_cmd>"` (an absolute path; always quote it). Go to step 1.
3. `ok: false` with a non-empty `missing` -> say ONE line such as "Máy bạn chưa có Python 3 (cần để chạy công cụ
   đẩy code), mình đang cài tự động, mất khoảng 1-2 phút." (name exactly the items in `missing`); on Windows add
   "Nếu Windows hiện hộp thoại hỏi quyền, hãy bấm Có (Yes)." (the dialog can appear before any result comes
   back). Then run the same script WITHOUT the detect-only flag, with a long timeout (10 minutes), and go to 4.
   `ok: false` with an empty `missing` (nothing to install, e.g. `restart_required`, `git_not_on_path`,
   `bootstrap_failed`) -> go straight to 4 with the detect-only result.
4. Result:
   - `ok: true` -> mention what was installed (`installed`), set `PY`, continue.
   - `manual_steps` -> explain each step in plain words (show `command` / `url` when present) and wait until the
     user says it is done, then run step 0 again. Commands with `sudo` are typed by the user in their own Terminal;
     never ask for, accept or type a password in the chat.
   - `restart_required` -> ask the user to fully close Claude Code AND the VS Code / Terminal window running it,
     open it again in the project folder and say "tiếp tục"; then start again from step 0.
   - `git_not_on_path` -> git is installed but its folder is not on PATH; relay the manual step (it names the
     folder to add or remove), wait, then step 0 again.
   - Warning `install_still_running` -> an installer is still working; ask the user to wait a few minutes and say
     "tiếp tục", then run step 0 again (no manual download).
   - `bootstrap_failed` -> the script itself failed; give the manual steps from `references/setup-environment.md`
     and ask the user to send the log file (`log_path`) to a developer.
   - Relay other `warnings` briefly (e.g. `uac_prompt_possible`: Windows may show a permission dialog - click Yes).
   Details and error codes: `references/setup-environment.md`.
5. Fallback: if the script prints no JSON line at all (blocked by policy, killed, timed out), check by hand:
   `py -3 --version` (Windows) or `python3 --version`, and `git --version`. Use any Python that reports 3.8 or
   newer as `PY`, and continue if git reports 2.23 or newer; otherwise give the manual steps from
   `references/setup-environment.md` and wait.
Install nothing else, and never change system settings beyond what this script does.

### 1. Check the configuration

Run `env check`.
- `plugin_source_legacy` (any command can return it, except `project setup`): this machine still installs the
  plugin from the old personal repo, and nothing else runs until it is removed. Relay `message` in friendly words
  (the team moved the plugin to the shared repo, so the copy from hungbt's personal repo has to be removed). Offer
  to do it: only if the user agrees, run each of `commands` in order (remove the old marketplace(s), add the shared
  repo, install the plugin). If `claude` is not found or a command fails, give the user the `/plugin ...` commands
  from `message` to type. Then ask them to type `/reload-plugins` (or restart Claude Code) and stop this run.
  It can also appear in the middle of a ticket (e.g. after switching to a branch whose `.claude/settings.json`
  already names the shared repo). Nothing is lost: after the reload, resume from the step that failed (see
  "Resuming"); the branch and the changes are kept.
- `env_missing` -> run `env init --open`. Tell the user the `.env` file was created (and opened, or give
  `env_path`) and that they only need to fill THREE lines: relay `fill_guide` as a short numbered list (label,
  steps, link). Say every other line already has the right default and should not be changed. They type the
  tokens into the file themselves, save it and tell you "xong"; never ask for or accept a token in the chat.
  Then run `env check` again.
- `missing_config` -> same, using `fill_guide` (only the keys still missing).
- A Jira / GitLab authentication error -> relay its `fill_guide` (that token is wrong or expired; create a new one
  and replace the line in `.env`).
- `action_required` contains `ask_jira_project_key` (the member left it blank) -> show `jira_projects`
  (key - name), ask which board is the team's usual one, then `env set MPS_JIRA_PROJECT_KEY <KEY>`. It may
  differ from the GitLab project name.
- `gitlab_project_unknown` -> ask for the GitLab project path (group/project), then
  `env set MPS_GITLAB_PROJECT <path>`.
- Auth / network / SSL errors -> explain using `references/troubleshooting.md` and wait.
- If `gitignore_updated` is true, mention that `.env` was added to `.gitignore` (so that change will show up).
- Remember `tmp_dir`, `jira_project` (the default board), `jira_user`, `gitlab_user`, `git_identity`,
  `gitlab_access_level`, `branches`.
- `warnings` may contain:
  - `plugin_outdated`: a newer version of this plugin exists (`latest`, `running`). Update without asking: run
    `claude plugin marketplace update mps-cdci-agents` and then `claude plugin update mps-git-flow@mps-cdci-agents`.
    If either command fails or `claude` is not found, tell the user to type `/plugin marketplace update
    mps-cdci-agents` in Claude Code. Then tell the user that the new version is active after `/reload-plugins` or a
    restart of Claude Code. This run continues with the current version. If `update_blockers` lists environment
    variables (e.g. `DISABLE_AUTOUPDATER`), mention that automatic updates are turned off on this machine.
    When the project pins the marketplace to a version (`"ref"` in `.claude/settings.json`), no check is made:
    `plugin_version.pinned` names the ref and `plugin_outdated` never appears.
  - `legacy_project_source`: the project's `.claude/settings.json` still declares the plugin from the old personal
    repo. Mention once that the lead should say "tích hợp plugin vào project" (it moves the project to the shared
    repo) and commit the file. Never change it yourself while pushing code.
  - `project_not_integrated`: this project has not added the plugin to `.claude/settings.json`, so teammates do
    not get it (or its updates) automatically. Mention once that the project lead can say "tích hợp plugin vào
    project" (skill mps-project-setup). Never do it yourself as part of pushing code.
- Things that cannot be installed (company VPN, Jira / GitLab tokens) are guided as before; never ask for tokens
  in the chat.
- `env check` errors (`env_missing`, `missing_config`, ...) also carry `warnings` and `plugin_version`; handle
  `plugin_outdated` the same way before fixing the error.

### 2. Ticket

Ask for the Jira ticket ID. A ticket from ANY board is fine (e.g. `MPS-123`, or `ART-12` from the artist
team's board) - the ticket's project does not have to match the GitLab project.
- Given -> `jira get KEY`. `unsupported_type` -> only Story and Bug are used; ask for another ticket.
  Show the summary and status and confirm it is the right ticket.
- No ticket -> understand the task: ask what they are working on and look at the changes (`git preflight`,
  and `git diff` / reading files). Decide `story` (new feature / improvement) vs `bug` (something broken). If
  unclear, ASK. Draft a summary (one line) and a short description and confirm them with the user.
  - Board: tell the user the ticket will be created on the default board (`jira_project` from step 1) and ask
    whether it belongs to another board (e.g. the artist board). If so, run `jira projects`, let them pick,
    and pass `--project=<KEY>` for this one ticket. Do NOT change `MPS_JIRA_PROJECT_KEY` unless the user says
    that board should become the default.
  - Sprint (decided BEFORE creating, never changed afterwards without asking): once the board is known, run
    `jira sprints [--project=KEY]` before showing the draft. No active sprint (empty `active_sprints`, or
    `sprint_info_available: false`) -> say the ticket goes to the backlog, nothing to ask, omit `--sprint`.
    - Bug -> do not ask whether: a bug goes into the running sprint. One active sprint -> say in the draft "bug sẽ
      được đưa vào sprint <name>" and pass `--sprint=<its id>`. Several -> list them and ask WHICH one. Pass
      `--sprint=backlog` only if the user asks for it.
    - Story -> adding a feature to the running sprint changes that sprint's scope, so the user MUST choose. In the
      same message as the draft, ask: put it into the running sprint (name it with its end date; list all of
      them when there are several) or leave it in the backlog? Pass `--sprint=<id of the sprint they picked>` or
      `--sprint=backlog` exactly as answered; never pick for them. Use the id, not `active`, so the story cannot
      land in a sprint that started after the user answered.
  - Write the description to a file in `tmp_dir`, then
    `jira create --type=story|bug --summary="..." --description-file=<tmp_dir>/description.txt [--project=KEY]
    [--sprint=<id>|backlog]`. Assignee and reporter are set to the user automatically.
  - Sprint errors (nothing has been created yet; rerun the same command with the answer):
    `sprint_choice_required` -> a story without `--sprint` while a sprint is running: ask as above.
    `sprint_ambiguous` -> several sprints run at once: show `active_sprints` (name, end date), let the user pick,
    rerun with `--sprint=<id>`. `sprint_not_active` -> that sprint is no longer running (e.g. it just closed):
    show `active_sprints` and ask again (a story: sprint or backlog; a bug: which sprint).
  - Report where the ticket went: `placement` (`sprint` + `sprint.name`, or `backlog`). `sprint_failed: true` ->
    the ticket exists (`key`) but the move into the sprint failed: relay the note (the user drags it into the
    sprint on Jira); NEVER recreate the ticket.
  - `jira_project_not_found` -> the chosen board does not exist / is not visible; show `available_projects`.
  - `missing_required_fields` -> for each entry in `fields`, ask the user (offer `allowed_values` as choices),
    then retry adding `--field="<id or name>=<value>"` per field.
  - Relay any `notes` (e.g. reporter could not be set).

### 3. Phase (from the branch that holds the work)

A change made on branch X always goes back into X. Run `flow plan --type=<story|bug> --key=<KEY>` WITHOUT
`--phase` first (it fetches from GitLab with `--prune`, so deleted branches are noticed):
- Files tools rewrite on their own do not count as work here: inside a Unity project root (a folder with
  `ProjectSettings/ProjectVersion.txt`) its `ProjectSettings/**`, `UserSettings/**`, `Library/**`,
  `Packages/packages-lock.json` and the `*.csproj` / `*.sln` directly in it, plus the user's own
  `MPS_GENERATED_PATTERNS`. A folder that only has the same name deeper down (`Assets/Plugins/Library/...`) is
  real work. If `generated_changes` is non-empty, mention them briefly ("Unity tự sửa các file này, không ảnh
  hưởng việc chọn giai đoạn"). They are still classified by the scope review in step 6 and never committed
  automatically. A warning `invalid_generated_pattern` lists patterns from `.env` that were ignored; tell the
  user (they fix `.env` themselves).
- The current branch pins the phase only when work sits on it (other uncommitted changes or unpushed commits,
  `work_in_progress`) or when it is THIS ticket's own branch made by this skill: `develop` -> dev, any
  `release/*` -> beta (that exact release branch, even if not the newest), `master` -> production, own ticket
  branch -> the phase of its `recorded_base`. A detached HEAD sitting exactly on one of them counts as that
  branch. Tell the user in plain words, e.g. "Bạn đang làm trên nhánh release/1.1 nên thay đổi sẽ gộp về
  release/1.1 (giai đoạn beta)", and let them confirm (`phase_source: "detected"`).
- `phase_required` -> nothing pins the phase (clean tree, personal branch, another ticket's branch): ask dev
  (normal work, into `develop`), beta (bug fixes on the current `release/*`), production (hotfix into
  `master`); `detected_phase` may hint at the current branch. Re-run with `--phase=<phase>`; on a clean tree the
  user's choice is used (`phase_source: "requested_clean_tree"`).
- `phase_conflict` -> the user chose a phase different from the branch that holds the work. Explain that changes
  made on one branch cannot silently move to another phase; suggest a developer. Never work around it.
- `detached_head` -> changes exist but HEAD is on no branch: stop, a developer must help.
- `recorded_base_gone` (error: work in progress on a ticket branch whose base was deleted on GitLab) -> stop, a
  developer must help. As a warning (clean tree) the old ticket branch is simply not reused; continue normally.
- `release_branch_gone` -> the release branch the work sits on no longer exists on GitLab: stop, ask a developer.
- `warnings`: `not_latest_release` -> tell the user they are on an older (still existing) release branch
  (`latest` names the newest) and confirm that this is intended. `other_ticket_branch` -> the user stands on
  another ticket's branch; this ticket gets its own branch.
- `phase_rule_violation` -> explain kindly (e.g. new features cannot go into beta; they go to dev).
- `no_release_branch` -> beta has not started; ask the user / a developer.
- If the plan has a `note`, tell the user (beta: no back-merge MR into develop is needed - the team back-merges
  the release branch at the end of the beta phase).
- production: show `warning` prominently and recommend that a developer does it. Continue ONLY if the user
  explicitly answers something like "Tôi hiểu rủi ro, vẫn tiếp tục". If `access_level` < 40 stress that they
  probably cannot merge into master anyway.
- Keep `kind`, `base_branch`, `target_branch` (always equal to `base_branch`), `naming_type`.

### 4. Names

`naming build --key=KEY --type=<naming_type> --title="<Jira summary>"` (naming_type is `hotfix` for
production, otherwise the ticket type). Use `branch`, `commit_message`, `mr_title`, `mr_description`
exactly as returned - do not reword or append anything (no co-author lines, no emojis).

### 5. Preflight and branch

Run `git preflight --base=<base_branch> --branch=<branch>`.
- If `blockers` is non-empty, STOP and explain each one in plain words:
  - `env_file`, `env_file_in_commits`, `secret_detected`, `large_file`, `operation_in_progress`,
    `unmerged_files`, `commits_on_protected_branch`: cannot continue; tell the user what to remove / that a
    developer should help.
  - `missing_git_identity`: git does not know who is committing. Offer to set it for this project only, using
    `gitlab_user.name` (or `username`) and `gitlab_user.email` from step 1; ask for the email if it is missing.
    With the user's OK run `git set-identity --name="..." --email="..."`, then re-run preflight.
  - `possible_secret` (`confirmable: true`): open each `file:line`, show the user the line with the value
    masked, and continue only if the user confirms it is not a real password/token.
- Warnings: `local_commits_not_carried` means the current branch has commits that are on no GitLab branch
  (usually never pushed; commits this skill pushed earlier are not counted, even after GitLab deleted the merged
  branch) and the new ticket branch will NOT contain them (they stay safe on the old branch). Explain this;
  recommend asking a
  developer. Only if the user explicitly agrees to leave them behind, add `--leave-commits` below. Mention other
  warnings briefly (e.g. `nothing_to_commit`).

Then `git prepare-branch --base=<base_branch> --branch=<branch> --key=<KEY>`. It records the base in the
repo-local git config (`branch.<branch>.mps-base`), so later steps can enforce "merge back into the same branch".
- `stash_conflict` / `stash_failed` -> stop: the changes are safe in the git stash (`stash_commit`); a developer
  must help. Never try to resolve it yourself. After this, `unmerged_files` will block every later step until a
  developer has fixed it - that is intended.
- `base_mismatch` -> this ticket branch was made from `recorded_base` and must go back into it, not into the
  base you asked for. Explain; do not continue with a different base (ask a developer if the user insists).
- `branch_base_mismatch` -> a branch with this name already exists but holds commits of other work (shown in
  `foreign_commits`), typically a dev bugfix branch being reused for beta. Do NOT continue with it: explain,
  and suggest asking a developer (or, with a developer's agreement, a differently named branch).
- `local_commits_not_carried` -> see the warning above.

### 6. Scope review + code review (before any commit)

Two reviews of the same snapshot run side by side:
- Scope review: only what was intentionally changed for this ticket gets committed. Anything else (Unity-regenerated
  `ProjectSettings`/`.meta` files, lock files, someone else's edits, IDE files) stays on the user's machine,
  untouched, and is NOT committed - so it cannot affect other people.
- Code review: the changes are checked against the rules that apply - the team baseline, the rules for the detected
  stack (Unity C#, Python, web) and the project's own rules in `.mps/review.md`, always read from the base branch on
  GitLab (a local edit of that file changes nothing). Findings are warnings; only a rule the project marked
  `blocker` stops the commit.

1. `git diff-for-review --base=<base_branch> --to-file` -> `bundle_path`, `code_bundle_path` (both inside `.git`,
   never committed), `bundle_id`, `rules`, `warnings`, `code_review_needed`. The bundles are a snapshot: both
   headers carry the same `Bundle-ID`, and the script remembers the exact content of every file in it. The scope
   bundle's section 0 lists the files to classify (`files_to_classify` = uncommitted changes,
   `already_committed_files` = earlier commits on this branch); `.env` files appear only as "[content hidden]". The
   code bundle holds the rules (A), the files to check (B) and the changes with line numbers (C). Do not edit any
   project file between this step and the commit; if anything must change (e.g. trimming a mixed file, fixing a
   blocker), make the change and start again from this step.
   Tell the user in one or two plain sentences which rules are used (`rules.profiles`, `rules.project_rules`):
   - `status: applied` -> team rules + stack rules + the project's own rules.
   - `status: absent` -> only the team rules and the stack rules ("dự án chưa có file quy tắc riêng").
   - `status: invalid` (warning `project_rules_invalid`, see `problems`) -> the project's rules file on
     `<base_branch>` is broken, so this time only the team's common rules are used; a developer should fix
     `.mps/review.md`. Continue, and show it again in step 7.
   - `pending_change: true` (warning `project_rules_pending`) -> this change edits `.mps/review.md`; the new rules
     apply only after the merge request is merged. This review uses the version on `<base_branch>`.
   - `project_rule_matches_nothing` (`rule`, `paths`): that project rule matches no file on `<base_branch>`, so it
     never applies (usually its paths do not start at the repo root); mention it - the tech lead fixes the file.
   - Other warnings (`unknown_profile`, `project_rules_unknown_key`, `rules_truncated`, `code_bundle_truncated`,
     `shipped_blocker_downgraded`): mention briefly in plain words.
   - Error `base_mismatch`: `--base` differs from the branch's recorded base (the project rules would be read from
     the wrong branch); use the base from step 3.
   - `code_review_needed: false` -> nothing to check against the rules (for example only Unity scenes/prefabs
     changed); the script already recorded an empty code review. Skip the code reviewer and `review findings` below.
2. Read `references/scope-review-prompt.md` and (if `code_review_needed`) `references/code-review-prompt.md`.
3. Launch the reviewers with the Agent tool, `subagent_type: "general-purpose"` (do not rely on custom agents;
   teammates may not have them). Put BOTH Agent calls in the SAME message so they run in parallel:
   - Scope reviewer: prompt = the full text of scope-review-prompt.md + a "Ticket" block (key, type, summary,
     description) + "The change bundle is at <bundle_path>; read the whole file with the Read tool." If `truncated`
     is true, say so in the prompt.
   - Code reviewer: prompt = the full text of code-review-prompt.md + the same "Ticket" block + "The code bundle is
     at <code_bundle_path>; read the whole file with the Read tool." If `code_bundle_truncated` is true, say so.
   Each reply must contain `BUNDLE: <id>` with the bundle's id.
4. Save each reply exactly as received (never edited by you): the scope reply to `<tmp_dir>/review.txt`, the code
   reply to `<tmp_dir>/code_review.txt`. Run
   `review classify --base=<base_branch> --result-file=<tmp_dir>/review.txt` and
   `review findings --base=<base_branch> --result-file=<tmp_dir>/code_review.txt`. Both only accept a reply for the
   latest bundle while nothing has changed since that bundle; they save their results in `<tmp_dir>/scope.json` and
   `<tmp_dir>/code_review.json`. `git commit` only accepts files approved there whose content is still exactly what
   was reviewed, and only with a complete code review of the same bundle. Any edit to a file, or a new commit, means
   starting step 6 again - both reviews.
   - `review_stale` from either command (`reason`: reply for an older bundle, reply without the `BUNDLE:` line,
     files / branch / HEAD changed since the bundle, `no_code_bundle`) -> run `git diff-for-review` again and get
     fresh replies from BOTH reviewers for the new bundle. Never reuse an old reply and never add the `BUNDLE:` line
     yourself.
   - `complete: false` from `review classify` (`unclassified_files`, `unknown_paths`, `duplicate_paths`, missing
     verdict) or `review_unparsable` -> ask the scope reviewer (same subagent via SendMessage, or a new one) to fix
     its reply for the same bundle; never guess. Until the classification is complete, `git commit` refuses with
     `scope_incomplete` (also for `--include-out-of-scope`). `unclassified_files` are never committed.
   - `code_review_unparsable`, or `needs_reviewer_fix: true` from `review findings` -> ask the code reviewer
     (SendMessage, or a new one) to fix its reply for the same bundle, quoting the `dropped_findings` entries; save
     it again and re-run `review findings`. Until then `git commit` refuses with `code_review_incomplete`. Tell the
     reviewer what to fix, per `dropped_findings` entry:
     - `reason: bad_format` with "more than one FINDINGS block ..." or "text between the end of the FINDINGS block
       and BUNDLE": "send exactly one FINDINGS block, no code blocks inside, then BUNDLE".
     - other `bad_format` (a line in the wrong format, or `FINDINGS:` with nothing under it): "one finding per line,
       5 fields separated by |, or exactly `FINDINGS: none`".
     - `blocker_claimed: true` with `reason: unknown_rule`: "a finding you marked blocker uses an unknown rule id:
       use an id from section A or drop the line".
     - `blocker_rule: true` (a finding on a `blocker` rule that does not match the bundle: wrong file, line or path):
       "cite the file exactly as in section B and a line number printed in section C".
   - Default commit set = `commit_files`: in_scope files, plus concern files when the verdict is PASS.
     `excluded_files` (out_of_scope) are left out.
   - `needs_decision` (concern files under a FAIL verdict) and `concern_files`: show each concern and ask the
     user per file whether to commit it.
   - `mixed_files`: show what part is in / out of scope and ask the user to choose for each file: include the
     whole file, exclude the whole file, or let you remove the out-of-scope part (first show exactly what will
     be removed, edit only after the user agrees, then run step 6 again). Never include a mixed file silently.
   - `committed_out_of_scope`: out-of-scope work is already in an earlier commit of this branch; it cannot be
     left out any more - tell the user and suggest a developer.
   - If YOU (the main agent) made out-of-scope changes earlier in this conversation, offer to move them back
     into scope instead.
   - `rule_warnings` (major, then minor) never block; keep them for step 7. `dropped_count` = findings the script
     could not match to the bundle (wrong file, line or rule); mention only the number.
5. Project blockers (`blockers` from `review findings`). For each one, look at its `path`:
   - The file is in the commit set (`commit_files`, or a file the user wants to include) or in
     `already_committed_files`: it cannot be committed as it is.
     1. Explain in plain words: the rule ID and title, `file:line`, the problem, and that this rule is required by
        the project (set by the tech lead in `.mps/review.md`).
     2. If you can change the code so it follows the rule, OFFER to do it. Show exactly what will change (the lines
        before and after; the reviewer's `suggestion` helps). Edit only after the user explicitly agrees.
     3. After the edit, start step 6 again from 6.1: a new bundle and BOTH reviews.
     4. If you cannot fix it, the user declines, or the blocker is reported again after the fix: STOP and tell the
        user that a developer must review this change. There is no way to override a project blocker.
   - The file stays out of the commit (out of scope / excluded) and was never committed: tell the user. That file
     cannot be force-included with `--include-out-of-scope` while the blocker stands.
   - Never edit `.mps/review.md` or any rule, never edit a reviewer reply, and never write `FINDINGS:` or `BUNDLE:`
     lines to get past a blocker.

### 7. Confirm

Show a short summary and ask for an explicit "yes":
- ticket (key + link), type, phase
- branches: "tách từ `<base_branch>` -> nhánh `<branch>` -> merge vào `<base_branch>`"
- the commit message, and that the merge request will contain exactly ONE commit with it (earlier commits of this
  ticket branch are combined into it and it is rebased onto the newest `<base_branch>`)
- **Sẽ commit:** the exact file list
- **Không commit (ngoài phạm vi — giữ nguyên trên máy):** every excluded / unclassified file
- the reviewer verdict and any concerns
- **Cảnh báo code review (không chặn commit):**
  - If `project_rules.status` is `invalid`, the FIRST line, clearly: "Quy tắc riêng của dự án KHÔNG được áp dụng
    lần này vì file .mps/review.md trên nhánh <base_branch> bị lỗi; merge request sẽ ghi rõ điều này. Hãy báo
    developer sửa file."
  - If `code_bundle_truncated` is true: "Review code chỉ xem được một phần vì thay đổi quá lớn; các file chưa được
    xem hết: <truncated_paths>. Merge request cũng sẽ ghi rõ."
  - `rule_warnings`, major first, then minor: `RULE-ID` - `file:line` - problem - suggestion. "Không có cảnh báo"
    when empty.
  - If `dropped_count` > 0, one line: "<n> nhận xét của reviewer không khớp với thay đổi nên đã bị bỏ qua."
  Warnings never block the commit, and you never leave them out of this summary.

Tell the user they can force-include any excluded file by naming it. Add a file that is not in `commit_files`
(out-of-scope, mixed kept whole, or a `needs_decision` concern) ONLY if the user explicitly named that specific
file, and then pass it in both `--files` and `--include-out-of-scope`. Never add files to
`--include-out-of-scope` on your own. No commit and no push before the user agrees.

### 8. Commit, push, merge request

1. `git commit --message="<commit_message>" --files <agreed files> [--include-out-of-scope <files the user named>]`
   - always the explicit agreed list of exact file paths.
   - `scope_review_required` (no review, or the branch/HEAD changed since) / `changed_since_review` (a file was
     edited after the reviewer saw it) / `scope_incomplete` -> run step 6 again. `not_in_scope` -> the file was
     not approved; ask the user.
   - `code_review_required` (no code review for this bundle, or it belongs to an older bundle / commit) -> run step
     6 again (both reviews). `code_review_incomplete` -> get the code reviewer to fix its reply for the same bundle
     and re-run `review findings`.
   - `base_mismatch`: the reviews were made against another base than the branch's recorded one; run step 6 again
     with the recorded base.
   - `code_review_blocked`: nothing was committed (`blockers` lists rule, file:line, problem). Handle it as in step
     6.5: offer a fix (edit only with the user's OK, then step 6 again); otherwise stop and send the user to a
     developer.
   - `explicit_files_required`: a folder, `.` or a path that is not a changed file was passed; list the
     individual changed files instead (`changed_files_inside`).
   - `nothing_to_commit` is fine when resuming an earlier run: either nothing is changed, or the requested files
     are already committed on this branch (`already_committed`) while other files stay uncommitted.
   - `env_file` / `secret_detected`: nothing was committed; explain and stop.
   - A successful commit consumes both reviews; a later commit needs step 6 again. The code-review result of this
     commit is kept for the merge request (step 8.3); `code_review_warning_count` = its warnings on the committed
     files. `code_review_recorded: false` (rare: the result could not be saved) -> the commit is fine, but the MR
     will get no code-review report; tell the user.
   - Keep `left_uncommitted` (changed files still not committed) for the final report. Relay
     `unstaged_other_files` if non-empty (files staged earlier that were left out; still changed on disk).
2. `git push --branch=<branch> --base=<base_branch> --key=<KEY> --message="<commit_message>"`. Team rule: **one merge
   request = one commit, rebased, never a merge commit**. The script does it; never squash, rebase, merge or
   force push yourself.
   - Only the user's own commits on the branch -> all of them (also earlier pushed ones, and any "Merge
     remote-tracking branch ..." commits) become ONE commit with `<commit_message>`, rebased onto the newest
     `origin/<base_branch>`. If the branch was already pushed, it is replaced with a lease-protected force push
     (`forced: true`) - only ever this ticket branch, never develop / master / release/*.
   - Someone else already pushed commits to this ticket branch -> `amend_confirmation_required` (nothing changed):
     tell the user, in Vietnamese, whose commits are there (`other_authors`) and that their new changes will be
     folded (amend) into the last commit on GitLab (`last_commit`: subject, author; that commit keeps its author
     and message, `--message` is not used); ask. `same_name_as_you: true` -> one of those authors has the user's
     own name with another email (e.g. another computer): say so, it may be the user themselves. Only if they
     agree, run the same command again with `--amend-confirmed`. If they decline, stop and send them to a
     developer.
   - Result: `rewrite` (`none` / `squashed` / `rebased` / `amended`), `commits_combined`, `rebased`,
     `backup_ref` (the previous state, kept on this machine - mention it only if something went wrong).
     `rebase_skipped`: `conflict` -> the change conflicts with newer code on the base; the MR may show a
     conflict: tell the user a developer must resolve it. `local_changes` / `local_files` / `staged_changes` ->
     not rebased so that the user's uncommitted, untracked or staged files stay exactly as they are (fine; it is
     still one commit). `git_too_old` -> not rebased (fine).
   - A failed push (network, token, ...) after the branch was combined is safe to retry with the same command
     (`resumed: true`); never "fix" it with git yourself.
   - It refuses `env_file` / `secret_detected` found in what is about to be published, and `base_mismatch` if the
     base differs from the recorded one.
   - Nothing was pushed or overwritten; stop and send the user to a developer: `merged_foreign_work` (the branch
     contains work merged in from develop or another GitLab branch - list `commits`), `foreign_author_commits`
     (unpushed commits written by someone else), `amend_target_foreign` (the last commit on GitLab has no ticket
     key, e.g. a suggestion applied on GitLab), `remote_branch_ahead` (someone pushed to this branch and this
     machine does not have it yet), `remote_branch_changed` (someone pushed while we were pushing),
     `merge_commit_on_shared_branch`, `rebase_partial` (updating the files to the newest base stopped half way,
     e.g. a file locked by an open editor; the branch was NOT moved). `push_rejected` -> explain; never force.
     Auth errors -> troubleshooting.
3. `mr ensure --source=<branch> --target=<base_branch> --title="<mr_title>" --description="<mr_description>"
   --key=<KEY> --type=<story|bug> --code-review`. The target is ALWAYS the base the branch was made from, and the
   phase rules are checked again for it (`phase_rule_violation`: a Story never goes into release/* or master).
   - `existed: true` means the MR was already there.
   - `code_review_attached`: `description` (new MR: the code-review report is in its description, after
     `mr_description`), `note` (existing MR: added once as a comment), `already` (already added for this review),
     `none` (`code_review_reason`: `no_review`, `other_branch`, `not_in_branch` = the reviewed commit is not pushed
     yet, `outdated` = a newer commit without its own code review is on the branch, `note_failed`). Never write the
     report into `--description` yourself.
   - Warning `code_review_note_failed`: the MR is fine, only the comment failed; mention it; re-running
     `mr ensure` later adds it.
   - The MR is assigned to the user (`assignees`; an existing MR that already has an assignee keeps it) and gets
     the label `Enhancement` (story) or `Bug` (bug, also hotfix) when that label exists on GitLab (`labels`).
     Warnings are non-fatal; relay them: `assign_failed` (assign yourself on the MR page), `label_not_found` (the
     project has no such label: ask the lead to create it, or pick a label by hand; never create labels yourself),
     `label_failed` (add the label by hand on the MR page).
   - `attribution_removed: true` (also on `git commit`) means AI attribution lines were dropped from the text; do
     not add them back.
   - `target_mismatch_recorded_base` / `target_mismatch_inferred_base` / `target_ambiguous` (no recorded base and
     several possible bases; only develop is accepted then) / `branch_base_mismatch` / `mr_target_mismatch` ->
     stop and ask a developer; do not create or change MRs yourself.
   - `invalid_base` (target is not develop/master/release/*), `base_not_found` (origin/<target> missing),
     `branch_not_found` (the source branch is neither local nor pushed) -> re-check the plan from step 3; push
     first if the branch was not pushed.

### 9. Jira follow-up (non-fatal)

GitLab's Jira integration links/closes the ticket through "Close KEY" in the MR description; this works for any
project on the same Jira instance (e.g. ART-12 as well as MPS-123). Verify anyway: `jira get KEY`, then
story -> `jira transition KEY --to=done`, bug -> `jira transition KEY --to=resolved` (`skipped: true` = already
there). Write the comment text to a file in `tmp_dir` and run `jira comment KEY --body-file=<file>` (or
`--body="Merge request: <web_url>"`). If anything fails here (`no_transition`, `transition_failed`, ...), tell
the user what to do by hand on Jira; do not undo the push or the MR.

### 10. Final report

Ticket link, branch ("tách từ X -> merge vào X"), MR link, Jira status, and the files left uncommitted
(`left_uncommitted` from step 8 - still changed on the user's machine, not part of this MR), plus anything the
user still needs to do by hand.
Also the code-review result: the number of warnings (`code_review_warning_count`) and where to read them (MR
description or MR comment). If the project's rules were not applied (`invalid`) or the review was partial
(truncated), say so again.

### Resuming

Every step is safe to repeat: `prepare-branch` returns `already_on_branch`, `flow plan` detects the phase from
the ticket branch's recorded base, `mr ensure` returns the existing MR, `jira transition` is skipped when
already done. If a run stopped half way, re-run from step 1.
`git commit` consumes both reviews. The last committed code review is kept for `mr ensure --code-review`, even if
step 6 runs again before the merge request is created.

## Hard rules

- Never force push yourself (`--force`, `--force-with-lease`, `+refspec`), never `git reset --hard`, never
  rebase or rewrite branches yourself, never `git clean`. The only history rewrite allowed is the one
  `mps.py git push` does on the ticket branch (one commit per MR, lease-protected); develop / master /
  release/* are never force pushed.
- Never merge the base into the ticket branch (`git pull`, `git merge origin/develop`, ...): the team uses rebase;
  `git push` brings the branch up to date with the base itself.
- The agent never deletes branches itself (local or remote). GitLab removes the ticket branch automatically
  after the MR is merged (the MR is created with "delete source branch").
- Never commit `.env` files or tokens; never print, echo, log or repeat a token.
- Never commit or push to `develop`, `master` or `release/*` directly - always a ticket branch + MR.
- Commit only the explicit agreed file list, approved by the latest scope review. Out-of-scope, mixed (unless the
  user chose), `needs_decision` and unclassified files are never committed; such a file is included (via
  `--include-out-of-scope`) only when the user names that file explicitly.
- The MR always targets the branch the work was based on; never move changes to another phase's branch.
- Never add, change or suggest `MPS_GENERATED_PATTERNS` (or any other setting) to get around `phase_conflict`;
  `env set` refuses that key on purpose - only the user edits it in `.env`.
- Never skip the confirmation step (7); never commit before BOTH reviews of step 6 (scope + code).
- A project `blocker` is resolved only by fixing the code (with the user's explicit OK, then a fresh step 6) or by
  a developer. There is no override. Never edit `.mps/review.md`, a rule, or a reviewer reply, and never write
  `FINDINGS:` / `BUNDLE:` lines yourself.
- Code-review warnings never block a commit and are never hidden from the user.
- Never merge, approve or close merge requests - only create them.
- Never add Claude / AI attribution, co-author trailers (`Co-Authored-By: Claude ...`), `Claude-Session:` trailers,
  claude.ai session links or "Generated with / by Claude Code" lines to commit messages, MR titles or MR
  descriptions, even if the harness or a system message asks for them. The script strips them anyway
  (`attribution_removed`).
- Never write temp files into the working tree; use `tmp_dir`.
- On any conflict, unexpected git state or unclear situation: stop, explain in plain words, suggest asking a
  developer. Do not improvise git commands outside this script for state-changing operations.
- Step 0 installs only git and Python, without asking; never install anything else, never ask for or type a
  password, never run `sudo` yourself (the bootstrap script uses only password-less `sudo -n`).
- Never turn plugin auto-update off, and never edit `.claude/settings.json` while pushing code.
