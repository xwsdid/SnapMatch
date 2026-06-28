import os
import json
import asyncio
import tempfile
import threading
import time
import hashlib
import ast
import re
import io
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field
from pydantic.functional_validators import field_validator

import torch
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from PIL import Image

print('Qwen2.5-VL-7B-Instruct (Optimized)')

# --------- Config (via env) ---------
MODEL_ID = os.getenv("VLM_MODEL_ID", "./qwen_vl_model/qwen/Qwen2.5-VL-7B-Instruct")
MAX_NEW_TOKENS = int(os.getenv("VLM_MAX_NEW_TOKENS", "300"))  # 减少到300，足够用
TEMPERATURE = float(os.getenv("VLM_TEMPERATURE", "0.0"))  # 改为0，最快
TOP_P = float(os.getenv("VLM_TOP_P", "1.0"))  # temperature=0时top_p无效，设为1.0

# 图像预处理优化
MAX_IMAGE_SIDE = int(os.getenv("VLM_MAX_IMAGE_SIDE", "896"))  # 从1280降到896，减少token
# Qwen2.5-VL专用：控制图像patch数量，直接影响速度
MIN_PIXELS = int(os.getenv("VLM_MIN_PIXELS", "200704"))  # 256 * 28 * 28
MAX_PIXELS = int(os.getenv("VLM_MAX_PIXELS", "802816"))  # 1024 * 28 * 28

MAX_CONCURRENT = int(os.getenv("VLM_MAX_CONCURRENT", 1))
_sema = asyncio.Semaphore(MAX_CONCURRENT)

DRY_RUN = os.getenv("VLM_DRY_RUN", "0") in ("1", "true", "True")
DEBUG = os.getenv("VLM_DEBUG", "0") in ("1", "true", "True")
FAIL_OPEN = os.getenv("VLM_FAIL_OPEN", "1") in ("1", "true", "True")
RETURN_META = os.getenv("VLM_RETURN_META", "0") in ("1", "true", "True")

_TORCH_DTYPE_STR = os.getenv("VLM_TORCH_DTYPE", "bfloat16")  # 改为bfloat16，与FlashAttention2配合
_DEVICE_MAP = os.getenv("VLM_DEVICE_MAP", "auto")

# Flash Attention 2 开关（需要GPU支持）
USE_FLASH_ATTN = os.getenv("VLM_USE_FLASH_ATTN", "1") in ("1", "true", "True")


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
_backend = None

_init_lock = threading.Lock()
_loading = False
_load_error: Optional[str] = None


def _load_qwen2_5_vl(model_id: str):
    from transformers import AutoProcessor
    try:
        from transformers import Qwen2_5_VLForConditionalGeneration
    except Exception as e:
        raise RuntimeError("Please upgrade transformers for Qwen2.5-VL support.") from e

    torch_dtype = _resolve_torch_dtype()

    # 加载模型时启用 Flash Attention 2
    attn_implementation = "flash_attention_2" if USE_FLASH_ATTN and torch.cuda.is_available() else None

    model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
        model_id,
        torch_dtype=torch_dtype,
        device_map=_DEVICE_MAP,
        attn_implementation=attn_implementation  # 启用Flash Attention 2
    )

    # 配置processor的像素限制，减少图像token数
    processor = AutoProcessor.from_pretrained(model_id, min_pixels=MIN_PIXELS, max_pixels=MAX_PIXELS)

    model.eval()

    if attn_implementation == "flash_attention_2":
        print(f"Flash Attention 2 enabled, max_pixels={MAX_PIXELS}")
    else:
        print(f"Flash Attention 2 not enabled, max_pixels={MAX_PIXELS}")

    return model, processor


def _load_qwen_vl_chat(model_id: str):
    from transformers import AutoTokenizer, AutoModelForCausalLM
    torch_dtype = _resolve_torch_dtype()
    tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(model_id,
                                                 torch_dtype=torch_dtype,
                                                 device_map=_DEVICE_MAP,
                                                 trust_remote_code=True)
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
            if "qwen2.5-vl" in MODEL_ID.lower():
                _model, _processor = _load_qwen2_5_vl(MODEL_ID)
                _backend = "qwen2.5-vl"
            else:
                _model, _processor = _load_qwen_vl_chat(MODEL_ID)
                _backend = "qwen-vl-chat"
        except Exception as e:
            _load_error = f"{type(e).__name__}: {e}"
            raise
        finally:
            _loading = False


def _build_user_prompt(task: str) -> str:
    # 极简user prompt
    if task == "advice":
        return "输出JSON"
    if task == "pose":
        return "输出JSON"
    raise ValueError("task must be 'advice' or 'pose'")


# -------------------------- 拍摄建议 --------------------------
class ShootingAdvice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    composition: str = Field(max_length=120)
    focus: str = Field(max_length=120)
    atmosphere: str = Field(max_length=120)

    @field_validator("composition")
    @classmethod
    def _composition_prefix(cls, v):
        if not v.startswith("构图优化："):
            raise ValueError("必须以 构图优化： 开头")
        return v

    @field_validator("focus")
    @classmethod
    def _focus_prefix(cls, v):
        if not v.startswith("焦点调整："):
            raise ValueError("必须以 焦点调整： 开头")
        return v

    @field_validator("atmosphere")
    @classmethod
    def _atmosphere_prefix(cls, v):
        if not v.startswith("氛围强化："):
            raise ValueError("必须以 氛围强化： 开头")
        return v


# -------------------------- 姿势引导 --------------------------
class PoseGuide(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pose_title: str = Field(min_length=8, max_length=40)
    instructions: list[str] = Field(min_length=3, max_length=6)

    @field_validator("pose_title")
    @classmethod
    def _pose_title_format(cls, v: str) -> str:
        if not v.startswith("推荐姿势："):
            raise ValueError("pose_title must start with 推荐姿势：")
        if len(v.replace("推荐姿势：", "").strip()) == 0:
            raise ValueError("pose_title missing pose name")
        return v

    @field_validator("instructions")
    @classmethod
    def _instructions_each(cls, v: list[str]) -> list[str]:
        for item in v:
            if not isinstance(item, str) or len(item.strip()) < 4:
                raise ValueError("each instruction must be a complete sentence")
            bad = ("-", "•", "*", "1.", "2.", "3.")
            if item.strip().startswith(bad):
                raise ValueError("no bullets/numbering")
        return v


def _system_prompt_for(task: str) -> str:
    # 极简system prompt，让processor自动添加特殊token
    if task == "advice":
        return ("摄影专家。输出JSON："
                '{"composition":"构图优化：xxx","focus":"焦点调整：xxx","atmosphere":"氛围强化：xxx"}'
                " 限制：仅JSON，中文")
    if task == "pose":
        return ("姿势专家。输出JSON："
                '{"pose_title":"推荐姿势：xxx","instructions":["xxx","xxx","xxx"]}'
                " 限制：仅JSON，中文")
    raise ValueError("task must be 'advice' or 'pose'")


def _extract_json_object(text: str) -> str:
    text = text.replace("｛", "{").replace("｝", "}")
    start = text.find("{")
    if start == -1:
        raise ValueError("no JSON")
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    raise ValueError("unclosed JSON")


def _parse_kv_fallback(task: str, text: str) -> dict:
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)

    def get(key):
        m = re.search(rf"(?im)^\s*{re.escape(key)}\s*[:：]\s*(.+)$", text)
        if not m:
            return None
        v = m.group(1).strip().strip(",").strip('"').strip("'")
        return v if v else None

    if task == "advice":
        o = {"composition": get("composition"), "focus": get("focus"), "atmosphere": get("atmosphere")}
        if all(o.values()):
            return o
    if task == "pose":
        t = get("pose_title")
        m = re.search(r"(?im)instructions\s*[:：]\s*(\[.*\])", text)
        arr = json.loads(m.group(1)) if m else []
        if t and isinstance(arr, list) and len(arr) >= 3:
            return {"pose_title": t, "instructions": arr}
    raise ValueError("kv parse failed")


def _parse_prefixed_lines(task: str, text: str) -> dict:
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL).replace("\r\n", "\n")

    def clean(s):
        return re.sub(r"^[-•*\d.)、]+", "", s.strip()).strip()

    if task == "advice":
        lines = [clean(ln) for ln in text.splitlines() if clean(ln)]
        res = {}
        for ln in lines:
            if ln.startswith("构图优化："):
                res["composition"] = ln
            if ln.startswith("焦点调整："):
                res["focus"] = ln
            if ln.startswith("氛围强化："):
                res["atmosphere"] = ln
        if len(res) == 3:
            return res
    if task == "pose":
        lines = [clean(ln) for ln in text.splitlines() if clean(ln)]
        title = next((ln for ln in lines if ln.startswith("推荐姿势：")), None)
        instr = [ln for ln in lines if not ln.startswith("推荐姿势：")][:6]
        if title and len(instr) >= 3:
            return {"pose_title": title, "instructions": instr}
    raise ValueError("line parse failed")


def _validate_and_normalize(task: str, raw: str) -> dict:
    raw = raw.strip()
    if "{" in raw:
        js = _extract_json_object(raw)
        try:
            obj = json.loads(js)
        except:
            obj = ast.literal_eval(js)
        return ShootingAdvice.model_validate(obj).model_dump() if task == "advice" else PoseGuide.model_validate(
            obj).model_dump()
    try:
        return _parse_kv_fallback(task, raw)
    except:
        return _parse_prefixed_lines(task, raw)


def _image_stats(img):
    try:
        g = img.convert("L").resize((128, 128))
        ps = list(g.getdata())
        avg = sum(ps) / len(ps)
        dev = (sum((p - avg)**2 for p in ps) / len(ps))**0.5
        return avg, dev
    except:
        return 127, 0


def _fallback_seed(img):
    try:
        return int(hashlib.sha256(img.tobytes()).hexdigest()[:8], 16)
    except:
        return hash(img.size)


def _fallback_advice(img):
    avg, dev = _image_stats(img)
    comp = "构图优化：将主体放在三分线位置，适当留白，画面更平衡。"
    focus = "焦点调整：对准主体关键部位，确保清晰，背景适度虚化。"
    atm = "氛围强化：光线自然柔和，色彩适中，整体干净通透。"
    if avg < 80:
        atm = "氛围强化：画面偏暗，可适当提亮，保留细节更清晰。"
    elif avg > 175:
        atm = "氛围强化：画面偏亮，略微压暗，层次更明显。"
    return {"composition": comp, "focus": focus, "atmosphere": atm}


def _fallback_pose(img):
    return {"pose_title": "推荐姿势：自然站姿", "instructions": ["身体微侧，放松肩膀", "双手自然摆放", "眼神柔和看向前方"]}


def _run_generate_json(image: Image.Image, path: str, task: str) -> dict:
    _lazy_init()
    system = _system_prompt_for(task)
    user = _build_user_prompt(task)

    # 构建messages（processor会自动添加特殊token）
    msgs = [{
        "role": "system",
        "content": system
    }, {
        "role": "user",
        "content": [{
            "type": "image",
            "image": image
        }, {
            "type": "text",
            "text": user
        }]
    }]

    # 应用chat template
    text = _processor.apply_chat_template(msgs, add_generation_prompt=True)

    # 处理输入
    ipt = _processor(text=[text], images=[image], padding=True,
                     return_tensors="pt").to(next(_model.parameters()).device)

    # 生成参数优化：temperature=0, do_sample=False, num_beams=1, 减少max_new_tokens
    with torch.no_grad():
        out = _model.generate(
            **ipt,
            max_new_tokens=MAX_NEW_TOKENS,
            temperature=TEMPERATURE,
            top_p=TOP_P,
            do_sample=False,  # 贪心解码，最快
            num_beams=1,  # 束搜索=1
            pad_token_id=_processor.tokenizer.pad_token_id,
            eos_token_id=_processor.tokenizer.eos_token_id)

    # 解码输出
    output_text = _processor.decode(out[0][ipt.input_ids.shape[1]:], skip_special_tokens=True).strip()

    # 验证并规范化
    try:
        res = _validate_and_normalize(task, output_text)
        res["__source"] = "model"
        return res
    except Exception as e:
        print(f"Validation failed: {e}, output: {output_text[:200]}")
        if FAIL_OPEN:
            fb = _fallback_advice(image) if task == "advice" else _fallback_pose(image)
            fb["__source"] = "fallback"
            return fb
        raise HTTPException(500, f"inference failed: {e}")


app = FastAPI(title="VLM API Optimized")


@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL_ID}


@app.get("/model/status")
def status():
    return {
        "model": MODEL_ID,
        "loaded": _model is not None,
        "cuda": torch.cuda.is_available(),
        "device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "flash_attention": USE_FLASH_ATTN and torch.cuda.is_available(),
        "max_pixels": MAX_PIXELS,
        "min_pixels": MIN_PIXELS
    }


@app.post("/vlm/infer")
async def infer(file: Optional[UploadFile] = File(None),
                image: Optional[UploadFile] = File(None),
                task: str = Form(...)):
    print(f'New task {task}: 0.000')
    t0 = time.time()
    up = file or image
    if not up:
        raise HTTPException(422, "missing image")
    raw = await up.read()
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(suffix=".jpg")
        os.close(fd)
        with open(tmp, "wb") as f:
            f.write(raw)
        im = Image.open(io.BytesIO(raw)).convert("RGB")

        # 调整图片尺寸（进一步减少处理时间）
        if MAX_IMAGE_SIDE and max(im.size) > MAX_IMAGE_SIDE:
            r = MAX_IMAGE_SIDE / max(im.size)
            im = im.resize((round(im.width * r), round(im.height * r)), Image.Resampling.LANCZOS)
            im.save(tmp, "JPEG", quality=85)  # 降低quality到85，加快保存

        async with _sema:
            delta_time = time.time() - t0
            print(f'Start inferencing: {delta_time:.3f}s')
            data = await asyncio.to_thread(_run_generate_json, im, tmp, task)
            delta_time = time.time() - t0
            print(f'Complete inferencing: {delta_time:.3f}s')
    finally:
        if tmp and os.path.exists(tmp):
            os.remove(tmp)

    if not RETURN_META:
        for k in list(data.keys()):
            if k.startswith("__"):
                del data[k]
    return JSONResponse(data)


@app.on_event("startup")
def startup():
    if not DRY_RUN:
        _lazy_init()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8500)
