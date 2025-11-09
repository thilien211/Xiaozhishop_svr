
## 🚀 Cách cài xiaozhishop svr
### 👉 Code được mod lại từ code của bác Trần Thương, E Cảm ơn bác đã chia sẻ code zingmp3 siêu hữu ích cho tất cả mọi người nhé! 🥰

Git Clone repo trước:
```bash
git clone https://github.com/thilien211/Xiaozhishop_svr.git
```

Thực hiện vào thư mục và tạo venv:
```bash
cd Xiaozhishop_svr
python3 -m venv .xiaozhi
```
Vào môi trường venv:
```bash
source .xiaozhi/bin/activate
```
Thực hiện cài requirements:
```bash
pip install flask requests
```
Chạy server:
```bash
python xiaozhi.py
```
Test server:
```bash
curl http://localhost:5005/stream_pcm?song=Đừng Làm Trái Tim Anh Đau
```

(Tùy chọn) Chạy server trong nền và lưu log:
```bash
nohup python xiaozhi.py > xiaozhi.log 2>&1 &
```
Kiểm tra tiến trình:
```bash
ps aux | grep xiaozhi.py
```
Tắt tiến trình:
```bash
kill $(pgrep -f xiaozhi.py)
```
(Tùy chọn) Khởi động cùng hệ thống:

Em lười quá nhờ các bác hỏi AI ạ 😀
