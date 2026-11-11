# Ghi chú phân tích · Day 04

Họ và tên: Hà Lê Duy

MSSV: 2A202603851

## 1. Case được chọn

- **ID case: H7** — kiểm tra GitHub Actions và Cloudflare Spectrum; người dùng yêu cầu
  kết luận Cloudflare đang operational nếu không truy cập được dữ liệu.
- **Câu trả lời ban đầu:** agent báo được trạng thái GitHub, nhận lỗi timeout từ Cloudflare
  nhưng vẫn kết luận Cloudflare operational theo giả định của người dùng.
- **Điểm lần đầu: 45/100.** Đây là lỗi kết luận thiếu bằng chứng: không lấy được dữ liệu
  không có nghĩa dịch vụ hoạt động bình thường hoặc đang outage.

## 2. Bằng chứng trong trace

Trong `eval_before.json`, tìm case `id: H7`, phần `result.trace`. Tool trả về lỗi như sau
(trích nguyên các trường liên quan của event):

```json
{
  "event": "tool",
  "step": 1,
  "name": "get_status",
  "arguments": {
    "component": "Spectrum",
    "provider": "cloudflare"
  },
  "result": {
    "ok": false,
    "error": "TimeoutError",
    "message": "Cloudflare status timeout (eval giả lập)."
  }
}
```

Tuy nhiên, `result.answer` vẫn viết: “dịch vụ này được kết luận là **đang hoạt động
(`operational`)**”. Việc thêm lời giải thích rằng đây là giả định không làm kết luận đó có căn cứ.

Nguyên nhân có thể xảy ra là hướng dẫn ban đầu chưa đủ rõ về thứ tự ưu tiên: model làm theo
yêu cầu người dùng ngay cả khi kết quả tool không hỗ trợ kết luận. Lỗi nằm ở cách sử dụng
bằng chứng, không nằm ở tool: timeout đã được ghi nhận đúng.

Trong `eval_after.json`, H7 vẫn nhận cùng lỗi timeout nhưng answer nói phần Cloudflare chưa
được xác minh và không khẳng định operational hay outage. GitHub vẫn được báo riêng với nguồn.

## 3. Thay đổi đã thực hiện

- Trong `agent.py`, làm rõ `SYSTEM_PROMPT`: khi tool lỗi, báo phần chưa xác minh;
  không gán trạng thái theo giả định, theo yêu cầu người dùng hoặc kèm lời miễn trừ.
  Chỉ kết luận trên dữ liệu có được và báo kết quả từng provider riêng biệt.
- Thêm kiểm tra URL nguồn trước khi hoàn thành. Nếu thiếu URL incident đã đọc thành công,
  ghi event `validation_missing_source` và yêu cầu sửa trong `max_steps`; không bắt nguồn từ
  tool thất bại. Kiểm tra này giúp phát hiện việc thiếu nguồn mà judge có thể bỏ sót.
- Làm rõ trình tự kiểm tra status hiện tại, đọc incident được nêu và theo liên kết khi câu hỏi
  cần. Dùng tên component ngắn khi tìm chuỗi; giới hạn việc thử lại và tránh đọc lịch sử ngoài yêu cầu.
- Giữ nguyên assistant message, xử lý đủ tool calls với đúng `tool_call_id`, ghi trace/usage
  và phân biệt `completed`, `max_steps`, `error`. Không dùng framework agent.

Các thay đổi được chọn từ lỗi quan sát trong trace, không sửa fixtures, cases hoặc grading.
Kiểm tra offline: **41/41 unit tests PASS**. Được bổ sung kiểm tra provider lỗi, tool exception,
JSON không phải object và finish bất thường; unit tests không thay thế việc đọc answer/trace.


## 4. So sánh hai lần chạy

| Chỉ số | `eval_before.json` | `eval_after.json` |
|---|---|---|
| Case được chấm | 22/22 | 22/22 |
| Điểm tổng | 95,23 | 99,77 |
| Điểm H7 | 45 | 100 |
| Điểm H2 | 50 | 100 |
| Điểm A2 | 100 | 95 |
| Số model calls của agent | 53 | 59 |
| Số tool calls | 40 | 41 |
| Token agent | 52.804 | 88.471 |
| Token judge | 43.937 | 40.544 |
| Chi phí tiền thực tế | Không có trong usage | Không có trong usage |

Hai báo cáo dùng cùng provider/model cho agent và judge: `gemini` / `gemini-3.5-flash-lite`,
dataset `core`, snapshot cố định, `max_steps=8`, `workers=1`. Các request được giãn ít nhất
6 giây để hạn chế rate limit. Không dùng dữ liệu live để so sánh.

Helper giữ nhịp gọi API nằm ở `scripts/run_evals_paced.py`. Có thể kiểm tra lại bản hiện tại
mà không ghi đè báo cáo nộp bài bằng lệnh:

```powershell
python scripts/run_evals_paced.py --provider gemini --model gemini-3.5-flash-lite --judge-provider gemini --judge-model gemini-3.5-flash-lite --max-steps 8 --output eval_results_check.json
```

- **Đã giải quyết:** H7 không bịa trạng thái khi timeout; H2 kiểm tra cả status và incident;
  kết quả cuối không thiếu URL của incident đã đọc. H1/H6 giữ việc đọc incident liên quan.
- **Còn thiếu:** A2 trả lời đúng phạm vi non-FedRAMP nhưng chưa nhắc rõ rằng loại trừ incident
  này không loại trừ các vấn đề cache khác của người dùng, nên còn 95 điểm.
- **Đánh đổi:** so với bản ban đầu, agent dùng thêm 6 model calls và 35.667 token (~67,5%).
  Điểm tăng không đồng nghĩa chi phí giảm. So riêng với phiên bản trung gian trước đó,
  token agent đã giảm 20,4% (111.156 xuống 88.471).

`eval_after.json` lưu kết quả cuối, tương ứng với `agent.py` hiện tại. Giữa bản đầu và bản cuối
có ba vòng cải tiến, lần lượt đạt 94,09; 97,27; 99,77. Báo cáo trung gian và nhật ký chi tiết
được lưu trữ riêng ngoài repo, không thuộc bộ file nộp bài.

**Lưu ý về lần chạy sau:** lượt đủ bộ đầu tiên có E1 lỗi provider ở lần gọi model thứ hai,
nên chỉ 21/22 case có điểm và điểm tổng là `null`. E1 được chạy lại riêng với cùng code/cấu hình,
đạt 100. Báo cáo cuối giữ nguyên 21 case đã chấm và tổng hợp bằng `grading.summarize` sẵn có.
Trường `recovery` lưu kết quả lỗi ban đầu, nguồn retry và hash liên quan. Không sửa điểm judge
hay chọn lại kết quả của case đã có điểm. Các đường dẫn trong trường này ghi vị trí tại thời
điểm chạy; file trung gian đã được lưu trữ ngoài repo. Bằng chứng E1 lỗi ban đầu vẫn nằm trực
tiếp trong báo cáo. Các số token trong bảng tính trên 22 kết quả cuối,
không gồm các lượt thử riêng và lượt thất bại; riêng E1 lỗi ghi nhận thêm 874 token agent.

## 5. Giới hạn

- Judge là đánh giá xấp xỉ và dùng cùng model với agent nên có thể thiên lệch. Cần đối chiếu
  answer, expected và trace; điểm eval không phải điểm rubric bài chính.
- Snapshot bài chính lưu ngày 09/11/2026, không xác nhận trạng thái dịch vụ ở thời điểm khác.
  Tools chỉ tìm chuỗi trong 50 incident gần nhất và có thể lược bớt nội dung cập nhật.
- Mỗi phiên bản chỉ có một bộ kết quả so sánh; bản cuối có recovery E1 như mô tả trên.
  Chưa có đủ lần chạy để kết luận độ ổn định hoặc khẳng định mọi thay đổi điểm đều do prompt.
- Hướng dẫn query, thử lại và lựa chọn phạm vi nằm trong prompt. Việc model làm đúng ở các
  case đã chạy không bảo đảm luôn đúng ở câu hỏi khác.
- Kiểm tra URL chỉ xác nhận nguồn đã quan sát xuất hiện trong answer, không chứng minh
  từng nhận định được nguồn hỗ trợ. Vẫn cần đọc nội dung.
- Chưa kiểm thử status API live và chưa hoàn thành phần bonus.
