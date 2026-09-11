"""Google Flow batchexecute RPC Codec and Protocol Engine.

Implements encoding of request envelopes and decoding of response payloads for
Google Flow's AiSandboxAngularFrontend BOQ batchexecute API:
    https://flow.google.com/_/AiSandboxAngularFrontend/data/batchexecute

Wire format:
    f.req = [[[rpcid, "<inner payload JSON string>", null, "generic"]]]

Response format:
    )]}'
    <byte_length>
    [["wrb.fr", rpcid, "<inner payload JSON string>", null, null, null, "generic"], ...]
"""
from __future__ import annotations

import json
import random
import re
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, NamedTuple, Optional, Tuple, Union

BATCH_PATH = "/_/AiSandboxAngularFrontend/data/batchexecute"
MEDIA_HOST = "flow-content.google"
DEFAULT_PROJECT_ID = "f1ed51bc-cf49-4907-8440-ddb25e699158"

# ── RPC IDs ──────────────────────────────────────────────────────────────────
RPC_CREDITS = "nzlxg"        # GetCredits: [] -> [credits, tier, ..., credits]
RPC_GEN_IMAGE = "ogiZ0b"      # GenerateImage: [context, prompt, aspect, count, ...] -> Signed Image CDN URLs
RPC_UPLOAD_IMAGE = "maseQ"   # UploadMedia: [context, base64_bytes, mime, ...] -> media_id
RPC_GEN_VIDEO = "eb1hJf"      # GenerateVideo: [context, model, duration, source_media_id, ...] -> op_id & media_id
RPC_OPERATION = "jwpduf"      # GetOperation: [null, null, [[op_id]]] -> status (CAE = done)
RPC_MEDIA = "as29s"          # GetMedia: [media_id] -> Signed Video CDN URL
RPC_PROJECT_MEDIA = "Zzl0ze"  # GetProjectMedia: [project_path, ...] -> project items

# ── reCAPTCHA Enterprise Action Names ────────────────────────────────────────
CAPTCHA_IMAGE = "IMAGE_GENERATION"
CAPTCHA_VIDEO = "VIDEO_GENERATION"
CAPTCHA_SLOT = "__CAPTCHA__"

# ── Image Model Keys ─────────────────────────────────────────────────────────
IMAGE_MODELS = {"GEM_PIX_2", "NARWHAL"}
IMAGE_MODEL = "GEM_PIX_2"  # Nano Banana Pro by default
IMAGE_MODEL_BY_NICKNAME = {
    "NANO_BANANA_PRO": "GEM_PIX_2",
    "NANO_BANANA_2": "NARWHAL",
    "pro": "GEM_PIX_2",
    "standard": "NARWHAL",
    "lite": "NARWHAL",
}

# ── Image Aspect Ratios ──────────────────────────────────────────────────────
ASPECT_SQUARE = 1           # 1024x1024 (1:1)
ASPECT_PORTRAIT = 2         # 768x1376  (9:16)
ASPECT_LANDSCAPE = 3        # 1376x768  (16:9)
ASPECT_PORTRAIT_4_3 = 4     # 896x1200  (3:4)
ASPECT_LANDSCAPE_4_3 = 5    # 1200x896  (4:3)

ASPECT_BY_NAME = {
    "IMAGE_ASPECT_RATIO_SQUARE": ASPECT_SQUARE,
    "IMAGE_ASPECT_RATIO_PORTRAIT": ASPECT_PORTRAIT,
    "IMAGE_ASPECT_RATIO_LANDSCAPE": ASPECT_LANDSCAPE,
    "IMAGE_ASPECT_RATIO_PORTRAIT_FOUR_THREE": ASPECT_PORTRAIT_4_3,
    "IMAGE_ASPECT_RATIO_LANDSCAPE_FOUR_THREE": ASPECT_LANDSCAPE_4_3,
    "VIDEO_ASPECT_RATIO_PORTRAIT": ASPECT_PORTRAIT,
    "VIDEO_ASPECT_RATIO_LANDSCAPE": ASPECT_LANDSCAPE,
    "portrait": ASPECT_PORTRAIT,
    "landscape": ASPECT_LANDSCAPE,
    "square": ASPECT_SQUARE,
    "9:16": ASPECT_PORTRAIT,
    "16:9": ASPECT_LANDSCAPE,
    "1:1": ASPECT_SQUARE,
    "4:3": ASPECT_LANDSCAPE_4_3,
    "3:4": ASPECT_PORTRAIT_4_3,
}

# ── Video Models & Aspects ───────────────────────────────────────────────────
VIDEO_MODEL = "veo_3_1_i2v_lite_low_priority"
VIDEO_MODELS = {
    "veo_3_1_t2v_lite_4s",
    "veo_3_1_t2v_lite_4s_low_priority",
    "veo_3_1_i2v_lite_low_priority",
    "veo_3_1_i2v_lite",
    "veo_3_1_i2v_s_fast_ultra",
}

VIDEO_ASPECT_PORTRAIT = 1   # 720x1280 (9:16)
VIDEO_ASPECT_LANDSCAPE = 2  # 1280x720 (16:9)

VIDEO_ASPECT_BY_NAME = {
    "VIDEO_ASPECT_RATIO_PORTRAIT": VIDEO_ASPECT_PORTRAIT,
    "VIDEO_ASPECT_RATIO_LANDSCAPE": VIDEO_ASPECT_LANDSCAPE,
    "IMAGE_ASPECT_RATIO_PORTRAIT": VIDEO_ASPECT_PORTRAIT,
    "IMAGE_ASPECT_RATIO_LANDSCAPE": VIDEO_ASPECT_LANDSCAPE,
    "portrait": VIDEO_ASPECT_PORTRAIT,
    "landscape": VIDEO_ASPECT_LANDSCAPE,
    "9:16": VIDEO_ASPECT_PORTRAIT,
    "16:9": VIDEO_ASPECT_LANDSCAPE,
}

# Status Constants
STATUS_DONE = "CAE"
OUTCOME_OK = 3
OUTCOME_COMPLAINT = 4
SURFACE_ID = 22
FULL_FRAME_CROP = [None, 0.0038759689922481244, 1, 0.9961240310077519]
REF_TYPE_IMAGE = 1


# ── Data Classes & Exceptions ────────────────────────────────────────────────
class RpcError(RuntimeError):
    """A batchexecute envelope came back with an error slot instead of data."""
    def __init__(self, rpcid: str, detail: Any):
        super().__init__(f"{rpcid} failed: {detail!r}")
        self.rpcid = rpcid
        self.detail = detail


class FlowBatchError(RuntimeError):
    """The call succeeded but the payload did not hold what we expected."""


class CreditsInfo(NamedTuple):
    remaining: int
    tier: str

    def __int__(self):
        return self.remaining


@dataclass(frozen=True)
class RpcResult:
    rpcid: str
    data: Any
    error: Any = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass(frozen=True)
class GeneratedImage:
    media_id: str
    url: str


@dataclass(frozen=True)
class Operation:
    operation_id: str
    project_id: Optional[str]
    status: Optional[str]
    error: Optional[str] = None

    @property
    def done(self) -> bool:
        return self.status == STATUS_DONE

    @property
    def complained(self) -> bool:
        return self.error is not None


@dataclass(frozen=True)
class MediaUrls:
    media_id: str
    video: Optional[str] = None
    image: Optional[str] = None


# ── Resolvers ────────────────────────────────────────────────────────────────
def resolve_image_model(key: Optional[str]) -> str:
    """Resolve image model nickname or REST key to RPC wire name."""
    if isinstance(key, str):
        if key in IMAGE_MODEL_BY_NICKNAME:
            return IMAGE_MODEL_BY_NICKNAME[key]
        if key in IMAGE_MODELS:
            return key
    return IMAGE_MODEL


def resolve_video_model(key: Optional[str], duration: int = 4) -> str:
    """Map any REST-era model key or duration onto one the batch path accepts."""
    if isinstance(key, str):
        if key in VIDEO_MODELS:
            return key
        lower = key.lower()
        if "4s" in lower or duration == 4:
            if "low_priority" in lower:
                return "veo_3_1_t2v_lite_4s_low_priority"
            return "veo_3_1_t2v_lite_4s"
        if "ultra" in lower:
            return "veo_3_1_i2v_s_fast_ultra"
        if "low_priority" in lower:
            return "veo_3_1_i2v_lite_low_priority"
        if "lite" in lower:
            return "veo_3_1_i2v_lite"
    if duration == 4:
        return "veo_3_1_t2v_lite_4s"
    return VIDEO_MODEL


def resolve_aspect(aspect: Any) -> int:
    """Resolve aspect name to integer code 1-5 for images."""
    if isinstance(aspect, int):
        return aspect
    try:
        return ASPECT_BY_NAME[aspect]
    except KeyError:
        return ASPECT_LANDSCAPE


def resolve_video_aspect(aspect: Any) -> int:
    """Resolve video aspect to 1 (portrait 9:16) or 2 (landscape 16:9)."""
    if isinstance(aspect, int):
        if aspect in (VIDEO_ASPECT_PORTRAIT, VIDEO_ASPECT_LANDSCAPE):
            return aspect
        return VIDEO_ASPECT_LANDSCAPE
    try:
        return VIDEO_ASPECT_BY_NAME[aspect]
    except KeyError:
        return VIDEO_ASPECT_LANDSCAPE


# ── Envelopes Codec ──────────────────────────────────────────────────────────
def build_envelope(rpcid: str, inner: Any) -> str:
    """Wrap an inner payload as the f.req string batchexecute expects."""
    return json.dumps(
        [[[rpcid, json.dumps(inner, separators=(",", ":"), ensure_ascii=False), None, "generic"]]],
        separators=(",", ":"),
        ensure_ascii=False,
    )


def parse_envelope(text: str) -> List[RpcResult]:
    """Unwrap the )]}' sentinel and length-prefixed JSON chunks."""
    if not text:
        return []
    body = text.split("\n", 1)[1] if text.startswith(")]}'") else text
    decoder = json.JSONDecoder()
    results: List[RpcResult] = []
    index = 0
    while index < len(body):
        start = body.find("[", index)
        if start == -1:
            break
        try:
            chunk, consumed = decoder.raw_decode(body[start:])
        except json.JSONDecodeError:
            index = start + 1
            continue
        index = start + consumed
        for entry in chunk if isinstance(chunk, list) else []:
            if not isinstance(entry, list) or not entry or entry[0] != "wrb.fr":
                continue
            rpcid = entry[1] if len(entry) > 1 else "?"
            payload = entry[2] if len(entry) > 2 else None
            if payload is None:
                results.append(RpcResult(rpcid, None, entry[5] if len(entry) > 5 else True))
                continue
            results.append(
                RpcResult(rpcid, json.loads(payload) if isinstance(payload, str) else payload)
            )
    return results


def first_payload(text: str, rpcid: str) -> Any:
    """Get the payload of the first matching envelope, or raise RpcError / FlowBatchError."""
    results = parse_envelope(text)
    for result in results:
        if result.rpcid != rpcid:
            continue
        if not result.ok:
            raise RpcError(rpcid, result.error)
        return result.data
    raise FlowBatchError(f"no {rpcid} envelope in response ({len(results)} other envelopes found)")


# ── Request Builders ─────────────────────────────────────────────────────────
def _client_uuid() -> str:
    return str(uuid.uuid4()).upper()


def _context(project_id: str) -> list:
    return [None, SURFACE_ID, None, None, None, project_id, None, None, None, None,
            [CAPTCHA_SLOT, 1]]


def _reference(media_id: str) -> list:
    return [media_id, None, None, None, REF_TYPE_IMAGE]


def credits_request() -> str:
    """Build batchexecute request for RPC nzlxg (GetCredits)."""
    return build_envelope(RPC_CREDITS, [])


def image_request(
    prompt: str,
    project_id: str = DEFAULT_PROJECT_ID,
    count: int = 1,
    aspect: Any = ASPECT_SQUARE,
    seed: Optional[int] = None,
    prompts: Optional[List[str]] = None,
    model: str = IMAGE_MODEL,
    ref_media_ids: Optional[List[str]] = None,
) -> str:
    """Build batchexecute request for RPC ogiZ0b (GenerateImage)."""
    ratio = resolve_aspect(aspect)
    base = seed if seed is not None else random.randint(1, 10**9)
    items = []
    for index in range(max(1, count)):
        text = prompts[index] if prompts and index < len(prompts) else prompt
        refs = [_reference(mid) for mid in (ref_media_ids or [])] or None
        items.append([None, None, refs, base + index * 9973, ratio, model, None,
                      _context(project_id), [[[text]]], None, None, None,
                      _client_uuid(), _client_uuid()])
    return build_envelope(RPC_GEN_IMAGE, [None, items, 1, _context(project_id), [_client_uuid()]])


def video_request(
    prompt: str,
    project_id: str = DEFAULT_PROJECT_ID,
    source_media_id: Optional[str] = None,
    crop: Optional[list] = None,
    aspect: Any = VIDEO_ASPECT_LANDSCAPE,
    model: str = VIDEO_MODEL,
) -> str:
    """Build batchexecute request for RPC eb1hJf (GenerateVideo)."""
    inner = [
        [[[None, None, [[[prompt]]]], model, resolve_video_aspect(aspect), None,
          [None, source_media_id, None, None, None,
           FULL_FRAME_CROP if crop is None else crop] if source_media_id else None,
          [None, None, None, None, _client_uuid(), _client_uuid()]]],
        _context(project_id),
        [_client_uuid(), 2],
    ]
    return build_envelope(RPC_GEN_VIDEO, inner)


def upload_request(
    image_b64: str,
    project_id: str = DEFAULT_PROJECT_ID,
    mime_type: str = "image/jpeg",
    file_name: str = "upload.jpg",
) -> str:
    """Build batchexecute request for RPC maseQ (UploadMedia)."""
    return build_envelope(RPC_UPLOAD_IMAGE, [
        _context(project_id), image_b64, mime_type, 1, None, None, None, None,
        file_name, None, _client_uuid(), _client_uuid(),
    ])


def operation_request(operation_id: str) -> str:
    """Build batchexecute request for RPC jwpduf (GetOperation)."""
    return build_envelope(RPC_OPERATION, [None, None, [[operation_id]]])


def media_request(media_id: str) -> str:
    """Build batchexecute request for RPC as29s (GetMedia)."""
    return build_envelope(RPC_MEDIA, [media_id])


def project_media_request(project_id: str = DEFAULT_PROJECT_ID) -> str:
    """Build batchexecute request for RPC Zzl0ze (GetProjectMedia)."""
    return build_envelope(RPC_PROJECT_MEDIA, [f"projects/{project_id}", None, None, None, [1]])


# ── Response Parsers ─────────────────────────────────────────────────────────
def _walk_strings(node: Any):
    if isinstance(node, str):
        yield node
    elif isinstance(node, list):
        for item in node:
            yield from _walk_strings(item)


def _walk_lists(node: Any):
    if isinstance(node, list):
        yield node
        for item in node:
            yield from _walk_lists(item)


def read_credits(payload: Any) -> CreditsInfo:
    """Parse remaining credits & tier info from RPC nzlxg payload.
    e.g. [46, 2, 3, 3, null, 46] -> CreditsInfo(remaining=46, tier='TIER_2')
    """
    if isinstance(payload, list) and payload:
        val = payload[0]
        credits = int(val) if isinstance(val, (int, float)) else 0
        tier_val = payload[1] if len(payload) > 1 and payload[1] is not None else 1
        tier_str = f"TIER_{tier_val}"
        return CreditsInfo(remaining=credits, tier=tier_str)
    return CreditsInfo(remaining=0, tier="UNKNOWN")


def read_images(payload: Any) -> List[GeneratedImage]:
    """Extract signed CDN URLs and media IDs from RPC ogiZ0b response."""
    images: List[GeneratedImage] = []
    seen: set = set()
    for text in _walk_strings(payload):
        if not text.startswith("https://"):
            continue
        if MEDIA_HOST not in text and "google" not in text and ".jpg" not in text and ".png" not in text:
            continue
        media_id = None
        if "/image/" in text:
            media_id = text.split("/image/", 1)[1].split("?", 1)[0]
        elif "/img/" in text:
            media_id = text.split("/img/", 1)[1].split("?", 1)[0]
        else:
            match = re.search(r"([0-9a-fA-F-]{36})", text)
            if match:
                media_id = match.group(1)
        if not media_id:
            parts = text.rstrip("/").split("/")
            if parts:
                media_id = parts[-1].split("?")[0]
        if not media_id or media_id in seen:
            continue
        seen.add(media_id)
        images.append(GeneratedImage(media_id=media_id, url=text))
    return images


def read_uploaded_media_id(payload: Any) -> str:
    """Extract media_id from RPC maseQ response."""
    record = payload[0] if isinstance(payload, list) and payload else None
    media_id = record[0] if isinstance(record, list) and record else None
    if not isinstance(media_id, str) or not media_id:
        for node in _walk_lists(payload):
            if node and isinstance(node[0], str) and re.match(r"^[0-9a-fA-F-]{36}$", node[0]):
                return node[0]
        raise FlowBatchError("upload response carried no valid media id")
    return media_id


def read_video_media_id(payload: Any) -> Tuple[Optional[str], Optional[str]]:
    """Return (media_id, operation_id) from RPC eb1hJf response."""
    media_id = None
    operation_id = None
    if isinstance(payload, list) and len(payload) > 2 and isinstance(payload[2], list) and payload[2]:
        op_rec = payload[2][0]
        if isinstance(op_rec, list) and len(op_rec) > 0:
            operation_id = op_rec[0]
            if len(op_rec) > 3 and isinstance(op_rec[3], list) and len(op_rec[3]) > 4:
                media_id = op_rec[3][4]
    if not media_id and isinstance(payload, list) and len(payload) > 3 and isinstance(payload[3], list) and payload[3]:
        m_rec = payload[3][0]
        if isinstance(m_rec, list) and len(m_rec) > 0:
            media_id = m_rec[0]
            if len(m_rec) > 2:
                operation_id = operation_id or m_rec[2]
    # Fallback scan strings in payload
    if not media_id or not operation_id:
        uuids = []
        for text in _walk_strings(payload):
            if re.match(r"^[0-9a-fA-F-]{36}$", text) and text not in uuids:
                uuids.append(text)
            elif ("media" in text.lower() or "op" in text.lower()) and text not in uuids:
                uuids.append(text)
        if len(uuids) >= 2:
            for u in uuids:
                if "op" in u.lower():
                    operation_id = operation_id or u
                elif "media" in u.lower():
                    media_id = media_id or u
            media_id = media_id or uuids[0]
            operation_id = operation_id or uuids[1]
        elif len(uuids) == 1:
            media_id = media_id or uuids[0]
            operation_id = operation_id or uuids[0]
    return media_id, operation_id


def read_operation(payload: Any) -> Operation:
    """Extract Operation status from RPC jwpduf response."""
    records = payload[2] if isinstance(payload, list) and len(payload) > 2 else None
    record = records[0] if isinstance(records, list) and records else None
    if not isinstance(record, list) or not record:
        raise FlowBatchError("operation payload carried no record")
    return Operation(
        operation_id=record[0],
        project_id=record[1] if len(record) > 1 else None,
        status=record[3] if len(record) > 3 else None,
        error=read_operation_error(record),
    )


def read_operation_error(record: list) -> Optional[str]:
    detail = record[5] if len(record) > 5 else None
    if not isinstance(detail, list) or len(detail) <= 8:
        return None
    block = detail[8]
    if not isinstance(block, list) or not block or block[0] != OUTCOME_COMPLAINT:
        return None
    for text in _walk_strings(block):
        return text
    return "operation failed without a message"


def read_media_urls(payload: Any, media_id: str) -> MediaUrls:
    """Extract signed video MP4 CDN URL and thumbnail image from RPC as29s response."""
    video = None
    image = None
    for text in _walk_strings(payload):
        if not text.startswith("https://"):
            continue
        if (MEDIA_HOST + "/video/" in text or ".mp4" in text or "video" in text) and video is None:
            video = text
        elif (MEDIA_HOST + "/image/" in text or ".jpg" in text or ".png" in text) and image is None:
            image = text
    return MediaUrls(media_id=media_id, video=video, image=image)


_MEDIA_SLOT = re.compile(r'null,null,\\?"([0-9a-fA-F-]{36})\\?"')


def find_media_id_in_text(text: str, operation_id: str) -> Optional[str]:
    """Find media_id in raw project listing text by operation_id."""
    start = text.find(operation_id)
    if start == -1:
        return None
    match = _MEDIA_SLOT.search(text, start, start + 800)
    return match.group(1) if match else None
