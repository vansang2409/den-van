"""Các kết nối dịch vụ. Khóa được đọc từ môi trường ngay trước khi gọi."""
import base64
import json
import mimetypes
import os
import time
import uuid
from urllib.error import HTTPError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen


class BatchComplete(Exception):
    pass


remaining_calls = None


def limit_calls(count):
    global remaining_calls
    if count is not None and count < 1:
        raise ValueError("--limit cần là số nguyên dương.")
    remaining_calls = count


def required(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"Thiếu biến môi trường {name}.")
    return value


def http(url, headers=None, payload=None, raw=False):
    global remaining_calls
    if payload is not None and remaining_calls is not None:
        if not remaining_calls:
            raise BatchComplete("Đã đạt số lượt API của đợt này. Dùng run --live để tiếp tục.")
        remaining_calls -= 1
    headers = dict(headers or {})
    if isinstance(payload, dict):
        payload = json.dumps(payload, ensure_ascii=False).encode()
        headers["Content-Type"] = "application/json"
    try:
        with urlopen(Request(url, data=payload, headers=headers), timeout=300) as result:
            data = result.read()
    except HTTPError as exc:
        raise ValueError(f"{urlsplit(url).hostname} trả HTTP {exc.code}. Kiểm tra quyền, quota và tham số.") from None
    return data if raw else json.loads(data)


def auth():
    return {"Authorization": "Bearer " + required("OPENAI_API_KEY")}


def data_uri(path):
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def response(instructions, question, images=(), structured=False):
    content = [{"type": "input_text", "text": question}]
    content.extend({"type": "input_image", "image_url": data_uri(path)} for path in images)
    body = {"model": os.getenv("STUDIO_TEXT_MODEL", "gpt-6.1-terra"),
            "instructions": instructions, "input": [{"role": "user", "content": content}],
            "store": False, "max_output_tokens": 10000}
    if structured:
        body["text"] = {"format": {"type": "json_object"}}
    obj = http("https://api.openai.com/v1/responses", auth(), body)
    if obj.get("status") != "completed":
        raise ValueError("Phản hồi văn bản chưa hoàn chỉnh. Kiểm tra giới hạn model.")
    result = "\n".join(c["text"] for m in obj["output"] for c in m.get("content", [])
                       if c["type"] == "output_text").strip()
    if not result:
        raise ValueError("Agent chưa trả nội dung.")
    return json.loads(result) if structured else result


def frame(prompt, refs):
    fields = {"model": os.getenv("STUDIO_IMAGE_MODEL", "gpt-image-2"), "prompt": prompt,
              "size": "1280x720", "quality": "medium", "output_format": "png"}
    url = "https://api.openai.com/v1/images/"
    headers = auth()
    if refs:
        boundary = uuid.uuid4().hex
        parts = []
        for key, value in fields.items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
        for i, path in enumerate(refs):
            mime = mimetypes.guess_type(path.name)[0]
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="image[]"; filename="ref{i}{path.suffix}"\r\nContent-Type: {mime}\r\n\r\n'.encode())
            parts.extend([path.read_bytes(), b"\r\n"])
        parts.append(f"--{boundary}--\r\n".encode())
        headers["Content-Type"] = "multipart/form-data; boundary=" + boundary
        result = http(url + "edits", headers, b"".join(parts))
    else:
        result = http(url + "generations", headers, fields)
    return base64.b64decode(result["data"][0]["b64_json"], validate=True)


def runway_headers():
    return {"Authorization": "Bearer " + required("RUNWAYML_API_SECRET"),
            "X-Runway-Version": "2024-11-06"}


def start_video(image, motion, duration):
    uri = data_uri(image)
    if len(uri) > 5_000_000:
        raise ValueError("Keyframe vượt giới hạn data URI 5 MB của Runway.")
    body = {"model": "gen4_turbo", "promptImage": uri, "promptText": motion[:1000],
            "ratio": "1280:720", "duration": duration}
    return http("https://api.dev.runwayml.com/v1/image_to_video", runway_headers(), body)["id"]


def finish_video(job_id):
    url = "https://api.dev.runwayml.com/v1/tasks/" + quote(job_id, safe="")
    for _ in range(60):
        task = http(url, runway_headers())
        if task["status"] == "SUCCEEDED":
            output = task["output"][0]
            if urlsplit(output).scheme != "https":
                raise ValueError("Địa chỉ kết quả video không hợp lệ.")
            return http(output, raw=True)
        if task["status"] in {"FAILED", "CANCELED", "CANCELLED"}:
            raise ValueError(f"Job {job_id} đã {task['status']}. Xem lỗi trong Runway rồi dùng retake.")
        time.sleep(8)
    raise ValueError(f"Job {job_id} còn chờ. Chạy lại run để tiếp tục job hiện tại.")


def sound(prompt, duration):
    return http("https://api.elevenlabs.io/v1/sound-generation",
                {"xi-api-key": required("ELEVENLABS_API_KEY")},
                {"text": prompt, "duration_seconds": duration}, raw=True)


def speech(voice_id, line):
    return http("https://api.elevenlabs.io/v1/text-to-speech/" + quote(voice_id, safe=""),
                {"xi-api-key": required("ELEVENLABS_API_KEY")},
                {"text": line, "model_id": "eleven_flash_v2_5", "language_code": "vi"}, raw=True)
