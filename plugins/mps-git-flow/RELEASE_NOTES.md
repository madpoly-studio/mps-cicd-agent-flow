# Có gì mới trong mps-git-flow

Mỗi phiên bản có một mục ngắn ở đây (mới nhất ở trên), viết cho người dùng. Sau khi plugin được cập nhật, lần mở
Claude Code kế tiếp sẽ tự hiện mục của phiên bản mới (một lần cho mỗi phiên bản). Chi tiết kỹ thuật: `CHANGELOG.md`
ở gốc repo.

## 0.3.0 - 2026-11-09
- Quy tắc mới của team: mỗi merge request chỉ có một commit. Bạn vẫn commit bao nhiêu lần cũng được; khi đẩy lên,
  Claude tự gộp thành một commit đặt tên đúng quy tắc.
- Dùng rebase thay cho merge: khi đẩy, nhánh của bạn được đặt lên bản mới nhất của nhánh gốc. Đừng tự pull /
  merge develop vào nhánh ticket nữa.
- Nhánh ticket đã có commit của người khác: Claude hỏi bạn trước khi gộp. Không bao giờ ghi đè thay đổi của người
  khác hay các nhánh develop / release / master.

## 0.2.4 - 2026-11-09
- Sau mỗi lần plugin được cập nhật, Claude Code hiện ngắn gọn phiên bản mới có gì thay đổi (chỉ một lần).

## 0.2.3 - 2026-11-08
- Tạo ticket Bug mới: tự đưa vào sprint đang chạy.
- Tạo ticket Story mới: Claude hỏi bạn muốn đưa vào sprint đang chạy hay để ở backlog, vì thêm vào sprint làm
  thay đổi phạm vi của sprint.
- Không có sprint nào đang chạy thì ticket nằm ở backlog.

## 0.2.2 - 2026-11-07
- Máy nào còn cài plugin từ repo cá nhân cũ của hungbt sẽ được nhắc gỡ và cài lại từ repo chung của tổ chức
  (mất khoảng một phút); chưa chuyển thì chưa dùng tiếp được.

## 0.2.1 - 2026-11-07
- Plugin chuyển về repo chung của tổ chức (madpoly-studio/mps-cicd-agent-flow). Tên plugin giữ nguyên.

## 0.2.0 - 2026-11-06
- Review code tự động trước khi commit: theo quy tắc chung của team, theo công nghệ của dự án (Unity C#, Python,
  web) và theo quy tắc riêng của dự án (file `.mps/review.md` do lead tạo).
- Nhận xét mặc định chỉ là cảnh báo; chỉ quy tắc dự án đánh dấu blocker mới chặn commit.
- Kết quả review được ghi vào merge request.

## 0.1.1 - 2026-11-06
- Máy còn thiếu Git / Python thì được tự cài.
- File `.env` chỉ cần điền 3 dòng; Claude hướng dẫn từng bước lấy token, kể cả khi token hết hạn.
- Commit và merge request không còn dòng ghi công AI.
- Merge request tự giao cho bạn và gắn nhãn Enhancement / Bug.
- Báo khi có phiên bản plugin mới.

## 0.1.0
- Phiên bản đầu tiên.
