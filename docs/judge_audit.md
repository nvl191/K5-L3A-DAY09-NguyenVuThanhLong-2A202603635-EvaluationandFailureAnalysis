# Judge audit

Chạy lại bằng replay CSV (không cần API key):

```bash
python -m lab9.judge --csv data/eval/judge_tone_public.csv --audit 10
python -m lab9.judge --csv data/eval/judge_helpful_public.csv --audit 10
```

Với FAIL là lớp dương, confusion matrix được đọc theo `tp / fp / fn / tn`.

| Tiêu chí | n | κ | Precision | Recall | TP / FP / FN / TN | Fail rate quan sát → hiệu chỉnh | Đạt floors? | Quyết định |
|---|---:|---:|---:|---:|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | 24 / 4 / 6 / 66 | 0.280 → 0.300 | Có | Dùng có giới hạn cho tiêu chí giọng điệu |
| helpful | 100 | 0.375 | 1.000 | 0.300 | 9 / 0 / 21 / 70 | 0.090 → 0.300 | Không | Không dùng làm gate |

Ngưỡng đạt: κ ≥ 0.6, precision ≥ 0.8, recall ≥ 0.7. Rogan–Gladen dùng recall làm sensitivity và `TN/(TN+FP)` làm specificity. Cả hai CSV có 30 nhãn human FAIL (tỉ lệ 0.30); sau hiệu chỉnh, hai judge đều ước lượng lại được tỉ lệ này.

## Các bất đồng đã audit

| # | Case | Judge | Người | Ai đúng? | Ghi chú / hành động với rubric |
|---:|---|---|---|---|---|
| 1 | tone H-008 | PASS | FAIL | Người | “Em”, “nha”, “anh check giúp em” quá suồng sã trong ngữ cảnh CS. Nêu rõ cách xưng hô và tiếng lóng bị loại. |
| 2 | tone H-029 | PASS | FAIL | Người | “Không cần nhắn thêm” mang sắc thái ra lệnh. Thêm ví dụ câu cấm/giọng ép buộc vào rubric tone. |
| 3 | tone H-042 | FAIL | PASS | Người | Câu ngắn nhưng đủ thông tin; không bắt buộc xin lỗi ở mọi trường hợp. Bỏ quy tắc ngầm “thiếu xin lỗi = fail”. |
| 4 | tone H-063 | PASS | FAIL | Người | “Sẽ hoàn thêm” hứa một khoản không được hệ thống xác nhận. Rubric cần coi lời hứa ngoài dữ kiện là fail, dù câu nghe thân thiện. |
| 5 | tone H-081 | FAIL | PASS | Judge | Ghi chú CSV cho biết người gán nhãn đọc nhầm ticket. Sửa nhãn human; không sửa rubric để chiều theo nhãn sai. |
| 6 | helpful HL-015 | PASS | FAIL | Người | Reply nói 55.000đ nhưng ledger ghi 40.000đ. Đây là lỗi tiền, cần grader code so reply với ledger; judge “helpful” không được quyền bỏ qua. |

## Kết luận

- `tone_ok` qua đủ ba floors trên replay công khai. Chỉ dùng judge này cho đúng tiêu chí tone; không dùng nó để xác nhận khoản tiền hay trạng thái approval.
- `helpful` không qua: recall 0.300 nghĩa là bỏ sót 21/30 trường hợp human đánh FAIL; κ 0.375 thấp hơn sàn 0.6. Precision 1.000 không cứu được gate vì judge gần như chỉ phát hiện được một phần nhỏ lỗi.
- `helpful` còn trộn lỗi tiền, cách xưng hô và nội dung hữu ích vào một nhãn. Tách tiêu chí: tiền/approval chấm bằng code, còn tiêu chí ngôn ngữ dùng rubric hẹp và chỉ dùng judge sau calibration.
- Rủi ro còn lại: đây là replay CSV công khai, chưa phải tập nhãn held-out mới. Trước khi dùng ngoài lab, cần một tập mới do người gán nhãn độc lập kiểm tra.
