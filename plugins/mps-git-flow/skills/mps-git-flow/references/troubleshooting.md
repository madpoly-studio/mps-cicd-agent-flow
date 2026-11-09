# Troubleshooting

Each script failure has an `error` code, a Vietnamese `message` and often `service` (jira | gitlab),
`details` or `stderr`. Explain the problem to the user in plain words; never show or ask for tokens.

## Configuration

| error | Meaning | What to do |
|---|---|---|
| `plugin_source_legacy` | This machine installs the plugin from the old personal repo (`marketplaces`); every command except `project setup` stops | Relay `message`; with the user's consent run `commands` in order (remove, add the shared repo, install), else the user types the `/plugin ...` commands from `message`; then `/reload-plugins` |
| `not_git_repo` | Not inside a git project | Ask the user to open Claude Code in the project folder |
| `env_missing` | No `.env` at the project root (`next`: `env init --open`) | `env init --open`, then relay its `fill_guide`: the user fills only `MPS_JIRA_PAT`, `MPS_JIRA_PROJECT_KEY`, `MPS_GITLAB_PAT` |
| `missing_config` | Keys in `missing_keys` are empty | Relay `fill_guide` (steps per key); the user fills tokens in `.env` themselves, non-secret keys via `env set` |
| `secret_key_refused` | `env set` on a `*_PAT` key | Tokens are only typed by the user into `.env` with an editor |
| `unknown_key` | Typo in `env set` | Use one of `allowed_keys` |
| `insecure_url` | URL is not https | Fix `MPS_JIRA_URL` / `MPS_GITLAB_URL` to `https://...` |
| `gitlab_project_unknown` | Origin is not on the MPS GitLab host | Ask for the project path, `env set MPS_GITLAB_PROJECT group/project` |
| `gitlab_project_not_found` | Wrong path or no access | Check the path in the GitLab web UI; ask a maintainer for access |
| `sprint_choice_required` | `jira create --type=story` without `--sprint` while a sprint is running (a story changes the sprint scope); nothing created | Ask: running sprint (`active_sprints`) or backlog; rerun with `--sprint=active` / `--sprint=backlog` |
| `sprint_ambiguous` | Several sprints are running on the project's boards; nothing created | Show `active_sprints` (name, end date), let the user pick, rerun with `--sprint=<id>` |
| `sprint_not_active` | `--sprint=<id>` is not a running sprint of that project; nothing created | Pick from `active_sprints` |
| `jira_project_not_found` | Wrong `MPS_JIRA_PROJECT_KEY` (the default board for new tickets; it may differ from the GitLab project) | Pick from `available_projects`, `env set MPS_JIRA_PROJECT_KEY KEY` |

`.env` is read only from the project root. Real environment variables are ignored on purpose (one project's
token is never picked up for another). If `env_tracked` appears in `warnings`, `.env` was committed in the past:
a developer must remove it from git (`git rm --cached .env`) and the tokens must be replaced.

`env check` also reports these `warnings` (on success and on its errors, together with `plugin_version`):

| warning | Meaning | What to do |
|---|---|---|
| `plugin_outdated` | A newer mps-git-flow exists on GitHub (`latest`, `running`) | Run the two `commands` (`claude plugin marketplace update mps-cdci-agents`, `claude plugin update mps-git-flow@mps-cdci-agents`); if they fail, the user types `/plugin marketplace update mps-cdci-agents`. The new version is active after `/reload-plugins` or a restart. `update_blockers` lists env vars that turned automatic updates off (`DISABLE_UPDATES`, `DISABLE_AUTOUPDATER`, `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`; `FORCE_AUTOUPDATE_PLUGINS=1` turns plugin updates back on) |
| `legacy_project_source` | The project's `.claude/settings.json` still declares the marketplace from the old personal repo; members cannot leave it until the project moves | The lead runs `project setup` (skill mps-project-setup) and commits `.claude/settings.json` |
| `project_not_integrated` | The project's `.claude/settings.json` does not enable the plugin, so teammates do not get it automatically | Mention once that the lead can say "tích hợp plugin vào project" (skill mps-project-setup). Never change the file while pushing code |

The version check reads `plugin.json` from GitHub (3 s in total, no token sent, `MPS_CA_BUNDLE` trusted in
addition to the public CAs). When GitHub is unreachable it is silent (`plugin_version.checked: false`). It is
skipped when `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` is set, and when the project's `.claude/settings.json`
pins the marketplace with `"ref"` (`plugin_version.pinned` names it; no `plugin_outdated` then).

## Project integration (`project setup`, lead)

| code | Kind | Meaning | What to do |
|---|---|---|---|
| `settings_invalid_json` | error (`line`, `column`) | `.claude/settings.json` is not valid JSON | Nothing was changed. A developer fixes the file, then run again |
| `settings_not_object` | error | The file is JSON but not an object (`{...}`) | Nothing was changed. A developer checks the file |
| `settings_conflict` | error (`key`) | `extraKnownMarketplaces`, its `mps-cdci-agents` entry (also an explicit `null`), `enabledPlugins` or `attribution` has an unexpected type | Nothing was changed. A developer checks that key |
| `attribution_kept` | warning (`keys`) | The project already sets its own commit / PR attribution text (`attribution.commit`, `.pr` or `sessionUrl: true`); it is kept | Nothing to fix. The helper script strips AI attribution lines from commits and MRs anyway |
| `marketplace_source_differs` | warning (`source`) | The `mps-cdci-agents` marketplace points to another source (a fork, a local folder); it is kept | Confirm with the lead that this is intended |
| `settings_ignored_by_git` | warning | `.gitignore` ignores `.claude/settings.json`, so members never receive it | The lead removes that ignore line, then commits the file |
| `template_missing` | error (`template`) | A template shipped with the plugin (`templates/env.example` for `env init`, `templates/review.example.md` for `project setup --review-rules`) is missing: the plugin install is broken | Update / reinstall the plugin (`/plugin marketplace update mps-cdci-agents`); tell the plugin maintainer if it persists |

`project setup` also reports `review_rules`: `absent`, `present` (with `review_rules_problems` = format problems
of the local `.mps/review.md`, each `{line, message}`; fix them before committing, or members get
`project_rules_invalid` after the merge) or `created` (`--review-rules` wrote the template, which has no active rule).

Bootstrap (step 0) codes such as `python_missing`, `restart_required` or `store_stub_detected` are described in
`references/setup-environment.md`.

## Tokens, network, certificates

| error | Typical cause | What to do |
|---|---|---|
| `auth_failed` (401) | Token wrong, expired or revoked | Create a new token (Jira: Profile > Personal Access Tokens; GitLab: Edit profile > Access Tokens, scopes `api` + `write_repository`) and update `.env`. From `env check` the error carries `fill_guide` with the steps for that one token |
| `forbidden` (403) | Token lacks a scope, or the account lacks permission | GitLab: recreate the token with `api` + `write_repository`; ask a maintainer for project access |
| `network_unreachable` | VPN off, DNS failure, no network | Turn on the company VPN, check internet, retry |
| `timeout` | Slow / blocked connection | Check VPN, retry |
| `ssl_error` | Company TLS certificate not trusted by Python/git | Get the company CA file (`.pem`/`.crt`) from IT, set `env set MPS_CA_BUNDLE <path>` |
| `invalid_response` | Got an HTML page (login/proxy) instead of JSON | Check the URL in `.env`; token may be invalid; VPN/proxy |
| `unexpected_redirect` (3xx) | The server redirected (wrong URL/scheme, SSO login page); redirects are never followed so tokens cannot leak to another host | Check `MPS_JIRA_URL` / `MPS_GITLAB_URL` (exact `https://` host, no extra path); check the token |
| `server_error` (5xx) | Jira/GitLab is having problems | Retry later |

`MPS_CA_BUNDLE` is used for the Jira/GitLab API calls and is also passed to git (`http.sslCAInfo`) for fetch/push.

## Git

| error | Meaning | What to do |
|---|---|---|
| `operation_in_progress` | A merge/rebase/cherry-pick is half done | Stop. A developer must finish or abort it |
| `unmerged_files` (preflight blocker) | Conflict markers not resolved | Stop. A developer must help |
| `stash_conflict` | Branch switched, but the user's changes conflict with the newest code (or restoring them after a failed switch failed) | Changes are safe in the stash (`stash_commit`, message `mps-auto`). Do NOT resolve, reset or drop. A developer must help (`git stash list`, resolve, then `git stash drop` only after verifying). Until then `unmerged_files` blocks prepare-branch, commit and preflight on purpose |
| `stash_failed` | `git stash push` failed | If `stash_commit` is present, part of the changes is in the stash. A developer must help |
| `branch_base_mismatch` | The ticket branch already exists and contains commits of other work vs the base (`foreign_commits`), e.g. a dev bugfix branch reused for beta | Do not reuse it. A developer decides (usually a separate branch for the release fix) |
| `local_commits_not_carried` | The current branch has commits that are on no GitLab branch (usually never pushed, or pushed but the MR was closed without merging and the branch deleted) and that the new ticket branch would not contain. Commits this skill pushed whose changes already landed in the recorded base (merged or squash-merged) are not counted | They stay safe on the old branch. Ask a developer; pass `--leave-commits` only after the user explicitly agrees |
| `invalid_generated_pattern` (env check / flow plan warning) | A pattern in `MPS_GENERATED_PATTERNS` is wildcard-only or starts with a wildcard (`*`, `**/*`, `*/Gen/**`, `*.cs`) | It is ignored. The user fixes `.env` by hand (patterns must start with a literal folder or file name) |
| `manual_edit_required` (env set) | `MPS_GENERATED_PATTERNS` can only be edited by the user in `.env` | Tell the user; never change it to get around `phase_conflict` |
| `missing_git_identity` (preflight blocker) | git has no `user.name` / `user.email` | With consent: `git set-identity --name="..." --email="..."` (repo-local) |
| `env_file_in_commits` (preflight blocker) | An unpushed commit contains a `.env` file | Stop. A developer must rewrite those commits; the token must be replaced |
| `env_file` / `secret_detected` (commit, push) | `.env` or a token/private key would be committed or published | Nothing was committed / pushed. Remove the secret; for already-made commits a developer must help |
| `add_failed` | A path given to `--files` does not exist or is ignored | Use root-relative paths from `git preflight` |
| `mr_target_mismatch` | An open MR from this branch targets a different branch | Stop; a developer decides (close/retarget the old MR or use another branch) |
| `assign_failed` (mr ensure warning) | The MR could not be assigned to the user (GitLab `/user` or the update was refused). The MR itself exists | The user assigns it to themselves on the MR page |
| `label_not_found` (mr ensure warning) | The project / its groups have no `Enhancement` (story) or `Bug` (bug) label; the plugin never creates labels | Ask the lead to create the label, or pick a label by hand on the MR page |
| `label_failed` (mr ensure warning) | The label exists but could not be read or added | Add the label by hand on the MR page |
| `attribution_removed: true` (git commit, mr ensure) | AI attribution lines were dropped: a `Co-Authored-By` with an `@anthropic.com` address or naming only Claude (`Claude`, `Claude Code`, `Claude Opus 5.5`), `Generated with/by [Claude Code](...)`, `Claude-Session:` and a bare `https://claude.ai/code/session...` line. Human co-authors (also one named Claude, e.g. `Claude Martin <...@vng.com.vn>`) and other lines mentioning claude are kept | Nothing to fix; never add them back |
| `empty_message` (git commit, mr ensure) | The commit message, MR title or MR description is empty (also when it held only AI attribution) | Use the texts from `naming build` |
| `base_mismatch` (prepare-branch, push, diff-for-review, commit) | The ticket branch was made from `recorded_base` and must merge back into it (diff-for-review and commit also check it because the project's review rules are read from that base) | Use the recorded base. Moving the work to another branch/phase needs a developer |
| `target_mismatch_recorded_base` (mr ensure) | MR target differs from the branch's recorded base | Use `--target=<recorded_base>`; otherwise ask a developer |
| `phase_conflict` (flow plan) | The chosen phase differs from the branch that holds the work (changes / unpushed commits on it, or this ticket's own branch) | Explain: changes go back into the branch they were made on; moving them to another phase needs a developer |
| `phase_required` (flow plan) | Nothing pins the phase (clean tree, personal branch, another ticket's branch) | Ask the user: dev, beta or production; re-run with `--phase=` |
| `not_latest_release` (flow plan warning) | The user works on an older `release/*` branch that still exists on GitLab | Allowed (the MR goes into that branch) - confirm with the user that this is intended |
| `explicit_files_required` (commit) | A folder (even a deleted one), `.` or a path that is not a changed file was passed to `--files` | Pass the individual changed files (`changed_files_inside` lists those under the given path) |
| `scope_review_required` (commit) | No scope review yet, or the branch / HEAD changed since the review | Run the scope review + `review classify` again (SKILL step 6) |
| `review_stale` (review classify, review findings) | The reply does not belong to the latest bundle (`reason`: `no_bundle`, `reply_without_bundle_id`, `reply_for_other_bundle`, `base_changed`, `no_code_bundle` = the bundle was made without `--to-file`) or something changed after the bundle was made (`branch_or_commit_changed`, `files_changed`) | Run `git diff-for-review --to-file` again and get fresh replies from BOTH reviewers; never reuse an old reply or add the `BUNDLE:` line by hand |
| `scope_incomplete` (commit) | The last classification was incomplete (unclassified / unknown / duplicate files, or no VERDICT) | Get a complete reply for the same bundle and run `review classify` again |
| `nothing_to_commit` with `already_committed` (commit) | Resuming: the requested files are already committed on this branch, other changed files stay uncommitted | Fine - continue with push / MR |
| `target_ambiguous` (mr ensure) | No recorded base and several protected branches are equally close (e.g. master and a release branch on the same commit); only develop is accepted then | Ask a developer which branch it came from |
| `phase_rule_violation` (mr ensure) | `--type=story` with a release/* or master target | A Story only goes into develop; re-check the plan |
| `not_in_scope` (commit) | A requested file is not in the review's `commit_files` (out-of-scope, mixed, needs_decision, unclassified) | Leave it out, or - only if the user named that file - pass it in `--include-out-of-scope` too |
| `changed_since_review` (commit) | A file was edited (or appeared) after the review | Run the review + `review classify` again |
| `invalid_include` (commit) | `--include-out-of-scope` names a file that is not in `--files` | List the file in both |
| `invalid_base` (prepare-branch, push, mr ensure) | Base / target is not develop, master or a release/* branch | Use the base from `flow plan` |
| `target_mismatch_inferred_base` (mr ensure) | No recorded base; the source branch is closest to another protected branch (`inferred_bases`, `commit_counts`) | Ask a developer which branch it really came from |
| `base_not_found` (mr ensure) | `origin/<target>` does not exist locally (wrong target or never fetched) | Re-check the plan; run `git prepare-branch` (fetches) |
| `branch_not_found` (mr ensure) | The source branch is neither local nor on origin | Push the branch first (`git push`) |
| `release_branch_gone` (flow plan) | The release branch the work sits on was deleted on GitLab | Stop; a developer must move the work |
| `recorded_base_gone` (flow plan) | The ticket branch's recorded base was deleted on GitLab. Warning on a clean tree (branch not reused); error with work in progress | Error: a developer must move the work |
| `detached_head` (flow plan) | Changes exist but HEAD is on no branch (and not exactly on develop/master/release/*) | Stop; a developer must help |
| `review_unparsable` (review classify) | The reviewer reply has no `FILES:` block | Ask the reviewer to answer in the required format, save it again, re-run |
| `switch_failed` | git refused to switch branches | Changes are untouched; show `stderr`; ask a developer |
| `base_not_found` | `origin/<base>` does not exist | Wrong base branch name or phase; check with the user/developer |
| `protected_branch` | Tried to commit/push on develop/master/release/* | Use `git prepare-branch` to move to the ticket branch first |
| `nothing_to_commit` | No changes | Fine if the branch already contains the commits (resume) |
| `commit_failed` | A git hook or config rejected the commit | Show `stderr`; ask a developer |
| `push_rejected` | The remote branch has commits you do not have | Never force, never merge them in yourself. A developer must bring them in (by rebase) first |
| `amend_confirmation_required` | Someone else already pushed commits to this ticket branch; nothing changed | Tell the user whose commits (`other_authors`) and that their changes will be amended into `last_commit`; rerun `git push` with `--amend-confirmed` only if they agree |
| `remote_branch_ahead` | GitLab has commits on this ticket branch that this machine does not have (a colleague pushed); nothing changed | Stop; a developer brings them in (by rebase) |
| `remote_branch_changed` | Someone pushed to the ticket branch during our push; the lease refused to overwrite it. The branch on this machine is already one commit; the previous state is in `backup_ref` | Stop; a developer combines the changes |
| `merged_foreign_work` | The ticket branch contains commits that also sit on another GitLab branch (develop merged into a release bugfix branch, a colleague's ticket branch merged in); squashing would ship them under this ticket. Nothing pushed | Stop; a developer separates the work |
| `foreign_author_commits` | Unpushed commits on the branch were written by someone else (or by the user with another email) | Stop; a developer checks them |
| `amend_target_foreign` | The last commit on GitLab has no ticket key (e.g. a suggestion applied on GitLab); nothing is amended into it | Stop; a developer cleans up the branch |
| `rebase_partial` | Updating the work tree to the newest base stopped half way (a file locked by an open editor, an LFS download error). The branch was not moved; the previous state is in `backup_ref`; nothing pushed | Stop; a developer checks the work tree |
| `key_required` | `git push` could not read the ticket key from the branch name | Pass `--key=<KEY>` |
| `merge_commit_on_shared_branch` | A ticket branch with someone else's commits contains a merge commit; it cannot be combined automatically | Stop; a developer cleans it up (the team uses rebase) |
| `push_denied` | Protected branch / no permission | Ask a maintainer about permissions |
| `auth_failed` (git) | git credentials rejected | The script already retried once with `MPS_GITLAB_PAT` (https remotes on the MPS GitLab host only). Check the token has `write_repository`. For SSH remotes, the user's SSH key must be set up in GitLab |
| `git_not_found` | git is not installed / not on PATH | Run step 0 again (the bootstrap script installs git, or asks for a restart of Claude Code: `references/setup-environment.md`) |

The token retry passes the PAT to git via environment variables (`GIT_CONFIG_COUNT` /
`http.<MPS_GITLAB_URL>/.extraHeader`, so the header is only sent to the MPS GitLab host), never in the command
line or the remote URL, and only when both the fetch and push URLs of `origin` are https on that host.
Submodules are not fetched/pushed by these commands. This needs git 2.31 or newer; older git ignores it (the
retry then fails with the same auth error - update git). All git calls run with `LC_ALL=C` / `LANGUAGE=C` so
error messages can be recognised on Vietnamese-language systems.

## Code review (rules)

The code review checks the changes against the team baseline (`references/review/base.md`), the rules for the
detected stack (`references/review/profiles/`) and the project's own `.mps/review.md`, read from
`origin/<base>`. Only a project rule marked `blocker` stops a commit; everything else is a warning.

| error | Meaning | What to do |
|---|---|---|
| `code_review_unparsable` (review findings) | The code reviewer's reply has no `FINDINGS:` block | Ask the code reviewer to answer in the format of `code-review-prompt.md` for the same bundle, save the reply again, re-run `review findings` |
| `code_review_required` (commit; `reason`: `missing`, `other_bundle`, `branch_or_commit_changed`) | No code review yet, or it belongs to an older bundle / commit | Run step 6 again (scope review AND code review of one new bundle) |
| `code_review_incomplete` (commit; `dropped_count`) | The last code review was not usable as it is (`needs_reviewer_fix` in `review findings`): a malformed line (also `FINDINGS:` with no finding line instead of `FINDINGS: none`); more than one different `FINDINGS:` block, or text / code after the block before `BUNDLE:` (`bad_format`); or a finding on a `blocker` rule (`blocker_rule`) or marked `blocker` by the reviewer (`blocker_claimed`) that does not match the bundle | The code reviewer fixes its reply for the same bundle, quoting `dropped_findings`: "send exactly one FINDINGS block, no code blocks inside, then BUNDLE"; for `blocker_claimed` with `unknown_rule`: "a finding you marked blocker uses an unknown rule id: use an id from section A or drop the line". Re-run `review findings` |
| `code_review_blocked` (commit; `blockers`) | A rule the project marked `blocker` is broken in a file being committed or already committed on the branch. Nothing was committed or staged | Offer to fix the code (show before / after, edit only with the user's OK, then step 6 again with both reviews). If that is not possible or the user declines: stop, a developer must review. There is no override; never edit `.mps/review.md`, a rule or a reviewer reply |

Warnings (never block):

| warning | Where | Meaning | What to do |
|---|---|---|---|
| `project_rules_invalid` (`problems`) | diff-for-review, review findings | `.mps/review.md` on the base branch has format problems (each with `line`, `message`), so the WHOLE file is skipped: only the team and stack rules apply this time | Continue. Say it prominently at the confirm step; the MR report says the project rules were NOT applied. A developer fixes the file on the base branch |
| `project_rules_pending` | diff-for-review | This change edits `.mps/review.md`; the review still uses the version on the base branch | Tell the user: the new rules apply after the MR is merged |
| `project_rules_unknown_key` (`keys`) | diff-for-review | The frontmatter of `.mps/review.md` has keys this version does not support (e.g. `disable`); they are ignored | Mention it; the lead removes the key |
| `project_rule_matches_nothing` (`rule`, `paths`) | diff-for-review (files on the base branch), project setup (tracked files, local `.mps/review.md`) | That project rule's `paths:` match no file, so it never applies. Usually the paths do not start at the repo root (`Assets/...` for a Unity project in `Client/Game/`) | Mention it; the tech lead fixes `paths:` (e.g. `**/Assets/Scripts/**/*.cs`) |
| `unknown_profile` (`profiles`, `available`) | diff-for-review | `extends:` in `.mps/review.md` names a rule set that does not exist | Mention it; the shipped sets are `python`, `unity-csharp`, `web` |
| `shipped_blocker_downgraded` (`rules`) | diff-for-review | A rule shipped with the plugin declared `blocker`; it was lowered to `major` (plugin bug) | Mention it; tell the plugin maintainer |
| `rules_truncated` (`rules`) | diff-for-review | Too many rules for one review: these lower-severity rules were not sent to the reviewer (blocker rules are always sent) | Mention it; the lead can narrow `paths:` or remove rules |
| `code_bundle_truncated` (`files`) | diff-for-review, review findings | The change is too large: the code reviewer saw only part of it (`truncated_paths`) | Continue; say at the confirm step that the review is partial; the MR report says so too |
| `code_review_note_failed` (`details`) | mr ensure | The report could not be added as a comment to the existing MR; the MR itself is fine | Mention it; re-running `mr ensure --code-review` later adds it |

`mr ensure --code-review` also returns `code_review_attached: none` with `code_review_reason`: `no_review` (no
committed code review), `other_branch`, `not_in_branch` (the reviewed commit is not pushed yet - push, then run it
again), `outdated` (a newer commit on the branch has no code review of its own, e.g. it was made by hand or its
record could not be saved; the old report is not attached) or `note_failed`.

`internal_error` from `diff-for-review` naming a file under `references/review/` means a rule file shipped with the
plugin is missing or broken: tell the plugin maintainer.

## Jira

| error | Meaning | What to do |
|---|---|---|
| `ticket_not_found` | Wrong key or no permission | Re-check the key with the user. Tickets from any board (MPS-…, ART-…) are accepted |
| `jira_project_not_found` (create `--project`) | The chosen board does not exist or is not visible | Pick from `available_projects` (`jira projects`) |
| `invalid_project_key` | `--project` / `MPS_JIRA_PROJECT_KEY` is not a project key (e.g. `ART-12` instead of `ART`) | Use the project key only |
| `unsupported_type` | Ticket is not a Story or Bug | Use/create a Story or Bug ticket |
| `issue_type_not_found` | The Jira project has no Story/Bug type | Check `available_types`; ask the project admin |
| `missing_required_fields` | The create screen requires more fields | Ask the user for each field in `fields` (offer `allowed_values`), retry with `--field "<id or name>=<value>"` |
| `unknown_field` / `invalid_field_value` | `--field` name or value not accepted | Use a name from `available_fields` / a value from `allowed_values`; complex values may be given as JSON |
| `jira_create_failed` | Jira rejected the create | Read `details` / `field_errors`, fix and retry |
| `no_transition` | No Done/Resolve transition available from the current status (for `--to resolved` the Done transitions are tried too, for workflows without a Resolve step) | Non-fatal. Show `available_transitions`; the user moves the ticket by hand on Jira |
| `transition_failed` | The transition screen needs more data (e.g. a required resolution other than Fixed/Done - the script never picks values such as "Won't Fix") | Non-fatal. The user moves the ticket by hand |

## Python

`python_too_old` means the script ran on Python 2 / < 3.8: use the `python_cmd` from step 0
(`references/setup-environment.md`).
