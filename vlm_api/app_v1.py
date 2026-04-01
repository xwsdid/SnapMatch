import os
import json
import asyncio
import tempfile
import threading
import time
import hashlib
import ast
import re
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field
from pydantic.functional_validators import field_validator

import torch
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from PIL import Image


# --------- Config (via env) ---------
MODEL_ID = os.getenv("VLM_MODEL_ID", "Qwen/Qwen2-VL-2B-Instruct")
MAX_NEW_TOKENS = int(os.getenv("VLM_MAX_NEW_TOKENS", "512"))
TEMPERATURE = float(os.getenv("VLM_TEMPERATURE", "0.2"))
TOP_P = float(os.getenv("VLM_TOP_P", "0.9"))

# Optional: downscale large images before inference to reduce latency and GPU memory.
# Default is 1280 to avoid CUDA OOM on common 8GB GPUs; set 0 to disable.
MAX_IMAGE_SIDE = int(os.getenv("VLM_MAX_IMAGE_SIDE", "1280"))

# Limit concurrency to avoid OOM / GPU contention.
MAX_CONCURRENT = int(os.getenv("VLM_MAX_CONCURRENT", "1"))
_sema = asyncio.Semaphore(MAX_CONCURRENT)

DRY_RUN = os.getenv("VLM_DRY_RUN", "0") in ("1", "true", "True")
DEBUG = os.getenv("VLM_DEBUG", "0") in ("1", "true", "True")

# If strict JSON generation fails after retries, return a conservative fallback instead of 500.
FAIL_OPEN = os.getenv("VLM_FAIL_OPEN", "1") in ("1", "true", "True")

# Return extra debug meta fields (e.g. __source, __sha16) in responses.
# Disabled by default to keep backward compatibility with existing clients.
RETURN_META = os.getenv("VLM_RETURN_META", "0") in ("1", "true", "True")

# torch dtype/device
_TORCH_DTYPE_STR = os.getenv("VLM_TORCH_DTYPE", "auto").lower()  # auto|float16|bfloat16|float32
_DEVICE_MAP = os.getenv("VLM_DEVICE_MAP", "auto")


def _resolve_torch_dtype() -> Optional[torch.dtype]:
    if _TORCH_DTYPE_STR == "auto":
        return None
    if _TORCH_DTYPE_STR in ("float16", "fp16"):
        return torch.float16
    if _TORCH_DTYPE_STR in ("bfloat16", "bf16"):
        return torch.bfloat16
    if _TORCH_DTYPE_STR in ("float32", "fp32"):
        return torch.float32
    raise ValueError(f"Unsupported VLM_TORCH_DTYPE={_TORCH_DTYPE_STR}")


# --------- Model/processor lazy-load ---------
_model = None
_processor = None
_backend = None  # 'qwen2-vl' | 'qwen-vl-chat'

_init_lock = threading.Lock()
_loading = False
_load_error: Optional[str] = None


def _load_qwen2_vl(model_id: str):
    # Qwen2-VL series (recommended small VLM for private deployment)
    from transformers import AutoProcessor
    try:
        from transformers import Qwen2VLForConditionalGeneration  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "Qwen2VLForConditionalGeneration not available. "
            "Please upgrade transformers to a version that supports Qwen2-VL."
        ) from e

    torch_dtype = _resolve_torch_dtype()

    model = Qwen2VLForConditionalGeneration.from_pretrained(
        model_id,
        torch_dtype=torch_dtype,
        device_map=_DEVICE_MAP,
    )
    processor = AutoProcessor.from_pretrained(model_id)
    model.eval()
    return model, processor


def _load_qwen_vl_chat(model_id: str):
    # Legacy Qwen-VL-Chat series.
    # Uses trust_remote_code and model.chat/tokenizer.from_list_format.
    from transformers import AutoTokenizer, AutoModelForCausalLM

    torch_dtype = _resolve_torch_dtype()

    tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        model_id,
        torch_dtype=torch_dtype,
        device_map=_DEVICE_MAP,
        trust_remote_code=True,
    )
    model.eval()
    return model, tokenizer


def _lazy_init():
    global _model, _processor, _backend, _loading, _load_error
    if _model is not None and _processor is not None and _backend is not None:
        return

    with _init_lock:
        if _model is not None and _processor is not None and _backend is not None:
            return

        _loading = True
        _load_error = None
        try:
            # Auto-select backend by model id.
            # - Qwen2-VL: Qwen/Qwen2-VL-*
            # - Qwen-VL-Chat: Qwen/Qwen-VL-Chat*
            if "qwen2-vl" in MODEL_ID.lower():
                _model, _processor = _load_qwen2_vl(MODEL_ID)
                _backend = "qwen2-vl"
            else:
                _model, _processor = _load_qwen_vl_chat(MODEL_ID)
                _backend = "qwen-vl-chat"
        except Exception as e:
            _load_error = f"{type(e).__name__}: {e}"
            raise
        finally:
            _loading = False


def _build_user_prompt(task: str) -> str:
    # Stage-2: user prompt stays minimal; system prompt enforces strict JSON.
    if task == "advice":
        return "请根据图片给出拍摄建议（只输出 JSON，格式由 system 指定；每个字段不要只写前缀，前缀后必须有完整建议句子）。"
    if task == "pose":
        return "请根据图片给出人像姿势引导（只输出 JSON，格式由 system 指定；每条动作要点必须是完整句子）。"
    raise ValueError("task must be 'advice' or 'pose'")


class ShootingAdvice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    composition: str = Field(min_length=12, max_length=120)
    focus: str = Field(min_length=12, max_length=120)
    atmosphere: str = Field(min_length=12, max_length=120)

    @field_validator("composition")
    @classmethod
    def _composition_prefix(cls, v: str) -> str:
        if not v.startswith("构图优化："):
            raise ValueError("composition must start with 构图优化：")
        return v

    @field_validator("focus")
    @classmethod
    def _focus_prefix(cls, v: str) -> str:
        if not v.startswith("焦点调整："):
            raise ValueError("focus must start with 焦点调整：")
        return v

    @field_validator("atmosphere")
    @classmethod
    def _atmosphere_prefix(cls, v: str) -> str:
        if not v.startswith("氛围强化："):
            raise ValueError("atmosphere must start with 氛围强化：")
        return v

# class ShootingAdvice(BaseModel):
#     model_config = ConfigDict(extra="forbid")
#     composition: str = Field(max_length=120)
#     focus: str = Field(max_length=120)
#     atmosphere: str = Field(max_length=120)

#     @field_validator("composition")
#     @classmethod
#     def _composition_prefix(cls, v: str) -> str:
#         if not v.startswith("构图优化："):
#             raise ValueError("composition must start with 构图优化：")
#         return v

#     @field_validator("focus")
#     @classmethod
#     def _focus_prefix(cls, v: str) -> str:
#         if not v.startswith("焦点调整："):
#             raise ValueError("focus must start with 焦点调整：")
#         return v

#     @field_validator("atmosphere")
#     @classmethod
#     def _atmosphere_prefix(cls, v: str) -> str:
#         if not v.startswith("氛围强化："):
#             raise ValueError("atmosphere must start with 氛围强化：")
#         return v




class PoseGuide(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pose_title: str = Field(min_length=8, max_length=40)
    instructions: list[str] = Field(min_length=3, max_length=6)

    @field_validator("pose_title")
    @classmethod
    def _pose_title_format(cls, v: str) -> str:
        if not v.startswith("✨ 推荐姿势："):
            raise ValueError("pose_title must start with ✨ 推荐姿势：")
        if len(v.replace("✨ 推荐姿势：", "").strip()) == 0:
            raise ValueError("pose_title must include a specific pose name")
        return v

    @field_validator("instructions")
    @classmethod
    def _instructions_each(cls, v: list[str]) -> list[str]:
        for item in v:
            if not isinstance(item, str) or len(item.strip()) < 4:
                raise ValueError("each instruction must be a non-empty short sentence")
            bad_prefixes = ("-", "•", "*", "1.", "2.", "3.")
            if item.strip().startswith(bad_prefixes):
                raise ValueError("instructions items must not start with bullets or numbering")
        return v


def _system_prompt_for(task: str) -> str:
    # 强约束：只允许输出“合法 JSON”，禁止 Markdown/代码块/额外字段/解释文字。
    if task == "advice":
        return (
            "你是智能摄影辅助系统的多模态摄影指导模型。\n"
            "你必须严格只输出 1 个 JSON 对象，且必须是可被 json.loads 直接解析的合法 JSON。\n"
            "禁止输出 Markdown、代码块、注释、解释说明、前后缀文本（包括 'system/user/assistant' 等）。\n"
            "JSON 只能包含且必须包含以下 3 个 key（不要多也不要少）：\n"
            "- composition\n- focus\n- atmosphere\n"
            "每个 value 必须是中文字符串，必须以固定前缀开头并给出可执行建议：\n"
            "- composition 必须以 '构图优化：' 开头\n"
            "- focus 必须以 '焦点调整：' 开头\n"
            "- atmosphere 必须以 '氛围强化：' 开头\n"
            "硬性长度要求：每个 value 在前缀后必须至少再写 18 个汉字（不能只输出到'：'）。\n"
            "建议长度：每条建议总长度（含前缀）控制在 24~120 字。\n"
            "严禁使用占位符或省略号（例如 '...'、'……'、'省略'）。必须写出完整可执行建议。\n"
            "输出要求：\n"
            "- 使用英文双引号\n- 不要换成单引号\n- 不要尾随逗号\n"
            "- 不要换行成列表，不要使用编号\n"
            "如果图片信息不足，也必须输出同样结构的 JSON，并给出保守通用建议。"
        )
    if task == "pose":
        return (
            "你是智能摄影辅助系统的多模态人像姿势指导模型。\n"
            "你必须严格只输出 1 个 JSON 对象，且必须是可被 json.loads 直接解析的合法 JSON。\n"
            "禁止输出 Markdown、代码块、注释、解释说明、前后缀文本（包括 'system/user/assistant' 等）。\n"
            "JSON 只能包含且必须包含以下 2 个 key（不要多也不要少）：\n"
            "- pose_title\n- instructions\n"
            "pose_title 必须是中文字符串，必须以 '✨ 推荐姿势：' 开头，且冒号后必须有具体姿势名称（不能空）。\n"
            "instructions 必须是字符串数组，长度 3~6 条，每条是一个可执行动作要点（中文）。\n"
            "硬性长度要求：每条 instructions 至少 8 个汉字；不要只写词组，要写完整可执行句子。\n"
            "严禁使用占位符或省略号（例如 '...'、'……'、'省略'）。必须写出完整动作要点。\n"
            "输出要求：\n"
            "- 使用英文双引号\n- 不要换成单引号\n- 不要尾随逗号\n"
            "- instructions 内不要写编号前缀（如 '1.'、'-'）\n"
            "如果图片信息不足，也必须输出同样结构的 JSON，并给出通用的人像姿势引导。"
        )
    raise ValueError("task must be 'advice' or 'pose'")


def _extract_json_object(text: str) -> str:
    """Best-effort extraction of the first JSON object from a messy model output."""
    # Normalize full-width braces sometimes produced by CJK models.
    text = text.replace("｛", "{").replace("｝", "}")
    start = text.find("{")
    if start == -1:
        raise ValueError("no JSON object found")

    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]

    raise ValueError("unterminated JSON object")


def _parse_kv_fallback(task: str, text: str) -> dict:
    """Parse non-JSON model outputs like:
    composition: "构图优化：..."
    focus: "焦点调整：..."
    atmosphere: "氛围强化：..."
    """
    # Strip code fences if any.
    text = re.sub(r"```[a-zA-Z0-9_-]*", "", text)
    text = text.replace("```", "")

    def _find_str(key: str) -> Optional[str]:
        # Allow separators ':' or '：', allow quotes or no quotes.
        m = re.search(rf"(?im)^\s*{re.escape(key)}\s*[:：]\s*(.+?)\s*$", text)
        if not m:
            return None
        v = m.group(1).strip().strip(",")
        # Trim surrounding quotes.
        if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
            v = v[1:-1].strip()
        return v

    if task == "advice":
        out = {
            "composition": _find_str("composition"),
            "focus": _find_str("focus"),
            "atmosphere": _find_str("atmosphere"),
        }
        if all(isinstance(out[k], str) and out[k] for k in out):
            return out  # type: ignore[return-value]
        raise ValueError("kv fallback parse failed")

    # pose
    pose_title = _find_str("pose_title")
    # instructions may be on one line like: instructions: ["..",".."]
    m = re.search(r"(?im)^\s*instructions\s*[:：]\s*(.+?)\s*$", text)
    instructions: list[str] = []
    if m:
        raw = m.group(1).strip()
        try:
            # Try JSON list first.
            instructions = json.loads(raw) if raw.startswith("[") else []
        except Exception:
            instructions = []

    if pose_title and instructions:
        return {"pose_title": pose_title, "instructions": instructions}
    raise ValueError("kv fallback parse failed")


def _parse_prefixed_lines(task: str, text: str) -> dict:
    """Parse model outputs that contain the required human-readable prefixes but are not JSON.

    Expected formats:
    - advice: three segments containing '构图优化：', '焦点调整：', '氛围强化：'
    - pose: first line startswith '✨ 推荐姿势：', following non-empty lines are instructions
    """
    # Strip code fences if any.
    text = re.sub(r"```[a-zA-Z0-9_-]*", "", text)
    text = text.replace("```", "")
    text = text.replace("\r\n", "\n")

    def _clean_line(s: str) -> str:
        s = s.strip().strip("\"").strip("'").strip()
        # Remove bullet/numbering prefixes.
        s = re.sub(r"^\s*(?:[-•*]|\d+[.)、])\s*", "", s)
        return s.strip()

    if task == "advice":
        prefixes = ["构图优化：", "焦点调整：", "氛围强化："]
        pos = [(p, text.find(p)) for p in prefixes]
        if any(i == -1 for _, i in pos):
            raise ValueError("missing required prefixes")
        # Sort by position in text.
        pos.sort(key=lambda x: x[1])

        segments: dict[str, str] = {}
        for idx, (p, start) in enumerate(pos):
            end = pos[idx + 1][1] if idx + 1 < len(pos) else len(text)
            seg = text[start:end].strip()
            # Keep only the first line if the model spilled extra commentary.
            seg = seg.split("\n", 1)[0].strip()
            seg = _clean_line(seg)
            # Ensure prefix is present.
            if not seg.startswith(p):
                seg = p + seg
            segments[p] = seg

        return {
            "composition": segments["构图优化："],
            "focus": segments["焦点调整："],
            "atmosphere": segments["氛围强化："],
        }

    # pose
    lines = [ln for ln in (l.strip() for l in text.split("\n")) if ln]
    if not lines:
        raise ValueError("empty output")
    title = _clean_line(lines[0])
    if not title.startswith("✨ 推荐姿势："):
        # Try to find a title line anywhere.
        t = next(( _clean_line(ln) for ln in lines if "✨ 推荐姿势：" in ln), None)
        if not t:
            raise ValueError("missing pose_title")
        title = t

    instr: list[str] = []
    seen: set[str] = set()
    for ln in lines[1:]:
        raw_ln = ln
        ln = _clean_line(ln)
        if not ln or "推荐姿势" in ln:
            continue

        # Skip label lines like "动作要点：" / "要点：".
        if re.search(r"(动作要点|要点)\s*[:：]?$", ln):
            continue

        # If model outputs a JSON-like list on one line, parse it.
        # Examples:
        #   instructions: ["...","...","..."]
        #   Instructions：['...','...']
        if re.search(r"(?i)^\s*instructions\s*[:：]", raw_ln) and "[" in raw_ln and "]" in raw_ln:
            after = re.split(r"(?i)instructions\s*[:：]", raw_ln, maxsplit=1)[-1].strip()
            try:
                # Normalize quotes for json.
                after2 = after.replace("'", '"')
                parsed = json.loads(after2)
                if isinstance(parsed, list):
                    for item in parsed:
                        if isinstance(item, str):
                            item2 = _clean_line(item)
                            if item2 and item2 not in seen:
                                seen.add(item2)
                                instr.append(item2)
                            if len(instr) >= 6:
                                break
                    continue
            except Exception:
                pass

        # If model outputs a single-line instructions string, split by comma-like separators.
        if re.search(r"(?i)^\s*instructions\s*[:：]", raw_ln):
            after = re.split(r"(?i)instructions\s*[:：]", raw_ln, maxsplit=1)[-1].strip()
            after = after.strip().strip("\"").strip("'")
            parts = re.split(r"[，,；;]\s*", after)
            for part in parts:
                part2 = _clean_line(part)
                if part2 and part2 not in seen:
                    seen.add(part2)
                    instr.append(part2)
                if len(instr) >= 6:
                    break
            continue

        # Skip label-only line like: instructions:
        if re.fullmatch(r"(?i)instructions\s*[:：]?", ln):
            continue

        if ln not in seen:
            seen.add(ln)
            instr.append(ln)
        if len(instr) >= 6:
            break

    if not instr:
        raise ValueError("missing instructions")
    return {"pose_title": title, "instructions": instr}


def _validate_and_normalize(task: str, raw_text: str) -> dict:
    raw_text = raw_text.strip()
    # 1) Try best-effort JSON object extraction.
    if "{" in raw_text:
        json_str = _extract_json_object(raw_text)
        try:
            obj = json.loads(json_str)
        except json.JSONDecodeError:
            # 1.1) If model used single quotes or python-ish dict, try literal_eval.
            obj = ast.literal_eval(json_str)
        if task == "advice":
            return ShootingAdvice.model_validate(obj).model_dump()
        return PoseGuide.model_validate(obj).model_dump()

    # 2) Fallback: key:value lines.
    obj = _parse_kv_fallback(task, raw_text)
    if task == "advice":
        return ShootingAdvice.model_validate(obj).model_dump()
    return PoseGuide.model_validate(obj).model_dump()


def _image_stats(image: Image.Image) -> tuple[float, float]:
    """Return (mean_luma, std_luma) in [0,255]."""
    try:
        g = image.convert("L")
        # Downsample for speed.
        g = g.resize((128, 128))
        pix = list(g.getdata())
        if not pix:
            return 127.0, 0.0
        mean = sum(pix) / len(pix)
        var = sum((p - mean) ** 2 for p in pix) / len(pix)
        return float(mean), float(var**0.5)
    except Exception:
        return 127.0, 0.0


def _fallback_seed_from_image(image: Image.Image) -> int:
    # Deterministic-ish seed from image bytes (after any resize) to avoid returning identical text.
    try:
        b = image.tobytes()
        h = hashlib.sha256(b).hexdigest()
        return int(h[:8], 16)
    except Exception:
        w, h = image.size
        return (w * 1315423911) ^ (h * 2654435761)


def _fallback_advice(image: Image.Image) -> dict:
    seed = _fallback_seed_from_image(image)
    mean_luma, std_luma = _image_stats(image)
    w, h = image.size
    portrait = h >= w

    comp_opts = [
        "构图优化：优先把主体放在三分线交点附近，避免居中死板，并保留一侧留白让画面更有呼吸感。",
        "构图优化：适当拉开主体与背景的距离，利用前景/背景分层增强纵深，同时把地平线控制在三分线位置。",
        "构图优化：尝试轻微侧移取景，让主体与环境形成对角线关系，并裁掉多余杂乱边缘以突出重点。",
    ]
    focus_opts = [
        "焦点调整：优先对焦人物眼睛或面部，开启人脸/眼部对焦更稳，快门按下前确认焦点框锁定在主体上。",
        "焦点调整：把对焦点放在主体最重要细节处（脸/眼/标志物），并适当增大光圈或拉长焦距让背景更干净。",
        "焦点调整：避免对到背景高对比区域，必要时点按屏幕重新对焦并略微提高快门速度防止抖动导致虚焦。",
    ]

    if mean_luma < 80:
        atm_hint = "氛围强化：当前画面偏暗，可适当提高曝光或补一盏柔光，同时保持肤色不过曝，氛围会更通透。"
    elif mean_luma > 175:
        atm_hint = "氛围强化：当前画面偏亮，可略降曝光并压高光，保留天空/皮肤细节，再轻微加对比增强层次。"
    elif std_luma < 35:
        atm_hint = "氛围强化：画面对比偏弱，可轻微提升对比与清晰度，并加一点暖色温让主体更立体、更有质感。"
    else:
        atm_hint = "氛围强化：整体光比合适，可轻微降曝光保高光细节，再提升一点对比与饱和，让画面更有冲击力。"

    # Small deterministic variation.
    comp = comp_opts[seed % len(comp_opts)]
    focus = focus_opts[(seed // 7) % len(focus_opts)]
    atmosphere = atm_hint
    if portrait and "地平线" in comp:
        comp = "构图优化：竖幅建议把主体上移到上三分线附近，减少脚下空白，并让背景线条更简洁以突出人物。"

    return {"composition": comp, "focus": focus, "atmosphere": atmosphere}


def _fallback_pose(image: Image.Image) -> dict:
    seed = _fallback_seed_from_image(image)
    titles = [
        "✨ 推荐姿势：侧身回头抓拍",
        "✨ 推荐姿势：站姿松弛版",
        "✨ 推荐姿势：坐姿三角构图",
    ]
    base = [
        ["身体微侧站立，肩颈放松", "一手自然下垂，另一手轻扶道具", "下巴微收看向斜前方"],
        ["重心落在一条腿，另一条腿轻点地", "手臂留出空隙避免贴身显僵", "眼神看向光源方向更显精神"],
        ["坐姿微前倾，背部保持挺直", "双手交叠放膝上或扶椅边", "脚尖指向镜头斜前方显腿长"],
    ]
    i = seed % len(titles)
    return {"pose_title": titles[i], "instructions": base[i]}


def _run_generate_json(image: Image.Image, image_path: str, task: str) -> dict:
    """Generate strict JSON with schema validation and one repair attempt."""
    _lazy_init()

    system_prompt = _system_prompt_for(task)
    user_prompt = _build_user_prompt(task)

    def _generate_once(extra_user_text: Optional[str] = None) -> str:
        if _backend == "qwen-vl-chat":
            # Qwen-VL-Chat: rely on query text; system prompt is prepended.
            query_text = user_prompt if extra_user_text is None else extra_user_text
            full_text = system_prompt + "\n\n" + query_text
            query = _processor.from_list_format(
                [
                    {"image": image_path},
                    {"text": full_text},
                ]
            )
            out, _ = _model.chat(_processor, query=query, history=None)
            return out

        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": user_prompt if extra_user_text is None else extra_user_text},
                ],
            },
        ]

        text = _processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = _processor(text=[text], images=[image], padding=True, return_tensors="pt")
        device = next(_model.parameters()).device
        inputs = {k: v.to(device) if hasattr(v, "to") else v for k, v in inputs.items()}

        with torch.no_grad():
            generated_ids = _model.generate(
                **inputs,
                max_new_tokens=MAX_NEW_TOKENS,
                do_sample=(TEMPERATURE > 0),
                temperature=TEMPERATURE,
                top_p=TOP_P,
            )
        # Decode only newly generated tokens (avoid echoing the full prompt).
        prompt_len = inputs["input_ids"].shape[-1]
        new_tokens = generated_ids[:, prompt_len:]
        return _processor.batch_decode(new_tokens, skip_special_tokens=True)[0].strip()

    attempts: list[str] = []
    last_error: Optional[str] = None

    first = _generate_once()
    attempts.append(first)
    try:
        out = _validate_and_normalize(task, first)
        out["__source"] = "model"
        return out
    except Exception as e:
        last_error = f"{type(e).__name__}: {e}"
        if DEBUG:
            print(f"[vlm] json validation failed (attempt#1): {last_error}", flush=True)

    # Repair pass #1: force rewrite to JSON only.
    # NOTE: do not include concrete example sentences here; models may copy them verbatim.
    repair1 = (
        "重写输出，必须严格只输出 1 个 JSON 对象（不要任何前后缀文字）。\n"
        "要求：\n"
        "- 必须以 '{' 开头并以 '}' 结尾\n"
        "- 只能使用英文双引号\n"
        "- 禁止 Markdown/代码块（不要 ```）\n"
        "- 每个字段必须包含完整可执行建议（不要只写前缀或空字符串）\n"
        "- advice 三个字段的 value 在前缀后必须至少再写 18 个汉字内容（不能只输出到'：'）\n"
        "- pose 的 instructions 每条至少 8 个汉字内容（不要只写词组）\n"
        "- 禁止使用 '...' 或 '……'\n"
        + (f"- 上一次错误：{last_error}\n" if last_error else "")
        + ("JSON keys: composition, focus, atmosphere\n" if task == "advice" else "JSON keys: pose_title, instructions\n")
    )
    second = _generate_once(extra_user_text=repair1)
    attempts.append(second)
    try:
        out = _validate_and_normalize(task, second)
        out["__source"] = "model"
        return out
    except Exception as e:
        last_error = f"{type(e).__name__}: {e}"
        if DEBUG:
            print(f"[vlm] json validation failed (attempt#2): {last_error}", flush=True)

    # Repair pass #2: even stricter, remove any ambiguity.
    schema_line = (
        "JSON schema: composition(string), focus(string), atmosphere(string)."
        if task == "advice"
        else "JSON schema: pose_title(string), instructions(array of strings)."
    )
    repair2 = (
        "最终修复：只输出 JSON（单个对象）。不要输出任何其他字符。\n"
        + schema_line
        + "\n硬性要求：英文双引号；不要 Markdown；不要代码块；不要多余换行解释。\n"
        + "每个字段必须是完整中文句子并包含可执行建议。\n"
        + "advice 三个字段的 value 在前缀后必须至少再写 18 个汉字；pose 的 instructions 每条至少 8 个汉字。\n"
        + (f"上一轮错误：{last_error}\n" if last_error else "")
    )
    third = _generate_once(extra_user_text=repair2)
    attempts.append(third)
    try:
        out = _validate_and_normalize(task, third)
        out["__source"] = "model"
        return out
    except Exception as e:
        # Extra attempt: ask for prefixed lines (not JSON) and parse them back.
        last_error = f"{type(e).__name__}: {e}"
        if DEBUG:
            print(f"[vlm] json validation failed (attempt#3): {last_error}", flush=True)

        lines_prompt = (
            "不要输出 JSON。只输出内容本身，不要任何解释。\n"
            if task == "advice"
            else "不要输出 JSON。只输出内容本身，不要任何解释。\n"
        )
        if task == "advice":
            lines_prompt += (
                "请只输出 3 行中文建议，每行必须以指定前缀开头，且前缀后至少再写 18 个汉字。\n"
                "必须按下面三行顺序输出（每行一条，不要多也不要少）：\n"
                "构图优化：后面直接写完整建议句子\n"
                "焦点调整：后面直接写完整建议句子\n"
                "氛围强化：后面直接写完整建议句子\n"
                "禁止 Markdown/代码块；不要编号/不要项目符号；不要输出省略号（.../……）。\n"
            )
        else:
            lines_prompt += (
                "请只输出姿势引导，格式如下：\n"
                "第 1 行：✨ 推荐姿势：<具体姿势名称>\n"
                "接下来 3~6 行：每行 1 条动作要点（每条至少 8 个汉字），不要编号/不要项目符号。\n"
                "不要输出 JSON；不要输出 'pose_title'/'instructions' 这些 key；不要输出方括号列表。\n"
                "禁止 Markdown/代码块；不要任何解释。\n"
            )

        fourth = _generate_once(extra_user_text=lines_prompt)
        attempts.append(fourth)
        try:
            obj = _parse_prefixed_lines(task, fourth)
            out = (ShootingAdvice.model_validate(obj).model_dump() if task == "advice" else PoseGuide.model_validate(obj).model_dump())
            out["__source"] = "model_lines"
            return out
        except Exception as e2:
            if DEBUG:
                print(f"[vlm] prefixed-lines parse failed: {type(e2).__name__}: {e2}", flush=True)

        if FAIL_OPEN:
            if DEBUG:
                joined = "\n\n-----\n\n".join(a[:2000] for a in attempts)
                print(
                    f"[vlm] strict json failed after retries; using fallback. last={type(e).__name__}: {e}. Raw outputs:\n{joined}",
                    flush=True,
                )
            out = _fallback_advice(image) if task == "advice" else _fallback_pose(image)
            out["__source"] = "fallback"
            return out

        if DEBUG:
            joined = "\n\n-----\n\n".join(a[:2000] for a in attempts)
            raise RuntimeError(f"JSON validation failed after retries: {type(e).__name__}: {e}. Raw outputs:\n{joined}")
        raise


def _run_generate(image: Image.Image, image_path: str, task: str) -> str:
    if DRY_RUN:
        if task == "advice":
            return json.dumps(
                {
                    "composition": "构图优化：将主体靠近右侧三分线，拉开与背景的层次关系。",
                    "focus": "焦点调整：对焦人物面部，适度虚化远处景物以突出主体。",
                    "atmosphere": "氛围强化：略降曝光并提高对比，保留水面反光的清透感。",
                },
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "pose_title": "✨ 推荐姿势：站姿松弛版",
                "instructions": [
                    "身体微侧站立，肩放松",
                    "一手自然下垂，另一手轻扶道具",
                    "下巴微收看向斜前方",
                ],
            },
            ensure_ascii=False,
        )

    _lazy_init()

    prompt = _build_user_prompt(task)

    if _backend == "qwen-vl-chat":
        # Qwen-VL-Chat path: image via local file path.
        query = _processor.from_list_format(
            [
                {"image": image_path},
                {"text": prompt},
            ]
        )
        # history=None for stateless API.
        out, _ = _model.chat(_processor, query=query, history=None)
        return out

    # Qwen2-VL path
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image", "image": image},
                {"type": "text", "text": prompt},
            ],
        }
    ]

    text = _processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = _processor(text=[text], images=[image], padding=True, return_tensors="pt")

    # Move tensors to the same device as model.
    device = next(_model.parameters()).device
    inputs = {k: v.to(device) if hasattr(v, "to") else v for k, v in inputs.items()}

    with torch.no_grad():
        generated_ids = _model.generate(
            **inputs,
            max_new_tokens=MAX_NEW_TOKENS,
            do_sample=(TEMPERATURE > 0),
            temperature=TEMPERATURE,
            top_p=TOP_P,
        )

    out = _processor.batch_decode(generated_ids, skip_special_tokens=True)[0]

    # Many chat templates include the prompt; best-effort trim to assistant answer.
    # Keep it conservative to avoid accidentally deleting content.
    if "assistant" in out.lower():
        # no strict guarantee; leave as-is
        return out
    return out


app = FastAPI(title="VLM API", version="0.1.0")


@app.get("/health")
def health():
    return {"status": "ok", "model_id": MODEL_ID, "dry_run": DRY_RUN}


@app.get("/model/status")
def model_status():
    return {
        "model_id": MODEL_ID,
        "dry_run": DRY_RUN,
        "loaded": _model is not None,
        "loading": _loading,
        "load_error": _load_error,
        "backend": _backend,
        "max_concurrent": MAX_CONCURRENT,
        "cuda_available": torch.cuda.is_available(),
        "cuda_device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
    }


@app.post("/vlm/infer")
async def vlm_infer(
    file: Optional[UploadFile] = File(None),
    image: Optional[UploadFile] = File(None),
    task: Literal["advice", "pose"] = Form(...),
):
    t0 = time.monotonic()
    upload = file or image
    if upload is None:
        # Keep compatibility with both field names used by different clients.
        raise HTTPException(status_code=422, detail="missing file (field name: file or image)")

    if DEBUG:
        fn0 = upload.filename or ""
        ct0 = upload.content_type or ""
        print(f"[vlm] begin task={task} filename={fn0} content_type={ct0}", flush=True)

    # Some HTTP clients (e.g. Go multipart forwarding) may set Content-Type to application/octet-stream.
    # Prefer header check but fall back to filename extension.
    ct = (upload.content_type or "").lower()
    fn = (upload.filename or "").lower()
    if not ct.startswith("image/"):
        if not (fn.endswith(".jpg") or fn.endswith(".jpeg") or fn.endswith(".png") or fn.endswith(".webp")):
            raise HTTPException(status_code=400, detail="file must be an image")

    tmp_path = None
    try:
        if DEBUG:
            print(f"[vlm] reading upload bytes... (+{time.monotonic() - t0:.3f}s)", flush=True)
        raw = await upload.read()
        if DEBUG:
            print(f"[vlm] read {len(raw)} bytes (+{time.monotonic() - t0:.3f}s)", flush=True)

        digest = hashlib.sha256(raw).hexdigest()[:16]
        if DEBUG:
            print(f"[vlm] sha256={digest} (+{time.monotonic() - t0:.3f}s)", flush=True)

        # Save to a temp file for Qwen-VL-Chat (needs a file path)
        fd, tmp_path = tempfile.mkstemp(suffix=".jpg")
        os.close(fd)
        with open(tmp_path, "wb") as f:
            f.write(raw)

        image = Image.open(io_bytes := __import__("io").BytesIO(raw)).convert("RGB")
        if DEBUG:
            print(f"[vlm] image decoded size={image.size} (+{time.monotonic() - t0:.3f}s)", flush=True)

        if MAX_IMAGE_SIDE and max(image.size) > MAX_IMAGE_SIDE:
            w, h = image.size
            if w >= h:
                new_w = MAX_IMAGE_SIDE
                new_h = max(1, int(h * (MAX_IMAGE_SIDE / float(w))))
            else:
                new_h = MAX_IMAGE_SIDE
                new_w = max(1, int(w * (MAX_IMAGE_SIDE / float(h))))

            if DEBUG:
                print(f"[vlm] resizing image {w}x{h} -> {new_w}x{new_h} (VLM_MAX_IMAGE_SIDE={MAX_IMAGE_SIDE})", flush=True)

            resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS", getattr(Image, "LANCZOS", 1))
            image = image.resize((new_w, new_h), resample=resample)
            # Keep qwen-vl-chat path consistent: overwrite temp file with resized JPEG.
            image.save(tmp_path, format="JPEG", quality=90)
            if DEBUG:
                print(f"[vlm] resized saved to tmp (+{time.monotonic() - t0:.3f}s)", flush=True)
    except Exception:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
        raise HTTPException(status_code=400, detail="invalid image")

    if DEBUG:
        # asyncio.Semaphore doesn't expose a public count; _value is best-effort.
        sema_val = getattr(_sema, "_value", None)
        print(f"[vlm] waiting semaphore value={sema_val} (+{time.monotonic() - t0:.3f}s)", flush=True)

    async with _sema:
        try:
            if DEBUG:
                sema_val = getattr(_sema, "_value", None)
                print(f"[vlm] acquired semaphore value={sema_val} (+{time.monotonic() - t0:.3f}s)", flush=True)
            # Offload to worker thread (avoid blocking event loop)
            if DRY_RUN:
                data = json.loads(await asyncio.to_thread(_run_generate, image, tmp_path, task))
                data["__source"] = "dry_run"
            else:
                data = await asyncio.to_thread(_run_generate_json, image, tmp_path, task)

            if DEBUG:
                print(f"[vlm] inference ok (+{time.monotonic() - t0:.3f}s)", flush=True)
        except Exception as e:
            # CUDA OOM is common when users upload 3K/4K images; prefer fail-open over 500.
            is_oom = (
                (hasattr(torch, "cuda") and hasattr(torch.cuda, "OutOfMemoryError") and isinstance(e, torch.cuda.OutOfMemoryError))
                or ("CUDA out of memory" in str(e))
                or ("OutOfMemoryError" in type(e).__name__)
            )
            if is_oom and hasattr(torch, "cuda") and torch.cuda.is_available():
                try:
                    torch.cuda.empty_cache()
                    torch.cuda.ipc_collect()
                except Exception:
                    pass

            if is_oom and FAIL_OPEN:
                if DEBUG:
                    print(f"[vlm] cuda oom; using fallback (+{time.monotonic() - t0:.3f}s): {type(e).__name__}: {e}", flush=True)
                data = _fallback_advice(image) if task == "advice" else _fallback_pose(image)
                data["__source"] = "fallback_oom"
            else:
                if DEBUG:
                    print(f"[vlm] inference failed (+{time.monotonic() - t0:.3f}s): {type(e).__name__}: {e}", flush=True)
                raise HTTPException(status_code=500, detail=f"model inference failed: {type(e).__name__}: {e}")
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

    if DEBUG:
        print(f"[vlm] end (+{time.monotonic() - t0:.3f}s)", flush=True)

    # Keep backward compatibility: by default strip meta keys.
    if RETURN_META:
        data["__sha16"] = digest
    else:
        for k in list(data.keys()):
            if isinstance(k, str) and k.startswith("__"):
                data.pop(k, None)

    return JSONResponse(data)


@app.on_event("startup")
def _startup():
    # Optional eager load. Two modes:
    # - VLM_EAGER_LOAD=1: load synchronously during startup
    # - VLM_BACKGROUND_LOAD=1: load asynchronously in background (recommended for dev)
    if DRY_RUN:
        return

    bg = os.getenv("VLM_BACKGROUND_LOAD", "0") in ("1", "true", "True")
    eager = os.getenv("VLM_EAGER_LOAD", "1")

    if bg:
        threading.Thread(target=_lazy_init, daemon=True).start()
        return

    if eager not in ("0", "false", "False"):
        _lazy_init()
