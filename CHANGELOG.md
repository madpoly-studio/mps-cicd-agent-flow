# Nhật ký thay đổi

Mỗi lần merge vào `main` phải tăng phiên bản (`VERSION` trong `mps.py` và `version` trong `plugin.json`, cùng một
giá trị) và thêm một mục ở đây, cùng một mục ngắn cho người dùng trong `plugins/mps-git-flow/RELEASE_NOTES.md`.
Mục mới nhất ở trên cùng.

## 0.3.1 - 2026-11-11
- Nâng ngưỡng chặn file lớn khi commit (`large_file` trong `git preflight`) từ 5MB lên 100MB
  (`LARGE_FILE_BLOCK_BYTES`), vì GitLab của team không giới hạn kích thước file. File trong Git LFS vẫn không bị
  chặn. Giới hạn đọc file cho review code / quét bí mật (`MAX_FILE_BYTES`) vẫn là 5MB: file lớn hơn chỉ được
  review ở mức file.

## 0.3.0 - 2026-11-09
- Quy tắc mới: mỗi merge request chỉ có một commit, dùng rebase thay cho merge commit. `git push` gộp mọi commit
  của nhánh ticket (kể cả commit "Merge remote-tracking branch ...") thành một commit theo `--message` (mặc định:
  message của commit mới nhất), rebase lên `origin/<base>` mới nhất (bỏ qua, không ép, khi xung đột / đụng file
  đang sửa / git cũ: `rebase_skipped`), rồi đẩy lên; nhánh đã đẩy trước đó được ghi đè bằng `--force-with-lease`
  chỉ trên nhánh ticket. Nhánh `develop` / `master` / `release/*` không bao giờ bị ghi đè.
- Nhánh ticket đã có commit của người khác: hỏi trước (`amend_confirmation_required`), đồng ý thì gộp (amend) vào
  commit cuối trên GitLab (giữ tác giả và message) với `--amend-confirmed`.
- Không bao giờ ghi đè commit của người khác: `remote_branch_ahead` (sau khi fetch), `remote_branch_changed`
  (lease từ chối), `merge_commit_on_shared_branch`, `amend_target_foreign` (commit cuối không có mã ticket). Trạng
  thái cũ luôn được lưu ở `refs/mps-backup/...` (giữ 5 bản mới nhất mỗi nhánh).
- Không bao giờ gộp lẫn code của nhánh khác: `merged_foreign_work` (commit cũng có trên nhánh GitLab khác, ví dụ
  merge develop vào nhánh bugfix của release), `foreign_author_commits` (commit chưa đẩy của người khác).
- Rebase không bao giờ đụng file của người dùng: bỏ qua khi có file chưa track / bị ignore trùng đường dẫn
  (`local_files`) hoặc có thay đổi đã stage (`staged_changes`); cập nhật dở dang thì dừng, không đẩy
  (`rebase_partial`). Push lỗi sau khi đã gộp (mạng, token) chạy lại được (`resumed`). `git push` nhận `--key`
  (mặc định lấy từ tên nhánh).
- `.env` / bí mật được kiểm tra trên nội dung thực sự được đẩy lên (sau khi gộp). Commit gộp không còn dòng ghi công
  AI. Kết quả review code đi theo commit mới (`outdated` khi commit đã review bị gộp chung với commit chưa review).

## 0.2.4 - 2026-11-09
- `plugins/mps-git-flow/RELEASE_NOTES.md` mới: "có gì mới" theo từng phiên bản, viết cho người dùng (có cả các bản
  trước).
- Hook `SessionStart` mới `hooks/whats-new.sh`: lần mở Claude Code đầu tiên sau khi plugin lên phiên bản mới, hiện
  mục của các phiên bản chưa xem (tối đa 5; máy chưa có trạng thái thì chỉ bản đang cài), một lần cho mỗi phiên
  bản. Đọc file đi kèm plugin, không cần mạng; trạng thái ở `~/.claude/mps-git-flow/last_seen_version`
  (hoặc `CLAUDE_CONFIG_DIR`).

## 0.2.3 - 2026-11-08
- `jira create`: Bug mới được tự đưa vào sprint đang chạy của board; Story mới phải chọn `--sprint=active` hoặc
  `--sprint=backlog` (lỗi `sprint_choice_required`, chưa tạo gì) vì thêm vào sprint làm thay đổi phạm vi sprint.
  Nhiều sprint chạy cùng lúc: `sprint_ambiguous`, chọn bằng `--sprint=<id>`. Không có sprint đang chạy (hoặc Jira
  không có Jira Software): ticket nằm ở backlog, kèm ghi chú. Chỉ tính sprint của chính các board Scrum của
  project (sprint của board team khác đang chứa ticket của project bị bỏ qua). Chuyển vào sprint thất bại (bị từ
  chối hoặc lỗi kết nối): ticket vẫn được tạo và trả về `key`, báo `sprint_failed` để không bao giờ tạo trùng.
  Kết quả có `placement` (`sprint` / `backlog`) và `sprint`.
- Lệnh mới `jira sprints [--project=KEY]`: liệt kê sprint đang chạy để hỏi người dùng trước khi tạo Story.

## 0.2.2 - 2026-11-07
- Máy còn cài plugin từ repo cá nhân cũ (`hung-bui-121/mps-cdci-agents`, nhận ra qua `known_marketplaces.json`
  của Claude Code) bị chặn: mọi lệnh `mps.py` trừ `project setup` trả lỗi `plugin_source_legacy`, kèm lời nhắc
  thân thiện và các lệnh `claude plugin ...` để gỡ bản cũ, thêm repo dùng chung và cài lại.
- Hook `SessionStart` mới (`hooks/hooks.json`) hiện lời nhắc đó ngay khi mở Claude Code.
- Project mà `.claude/settings.json` vẫn khai báo repo cũ: member không bị chặn, `env check` báo
  `legacy_project_source` để nhắc lead chạy `project setup`.
- `project setup` chuyển mọi dạng nguồn trỏ repo cũ (github, URL git https / ssh) sang repo mới, và báo
  `machine_source_legacy` khi máy của lead còn cài từ repo cũ (phải gỡ trước khi commit file settings).

## 0.2.1 - 2026-11-07
- Chuyển plugin sang repo của tổ chức `madpoly-studio/mps-cicd-agent-flow` (trước đây `hung-bui-121/mps-cdci-agents`).
  Tên marketplace `mps-cdci-agents` và plugin `mps-git-flow@mps-cdci-agents` giữ nguyên.
- Kiểm tra phiên bản mới đọc `plugin.json` từ repo mới.
- `project setup`: marketplace còn trỏ tới repo cũ được tự đổi sang repo mới, giữ nguyên `ref` (thay đổi
  `marketplace_source_migrated`, không còn cảnh báo `marketplace_source_differs`).

## 0.2.0 - 2026-11-06
- Review code theo quy tắc, chạy song song với review phạm vi trên cùng một bundle (cùng `Bundle-ID`): quy tắc
  chung của team, quy tắc theo công nghệ tự nhận ra (`unity-csharp`, `python`, `web`, tính từ thư mục của từng
  project) và quy tắc riêng của dự án trong `.mps/review.md`, luôn đọc từ nhánh gốc trên GitLab (sửa file chỉ có
  hiệu lực sau khi merge, báo `project_rules_pending`).
- Mọi nhận xét mặc định chỉ là cảnh báo; chỉ quy tắc `blocker` do chính dự án khai báo mới chặn commit
  (`code_review_blocked`, chưa đụng tới index). Trợ lý có thể đề nghị sửa code (chỉ sửa khi người dùng đồng ý, rồi
  review lại cả hai); nếu không, người dùng nhờ developer. Không có cách bỏ qua `blocker`.
- `git diff-for-review --to-file` ghi thêm bundle review code (`mps-code-review.md`: quy tắc, danh sách file, thay
  đổi có đánh số dòng tính từ merge base). Lệnh mới `review findings` kiểm tra khối `FINDINGS:` của reviewer với
  đúng những gì reviewer được xem; `git commit` cần review code đầy đủ của cùng bundle (`code_review_required`,
  `code_review_incomplete`). Thay đổi chỉ gồm file được bỏ qua (ví dụ prefab, scene) không cần reviewer.
- File `.mps/review.md` sai định dạng: bỏ qua cả file, chỉ dùng quy tắc chung, cảnh báo `project_rules_invalid`
  ở bước xác nhận và ghi rõ trong merge request. Bundle quá lớn chỉ là cảnh báo (`code_bundle_truncated`).
- `mr ensure --code-review`: merge request mới có phần "Kết quả review code tự động" trong mô tả (thêm sau khi đã
  gỡ dòng ghi công AI); merge request đã có nhận một ghi chú cho mỗi lần review (`code_review_note_failed` chỉ là
  cảnh báo). Mã quy tắc không bao giờ giống mã ticket Jira; mã Jira, `@tên` và `#số` trong nhận xét được đặt trong
  khối code để GitLab không tự liên kết hay gửi thông báo.
- `project setup` báo `review_rules` (`absent` / `present`, kèm `review_rules_problems` của bản trên máy);
  `project setup --review-rules` tạo `.mps/review.md` từ mẫu (không ghi đè). Skill `mps-project-setup` đề nghị
  tạo file này cho lead.
- Một vi phạm `blocker` không bao giờ bị bỏ qua âm thầm: khối `FINDINGS:` đặt trong khối code, đánh số hoặc in đậm
  mã quy tắc vẫn được đọc; `FINDINGS:` không có dòng nào, hoặc một nhận xét reviewer ghi `blocker` mà không khớp
  bundle, buộc reviewer trả lời lại (`needs_reviewer_fix`). Câu trả lời có nhiều khối `FINDINGS:` khác nhau, hoặc
  có chữ / code nằm sau khối trước dòng `BUNDLE:`, cũng bị trả lại cho reviewer (không bao giờ bị đọc thiếu).
- Quy tắc của dự án ghi rõ `paths:` được áp dụng cả trên file mà bộ quy tắc có sẵn bỏ qua (ví dụ
  `paths: **/*.prefab`); quy tắc không có `paths:` thì không làm các file đó được review. Cảnh báo
  `project_rule_matches_nothing` khi `paths:` của một quy tắc dự án không khớp file nào trên nhánh gốc hoặc trong
  thay đổi (đường dẫn tính từ gốc repo; file bị `ignore` của chính dự án không tính).
- `diff-for-review` và `git commit` kiểm tra nhánh gốc đã ghi nhận (`base_mismatch`), vì quy tắc dự án được đọc
  từ nhánh đó. `mr ensure --code-review` chỉ gắn kết quả review của commit mới nhất trên nhánh (`outdated`); một
  commit thất bại (ví dụ bị hook từ chối) không làm mất kết quả review của commit trước.
- README: phần "Quy tắc review code theo dự án" cho tech lead.

## 0.1.1 - 2026-11-06
- Tự cài Git/Python còn thiếu khi bắt đầu (không hỏi trước, có báo một dòng). Mọi lần cài dùng chung một giới hạn
  thời gian (~500 giây); trình cài còn chạy quá giờ được báo `install_still_running` thay vì bắt tải tay. Chỉ yêu
  cầu khởi động lại Claude Code khi việc đó thật sự có tác dụng; ngược lại báo `git_not_on_path` hoặc
  `git_too_old`. Mục PATH trỏ tới ổ đĩa không tồn tại không còn làm script lỗi.
- Lệnh project setup + skill mps-project-setup để lead tích hợp plugin vào project (tự cập nhật mặc định); giữ
  nguyên kiểu thụt lề và xuống dòng của file, ghi file an toàn (atomic).
- env check báo khi có phiên bản plugin mới (plugin_outdated), trừ khi project ghim phiên bản bằng `ref`; báo khi
  project chưa tích hợp plugin (project_not_integrated). Việc kiểm tra phiên bản không bao giờ làm chậm quá 3 giây.
- File .env mới chỉ cần điền 3 dòng (MPS_JIRA_PAT, MPS_JIRA_PROJECT_KEY, MPS_GITLAB_PAT); trợ lý hướng dẫn từng
  bước (fill_guide), kể cả khi token bị từ chối (sai/hết hạn). Lỗi env_missing kèm `next: "env init --open"`.
- Commit và merge request không bao giờ có dòng ghi công AI: script tự gỡ đúng các dạng do AI thêm
  (`Co-Authored-By` có địa chỉ @anthropic.com hoặc chỉ ghi Claude / Claude Code / Claude <model>, "Generated
  with/by Claude Code", `Claude-Session:`, link phiên claude.ai), giữ nguyên đồng tác giả là người thật (kể cả
  người tên Claude) và mọi dòng khác; báo `attribution_removed`.
  `project setup` cũng thêm `"attribution": {"commit": "", "pr": "", "sessionUrl": false}` (không ghi đè giá trị
  project đã đặt).
- Merge request được giao cho chính người chạy (MR có sẵn người được giao thì giữ nguyên) và gắn nhãn
  `Enhancement` (story) / `Bug` (bug, hotfix) nếu nhãn đã có trên GitLab; không tự tạo nhãn. Lỗi giao / gắn nhãn
  chỉ là cảnh báo (`assign_failed`, `label_not_found`, `label_failed`), MR vẫn được tạo. Nhãn được tìm qua mọi
  trang kết quả (kể cả nhãn của group). MR xuất hiện trong lúc tạo (GitLab trả 409 hoặc 422) được dùng tiếp.
- Trình cài còn chạy quá giờ không còn giữ luồng xuất (stdout) của trợ lý: trên Windows winget được chạy tách
  hẳn qua cmd.exe (không kế thừa handle), trên macOS / Linux tiến trình con không giữ stdout; dòng JSON trả về
  ngay.

## 0.1.0
- Phiên bản đầu tiên.
