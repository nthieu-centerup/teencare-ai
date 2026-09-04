# Rà nội dung state-v6 với model thật

Các dữ liệu trong `analysis_cases.json` và `app/demo-observations.json` đều là tình huống tổng hợp để thử hệ thống. Bộ pytest chỉ kiểm tra contract, validation và mock; không chứng minh model suy luận đúng. File này chuẩn bị tiêu chí rà thủ công, không tự gọi OpenAI.

Khi chủ động thử OpenAI, dùng service riêng với model đang cấu hình, giữ nguyên thời điểm đánh giá của từng fixture. Ghi lại model, prompt, input và output đã được phép dùng để đánh giá. Không thay thời gian của sự việc chỉ để khiến model nói có tiến bộ.

| Tình huống | Nội dung cần kiểm tra |
| --- | --- |
| `single_report` | Một sự việc không thành thói quen. Summary có nguồn và giới hạn; không tự đoán động lực hoặc khó khăn ở các mục khác. |
| `missing_context`, `unclear_support_basis` | Có thể để assessments/hypotheses/recommendations rỗng. Câu hỏi hoặc InformationGathering tập trung vào bối cảnh thiếu; không đưa SupportTrial thiếu căn cứ. |
| `partial_profile` | Giữ điểm mạnh hợp tác và sở thích teen tự nói; chỉ điền mục có bằng chứng. Không tạo tám kết luận hoặc điểm số. |
| `conflicting_sources`, `different_contexts` | Xác định nguồn nào nói gì và bối cảnh nào; giữ bất đồng chưa giải quyết. Mixed phù hợp khi thông tin còn khác nhau. Lần đầu không có mốc cùng dimension thì trend Unknown. |
| `invalid_event_times` | Ghi nhận có thời gian bất hợp lý chỉ dẫn đến câu hỏi xác nhận thời gian. Không dùng nó để kết luận tình hình hiện tại hoặc đề xuất hành vi. |
| Phản hồi sau hành động trong bộ demo | Gắn phản hồi với việc phụ huynh báo đã thực sự thử; có evidence hai giai đoạn. Không khẳng định cách hỗ trợ gây ra thay đổi hoặc vài buổi là tiến bộ bền vững. |
| Ghi nhận cũ nhập muộn | Dữ liệu mới với hệ thống không đồng nghĩa với diễn biến mới của con. Cần so thời điểm sự việc, không dùng thứ tự nhập. |

Đối với chuỗi cập nhật, lấy output thật của lần trước vào `previousState.state`, giữ `snapshotId`, `version`, `createdAt` và danh sách toàn bộ `inputRevisionIds`. Chuẩn bị `inputChanges` như backend (sửa/xóa chứa revision cũ; observations chứa bản hiện hành). Không đưa output mock vào làm kết luận của model thật.

1. **Cùng dữ liệu đánh giá lại:** `inputChanges` ba mảng rỗng. Cách hiểu và hướng dẫn còn phù hợp nên được giữ, không đổi câu chỉ vì có version mới. Summary về hiện tại khác phần giải thích thay đổi.
2. **Bổ sung một nguồn củng cố:** thêm observation mới; kiểm tra model có giữ đúng giới hạn cũ và giải thích vì sao có/không thay đổi đáng kể. Không tăng trend chỉ do số lượng báo cáo tăng.
3. **Bổ sung thông tin trái chiều:** thêm một tình huống ở bối cảnh khác; kiểm tra model xem lại cách hiểu và câu hỏi thay vì bỏ nguồn trước.
4. **Sau khi thử cách hỗ trợ:** thêm phản hồi có thời điểm sau các sự việc ban đầu và cùng hoạt động. Recommendation cần nói phụ huynh/mentor nên điều chỉnh gì, ExpectedOutcome nói điều gì cần theo dõi; không ép tạo một hành động mới nếu chưa cần.
5. **Sửa/xóa căn cứ duy nhất:** giữ bản cũ trong inputChanges, bỏ khỏi observations. Nhận định hiện tại không được trích bản đã rút; ChangeSummary có thể dẫn nó để giải thích việc bỏ hướng dẫn cũ.
6. **Mốc cũ không có dimension:** previousState giữ overview/dimension/status/trend/kind null. Không suy diễn dimension của kết quả cũ để tuyên bố trend; lần mới có tổng quan và khía cạnh đúng bằng chứng, trend Unknown cho mục chưa có mốc.

Đạt khi mỗi câu tổng quan truy được vào chi tiết; mỗi nhận định/giả thuyết truy được vào revision hiện hành; lời khuyên có hành động, căn cứ và điều cần theo dõi; mục không biết vẫn được thừa nhận. Thứ tự ba ưu tiên đầu cần hợp lý với nhu cầu trước mắt, không phụ thuộc thứ tự enum. Chất lượng từng hành động phải được đọc xét riêng, không thay bằng kiểm tra confidence hoặc trạng thái thông tin.


## Trọng tâm đầu ra cho phụ huynh và mentor

Dùng ba báo cáo ví dụ: phụ huynh kể chơi game trước bài tập; teen nói khó bắt đầu nhưng thường làm xong; mentor thấy tập trung và phản ứng tốt với bước nhỏ. Đây là dữ liệu để rà khả năng tổng hợp, không phải đáp án bắt buộc hoặc evidence dùng cho hồ sơ khác.

- Có một giả thuyết chính rõ ràng về bước bắt đầu, phân biệt với khả năng làm tiếp; vẫn thừa nhận lời tự kể chưa chứng minh khả năng hoàn thành ở mọi bối cảnh. `isPrimary` chọn theo giá trị giải thích/kiểm chứng, không phải confidence lớn nhất.
- Bằng chứng nối được vai trò từng nguồn, không đơn thuần chép lại ba báo cáo hoặc coi tất cả là bằng chứng xác nhận nguyên nhân.
- Phụ huynh biết việc nhỏ nên thử và cần ghi nhận gì. Mentor có việc kiểm tra bổ sung trong buổi gặp. Không suy ra game là nguyên nhân chính, cũng không khẳng định game không có vai trò.
- Rationale của mỗi việc trả lời rõ: vì sao có thể thử có giới hạn hoặc cần hỏi trước, và điều gì còn chưa chắc. Không dùng số 0.72 như đáp án chuẩn, không dùng một ngưỡng confidence để quyết định mọi hành động.
- Câu hỏi ưu tiên giúp phân biệt các cách giải thích, ví dụ việc trì hoãn chỉ ở bài tập hay cả hoạt động ưa thích. Thiếu căn cứ có thể không có giả thuyết hoặc hướng dẫn cho một hoặc cả hai đối tượng.
- Đánh giá lại cùng dữ liệu không tự thay giả thuyết chính. Bổ sung phản hồi có thể củng cố/điều chỉnh nó; xóa căn cứ cần xem lại. Nhãn phiên bản mới hoặc ChangeSummary khác không tự chứng minh tiến bộ.
- Đầu ra chính hiểu được mà không cần đọc tên dimension. Giữ các chi tiết có căn cứ cho người muốn tìm hiểu sâu.

Rà từng lần chạy model thật theo các câu hỏi trên; chỉ ghi kết quả khi đã thực sự gọi model được phép dùng. Bộ kiểm thử tự động mặc định không thực hiện bước này.
