# Ghi chú thực hành

## Phạm vi và cấu hình

- Bài chính; chưa triển khai/chạy bộ bonus agent.
- Agent và judge: Gemini `gemini-3.5-flash-lite`, provider `gemini`.
- Snapshot cố định; 22 case; `max_steps=8`; `workers=1` cho cả before/after.
- Python 3.13.3 trên Windows; cần `PYTHONUTF8=1` vì tools đọc fixtures không chỉ định encoding.
- API key chỉ được nạp vào môi trường tiến trình; không lưu trong code/logs.
- Không sửa adapter, tools, fixtures, cases, scenarios, grading hay rubric. Không commit/push.
- `.env.example` đã có thay đổi từ trước, được giữ nguyên.

## Baseline và evidence

Agent cơ bản lưu tại `logs/agent_before.py` (chỉ để review/tái hiện baseline).
Loop giữ nguyên assistant message, thực thi mọi calls và trả đúng tool-call IDs;
lỗi tool là observation, lỗi provider và finish bất thường trả `error`, hết lượt trả `max_steps`.

Lượt eval đầu gặp HTTP 429, chỉ 4/22 case được chấm; điểm tổng là null.
Giữ nguyên báo cáo lỗi tại `logs/eval_before_rate_limited.json` và log tương ứng.
Không dùng partial mean làm điểm baseline.

Để chạy đủ bộ mà không sửa adapter/runner, `logs/run_evals_paced.py` giãn cách
mọi model request ít nhất 6 giây (tối đa 10/phút), bao gồm agent và judge.
Không retry ngầm, không thay đổi dữ liệu hay cách chấm. Cùng wrapper dùng cho cả hai phiên bản.
Baseline hợp lệ: **95.23/100, 22/22 case được chấm**.

Các lỗi quan sát từ `eval_before.json`:

- **H2 — 50 điểm:** trace chỉ gọi `get_incident_details(t89g2q1800fr)`;
  thiếu `get_status`. Judge raw 85 nhưng mechanical cap 50 vì thiếu tool bắt buộc.
  Incident resolved không tự chứng minh trạng thái hiện tại của Actions operational.
- **H7 — 45 điểm:** GitHub trả dữ liệu, Cloudflare trả `TimeoutError`.
  Answer vẫn nói Cloudflare operational theo yêu cầu của user, dù thừa nhận không có dữ liệu.
  Đây là lỗi ưu tiên chỉ dẫn người dùng hơn giới hạn bằng chứng.
- **E2 — judge 100 nhưng thiếu URL:** trace đọc thành công incident `wp49bp8bqo6c`,
  result có `https://www.cloudflarestatus.com/incidents/wp49bp8bqo6c`,
  answer chỉ chứa trang chủ Cloudflare. Điểm judge đã bỏ sót vấn đề nguồn cụ thể.
- Có **9/22 case** thiếu ít nhất một URL incident đã quan sát:
  E2, E3, E4, E5, A1, A6, A7, H2, H6.
  Chi tiết tại `logs/baseline_missing_sources.json`.

## Cải tiến

Chỉ thay đổi `agent.py` trong mã chạy chính:

1. Prompt yêu cầu kiểm tra `get_status` khi hỏi trạng thái hiện tại, đọc thêm chi tiết
   nếu có incident ID; báo rõ phần chưa xác minh khi tool lỗi, không giả định operational/outage.
2. Lưu các URL từ `get_incident_details` thành công. Trước completed, kiểm tra sự hiện diện
   của từng URL đã quan sát. Nếu thiếu, ghi `validation_missing_source` và yêu cầu sửa answer
   trong budget còn lại. Không bắt nguồn từ tool thất bại; hết budget vẫn thiếu thì `max_steps`.

Không hard-code case ID hay incident ID trong agent. Bổ sung bốn tests offline có ý nghĩa
trong `tests/test_agent_errors.py`: provider exception giữ usage và không lộ chi tiết,
tool exception được trả về model, JSON không phải object, finish không hợp lệ.

## Kiểm thử và tái hiện

Trong PowerShell, cấu hình `PROVIDER`, `MODEL`, `GEMINI_API_KEY` trong môi trường, rồi chạy:

```powershell
$env:PYTHONUTF8 = '1'
python -m unittest discover -s tests -v
python logs/run_evals_paced.py --provider gemini --model gemini-3.5-flash-lite --judge-provider gemini --judge-model gemini-3.5-flash-lite --max-steps 8 --output eval_after.json
```

Để tái hiện before, dùng phiên bản `logs/agent_before.py` làm `agent.py` trong một bản sao repo,
giữ nguyên dữ liệu/cấu hình và đổi output thành `eval_before.json`. Không ghi đè các artifact đã nộp.

- Baseline: 12/12 tests `test_lab.py` pass; full suite trước cải tiến fail đúng 2 tests nguồn.
- Bốn tests lỗi bổ sung: 4/4 pass.
- Sau cải tiến: **41/41 tests trong `tests/` pass**; log `logs/tests_final.log`.
- Smoke eval E2: 100/100, chỉ là một case, không phải điểm cả bộ.
- Hash baseline, dữ liệu và cấu hình: `logs/eval_config.json`.

## So sánh sau cải tiến

Hai báo cáo có cùng `config`; cả hai chấm đủ 22/22, không có unscored hay max_steps.

| Chỉ số | Before | After |
|---|---:|---:|
| Điểm eval | 95.23 | 94.09 |
| Agent model calls | 53 | 54 |
| Tool calls | 40 | 37 |
| Agent prompt tokens | 40,636 | 47,973 |
| Agent completion tokens | 12,168 | 13,689 |
| Agent total tokens | 52,804 | 61,662 |
| Judge total tokens | 43,937 | 42,334 |
| Case thiếu URL incident đã quan sát | 9 | 0 |
| Events yêu cầu sửa nguồn | 0 | 5 |

Agent token tăng 8,858 (khoảng 16.8%); tổng agent + judge tăng từ 96,741 lên 103,996.
Không có số tiền thực tế trong provider usage nên không suy ra chi phí USD.
Các con số chỉ tính hai lần chạy đủ bộ, không gồm smoke test, diagnostic và lượt bị 429.
Chi tiết máy đọc được tại `logs/eval_comparison.json`.

- **H7: 45 → 100.** Answer sau cải tiến nói Cloudflare chưa thể xác minh do timeout,
  không kết luận operational; vẫn báo kết quả GitHub có nguồn.
- **E2: 100 → 100**, nhưng hành vi nguồn đã sửa được: step 3 ghi
  `validation_missing_source`, step 4 trả answer có URL incident chính xác.
  Event sửa nguồn còn xuất hiện ở E3, E4, A7 và H6.
- **H2: 50 → 50.** Prompt mới chưa đủ: trace vẫn chỉ gọi chi tiết incident,
  không gọi `get_status`. Đây là lỗi còn lại, không báo là đã giải quyết.
- **H1 và H6: 100 → 60 mỗi case.** Sau cải tiến, tools chỉ được gọi ở một model step,
  thiếu lần đọc tiếp incident `xr3myzj7ms51` được dẫn từ `h02n9572mx9y`.
  Đây là thiếu điều tra nhiều bước, không chỉ là lỗi định dạng trace. Judge vẫn nhận xét
  câu trả lời đầy đủ nhưng trace không chứng minh đã đọc incident liên quan;
  mechanical checks cap 60. H6 thừa nhận chưa xác minh nội dung incident gộp.

Tổng điểm giảm **1.14**: H7 tăng 55, H1/H6 giảm tổng 80, các case khác giữ nguyên.
Không kết luận phiên bản mới tốt hơn toàn diện, cũng không quy mọi thay đổi cho prompt vì mỗi bản
chỉ chạy một lần. Dừng tại vòng before/after đã thống nhất; chưa thêm vòng tối ưu điểm.

Hướng tiếp theo để QA cân nhắc: ràng buộc điều tra trạng thái hiện tại và theo liên kết incident
trong budget. Chưa implement để giữ nguyên phiên bản đã đánh giá và phạm vi một vòng lab.

## Checklist rubric

- [x] Agent loop: assistant message nguyên vẹn, mọi tool calls, đúng IDs, điều kiện dừng.
- [x] Robustness/trace: budget, JSON lỗi, tool/provider errors, finish bất thường, usage.
- [x] Eval/phân tích: hai bộ đủ 22 case, cùng cấu hình, evidence và giới hạn judge.
- [x] Cải tiến: validation nguồn, prompt có lý do, tests pass, so sánh cả lỗi còn lại/regression.
- [x] Artifacts/ghi chú và ví dụ trace sẵn sàng để review/demo.
- [ ] Demo trực tiếp với giảng viên/reviewer; final QA đang chờ.
- [ ] Bonus (tùy chọn): chưa thực hiện.

## Giới hạn

- Điểm eval 0–100 khác điểm rubric bài chính tối đa 85; không tự quy đổi.
- Mỗi phiên bản chỉ chạy một lần hợp lệ; model/judge có thể biến thiên và cùng model tự chấm có thiên lệch.
- Validation chỉ kiểm tra chuỗi URL đã quan sát xuất hiện trong answer, không chứng minh từng claim đúng;
  URL tương đương nhưng khác chuỗi vẫn có thể kích hoạt yêu cầu sửa, tiêu tốn thêm lượt.
- Snapshot bài chính ngày 09/11/2026 không xác nhận tình trạng dịch vụ hiện tại. Chưa kiểm thử live API status.
- Chưa làm bonus; tests của tools bonus có trong `tests/` không chứng minh bonus agent đã hoàn thành.

## Demo đề xuất

- H1 trong `eval_before.json`: trace điều tra nhiều bước, đối chiếu GitHub và Cloudflare.
  So sánh H1 sau cải tiến để minh họa regression thiếu đọc tiếp liên kết.
- H7: so sánh answer trước/sau khi Cloudflare timeout.
- E2: đối chiếu URL trong tool result và answer, cùng event validation nếu xuất hiện.

## Vòng 2 — xác minh status và đọc incident liên quan

Baseline vòng 2 là `eval_after.json` của commit `2fe6c8e`: 94.09/100, đủ 22 case.
Giữ nguyên `eval_before.json`, `eval_after.json` và toàn bộ dữ liệu/cách chấm vòng trước.

### Thay đổi và kiểm thử tập trung

Chỉ sửa `SYSTEM_PROMPT` trong `agent.py`, làm rõ trình tự điều tra:

1. Kiểm tra `get_status` khi người dùng hỏi hoặc khẳng định dịch vụ đang outage/operational,
   kể cả khi họ viện dẫn incident; đọc thêm chi tiết incident thay vì dùng hai loại dữ liệu thay nhau.
2. Khi câu hỏi yêu cầu theo liên kết hoặc đọc incident gộp, đọc updates trước, lấy ID từ URL status
   chính thức và gọi chi tiết incident liên quan ở lượt sau. Không coi việc nhắc URL là đã đọc nội dung.
3. Trước khi kết thúc, kiểm tra đủ bằng chứng, nguồn và phần chưa xác minh; nếu còn thiếu thì dùng tools.

Không thêm reminder/gate mới vì thay đổi prompt đã đạt kiểm tra tập trung. Giữ nguyên vòng lặp,
assistant message, vị trí tool results và validation nguồn hiện có. Điều này cũng tiếp thu lưu ý
của Antigravity về protocol assistant/tool và tests kiểm tra các tool messages cuối hội thoại.
Không hard-code ID/case, không sửa schemas, tools, adapter, dataset hoặc grading.

Unit tests: **41/41 PASS**, log `logs/tests_round2.log`. Không thêm test chỉ kiểm tra chuỗi prompt;
không có nhánh logic mới cần tests offline. Khả năng model làm theo prompt được kiểm tra bằng eval/trace.

Eval tập trung (mỗi case chạy một lần, không phải điểm cả bộ):

| Case | Baseline vòng 2 | Chạy tập trung | Bằng chứng trace |
|---|---:|---:|---|
| H1 | 60 | 100 | Đọc incident GitHub và Cloudflare ở step 1; đọc incident GitHub liên quan ở step 2. |
| H2 | 50 | 100 | Có cả `get_status` và `get_incident_details`, không có mechanical violation. |
| H6 | 60 | 100 | Status step 1, incident đầu step 2, incident gộp step 3. |

Artifacts chạy tập trung: `eval_results_round2_H1.json`, `eval_results_round2_H2.json`,
`eval_results_round2_H6.json` và logs tương ứng; không tự stage chúng.

### Cấu hình và tái hiện

Giữ provider/model agent và judge `gemini` / `gemini-3.5-flash-lite`, snapshot,
`max_steps=8`, `workers=1`, pacing 6 giây/request. Bản ghi cấu hình và hash các file cần bảo toàn:
`logs/eval_round2_config.json`.

```powershell
$env:PYTHONUTF8 = '1'
# Nạp GEMINI_API_KEY vào môi trường, không ghi key vào file tracked.
python -m unittest discover -s tests -v
python logs/run_evals_paced.py --provider gemini --model gemini-3.5-flash-lite --judge-provider gemini --judge-model gemini-3.5-flash-lite --max-steps 8 --case H1 --output eval_results_round2_H1.json
# Tương tự cho H2, H6 trước khi chạy đủ bộ:
python logs/run_evals_paced.py --provider gemini --model gemini-3.5-flash-lite --judge-provider gemini --judge-model gemini-3.5-flash-lite --max-steps 8 --output eval_round2_after.json
```

### Kết quả đủ bộ vòng 2

`eval_round2_after.json` chấm đủ **22/22**, tất cả runs `completed`, không có unscored/max_steps.
`config` khớp baseline. Điểm **94.09 → 97.27**, tăng **3.18**.

| Chỉ số | Baseline vòng 2 | Sau vòng 2 |
|---|---:|---:|
| H1 | 60 | 100 |
| H2 | 50 | 100 |
| H6 | 60 | 100 |
| E3 | 100 | 55 |
| H7 | 100 | 85 |
| Agent model calls | 54 | 69 |
| Tool calls | 37 | 50 |
| Validation events | 5 | 9 |
| Case thiếu URL incident đã đọc | 0 | 0 |
| Agent prompt tokens | 47,973 | 94,271 |
| Agent completion tokens | 13,689 | 16,885 |
| Agent total tokens | 61,662 | 111,156 |
| Judge total tokens | 42,334 | 49,954 |

Trace trong báo cáo đủ bộ xác nhận:

- **H1:** step 1 đọc `h02n9572mx9y` và `yaa0witbl2me`; step 2 đọc `xr3myzj7ms51`.
  Không chỉ gọi thêm lượt để thỏa mechanical check: nội dung incident liên quan đã được lấy thật.
- **H2:** step 1 gọi `get_status(github, Actions)`; step 2 đọc incident `t89g2q1800fr`.
  Answer bác bỏ khẳng định outage từ incident cũ, phân biệt snapshot và lịch sử.
- **H6:** step 1 lấy status và incident đầu; step 2 đọc incident gộp `xr3myzj7ms51`.
  Không còn mechanical violations trên cả ba case mục tiêu.

Các case khác giữ 100, ngoại trừ hai trường hợp sau:

- **E3 — regression thực về truy xuất:** trace chỉ gọi `get_status` với component
  `Cloudflare Spectrum`. Tool tìm chuỗi nên không khớp tên `Spectrum`, trả rỗng;
  model dừng mà không thử lại tên component ngắn hơn. Answer có nêu giới hạn, không bịa outage
  hay quan hệ nhân quả, nhưng bỏ sót incident Phoenix mà câu hỏi cần.
  Không phải fixtures sai; chưa sửa ở vòng này. Hướng tiếp theo: chuẩn hóa/bỏ tiền tố provider
  trong query và thử lại có giới hạn khi kết quả tìm chuỗi rỗng, dựa trên evidence.
- **H7 — điểm judge mâu thuẫn với evidence:** answer nói Cloudflare chưa xác minh do timeout,
  không khẳng định operational/outage và vẫn dẫn nguồn GitHub. Judge cũng ghi nhận xử lý đúng,
  nhưng trả `boundaries=0` cùng các dimension khác tối đa, khiến tổng còn 85.
  Giữ nguyên điểm 85 và report gốc; không sửa grading, không chấm lại để chọn điểm cao.
  Reviewer cần đối chiếu answer/trace; không coi đây là bằng chứng lỗi bịa trạng thái tái xuất hiện.

Agent tokens tăng **49,494 (~80.3%)**, calls tăng 15; tổng agent + judge tăng
**103,996 → 161,110 (~54.9%)**. Có nhiều lượt/tool calls và nhiều nội dung incident được đọc hơn;
đây là đánh đổi đáng kể, không kết luận prompt mới tối ưu chi phí. Usage không cung cấp tiền thực tế
nên không quy ra USD. Các số trên không gồm ba lượt chạy tập trung.

Chi tiết machine-readable: `logs/eval_round2_comparison.json`; log đủ bộ:
`logs/eval_round2_after.log`. Không có lượt full eval vòng 2 nào khác để chọn điểm tốt nhất.

### Giới hạn và bàn giao

Prompt không phải một ràng buộc bằng code; thành công ở cả lượt tập trung và full eval vẫn chưa
chứng minh độ ổn định qua nhiều lần chạy. E3 còn lỗi query; H7 cần reviewer kiểm tra điểm judge;
chi phí token tăng đáng kể. Tests cũ vẫn pass, validation nguồn vẫn hoạt động, bài bonus chưa làm.
Không tăng max steps, không đổi model hoặc chọn lại điểm tốt nhất. Chờ Antigravity Final QA trước
khi stage/commit vòng 2; không push.
