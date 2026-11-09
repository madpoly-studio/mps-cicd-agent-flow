# mps-cicd-agent-flow

Bộ plugin Claude Code cho team MPS. Hiện có một plugin:

**mps-git-flow** - giúp bạn đưa code lên GitLab MPS (https://git-gst.mto.zing.vn) đúng quy trình ticket
Jira (https://jira-mps.mto.zing.vn), kể cả khi bạn không phải developer. Bạn chỉ cần nói với Claude kiểu
"đẩy code giúp mình", Claude sẽ:

1. Kiểm tra cấu hình và token (Jira, GitLab).
2. Hỏi mã ticket Jira - ở **board nào cũng được** (ví dụ `MPS-123`, hoặc `ART-12` của board team artist) - hoặc
   giúp bạn tạo ticket mới (Story hoặc Bug) giao cho chính bạn, trên board mặc định hoặc board khác bạn chọn.
   Bug mới được tự đưa vào sprint đang chạy; Story mới thì Claude hỏi bạn đưa vào sprint đang chạy hay để ở
   backlog (vì thêm vào sprint làm thay đổi phạm vi sprint). Không có sprint nào đang chạy thì ticket nằm ở backlog.
3. Nhận biết giai đoạn từ nhánh bạn đang làm (**dev** = `develop`, **beta** = `release/*`, **production** =
   `master`) và áp dụng đúng luật nhánh: **làm từ nhánh nào thì merge về đúng nhánh đó**.
4. Đặt tên nhánh, nội dung commit, tiêu đề merge request (MR) theo chuẩn.
5. Kiểm tra an toàn: không cho commit file `.env`, token, khoá bí mật, file quá lớn.
6. Nhờ một trợ lý review xem các thay đổi có đúng phạm vi ticket không. **Chỉ những file thật sự làm cho ticket
   mới được commit**; file ngoài phạm vi (ví dụ Unity tự sửa `ProjectSettings`/`.meta`, file lock, thay đổi của
   người khác) được giữ nguyên trên máy, không commit - để không ảnh hưởng người khác.
7. Cùng lúc, một trợ lý khác **review code theo quy tắc**: quy tắc chung của team, quy tắc theo công nghệ (Unity
   C#, Python, web) và quy tắc riêng của dự án trong `.mps/review.md`. Mọi nhận xét chỉ là cảnh báo (ghi vào merge
   request); chỉ quy tắc mà chính dự án đánh dấu `blocker` mới chặn commit cho tới khi code được sửa.
8. Tóm tắt mọi thứ (danh sách "Sẽ commit" và "Không commit", cảnh báo code review) và **chỉ commit + push khi bạn
   đồng ý**.
9. Tạo merge request, giao (assign) cho chính bạn và gắn nhãn theo loại ticket (Story -> `Enhancement`, Bug ->
   `Bug`), kèm kết quả review code; cập nhật trạng thái ticket Jira và gắn link MR vào ticket; cuối cùng liệt kê
   các file còn chưa commit.

Plugin chỉ ghi đè (force push, có `--force-with-lease`) nhánh ticket của chính bạn để giữ mỗi MR một commit; không
bao giờ ghi đè commit của người khác, không tự xoá nhánh, không merge MR và không đẩy thẳng (hay ghi đè) `develop`,
`master`, `release/*`. (MR được tạo với tuỳ chọn "xoá nhánh nguồn": GitLab tự xoá nhánh của ticket sau khi MR được
merge.)

Commit và merge request **không bao giờ có dòng ghi công AI** (`Co-Authored-By: Claude ... <...@anthropic.com>`,
"Generated with/by Claude Code", `Claude-Session: ...`, link phiên `https://claude.ai/code/session...`): script tự
gỡ đúng các dòng đó; dòng đồng tác giả là người thật (kể cả người tên Claude) và các dòng khác nhắc tới claude
được giữ nguyên. Nhãn
`Enhancement` / `Bug` phải có sẵn trong project hoặc group trên GitLab: plugin không tự tạo nhãn mới; nếu chưa có,
Claude nhắc bạn nhờ lead tạo hoặc tự chọn nhãn trên trang MR. MR đã có người được giao thì giữ nguyên người đó.

## Cài đặt (thành viên)

Thường **không cần làm gì**: mở project trong Claude Code, bấm đồng ý ở hộp thoại "trust this folder" (tin cậy
thư mục), và plugin tự được cài nếu lead đã tích hợp plugin vào project (xem phần "Dành cho lead" bên dưới).
Plugin cũng tự cập nhật.

Lần đầu bạn nhờ Claude đẩy code, Claude tự kiểm tra máy và **tự cài Git / Python 3 nếu còn thiếu** (không hỏi
trước, chỉ báo một dòng). Có thể bạn sẽ thấy: trên Windows một hộp thoại hỏi quyền cài đặt (bấm Có / Yes); trên
Mac hộp thoại cài "Command Line Developer Tools" (bấm Install); trên Linux Claude đưa một lệnh có `sudo` để bạn
tự chạy trong Terminal (mật khẩu chỉ gõ trong Terminal, không gửi vào khung chat).

Lưu ý: Claude Code tải plugin từ GitHub bằng Git, nên máy cần có Git từ trước để plugin tự cài được (Claude Code
trên Windows vốn đã cần Git for Windows).

### Cài thủ công

Dùng khi project chưa được tích hợp, hoặc trên máy riêng của lead. Trong Claude Code, gõ:

```
/plugin marketplace add madpoly-studio/mps-cicd-agent-flow
/plugin install mps-git-flow@mps-cdci-agents
```

Khởi động lại Claude Code nếu được yêu cầu.

## Cấu hình file `.env` (mỗi project một file)

Cấu hình nằm trong file `.env` ở **thư mục gốc của project** bạn đang làm (không dùng cấu hình chung cho cả
máy). Lần đầu dùng, Claude sẽ tự tạo file này từ mẫu, tự thêm `.env` vào `.gitignore`, mở file cho bạn và hướng
dẫn từng bước.

Bạn **tự điền token bằng trình soạn thảo** (Notepad, VS Code...). **Không dán token vào khung chat.**

### Bạn chỉ cần điền

| Khoá | Ý nghĩa |
|---|---|
| `MPS_JIRA_PAT` | Token Jira: Jira > ảnh đại diện > Profile > Personal Access Tokens > Create token |
| `MPS_JIRA_PROJECT_KEY` | Mã board Jira của team (ví dụ `MPS`) - hỏi lead nếu chưa biết, hoặc để trống để Claude gợi ý danh sách rồi tự điền |
| `MPS_GITLAB_PAT` | Token GitLab: ảnh đại diện > Edit profile > Access Tokens, chọn scope `api` và `write_repository` |

Các dòng còn lại trong `.env` đã có sẵn giá trị mặc định đúng, không cần sửa.

### Cấu hình nâng cao (thường không cần sửa)

| Khoá | Ý nghĩa |
|---|---|
| `MPS_JIRA_URL` | Địa chỉ Jira (mặc định `https://jira-mps.mto.zing.vn`) |
| `MPS_JIRA_PAT` | Token Jira: Jira > ảnh đại diện > Profile > Personal Access Tokens > Create token |
| `MPS_JIRA_PROJECT_KEY` | Mã project Jira (board) mặc định khi tạo ticket mới (ví dụ `MPS`). Bắt buộc; để trống thì Claude hỏi và tự điền. Có thể khác project GitLab |
| `MPS_GITLAB_URL` | Địa chỉ GitLab (mặc định `https://git-gst.mto.zing.vn`) |
| `MPS_GITLAB_PAT` | Token GitLab: ảnh đại diện > Edit profile > Access Tokens, chọn scope `api` và `write_repository` |
| `MPS_GITLAB_PROJECT` | Đường dẫn project dạng `group/project`. Để trống thì tự lấy từ `git remote origin` |
| `MPS_BRANCH_DEV` | Nhánh dev (mặc định `develop`) |
| `MPS_BRANCH_BETA_PREFIX` | Tiền tố nhánh beta (mặc định `release/`) |
| `MPS_BRANCH_PROD` | Nhánh production (mặc định `master`) |
| `MPS_CA_BUNDLE` | (Tuỳ chọn) đường dẫn file chứng chỉ CA nội bộ nếu gặp lỗi SSL |
| `MPS_GENERATED_PATTERNS` | (Tuỳ chọn, chỉ bạn tự sửa trong `.env`) thêm mẫu file do công cụ tự sửa, cách nhau bằng dấu phẩy, mỗi mẫu bắt đầu bằng tên thư mục/file cụ thể (ví dụ `Assets/Gen/**`, `yarn.lock`; mẫu như `*` bị bỏ qua). Trong project Unity (có `ProjectSettings/ProjectVersion.txt`) đã có sẵn các file Unity tự sửa (`ProjectSettings/**`, `Packages/packages-lock.json`, `UserSettings/**`, `Library/**`, `*.csproj`, `*.sln`). Chúng không ảnh hưởng việc chọn giai đoạn, nhưng vẫn được review và không tự động commit |

Lưu ý: giá trị trong `.env` là nguồn duy nhất - biến môi trường của hệ điều hành không được dùng. Các khoá
đều có tiền tố `MPS_` để không đụng với `.env` riêng của ứng dụng.

Cần bật **VPN công ty** để kết nối Jira và GitLab.

## Cách dùng

Mở Claude Code trong thư mục project, rồi nói ví dụ:

- "Đẩy code giúp mình, ticket MPS-123"
- "Đẩy giúp mình phần icon mới, ticket ART-12" (ticket của board artist)
- "Mình sửa xong lỗi đăng nhập, tạo MR giúp mình" (chưa có ticket - Claude sẽ giúp tạo)
- "Commit và push phần sửa lỗi này lên beta"

Luật nhánh tóm tắt (làm từ nhánh nào thì merge về đúng nhánh đó):

| Giai đoạn | Loại ticket | Nhánh tạo từ | MR vào |
|---|---|---|---|
| dev | Story (`feature/...`), Bug (`bugfix/...`) | `develop` | `develop` |
| beta | chỉ Bug (`bugfix/...`) | nhánh `release/*` bạn đang làm (nếu chưa ở nhánh nào thì nhánh mới nhất) | đúng nhánh `release/*` đó |
| production | chỉ Bug (`hotfix/...`) - rủi ro cao, nên để developer làm | `master` | `master` |

Nếu bạn đang có thay đổi trên `release/1.1` thì thay đổi sẽ vào `release/1.1` (Claude sẽ nhắc nếu đó không phải
nhánh beta mới nhất). Nếu bạn đã sửa code trên một nhánh mà lại chọn giai đoạn khác, Claude sẽ dừng lại và giải
thích - việc chuyển thay đổi sang giai đoạn khác cần developer. Khi chưa sửa gì, Claude hỏi bạn giai đoạn.

Claude chỉ commit đúng những file đã qua review phạm vi và review code; nếu bạn sửa thêm sau khi review, Claude
sẽ review lại cả hai. Nếu review code phát hiện vi phạm một quy tắc `blocker` của dự án, Claude giải thích và có
thể đề nghị sửa giúp (chỉ sửa khi bạn đồng ý, rồi review lại); nếu không sửa được, bạn cần nhờ developer. Các cảnh
báo khác không chặn commit và được ghi vào merge request.

**Mỗi merge request chỉ có một commit, và dùng rebase chứ không dùng merge commit.** Trên nhánh ticket bạn có thể
commit nhiều lần; khi đẩy lên, Claude gộp tất cả thành một commit (đặt tên theo quy tắc bên dưới) nằm ngay trên
bản mới nhất của nhánh gốc. Sửa thêm sau review thì lần đẩy sau lại gộp vào đúng một commit đó (ghi đè nhánh
ticket một cách an toàn: nếu ai khác vừa đẩy lên thì dừng, không ghi đè). Nhánh ticket đã có commit của người khác:
Claude hỏi bạn trước khi gộp thay đổi của bạn vào commit cuối (amend). `develop`, `master`, `release/*` không bao
giờ bị ghi đè. Đừng tự `git pull` / merge `develop` vào nhánh ticket - Claude tự cập nhật bằng rebase khi đẩy.

Ví dụ: Story `MPS-123` "Thêm màn hình Đăng nhập bằng Google" -> nhánh
`feature/MPS-123-them-man-hinh-dang-nhap-bang-google`, commit `feat: MPS-123 Thêm màn hình Đăng nhập bằng Google`,
MR `MPS-123 Thêm màn hình Đăng nhập bằng Google` với mô tả `Close MPS-123`. Ticket của board khác cũng vậy:
`ART-12` "Vẽ lại icon nhân vật" -> nhánh `feature/ART-12-ve-lai-icon-nhan-vat`, mô tả MR `Close ART-12` (GitLab tự
liên kết với mọi project trên cùng Jira).

Chi tiết: [branch-rules.md](plugins/mps-git-flow/skills/mps-git-flow/references/branch-rules.md),
xử lý lỗi: [troubleshooting.md](plugins/mps-git-flow/skills/mps-git-flow/references/troubleshooting.md),
chuẩn bị môi trường (Git/Python): [setup-environment.md](plugins/mps-git-flow/skills/mps-git-flow/references/setup-environment.md).

## Dành cho lead: tích hợp plugin vào project

Làm một lần cho mỗi project để cả team tự có plugin (và các bản cập nhật):

1. Mở Claude Code trong project và nói **"tích hợp plugin vào project"** (skill `mps-project-setup`), hoặc tự chạy
   `py -3 <thư mục plugin>/skills/mps-git-flow/scripts/mps.py project setup`.
2. Lệnh này thêm vào `.claude/settings.json` của project (giữ nguyên mọi cấu hình khác) và đảm bảo `.env` nằm trong
   `.gitignore`. Nội dung được thêm:

   ```json
   {
     "extraKnownMarketplaces": {
       "mps-cdci-agents": {
         "source": {
           "source": "github",
           "repo": "madpoly-studio/mps-cicd-agent-flow"
         },
         "autoUpdate": true
       }
     },
     "enabledPlugins": {
       "mps-git-flow@mps-cdci-agents": true
     },
     "attribution": {
       "commit": "",
       "pr": "",
       "sessionUrl": false
     }
   }
   ```

   `attribution` tắt dòng ghi công của Claude Code (`Co-Authored-By: Claude ...`, "Generated with Claude Code") trong
   commit và merge request của project. Nếu project đã tự đặt `attribution` thì giữ nguyên. Dù vậy, script vẫn tự gỡ
   các dòng ghi công AI khỏi mọi commit và MR mà nó tạo.

3. Commit các file này qua chính mps-git-flow (ticket + merge request), ví dụ ticket "Tích hợp plugin mps-git-flow
   vào project".

Thành viên sẽ thấy: khi mở project, Claude Code hỏi "trust this folder"; sau khi đồng ý, plugin tự được cài từ
GitHub. Lần đầu dùng, Claude tự cài Git/Python nếu thiếu (một dòng thông báo; có thể có hộp thoại Yes/No trên
Windows, hộp thoại Install trên Mac, hoặc một lệnh `sudo` để tự chạy trong Terminal trên Linux).

Kiểm tra: gõ `/plugin`, tab **Installed** có mps-git-flow kèm phiên bản; tab **Marketplaces** có mps-cdci-agents
với auto-update bật.

Muốn giữ cố định một phiên bản (không khuyến khích): thêm `"ref": "v0.1.1"` vào `source` của marketplace (cùng cấp
với `"repo"`). Mặc định là luôn theo bản mới nhất trên `main`. Khi đã ghim `ref`, skill không kiểm tra và không
nhắc cập nhật phiên bản mới nữa.

## Quy tắc review code theo dự án (dành cho tech lead)

Mỗi lần thành viên đẩy code, một trợ lý review code theo ba lớp quy tắc:

| Lớp | Nguồn | Áp dụng cho |
|---|---|---|
| 1. Chung của team | đi kèm plugin (`references/review/base.md`) | mọi file |
| 2. Theo công nghệ | đi kèm plugin (`references/review/profiles/`): `unity-csharp`, `python`, `web` | tự nhận ra: thư mục có `ProjectSettings/ProjectVersion.txt` (Unity), `pyproject.toml` / `setup.py` / `requirements*.txt` (Python), `package.json` (web); đường dẫn tính từ thư mục đó |
| 3. Riêng của dự án | file `.mps/review.md` ở gốc repo | do tech lead viết |

**Mức độ:** mọi nhận xét mặc định chỉ là **cảnh báo** (`major`, `minor`), được ghi vào merge request và không chặn
commit. Chỉ quy tắc mà **chính dự án** đánh dấu `blocker` trong `.mps/review.md` mới chặn commit. Quy tắc đi kèm
plugin không bao giờ là `blocker`. Khi gặp `blocker`, trợ lý giải thích cho người dùng, có thể đề nghị sửa code
cho đúng quy tắc (chỉ sửa khi người dùng đồng ý, rồi review lại từ đầu); nếu không sửa được hoặc người dùng không
đồng ý, người dùng phải nhờ developer. Không có cách nào bỏ qua (override) một `blocker`.

**Đọc từ nhánh gốc:** `.mps/review.md` luôn được đọc từ nhánh gốc trên GitLab (`origin/develop`,
`origin/release/...` hoặc `origin/master`), không phải bản trên máy. Sửa file quy tắc chỉ có hiệu lực **sau khi
được merge** (trong lúc đó trợ lý báo `project_rules_pending`).

**File sai định dạng bị bỏ qua cả file:** khi `.mps/review.md` trên nhánh gốc có lỗi (tiêu đề sai dạng, mức độ
lạ, mã trùng, khối code chưa đóng...), lần review đó chỉ dùng quy tắc lớp 1 và 2, trợ lý cảnh báo
`project_rules_invalid` và merge request ghi rõ "Quy tắc riêng của dự án KHÔNG được áp dụng". Tech lead cần giữ file
luôn hợp lệ: chạy `project setup` (hoặc nói "tạo quy tắc review code cho dự án" để dùng skill `mps-project-setup`)
sẽ báo `review_rules_problems` của bản trên máy trước khi commit.

Tạo file: nói với Claude **"tạo quy tắc review code cho dự án"** hoặc chạy `mps.py project setup --review-rules`
(tạo `.mps/review.md` từ mẫu, chưa có quy tắc nào có hiệu lực; không bao giờ ghi đè file đã có). Commit file qua
mps-git-flow như mọi thay đổi khác.

### Cách viết

- Phần đầu file (tuỳ chọn) nằm giữa hai dòng `---`, các khoá:
  - `version: 1`
  - `extends: [unity-csharp, web]` - thêm bộ quy tắc có sẵn khi plugin không tự nhận ra công nghệ.
  - `ignore: **/Assets/ThirdParty/**, Docs/**` - file không cần review code. Bộ `unity-csharp` đã tự bỏ qua file
    Unity tự sinh (`*.unity`, `*.prefab`, `*.asset`, `*.meta`, `*.mat`, `*.anim`, `*.controller`,
    `ProjectSettings/**`, `Packages/packages-lock.json`), trừ những file mà một quy tắc của dự án ghi rõ trong dòng
    `paths:`: quy tắc dự án `paths: **/*.prefab` vẫn được review trên prefab. `ignore` của chính `.mps/review.md`
    thì luôn thắng (và một quy tắc chỉ khớp file bị `ignore` đó sẽ bị cảnh báo `project_rule_matches_nothing`).
  - Danh sách viết `a, b` hoặc `[a, b]`; dòng bắt đầu bằng `#` là ghi chú. Phiên bản này chưa có khoá `disable`
    (khoá lạ chỉ bị cảnh báo `project_rules_unknown_key`).
- Mỗi quy tắc là một tiêu đề cấp 2: `## MÃ-QUY-TẮC [blocker|major|minor] Tiêu đề`.
  - Mã: chữ IN HOA, số và dấu `-`; **mỗi phần sau dấu `-` phải bắt đầu bằng chữ cái** (`SH-NO-SYNC-IO`, không
    được `SH-12` hay `ABC-2-X`), để mã không bao giờ giống mã ticket Jira (GitLab sẽ tự liên kết ticket).
  - Dòng đầu tiên sau tiêu đề có thể là `paths: **/Assets/Scripts/**/*.cs, Tools/*.cs` (mặc định: mọi file). Mẫu
    không có `/` (như `*.cs`) khớp tên file ở mọi thư mục; `**` khớp nhiều thư mục. (Khác với
    `MPS_GENERATED_PATTERNS` trong `.env`, nơi mẫu không có `/` chỉ khớp ở thư mục gốc.)
  - **`paths:` và `ignore:` luôn tính từ gốc repo**, kể cả khi project Unity nằm trong thư mục con (ví dụ
    `Client/Game/`): viết `**/Assets/Scripts/**/*.cs` hoặc `Client/Game/Assets/Scripts/**/*.cs`, không viết
    `Assets/Scripts/**/*.cs` (sẽ không khớp gì). Quy tắc không khớp file nào trên nhánh gốc bị cảnh báo
    `project_rule_matches_nothing` (khi đẩy code, và khi chạy `project setup` với bản trên máy).
  - Quy tắc không có `paths:` áp dụng cho mọi file được review, nhưng KHÔNG làm file mà bộ quy tắc có sẵn bỏ qua
    (prefab, scene, `.meta`...) được review; muốn kiểm tra các file đó thì ghi rõ trong `paths:` (ví dụ
    `paths: **/*.prefab`).
  - Phần còn lại giải thích quy tắc, nên có ví dụ Sai / Đúng trong khối code. Tiêu đề `##` nằm trong khối code
    không bị tính là quy tắc; văn bản trước quy tắc đầu tiên bị bỏ qua.
- Quy tắc có cùng mã với quy tắc của lớp 1 / 2 sẽ **thay thế** quy tắc đó (ví dụ nâng lên `blocker`).

Ví dụ file `.mps/review.md` đầy đủ:

````markdown
---
version: 1
extends: unity-csharp
ignore: **/Assets/ThirdParty/**, **/Assets/Generated/**
---

# Quy tắc review code của dự án (ví dụ)

## SH-NO-SYNC-IO [blocker] Không đọc / ghi file đồng bộ trong Update
paths: **/Assets/Scripts/**/*.cs

Đọc file đồng bộ mỗi frame làm game đứng hình trên điện thoại. Đọc sẵn lúc load hoặc dùng API bất đồng bộ.

Sai:

```csharp
void Update() { var json = File.ReadAllText(path); }
```

Đúng:

```csharp
async void Start() { _json = await File.ReadAllTextAsync(path); }
```

## SH-SCORE-ON-SERVER [major] Điểm số chỉ được tính trên server
paths: **/Assets/Scripts/Battle/**/*.cs

Client chỉ hiển thị điểm do server gửi về, không tự cộng điểm (chống gian lận).

## UNITY-NO-FIND-IN-UPDATE [blocker] Không gọi Find / GetComponent trong Update
paths: **/*.cs

Dự án này nâng quy tắc có sẵn lên mức chặn commit (cùng mã nên thay thế cả quy tắc của bộ `unity-csharp`, vì vậy
ghi lại `paths:`).
````

Các phần sẽ làm sau (chưa có trong bản này): skill `mps-code-review` chạy riêng, chạy review trong GitLab CI, trợ
lý hỏi đáp để tạo quy tắc, và cách để developer cho phép bỏ qua một `blocker`.

## Cập nhật plugin

- Trong project đã tích hợp, plugin **tự cập nhật**: Claude Code kiểm tra trong phiên làm việc (sau tin nhắn đầu
  tiên, trong khoảng 10 phút). Phiên đang chạy vẫn dùng bản cũ và báo "Run /reload-plugins to apply"; lần mở sau
  dùng bản mới.
- Xem phiên bản đang cài: `/plugin`, tab Installed.
- Cập nhật tay: gõ `/plugin marketplace update mps-cdci-agents` trong Claude Code (hoặc trong Terminal:
  `claude plugin marketplace update mps-cdci-agents` rồi `claude plugin update mps-git-flow@mps-cdci-agents`), sau
  đó gõ `/reload-plugins`.
- Mỗi lần chạy, skill cũng tự kiểm tra phiên bản mới và cập nhật giúp bạn (cảnh báo `plugin_outdated`), trừ khi
  project ghim phiên bản bằng `ref`.
- Các biến môi trường tắt cập nhật tự động: `DISABLE_UPDATES`, `DISABLE_AUTOUPDATER`,
  `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` (biến cuối cũng tắt luôn việc skill tự kiểm tra phiên bản).
  `FORCE_AUTOUPDATE_PLUGINS=1` bật lại cập nhật plugin.
- Bật/tắt auto-update trong màn hình `/plugin` sẽ ghi vào `.claude/settings.json` của project. Đừng commit thay đổi
  đó (review phạm vi sẽ để nó ngoài commit, trừ khi ticket nói về việc này).
- Máy đã cài bản 0.1.0 bằng tay cần cập nhật tay **một lần** để lên 0.1.1 (bản 0.1.0 chưa tự kiểm tra phiên bản).

### Chuyển repo (từ 0.2.1)

Từ bản 0.2.1, plugin nằm ở repo của tổ chức `madpoly-studio/mps-cicd-agent-flow` (trước đây là
`hung-bui-121/mps-cdci-agents`). Tên marketplace vẫn là `mps-cdci-agents` và tên plugin vẫn là
`mps-git-flow@mps-cdci-agents`, nên cấu hình `enabledPlugins` của các project không đổi.

- Project đã tích hợp: lead chạy lại `project setup` (hoặc nói "tích hợp plugin vào project"). Lệnh này đổi `repo`
  của marketplace trong `.claude/settings.json` sang repo mới (giữ nguyên `ref` nếu có, báo
  `marketplace_source_migrated`), rồi commit file đó qua mps-git-flow như lần tích hợp đầu.
- Máy đã cài tay từ repo cũ: gõ `/plugin marketplace remove mps-cdci-agents`, rồi
  `/plugin marketplace add madpoly-studio/mps-cicd-agent-flow` và `/plugin install mps-git-flow@mps-cdci-agents`.
  Nếu sau khi project đã đổi nguồn mà `/plugin` (tab Marketplaces) vẫn hiện repo cũ, làm các bước này.
- Bản 0.2.0 trở về trước chỉ kiểm tra phiên bản mới ở repo cũ. Để các máy này tự thấy bản mới, repo cũ cần được
  cập nhật cùng bản đó; nếu không, mỗi máy phải chuyển sang repo mới bằng tay như trên.

Từ bản 0.2.2, máy nào còn cài plugin từ repo cũ sẽ **bị chặn cho tới khi gỡ bản cũ**:
- Khi mở Claude Code, hook `SessionStart` của plugin hiện lời nhắc: team đã thống nhất đưa plugin về repo dùng
  chung, nên cần gỡ bản cài từ repo cá nhân của hungbt, kèm các lệnh `/plugin` cần gõ.
- Mọi lệnh của `mps.py` (trừ `project setup`) trả lỗi `plugin_source_legacy` với cùng lời nhắc. Claude đề nghị chạy
  giúp các lệnh `claude plugin ...` (chỉ chạy khi người dùng đồng ý), rồi nhắc gõ `/reload-plugins`.
- Ngoại lệ: nếu chính `.claude/settings.json` của project vẫn khai báo repo cũ thì member không bị chặn (gỡ đi
  cũng sẽ bị cài lại từ repo cũ); thay vào đó `env check` báo `legacy_project_source` để nhắc lead chạy
  `project setup`. `project setup` không bao giờ bị chặn, để lead luôn chuyển được project.
- Lead dùng máy còn cài từ repo cũ: `project setup` trả thêm `machine_source_legacy`; lead gỡ bản cũ theo hướng dẫn
  đó **trước** khi commit `.claude/settings.json` (nếu không, các bước commit sẽ bị chặn), rồi chạy lại
  `project setup` để chắc file vẫn trỏ repo mới.
- Mỗi nhánh dài hạn (`develop`, các `release/*` đang mở, nhánh production) có bản `.claude/settings.json` riêng:
  chạy `project setup` (hoặc merge thay đổi) trên từng nhánh, nếu không member mở Claude Code ở nhánh đó sẽ bị kéo
  lại repo cũ.
- Bị chặn giữa chừng một ticket thì không mất gì: sau `/reload-plugins`, Claude làm tiếp từ bước bị dừng.
- Máy được nhận ra qua file `known_marketplaces.json` của Claude Code (thư mục `~/.claude/plugins`, hoặc
  `CLAUDE_CODE_PLUGIN_CACHE_DIR` / `CLAUDE_CONFIG_DIR`). Không đọc được file này thì không chặn.
- Hook chạy bằng bash (Git Bash trên Windows). Tên repo trong `hooks/legacy-source-check.sh` phải khớp
  `LEGACY_MARKETPLACE_REPOS` / `MARKETPLACE_REPO` trong `mps.py` (có test kiểm tra).

## Phát hành phiên bản mới (người phát triển plugin)

1. Làm trên nhánh riêng; tăng `VERSION` trong `mps.py` và `version` trong `plugin.json` (cùng một giá trị: bản vá
   cho sửa lỗi/tài liệu, bản minor cho tính năng hoặc thay đổi quy trình) và thêm một mục vào `CHANGELOG.md`.
   Không ghi `version` trong `marketplace.json`.
   Thêm cả một mục cùng phiên bản vào `plugins/mps-git-flow/RELEASE_NOTES.md`: vài gạch đầu dòng ngắn, viết cho
   người dùng (kể cả không phải developer), không mã lỗi hay tên lệnh nội bộ. Sau khi cập nhật, lần mở Claude Code kế
   tiếp tự hiện mục này cho từng thành viên (hook `hooks/whats-new.sh`, một lần cho mỗi phiên bản; máy nhớ phiên bản
   đã hiện ở `~/.claude/mps-git-flow/last_seen_version`). Bỏ qua nhiều phiên bản thì hiện gộp, tối đa 5 bản.
2. Chạy `py -3 -m unittest discover -s tests -v` (test kiểm tra các phiên bản khớp nhau).
3. Khi thay đổi đụng tới cài đặt / cập nhật, chạy danh sách kiểm tra thủ công bên dưới và ghi kết quả vào MR.
4. Tạo MR vào `main`; tuỳ chọn gắn tag `v<phiên bản>` lên commit merge. Thành viên tự nhận bản mới.

Kiểm tra thủ công (máy thật, ngoài phần test tự động):

- Windows (PowerShell 5.1, tài khoản không phải admin nếu được): `bootstrap.ps1 -DetectOnly` khi có `py -3`; khi
  chỉ có lối tắt Microsoft Store (`store_stub_detected`, không bị treo); cài Python bằng winget phạm vi user (không
  hiện hộp thoại quyền, `installed: ["python"]` ngay trong lần chạy); không có winget (`winget_missing`); Git cũ
  (`winget upgrade`, rồi `restart_required` / `git_too_old` / `git_not_on_path` đúng trường hợp); proxy công ty /
  mất mạng (`install_failed`, vẫn in dòng JSON); đọc `message` tiếng Việt qua cả Git Bash và PowerShell.
- macOS: máy chưa có Command Line Tools (detect-only không mở hộp thoại); không có Homebrew (`xcode_clt_install`);
  có Homebrew (`brew install` không hỏi gì); chỉ có Python từ python.org; chạy `bootstrap.sh` trong Git Bash trên
  Windows (`use_powershell`).
- Linux (Ubuntu): không có sudo không mật khẩu (`run_in_terminal`); có sudo không mật khẩu hoặc root (cài xong,
  `ok: true`).
- Tích hợp và cập nhật: project mới có `.claude/settings.json` từ `project setup` -> mở Claude Code -> hộp thoại
  tin cậy -> plugin có trong `/plugin` với auto-update bật (ghi lại `autoUpdate` ở phạm vi project có được tôn trọng
  không); phát hành thử một bản mới qua một fork làm marketplace (`ref`) và xem thông báo cập nhật, `/reload-plugins`,
  `plugin_outdated` trong `env check`; bật/tắt auto-update trong `/plugin` có làm `.claude/settings.json` thay đổi
  không.
- `claude plugin update mps-git-flow@mps-cdci-agents` có chạy được với plugin được bật qua `enabledPlugins` ở phạm vi
  project (không cài thủ công) không.
- Thành viên mở Claude Code trong một thư mục con (ví dụ `Client/` của project Unity) có còn nhận
  `.claude/settings.json` ở gốc git không. (Tài liệu Claude Code hiện ghi rằng file này được đọc từ thư mục làm việc
  lúc mở Claude Code, nên nhiều khả năng là KHÔNG; khi đó hướng dẫn thành viên mở Claude Code ở gốc repo.)
- MR mới được giao cho người chạy và có nhãn `Enhancement` / `Bug` trên GitLab thật; project thiếu nhãn thì có cảnh
  báo `label_not_found` và vẫn tạo MR; commit / MR không còn dòng ghi công AI.

**Không tăng phiên bản thì không ai nhận được thay đổi.**

## Cấu trúc repo

```
.claude-plugin/marketplace.json            # marketplace "mps-cdci-agents"
.gitattributes                             # *.sh luôn LF, *.ps1 luôn CRLF
CHANGELOG.md                               # nhật ký thay đổi theo phiên bản
plugins/mps-git-flow/
  .claude-plugin/plugin.json               # phiên bản plugin (nguồn duy nhất)
  RELEASE_NOTES.md                         # "có gì mới" theo phiên bản, viết cho người dùng (hiện sau khi cập nhật)
  hooks/hooks.json                         # hook SessionStart (2 script bên dưới)
  hooks/legacy-source-check.sh             # nhắc gỡ bản cài từ repo cá nhân cũ (bash)
  hooks/whats-new.sh                       # hiện "có gì mới" một lần sau mỗi lần cập nhật (bash)
  skills/mps-git-flow/
    SKILL.md                               # quy trình cho Claude
    scripts/mps.py                         # CLI Python (chỉ thư viện chuẩn), in ra JSON
    scripts/bootstrap.ps1                  # tự kiểm tra / cài Git + Python trên Windows
    scripts/bootstrap.sh                   # tự kiểm tra / cài Git + Python trên macOS / Linux
    references/                            # luật nhánh, prompt review phạm vi + review code, chuẩn bị môi trường, xử lý lỗi
    references/review/base.md              # quy tắc review code chung của team (lớp 1)
    references/review/profiles/            # quy tắc theo công nghệ: unity-csharp, python, web (lớp 2)
    templates/env.example                  # mẫu file .env
    templates/review.example.md            # mẫu .mps/review.md (project setup --review-rules)
  skills/mps-project-setup/
    SKILL.md                               # cho lead: tích hợp plugin vào project
tests/test_mps.py                          # unit test (hàm thuần) + test git chạy offline với origin cục bộ
```

## Dành cho người phát triển plugin

Chạy test (Python 3; trên Windows `python` có thể là Python 2, hãy dùng `py -3`):

```
py -3 -m unittest discover -s tests -v
```

Thử CLI: `py -3 plugins/mps-git-flow/skills/mps-git-flow/scripts/mps.py --help`. Mỗi lệnh in đúng một object
JSON (`{"ok": true, ...}` hoặc `{"ok": false, "error": "...", "message": "..."}`). File `mps.py` phải luôn
parse được bằng Python 2.7 (không f-string, không annotation...) để báo lỗi "cần Python 3.8" một cách thân
thiện.

`scripts/bootstrap.ps1` phải luôn là UTF-8 **có BOM** và chạy được trên Windows PowerShell 5.1 (không dùng cú
pháp của PowerShell 6+). `scripts/bootstrap.sh` phải là POSIX sh (không dùng tính năng riêng của bash), UTF-8
không BOM, xuống dòng LF. Test kiểm tra các điều này.
