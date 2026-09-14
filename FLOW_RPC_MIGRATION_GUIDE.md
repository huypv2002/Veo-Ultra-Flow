# Google Flow: Tài Liệu Chuyển Đổi Từ HTTP REST Auth (OAuth2) Sang batchexecute RPC

> **Mục tiêu tài liệu**: Phân tích chuyên sâu kiến trúc mạng nội bộ của Google Flow (`flow.google.com`), giải thích nguyên nhân thất bại của phương thức REST API cũ (`aisandbox-pa.googleapis.com` + OAuth2 Bearer), và cung cấp tài liệu kỹ thuật chi tiết để chuyển đổi hoàn toàn sang giao thức **batchexecute RPC** (Zero-Credit, Cookie Session + reCAPTCHA Enterprise).

---

## 1. Bối Cảnh & Lý Do Chuyển Đổi Kiến Trúc

### 1.1. Phương thức cũ: REST API qua Google API Sandbox
Trong các phiên bản trước, việc sinh ảnh/video trên Google Flow được thực hiện bằng cách gọi trực tiếp vào API Gateway:
- **Endpoint**: `https://aisandbox-pa.googleapis.com/v1/projects/{projectId}/flowMedia:batchGenerateImages`
- **Cơ chế xác thực**: Bắt buộc gắn Header OAuth2:
  ```http
  Authorization: Bearer ya29.a0AdMD6Eh...
  ```
- **Hạn chế nghiêm trọng**:
  1. **Token Lifetime cực ngắn**: Access token `ya29` chỉ có hiệu lực từ 15 đến 60 phút. Khi hết hạn, endpoint trả về lỗi:
     ```json
     {
       "error": {
         "code": 401,
         "message": "Request had invalid authentication credentials. Expected OAuth 2 access token, login cookie or other valid authentication credential.",
         "status": "UNAUTHENTICATED"
       }
     }
     ```
  2. **Cơ chế lấy token OAuth2 bị khóa**: Trên domain mới `flow.google.com`, Google không còn tự do cấp phát hoặc refresh `ya29` token qua RPC trpc công khai. Các request re-fetch token liên tục dính `401 Unauthorized`.
  3. **Trừ Credit & Paygate Tier**: Các lệnh gọi qua REST Gateway bị áp đặt hạn ngạch Paygate (`G1_PAYGATE_TIER`), làm tiêu tốn credits nhanh chóng và thường xuyên bị chặn khi tài khoản hết hạn ngạch.

### 1.2. Phương thức mới: batchexecute RPC Protocol
Google Flow trên web chạy trên nền tảng **BOQ (Google Application Framework)**, sử dụng giao thức chuẩn hóa `batchexecute` thay vì REST truyền thống:
- **Endpoint**: `https://flow.google.com/_/LabsFlowUi/data/batchexecute` (hoặc `AiSandboxAngularFrontend`)
- **Cơ chế xác thực**:
  - **Không dùng `Authorization: Bearer ya29`**.
  - **Cookie Session Google**: Bao gồm `SSID`, `SAPISID`, `__Secure-1PAPISID`, `SID`, `HSID`,...
  - **reCAPTCHA Enterprise Token**: Gắn trực tiếp vào envelope context theo từng `action` (`IMAGE_GENERATION` hoặc `VIDEO_GENERATION`).
- **Ưu điểm vượt trội**:
  - ✅ **0 Credit Consumption**: Các phiên Flow Live chạy qua RPC được tính là tương tác web nội bộ, giữ nguyên số credits gốc (ví dụ cố định 3 credits, không bị trừ).
  - ✅ **Không bao giờ bị lỗi 401 Token Expiration**: Cookie Google có thời hạn sống dài hàng tháng, không cần cơ chế refresh OAuth token liên tục.
  - ✅ **Tốc độ phản hồi cao**: Kết nối HTTP/2 / HTTP/3 trực tiếp đến server `flow.google.com`.

---

## 2. So Sánh Chi Tiết: REST API vs batchexecute RPC

| Tiêu chí | REST API (Cũ - Deprecated) | batchexecute RPC (Mới - Khuyến nghị) |
| :--- | :--- | :--- |
| **Domain & Path** | `aisandbox-pa.googleapis.com/v1/...` | `flow.google.com/_/LabsFlowUi/data/batchexecute` |
| **Authentication** | `Authorization: Bearer ya29...` | Google Cookies (`__Secure-1PAPISID`, `SAPISID`...) |
| **reCAPTCHA Token** | Gửi trong JSON payload `clientContext.recaptchaContext.token` | Nhúng vào mảng context envelope `[CAPTCHA_SLOT, 1]` |
| **Định dạng Request** | JSON thuần (`application/json`) | Form URL Encoded (`f.req=[[[rpcid, payload, ...]]]`) |
| **Định dạng Response** | JSON chuẩn | Google chunked array có Anti-XSSI prefix `)]}'` |
| **RPC ID đại diện** | Không có (xác định qua URL path) | `ogiZ0b` (Image), `eb1hJf` (Video), `nzlxg` (Credits) |
| **Mức tiêu hao Credit** | Trừ credit hoặc chặn theo Paygate Tier | **0 credit** (hoàn toàn miễn phí trên Live session) |
| **Độ ổn định Token** | Kém (hết hạn sau 15-60 phút) | Rất cao (đồng bộ với phiên đăng nhập Google) |

---

## 3. Đặc Tả Wire Format Của Giao Thức batchexecute

Giao thức `batchexecute` của Google đóng gói (envelope) một hoặc nhiều RPC calls vào trong một HTTP POST request duy nhất.

### 3.1. Cấu trúc URL & Query Parameters
Request được gửi tới URL:
```
POST https://flow.google.com/_/LabsFlowUi/data/batchexecute?rpcids={rpcid}&source-path=%2F&hl=vi&_reqid={reqid}&rt=c
```
- `rpcids`: Tên RPC đang thực thi (ví dụ: `ogiZ0b`).
- `source-path`: Trang nguồn trên frontend (`%2F` tương đương `/`).
- `hl`: Mã ngôn ngữ (`vi`, `en`).
- `_reqid`: Số nguyên ngẫu nhiên đại diện cho request ID (ví dụ: `100000 + random(0, 900000)`).
- `rt`: Kiểu trả về, `c` viết tắt của chunked transfer encoding.

### 3.2. Cấu trúc Request Body (`f.req`)
Body của POST request bắt buộc có `Content-Type: application/x-www-form-urlencoded;charset=UTF-8` chứa tham số `f.req`:

```text
f.req=[[["{rpcid}","{escaped_inner_json_payload}",null,"generic"]]]
```

> **Quy tắc quan trọng**: `inner_json_payload` bên trong mảng là một chuỗi JSON đã được escape chuỗi (JSON stringified).

Ví dụ cấu trúc envelope bằng Python:
```python
import json

def build_envelope(rpcid: str, payload: Any) -> str:
    inner_json = json.dumps(payload, separators=(',', ':'))
    req_array = [[[rpcid, inner_json, None, "generic"]]]
    return "f.req=" + urllib.parse.quote(json.dumps(req_array, separators=(',', ':')))
```

### 3.3. Cấu trúc Response Wire Format
Server Google trả về dữ liệu dạng text chunked với Anti-XSSI prefix ở dòng đầu:
```text
)]}'
245
[["wrb.fr","ogiZ0b","[\"https://flow-content.google/image/...\", ...]",null,null,null,"generic"]]
```

Quy trình parse response:
1. Bỏ qua tiền tố `)]}'` ở đầu dòng.
2. Tìm các mảng JSON chứa tag `"wrb.fr"`.
3. Kiểm tra phần tử index 1 (`entry[1] == rpcid`).
4. Phần tử index 2 (`entry[2]`) chính là payload kết quả (dạng JSON string). Parse chuỗi này để lấy dữ liệu thực tế.
5. Nếu `entry[2]` là `None` và có `entry[5]`, RPC đã trả về mã lỗi nghiệp vụ.

---

## 4. Danh Mục Các RPC Methods Trên Google Flow

### 4.1. RPC `ogiZ0b` — Sinh Ảnh (Generate Images)
Thay thế cho REST endpoint `flowMedia:batchGenerateImages`.

#### Cấu trúc Inner Payload:
```json
[
  null,
  [
    [
      null,
      null,
      null,                           // Reference media IDs (nếu có): [[media_id, null, null, null, 1]]
      17461,                          // Random Seed
      3,                              // Aspect Ratio Code: 1 (1:1), 2 (9:16), 3 (16:9), 4 (3:4), 5 (4:3)
      "GEM_PIX_2",                    // Model Key: "GEM_PIX_2" (Banana Pro) hoặc "NARWHAL" (Standard)
      null,
      [null, 22, null, null, null, "{project_id}", null, null, null, null, ["{RECAPTCHA_TOKEN}", 1]],
      [[["{prompt_text}"]]],          // Prompt đặt trong 3 lớp mảng
      null,
      null,
      null,
      "{client_uuid_1}",
      "{client_uuid_2}"
    ]
  ],
  1,
  [null, 22, null, null, null, "{project_id}", null, null, null, null, ["{RECAPTCHA_TOKEN}", 1]],
  ["{batch_uuid}"]
]
```

#### Bảng Ánh Xạ Aspect Ratio (Image):
| Tên Aspect Ratio | Mã Số Giao Thức (int) | Độ phân giải tương ứng |
| :--- | :---: | :--- |
| `IMAGE_ASPECT_RATIO_SQUARE` (1:1) | `1` | 1024 x 1024 |
| `IMAGE_ASPECT_RATIO_PORTRAIT` (9:16) | `2` | 768 x 1376 |
| `IMAGE_ASPECT_RATIO_LANDSCAPE` (16:9) | `3` | 1376 x 768 |
| `IMAGE_ASPECT_RATIO_PORTRAIT_FOUR_THREE` (3:4) | `4` | 896 x 1200 |
| `IMAGE_ASPECT_RATIO_LANDSCAPE_FOUR_THREE` (4:3) | `5` | 1200 x 896 |

#### Dữ liệu trả về (Output Data):
Payload giải mã từ RPC `ogiZ0b` chứa danh sách các URL CDN có chữ ký tạm thời:
```text
https://flow-content.google/image/{media_id}?Expires={timestamp}&GoogleAccessId=...&Signature=...
```
Từ URL này, ta trích xuất được `media_id` (UUID 36 ký tự) và đường dẫn tải ảnh trực tiếp mà không cần header xác thực đặc biệt nào khác.

---

### 4.2. RPC `eb1hJf` — Sinh Video (Generate Video)
Thay thế cho REST endpoint `whisk:generateVideo` hoặc `flowMedia:batchGenerateVideos`.

#### Cấu trúc Inner Payload:
```json
[
  [
    [
      [
        [null, null, [[["{prompt_text}"]]]],
        "veo_3_1_i2v_lite_low_priority", // Model Video
        2,                               // Aspect: 1 (9:16 Portrait), 2 (16:9 Landscape)
        null,
        [null, "{source_image_media_id}", null, null, null, [null, 0.00387, 1, 0.9961]], // Reference Image
        [null, null, null, null, "{client_uuid_1}", "{client_uuid_2}"]
      ]
    ]
  ],
  [null, 22, null, null, null, "{project_id}", null, null, null, null, ["{RECAPTCHA_TOKEN}", 1]],
  ["{batch_uuid}", 2]
]
```

#### Dữ liệu trả về:
Trả về `operation_id` (ví dụ: `operations/pinhole/...`) và `media_id` phục vụ việc thăm dò (polling).

---

### 4.3. RPC `jwpduf` — Thăm Dò Tiến Độ Video (GetOperation)
- **Input**: `[null, null, [["{operation_id}"]]]`
- **Output**: Trạng thái render:
  - Khi hoàn thành: `status == "CAE"`.
  - Kết quả đi kèm: `media_id` của video đã render xong.

---

### 4.4. RPC `as29s` — Lấy URL Video Hoàn Chỉnh (GetMedia)
- **Input**: `["{media_id}"]`
- **Output**: Link video MP4 CDN có chữ ký (`https://flow-content.google/video/{media_id}?...`).

---

### 4.5. RPC `nzlxg` — Lấy Số Dư Credit & Tier (GetCredits)
- **Input**: `[]`
- **Output**: Mảng `[credits_remaining, tier_number, ...]`, ví dụ: `[3, 2, ...]` biểu thị còn **3 credits**, tài khoản thuộc **TIER_2**.

---

### 4.6. RPC `maseQ` — Upload Ảnh Làm Tham Chiếu (UploadMedia)
- **Input**:
  ```json
  [
    [null, 22, null, null, null, "{project_id}", null, null, null, null, ["{RECAPTCHA_TOKEN}", 1]],
    "{base64_image_bytes}",
    "image/jpeg",
    1,
    null, null, null, null,
    "upload.jpg",
    null,
    "{client_uuid_1}", "{client_uuid_2}"
  ]
  ```
- **Output**: `media_id` đại diện cho ảnh vừa upload lên kho Google Flow.

---

## 5. Xác Thực Bằng Cookie & reCAPTCHA Enterprise

### 5.1. Bộ Headers Chuẩn Khi Gọi batchexecute
Khi thực hiện gọi request tới `flow.google.com`, **không được truyền** `Authorization: Bearer`:

```http
POST /_/LabsFlowUi/data/batchexecute?rpcids=ogiZ0b&source-path=%2F&hl=vi&_reqid=184921&rt=c HTTP/1.1
Host: flow.google.com
User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36
Accept: */*
Accept-Language: vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7
Content-Type: application/x-www-form-urlencoded;charset=UTF-8
Origin: https://flow.google.com
Referer: https://flow.google.com/
Cookie: SSID=...; SID=...; SAPISID=...; __Secure-1PAPISID=...; __Secure-3PSID=...
X-Same-Domain: 1
```

### 5.2. Cách Nhúng reCAPTCHA Enterprise Token
Google Flow sử dụng reCAPTCHA Enterprise Site Key trên domain `flow.google.com`:
- **Action cho Sinh Ảnh**: `"IMAGE_GENERATION"`
- **Action cho Sinh Video**: `"VIDEO_GENERATION"`

Vị trí đặt token trong Context Object của payload:
```python
def make_context(project_id: str, recaptcha_token: str) -> list:
    return [
        None,
        22,             # SURFACE_ID (Labs Flow)
        None,
        None,
        None,
        project_id,     # UUID Project Flow
        None,
        None,
        None,
        None,
        [recaptcha_token, 1]  # Slot gắn token reCAPTCHA Enterprise
    ]
```

Token được sinh trực tiếp từ trình duyệt thật (qua Chrome Extension Bridge) để đảm bảo Google Trust Score cao nhất (Score 0.9), triệt tiêu hoàn toàn mã lỗi 403 Forbidden.

---

## 6. Hướng Dẫn Code Minh Họa (Python Implementation)

Dưới đây là module chuẩn để gọi sinh ảnh qua RPC `ogiZ0b`:

```python
import json
import urllib.parse
import requests
import re

FLOW_BATCH_URL = "https://flow.google.com/_/LabsFlowUi/data/batchexecute"

def generate_flow_image_rpc(
    cookies_dict: dict,
    prompt: str,
    project_id: str,
    recaptcha_token: str,
    aspect_code: int = 3, # 3: 16:9 Landscape
    seed: int = 17461
) -> list[str]:
    """
    Sinh ảnh trực tiếp qua Google Flow RPC ogiZ0b.
    Trả về danh sách URL ảnh có chữ ký (CDN URLs).
    """
    # 1. Xây dựng Context Object
    context = [
        None, 22, None, None, None,
        project_id,
        None, None, None, None,
        [recaptcha_token, 1]
    ]

    # 2. Xây dựng mảng item
    item = [
        None,
        None,
        None,               # Reference media
        seed,
        aspect_code,
        "GEM_PIX_2",        # Nano Banana Pro
        None,
        context,
        [[[prompt]]],
        None,
        None,
        None,
        "9C35F92E-131B-4A73-A338-F1D19DA48967",
        "A8C66567-AE8C-479D-9F8C-521BCBDC2CA8"
    ]

    inner_payload = [
        None,
        [item],
        1,
        context,
        ["B7B309D1-45C7-47D2-89FC-2220AE2BBDB0"]
    ]

    # 3. Đóng gói f.req envelope
    inner_json_str = json.dumps(inner_payload, separators=(',', ':'))
    envelope = [[["ogiZ0b", inner_json_str, None, "generic"]]]
    encoded_body = "f.req=" + urllib.parse.quote(json.dumps(envelope, separators=(',', ':')))

    # 4. Thiết lập Headers
    headers = {
        "Host": "flow.google.com",
        "Origin": "https://flow.google.com",
        "Referer": "https://flow.google.com/",
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
        "X-Same-Domain": "1",
    }

    # 5. Gửi Request
    params = {
        "rpcids": "ogiZ0b",
        "source-path": "/",
        "hl": "vi",
        "_reqid": "521890",
        "rt": "c"
    }
    
    resp = requests.post(FLOW_BATCH_URL, params=params, headers=headers, cookies=cookies_dict, data=encoded_body, timeout=90)
    resp.raise_for_status()

    # 6. Parse Response lấy CDN URLs
    raw_text = resp.text
    cdn_urls = []
    
    # Bóc tách tất cả link https://flow-content.google/image/...
    matches = re.findall(r'(https://flow-content\.google/image/[^\s"\',\\]+)', raw_text)
    for url in matches:
        clean_url = url.replace(r'\u0026', '&')
        if clean_url not in cdn_urls:
            cdn_urls.append(clean_url)
            
    return cdn_urls
```

---

## 7. Xử Lý Tải Ảnh & Cơ Chế Fallback (`/bg-fetch`)

Khi tải ảnh thành phẩm từ URL `https://flow-content.google/image/{media_id}?Expires=...`:
1. **Direct Download**: Gọi `GET` thông thường bằng session chứa cookies hiện tại, không mang header `Authorization`.
2. **Fallback qua Extension Bridge**: Nếu môi trường client gặp sự cố chặn kết nối trực tiếp đến CDN Google (SSL Handshake, IP Restriction, Signed URL header mismatch):
   - Client gửi lệnh POST tới Bridge Server cục bộ:
     ```json
     POST http://127.0.0.1:3003/bg-fetch
     {
       "url": "https://flow-content.google/image/...",
       "timeout": 30
     }
     ```
   - Chrome Extension trong browser thật sẽ thực hiện `fetch()` URL với đầy đủ session context của trình duyệt, sau đó trả về dữ liệu Base64 để lưu file ảnh nguyên vẹn xuống ổ đĩa.

---

## 8. Kết Luận

Việc loại bỏ phương thức REST OAuth2 Bearer token cũ và chuyển dịch sang **batchexecute RPC** đã giải quyết triệt để 3 vấn đề cốt tử:
1. **Xóa sổ lỗi `401 Unauthorized (invalid_token)`**.
2. **Bảo toàn 100% hạn ngạch Credit (0 Credits consumed)**.
3. **Đồng bộ cơ chế reCAPTCHA Enterprise trực tiếp qua tab người dùng thật**, mang lại độ ổn định tối đa cho toàn bộ chu trình sinh ảnh và video trên Google Flow.
