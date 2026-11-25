# Đen & Vằn Studio

Studio sản xuất phim ngắn bằng tiếng Việt về đôi bạn chó Đen và mèo Vằn ở làng quê. Bạn đưa định hướng, góp ý và duyệt ba bản. Bộ điều phối lưu công việc theo tập để có thể tiếp tục sau khi đóng máy.

**Tập 01 đang chờ duyệt kịch bản.** Trong *Chừa tao một viên*, Vằn muốn nằm một mình dưới gầm chõng nên dụ Đen đi tìm viên gạch khô nhất nhà. Thời lượng dự kiến là 8 phút 40 giây. [Đọc kịch bản tập thử](creative/pilot.md) · [Sổ tay nhân vật và thế giới phim](creative/bible.md) · [Khảo sát công cụ và chi phí](docs/cong-cu.md)

## Vận hành trên máy này

Tại PowerShell, chạy các lệnh dưới đây từ thư mục dự án. Trên máy khác, có thể thay `.\studio.ps1` bằng `python -m studio` từ cùng thư mục. Bộ điều phối dùng Python 3.11 trở lên và thư viện chuẩn. Khâu xử lý media dùng FFmpeg và FFprobe, đã thử với bản 8.1 có libx264 và AAC.

Sau khi clone lần đầu, dùng `.\studio.ps1 init episodes/tap-01 --pilot` để khởi tạo thư mục riêng cho tập thử. Trên máy làm việc hiện tại thư mục này đã có sẵn.

```powershell
Set-Location -LiteralPath 'C:\den&van'
.\studio.ps1 status episodes/tap-01
```

Bạn có thể gửi quyết định hoặc góp ý ngay trong chat. Nếu dùng CLI, `status` hiển thị đường dẫn cần xem và mã phiên bản. Thay `MA_PHIEN_BAN` bằng mã vừa xem khi thực sự duyệt. Các lệnh dưới đây minh họa các thời điểm khác nhau trong quá trình làm phim.

| Khi cần | Thao tác |
|---|---|
| Góp ý kịch bản | `.\studio.ps1 rewrite episodes/tap-01 'Rút ngắn đoạn đợi mưa và giữ câu đùa cuối.'`, sau đó chạy `run --live` theo cú pháp bên dưới. Bản trước lưu trong `revisions/`. |
| Duyệt kịch bản | `.\studio.ps1 approve episodes/tap-01 script MA_PHIEN_BAN` |
| Gắn ảnh thật | `.\studio.ps1 ref episodes/tap-01 Đen 'D:\anh\den.jpg'` và `.\studio.ps1 ref episodes/tap-01 Vằn 'D:\anh\van.jpg'`. Có thể thêm 1–4 góc mỗi con. Dùng `--replace` để thay bộ ảnh của một con. |
| Chạy đến mốc kế | `.\studio.ps1 run episodes/tap-01 --live`. Để chỉ dùng tối đa 5 yêu cầu tạo nội dung trong lần chạy này, thêm `--limit 5`. Giá mỗi yêu cầu phụ thuộc công cụ. |
| Duyệt hình | Mở `storyboard.html` trong thư mục tập để đối chiếu ảnh gốc của Đen, Vằn và ảnh chuẩn bối cảnh với từng keyframe. Dùng `.\studio.ps1 approve episodes/tap-01 board MA_PHIEN_BAN`. |
| Chọn giọng | `.\studio.ps1 voices episodes/tap-01 VOICE_ID_DEN VOICE_ID_VAN`. Dùng ID hai giọng Việt đã nghe thử trong tài khoản ElevenLabs. Có thể đặt trước khi duyệt hình. |
| Sửa một shot | `.\studio.ps1 retake episodes/tap-01 video S012 'Giữ chân sau trên nền gạch khi quay đầu'`, rồi chạy lại. Chọn `frame`, `video`, `voice` hoặc `sound` theo hạng mục. |
| Duyệt và xuất | Xem phim ngang, đoạn dọc, nghe thoại và kiểm tra nội dung đăng ở thư mục `status` chỉ ra. Dùng `.\studio.ps1 approve episodes/tap-01 final MA_PHIEN_BAN`, sau đó `.\studio.ps1 release episodes/tap-01 releases/tap-01`. Gói này sẵn sàng để chủ kênh đăng. |
| Làm tập tiếp | `.\studio.ps1 init episodes/tap-02 --from-episode episodes/tap-01 --brief 'Một buổi trông sân ở làng quê'`. Lệnh kế thừa ảnh thật, hồ sơ nhận diện, ảnh chuẩn bối cảnh, bible, giọng đã chọn và kịch bản từ tập trước đã duyệt hình. |

### Cấu hình dịch vụ

Thiết lập các biến môi trường trong phiên chạy hoặc trình quản lý bí mật trên máy. Tài khoản từng dịch vụ cần quyền dùng model tương ứng và hạn mức chi trả.

| Biến | Công đoạn |
|---|---|
| `OPENAI_API_KEY` | Viết, lập shot, phân tích ảnh tham chiếu, tạo keyframe, nhận xét khung hình, soạn nội dung đăng |
| `RUNWAYML_API_SECRET` | Tạo video từ keyframe đã duyệt và theo dõi job Gen-4 Turbo |
| `ELEVENLABS_API_KEY` | Lồng tiếng Việt bằng Flash v2.5 và tạo ambience/foley |
| `FFMPEG`, `FFPROBE` | Đường dẫn hai chương trình khi máy chưa có trong PATH. Trình chạy PowerShell cũng tìm bản FFmpeg cài qua WinGet. |

`STUDIO_TEXT_MODEL` và `STUDIO_IMAGE_MODEL` cho phép đổi model tương thích với các endpoint hiện có. Mặc định là `gpt-6.1-terra` và `gpt-image-2`. Khi chạy live, ảnh tham chiếu được gửi cho OpenAI để làm hình và kiểm tra nhận diện, keyframe được gửi cho Runway, lời thoại và mô tả âm thanh được gửi cho ElevenLabs. Có thể đặt bản nhạc có quyền sử dụng vào `music.mp3` trong thư mục tập trước khi dựng.

## 10 vai trò và đường đi của một tập

Các vai trò dùng chung hợp đồng bàn giao theo shot. Phần sáng tạo dùng prompt theo vai, còn phê duyệt, tính phiên bản, quản lý job và dựng media được thực thi bằng mã. [Bộ chỉ dẫn của 10 vai trò](creative/agents.json)

| Bước | Phụ trách | Bàn giao và mốc duyệt |
|---|---|---|
| 1–3 | Executive Producer, Story Writer | Định hướng → ý tưởng → kịch bản có mốc thời gian và lời Việt. **Chủ dự án duyệt kịch bản.** |
| 4 | Screenwriter & Scene Planner | Phân cảnh và shot 3–10 giây, tổng 480–600 giây. Mỗi shot có nhân vật, hình, hành động, máy quay, âm thanh, thoại, thời lượng và trạng thái cuối để nối cảnh. |
| 5–6 | Character Director, Visual Director | Gắn ảnh thật, ghi đặc điểm nhìn thấy, dựng keyframe và storyboard đối chiếu được với ảnh nguồn. **Chủ dự án duyệt nhận diện và storyboard.** |
| 7–8 | AI Video Producer, Voice Director | Tạo clip, lưu mã job, gọi từng câu thoại theo voice ID, căn cue, thêm âm thanh sân làng và tiếng động theo shot. |
| 9–11 | Film Editor, Quality Controller | So đầu/giữa/cuối clip với ảnh và keyframe. Báo shot cần sửa. Ghép các shot đạt, đo thời lượng hình–tiếng, xuất phụ đề. Người duyệt xem chuyển động liên tục, nhịp cắt và nghe toàn bộ bản mix. |
| 12–13 | Publishing Manager, Film Editor, Executive Producer | Soạn tiêu đề, mô tả, hashtag và caption riêng cho TikTok, Reels, Shorts. Chọn timecode thumbnail và đoạn dọc, dựng file thực. **Chủ dự án duyệt gói cuối trước khi xuất.** |

Mỗi tập có lịch sử tại `approvals.json`. Khi đổi kịch bản, hệ thống yêu cầu duyệt lại kịch bản. Khi đổi ảnh, keyframe hoặc phân cảnh, hệ thống tính lại phiên bản storyboard. Khi đổi clip bằng `retake`, chọn lại giọng, thay nhạc hoặc sửa tệp trong gói cuối, lệnh xuất đối chiếu lại phiên bản được duyệt. Khóa theo thư mục tập giúp hai phiên chạy tránh đặt trùng cùng một job. Mã job đã lưu cho phép tiếp tục thăm dò sau khi mất kết nối.

### Giữ hình ảnh nhất quán qua các tập

Mỗi địa điểm có một mã dùng chung. Ví dụ `nha-mai-ngoi` bao gồm sân, hiên và ngưỡng cửa của cùng một nhà. Lần đầu xuất hiện, studio tạo một ảnh chuẩn góc rộng để bạn duyệt cùng storyboard. Các shot quay lại địa điểm đó dùng ảnh chuẩn để giữ vật liệu, mốc cố định và bố cục. Góc quay, ánh sáng, thời tiết và đạo cụ di động thay đổi theo nội dung. Bước QC đối chiếu ảnh chuẩn và ảnh nhân vật với khung đầu, giữa và cuối clip.

Khi nối tập bằng `--from-episode`, runner ghi mã storyboard nguồn và mang theo cả những địa điểm đã duyệt từ các tập trước đó. Nếu cần sửa một địa điểm, dùng `.\studio.ps1 retake episodes/tap-01 location nha-mai-ngoi 'Giữ sân gạch và mở rộng góc thấy cột hiên'`. Studio lấy ảnh hiện hành làm gốc, dựng lại các shot liên quan và chờ duyệt storyboard mới.

### Kiểm tra và xử lý lỗi

- Tệp `plans/.../shots.json` chứa danh sách shot. Runner kiểm thứ tự ID, tổng giây, biên cue và người nói. Dòng thoại trong kịch bản theo mẫu `**Đen** — lời nói` hoặc `**Vằn** — lời nói` được đối chiếu nguyên văn, theo thứ tự.
- Nếu model trả phân cảnh sai, runner gửi lại lỗi một lần và lưu bản trả sai ở tệp `.invalid.json`. Khi hết quota hoặc gián đoạn mạng, sửa điều kiện được báo rồi dùng lại `run --live`.
- QC hình gửi nhận xét và mã shot cho Video Producer để tự tạo lại tối đa một lần cho mỗi yêu cầu. Nếu shot vẫn lỗi, runner dừng tại shot đó. Khi lỗi nằm ngay ở keyframe, chọn `retake frame`. Với thoại quá dài, chỉnh khoảng cue trong shot và duyệt lại storyboard. Mỗi cú cắt dọc có một vị trí crop cố định, cần xem lại đoạn mà hai con đi tách xa nhau.
- Bộ dựng độc lập nhận được clip từ công cụ khác qua manifest cục bộ. `python -m studio.media check manifest.json` kiểm đầu vào. `python -m studio.media render manifest.json thu-muc-moi` dựng phim. Thêm `--sample` để thử đoạn ngắn. Cú pháp manifest xem trong [kiểm thử dựng mẫu](tests/test_media.py).
- Gói đầu ra gồm `film.mp4` (1920×1080), `vi.srt`, `thumbnail.jpg`, `shorts/*.mp4` (1080×1920), phụ đề từng đoạn, `qc.json` và `publishing.json`.

## Mức kiểm chứng

Đã thử các mốc duyệt qua CLI, tiếp tục job bị gián đoạn, kiểm lời thoại, trích khung để QC và dựng đoạn mẫu có tiếng bằng FFmpeg/FFprobe 8.1. Các dịch vụ sinh nội dung dùng phản hồi giả lập trong bộ test. Tập 01 đang ở bản nháp kịch bản. Độ giống hai con qua chuyển động, chất giọng tiếng Việt và chi phí thực tế cần được đo trên ảnh thật và tài khoản sản xuất. Để chạy bộ test cục bộ, dùng `python -m unittest discover -s tests -v`; các test media cần FFmpeg và FFprobe.
