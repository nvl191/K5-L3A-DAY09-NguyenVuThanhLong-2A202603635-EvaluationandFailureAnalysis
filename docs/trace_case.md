# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

## Case đã phân tích: ticket đè dữ kiện DB

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression`, `C-002@55`; report run ID `E-seeded_regression-20261117-f56e` |
| Triệu chứng | `DbFactKept` và `RefundAmountCorrect` fail. Agent báo resolved và ledger ghi 20.000đ; nhãn yêu cầu denied, hoàn 0đ. |
| Bước sai đầu tiên | Event 3, `model_override`: `{"delay_days": 5}` |
| Vì sao là bước đầu tiên | Event 1 tạo handoff đúng; event 2 đọc order DB với `delay_days=2`. Hai bước đó còn khớp dữ liệu gốc. Event 3 mới lấy số 5 trong ticket ghi đè DB. Sau đó quote 20.000đ và refund sai. |
| Failure mode | FM-03 `ticket_trust` |
| Đối chứng | Cùng claim/seed trên `fixed`: không có `model_override`, quote 0đ vì DB ghi trễ 2 ngày (thấp hơn ngưỡng 3 ngày), status denied, ledger 0đ. |
| Regression test | `test_trace_case_ticket_override_regression` trong `src/tests/test_lab9_graders.py`: xác nhận `DbFactKept` và `RefundAmountCorrect` bắt bản lỗi, đồng thời pass trên `fixed`. |
| Chưa chắc chắn | Đây là replay MockLLM với seed cố định; nó chứng minh bug trong variant và khả năng grader bắt bug, không ước lượng tần suất trên LLM thật. |

Tái hiện bằng lệnh:

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 55
python -m lab9.trace_case --shape fixed --claim C-002 --seed 55
```

Đọc **ledger trước reply**: câu trả lời nghe tự tin không làm cho khoản hoàn 20.000đ trở nên đúng. Thực tế order DB chỉ trễ 2 ngày nên khoản hoàn hợp lệ là 0đ.
