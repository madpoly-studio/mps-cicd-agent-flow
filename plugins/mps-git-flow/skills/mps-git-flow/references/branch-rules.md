# MPS branch rules

These rules are enforced by `mps.py flow plan` and `mps.py naming build`. Branch names come from `.env`
(`MPS_BRANCH_DEV`, `MPS_BRANCH_BETA_PREFIX`, `MPS_BRANCH_PROD`); defaults shown below.

## Phases

| Phase | When | Allowed ticket types | Kind | Branch from (base) | MR target |
|---|---|---|---|---|---|
| dev | normal development | Story, Bug | Story -> `feature`, Bug -> `bugfix` | `develop` | `develop` |
| beta | testing a release | Bug only | `bugfix` | the `release/*` being worked on (latest if not on one) | the same `release/*` |
| production | urgent fix on live | Bug only | `hotfix` | `master` | `master` |

**Golden rule: work based on branch X merges back into X.** The MR target is always the base branch.

## Detecting the phase from the current branch

`flow plan --key=<KEY>` first runs a pruned fetch, then looks at the branch the user is on:

| Current branch | Role | Phase | Base = MR target |
|---|---|---|---|
| `develop` | `dev` | dev | `develop` |
| any `release/*` (e.g. `release/1.1`, even if `release/1.2` exists) | `beta` | beta | that release branch; warning `not_latest_release` if it is not the newest, error `release_branch_gone` if GitLab no longer has it |
| `master` | `production` | production (hotfix warning) | `master` |
| this ticket's own `feature/` / `bugfix/` / `hotfix/` branch (created by this skill) | `ticket` | phase of its recorded base | the recorded base |
| detached HEAD exactly on one of develop / master / release/* | that role (`detached: true`) | as above | that branch |
| another ticket's branch, a branch whose recorded base is gone, a personal branch | `other` | ask the user | per the phase table |
| detached HEAD anywhere else | `detached` | ask the user (error `detached_head` if there are changes) | per the phase table |

The detected phase is binding ("pinned") only when work sits on the current branch - uncommitted changes or
commits not on any origin branch - or when it is the current ticket's own branch. Changes to files that tools
rewrite on their own do not count as work:
- Unity defaults, only inside a Unity project root (the repo root or a sub-folder that contains
  `ProjectSettings/ProjectVersion.txt`, tracked or present on disk): `ProjectSettings/**`, `UserSettings/**`,
  `Library/**`, `Packages/packages-lock.json`, and `*.csproj` / `*.sln` directly in that root. Patterns are
  anchored to the root, so `Assets/Plugins/Library/Core.cs` is real work. Without any Unity project root the
  defaults are not used at all (in a non-Unity repo `*.sln` / `*.csproj` are real work).
- The comma-separated globs in `MPS_GENERATED_PATTERNS` (`**` = any path, `*` = within one folder), anchored to
  the repo root and to every Unity project root. Each must start with a literal folder or file name
  (`Assets/Gen/**`, `yarn.lock`); wildcard-only or wildcard-first ones (`*`, `**/*`, `*/Gen/**`, `*.cs`) are
  ignored and reported as `invalid_generated_pattern` (`env check`, `flow plan`). Only the user edits this key by
  hand in `.env`; `env set` refuses it.

`flow plan` lists such files as `generated_changes`. This only affects choosing the phase: those files still go
through the scope review and are committed only if in scope or named by the user, and `prepare-branch` carries
them along with the other changes as usual. Then a different `--phase`
fails with `phase_conflict`: changes made on one phase's branch are never moved to another phase silently (a
developer must do that). On a clean tree nothing has been done on the current branch yet, so the user's chosen
phase is used (`phase_source: "requested_clean_tree"`); without a choice `flow plan` returns `phase_required`.

`git prepare-branch` records the base of every ticket branch in the repo-local git config
(`branch.<name>.mps-base`). Later `prepare-branch` / `push` with a different base fail with `base_mismatch`, and
`mr ensure` refuses a target other than the recorded base (`target_mismatch_recorded_base`). Without a recorded
base (branch made by hand or on another machine) the target must be the protected branch the source is closest
to - fewest commits in `origin/X..source` among develop, master and the existing release branches - else
`target_mismatch_inferred_base`; if several are equally close (a tie), only develop is accepted
(`target_ambiguous`). `mr ensure` also checks that every non-merge commit in `origin/<target>..<source>`
mentions the ticket key (`branch_base_mismatch`), using the pushed branch when there is one, and re-applies the
phase rules to the target with `--type` (a Story never goes into release/* or master). Bases and targets must
always be develop, master or a release/* branch (`invalid_base`).

`git push` also records the pushed commit (`branch.<name>.mps-pushed`). When GitLab squash-merges and deletes
the ticket branch, `fetch --prune` removes `origin/<name>` and its commits are on no remote branch any more; the
record keeps them from being counted as unpushed work (`local_commits_not_carried`, phase pinning) - but only
when their changes really are in `origin/<recorded base>` (equivalent patches per `git cherry`, or, after a
squash, identical content for every path the branch changed). If the MR was closed without merging, the commits
count again and are never left behind silently.

- Only two Jira issue types exist in this team: **Story** and **Bug**. Anything else is rejected
  (`unsupported_type`).
- **beta**: a Story is rejected (`phase_rule_violation`) - new features always go through dev. The "latest"
  release branch is chosen by version number (`release/1.10.0` > `release/1.9.2`); if any release branch name
  has no digits, the newest commit date decides instead. **No back-merge MR into develop is created**: the team
  back-merges the release branch into develop once at the end of the beta phase.
- **production (hotfix)**: not forbidden, but risky. The plan always carries a `warning` and
  `requires_explicit_confirmation: true`. Recommendation: a developer should do hotfixes; members should not.
  Proceed only after the user explicitly confirms they understand the risk. If the user's GitLab access level is
  below Maintainer (40) - Developer is 30 - the warning is stronger: they very likely cannot merge into master.

## Naming

| Kind (naming type) | Branch | Commit message | MR title | MR description |
|---|---|---|---|---|
| story | `feature/{KEY}-{slug}` | `feat: {KEY} {Title}` | `{KEY} {Title}` | `Close {KEY}` |
| bug | `bugfix/{KEY}-{slug}` | `fix: {KEY} {Title}` | `{KEY} {Title}` | `Close {KEY}` |
| hotfix | `hotfix/{KEY}-{slug}` | `fix: {KEY} {Title}` | `{KEY} {Title}` | `Close {KEY}` |

- `{KEY}` is the ticket key from ANY Jira project on the instance (e.g. `MPS-123`, or `ART-12` from the artist
  board). It does not have to match the GitLab project or `MPS_JIRA_PROJECT_KEY` (that key is only the default
  board for new tickets; `jira create --project=KEY` creates a one-off ticket on another board).
- `{Title}` = the Jira summary as written (whitespace collapsed). `{KEY}` stays upper case.
- MR title = commit message without the leading `feat: ` / `fix: `.
- MR description is exactly `Close {KEY}` (GitLab's Jira integration links / closes the ticket from it; this works
  for any project on the same Jira instance, and the skill's Jira follow-up step covers anything it misses).
- `{slug}`: Vietnamese letters folded to ASCII (accents removed, `đ`/`Đ` -> `d`), lower case, every run of other
  characters -> `-`, no leading/trailing dashes, at most 50 characters, cut at a dash so words are not split.
- The commit message is used exactly as built - nothing is appended.

## Examples

| Ticket | Phase | Branch | Commit message |
|---|---|---|---|
| Story MPS-123 "Thêm màn hình Đăng nhập bằng Google" | dev | `feature/MPS-123-them-man-hinh-dang-nhap-bang-google` | `feat: MPS-123 Thêm màn hình Đăng nhập bằng Google` |
| Bug MPS-7 "Sửa lỗi đăng nhập Đặc biệt!" | dev | `bugfix/MPS-7-sua-loi-dang-nhap-dac-biet` | `fix: MPS-7 Sửa lỗi đăng nhập Đặc biệt!` |
| Bug MPS-88 "Lỗi hiển thị giá" | beta (on `release/2.3.0`) | `bugfix/MPS-88-loi-hien-thi-gia` from and into `release/2.3.0` | `fix: MPS-88 Lỗi hiển thị giá` |
| Bug MPS-90 "Lỗi thanh toán" | production | `hotfix/MPS-90-loi-thanh-toan` from and into `master` | `fix: MPS-90 Lỗi thanh toán` |
| Story ART-12 "Vẽ lại icon nhân vật" (artist board) | dev | `feature/ART-12-ve-lai-icon-nhan-vat` | `feat: ART-12 Vẽ lại icon nhân vật` |

For MPS-123 the MR title is `MPS-123 Thêm màn hình Đăng nhập bằng Google` and the description `Close MPS-123`.

## Same ticket in two phases

A dev bugfix and a beta bugfix for the same ticket get the same branch name (`bugfix/{KEY}-{slug}`). An existing
branch is only reused when every commit it has on top of the base mentions the ticket key; otherwise
`git prepare-branch` stops with `branch_base_mismatch` (reusing a develop-based branch for a release MR would
ship unreleased develop work); if the branch has a recorded base that differs, it stops earlier with
`base_mismatch`. A developer then decides how to name the release-fix branch. Likewise `mr ensure` refuses
(`mr_target_mismatch`) when the branch already has an open MR into a different target.

## Commit only what belongs to the ticket

`git commit` takes only an explicit list of exact changed file paths (`--files a b c`); folders (also deleted
ones), `.`, unknown paths and an "everything" mode are refused (`explicit_files_required`). The list must be
approved by the latest scope review (`review classify` saves it in `.git/mps-tmp/scope.json` with a fingerprint
of every file): in-scope files (plus concern files on a PASS verdict) are committed; out-of-scope files - e.g.
Unity-regenerated `ProjectSettings/*.asset` / `.meta`, lock files, someone else's edits, IDE files - stay modified
on the user's machine and are reported as `left_uncommitted`. A file outside the approved list is committed only
when the user named it (`--include-out-of-scope`). Editing a file after the review (`changed_since_review`) or
committing in between (`scope_review_required`) requires a new review; each review approves one commit. The
review is bound to the bundle the reviewer read: `git diff-for-review` stamps a `Bundle-ID` and fingerprints
every file, the reply must quote it (`BUNDLE: <id>`), and `review classify` rejects replies for older bundles or
for files changed since (`review_stale`). Incomplete classifications approve nothing (`scope_incomplete`).

## One commit per merge request (rebase, no merge commits)

A ticket branch may collect several commits while the work goes on, but `git push` always publishes it as ONE
commit on top of the base, so every MR contains exactly one commit named by the naming rule:

- **Only the user's own commits on the branch** (judged by author email, against the commits already on
  `origin/<branch>`): every commit since the merge base - earlier pushed ones and "Merge remote-tracking branch
  ..." commits included - is squashed into one commit with `--message` (default: the newest commit on the
  branch's own first-parent line), then rebased onto the newest `origin/<base>` (`git merge-tree`, git 2.40+;
  the work tree is updated with `reset --keep`). The rebase is skipped, never forced, on a conflict
  (`rebase_skipped: conflict`), when it would touch a file with local changes (`local_changes`), overwrite an
  untracked or ignored file (`local_files`) or un-stage the index (`staged_changes`), or on an older git
  (`git_too_old`); the branch is still one commit. If the work tree update stops half way (a locked file, an LFS
  download error) nothing is pushed (`rebase_partial`). An already pushed branch is replaced with
  `--force-with-lease=<branch>:<the commit we fetched>`.
- **Never squashed in:** commits that also sit on another GitLab branch - develop merged into a release bugfix
  branch, a colleague's ticket branch merged in (`merged_foreign_work`) - and unpushed commits written by someone
  else (`foreign_author_commits`). Both stop before anything changes; a developer separates the work.
- **Someone else already pushed commits to the ticket branch**: their history stays; after the user agrees
  (`amend_confirmation_required` -> `--amend-confirmed`) the user's new commits are folded into the last pushed
  commit (an amend: its author and message are kept) and pushed with the same lease. A last commit without the
  ticket key (e.g. a suggestion applied on GitLab) is never amended into (`amend_target_foreign`).
- A push that fails after the branch was combined (network, token) is resumed by running it again: the rewrite
  is remembered in `branch.<name>.mps-rewrite` until the push succeeds. Backups beyond the newest 5 per branch
  are deleted after a successful push.
- Never overwritten: commits on GitLab that this machine does not have (`remote_branch_ahead`, checked after a
  fetch) or that arrive during the push (`remote_branch_changed`, the lease). Protected branches are never
  force pushed (`git push` refuses them before anything else).
- Before the branch moves, its previous commit is kept under `refs/mps-backup/<branch>/<time>-<sha>`.
- `.env` files and secrets are checked in what is actually published (after the squash), so a file added in one
  commit and removed in a later one is not published at all.
- The code-review record of the old tip follows the new commit; a review of an older commit that got folded in
  together with unreviewed commits counts as `outdated`.
- GitLab itself still adds one merge commit per MR when the MR is merged (project setting "Merge method"); that
  is accepted. Merging the base INTO a ticket branch is not: the push rebases instead.

## Protected branches

`develop`, `master` and every `release/*` branch are never committed to or pushed to directly by this skill:
`git commit` and `git push` refuse them, and `git preflight` blocks when local commits sit on one of them
unpushed (a developer must move those commits to a ticket branch).
