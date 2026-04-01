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
TEMPERATURE = float(os.getenv("VLM_TEMPERATURE", "0.1"))
TOP_P = float(os.getenv("VLM_TOP_P", "0.9"))

MAX_IMAGE_SIDE = int(os.getenv("VLM_MAX_IMAGE_SIDE", 1280))
MAX_CONCURRENT = int(os.getenv("VLM_MAX_CONCURRENT", 1))
_sema = asyncio.Semaphore(MAX_CONCURRENT)

DRY_RUN = os.getenv("VLM_DRY_RUN", "0") in ("1", "true", "True")
DEBUG = os.getenv("VLM_DEBUG", "0") in ("1", "true", "True")
FAIL_OPEN = os.getenv("VLM_FAIL_OPEN", "1") in ("1", "true", "True")
RETURN_META = os.getenv("VLM_RETURN_META", "0") in ("1", "true", "True")

_TORCH_DTYPE_STR = os.getenv("VLM_TORCH_DTYPE", "auto").lower()
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
_backend = None

_init_lock = threading.Lock()
_loading = False
_load_error: Optional[str] = None


def _load_qwen2_vl(model_id: str):
    from transformers import AutoProcessor
    try:
        from transformers import Qwen2VLForConditionalGeneration
    except Exception as e:
        raise RuntimeError("Please upgrade transformers for Qwen2-VL support.") from e

    torch_dtype = _resolve_torch_dtype()
    model = Qwen2VLForConditionalGeneration.from_pretrained(
        model_id, torch_dtype=torch_dtype, device_map=_DEVICE_MAP
    )
    processor = AutoProcessor.from_pretrained(model_id)
    model.eval()
    return model, processor


def _load_qwen_vl_chat(model_id: str):
    from transformers import AutoTokenizer, AutoModelForCausalLM
    torch_dtype = _resolve_torch_dtype()
    tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        model_id, torch_dtype=torch_dtype, device_map=_DEVICE_MAP, trust_remote_code=True
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
    if task == "advice":
        return "请根据图片给出拍摄建议（只输出JSON，格式由system指定）。"
    if task == "pose":
        return "请根据图片给出人像姿势引导（只输出JSON，格式由system指定）。"
    raise ValueError("task must be 'advice' or 'pose'")


# -------------------------- 拍摄建议（强制前缀，无长度限制，稳定不掉）--------------------------
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
        if not v.startswith("✨ 推荐姿势："):
            raise ValueError("pose_title must start with ✨ 推荐姿势：")
        if len(v.replace("✨ 推荐姿势：", "").strip()) == 0:
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
    if task == "advice":
        return (
            "你是专业摄影指导。只输出合法JSON，不要任何多余文字。\n"
            "严格遵守以下规则，绝对不能违反：\n"
            "1. 只输出JSON，不要解释、不要前缀、不要后缀、不要markdown。\n"
            "2. 三个字段必须写不同内容：构图→布局；焦点→清晰度；氛围→光线色彩。\n"
            "3. 每个值必须以固定前缀开头：\n"
            "   - composition 必须以「构图优化：」开头\n"
            "   - focus 必须以「焦点调整：」开头\n"
            "   - atmosphere 必须以「氛围强化：」开头\n"
            "4. 必须使用英文双引号，必须合法JSON。"
        )
    if task == "pose":
        return (
            "你是人像姿势指导。只输出合法JSON，不要多余文字。\n"
            "1. pose_title 必须以「✨ 推荐姿势：」开头\n"
            "2. instructions 必须是3-6条完整动作句子\n"
            "3. 严格JSON格式，不要任何多余内容。"
        )
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
                return text[start:i+1]
    raise ValueError("unclosed JSON")


def _parse_kv_fallback(task: str, text: str) -> dict:
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    def get(key):
        m = re.search(rf"(?im)^\s*{re.escape(key)}\s*[:：]\s*(.+)$", text)
        if not m: return None
        v = m.group(1).strip().strip(",").strip('"').strip("'")
        return v if v else None
    if task == "advice":
        o = {"composition": get("composition"), "focus": get("focus"), "atmosphere": get("atmosphere")}
        if all(o.values()): return o
    if task == "pose":
        t = get("pose_title")
        m = re.search(r"(?im)instructions\s*[:：]\s*(\[.*\])", text)
        arr = json.loads(m.group(1)) if m else []
        if t and isinstance(arr, list) and len(arr)>=3:
            return {"pose_title": t, "instructions": arr}
    raise ValueError("kv parse failed")


def _parse_prefixed_lines(task: str, text: str) -> dict:
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL).replace("\r\n", "\n")
    def clean(s): return re.sub(r"^[-•*\d.)、]+", "", s.strip()).strip()
    if task == "advice":
        lines = [clean(ln) for ln in text.splitlines() if clean(ln)]
        res = {}
        for ln in lines:
            if ln.startswith("构图优化："): res["composition"] = ln
            if ln.startswith("焦点调整："): res["focus"] = ln
            if ln.startswith("氛围强化："): res["atmosphere"] = ln
        if len(res) == 3: return res
    if task == "pose":
        lines = [clean(ln) for ln in text.splitlines() if clean(ln)]
        title = next((ln for ln in lines if ln.startswith("✨ 推荐姿势：")), None)
        instr = [ln for ln in lines if not ln.startswith("✨")][:6]
        if title and len(instr)>=3:
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
        return ShootingAdvice.model_validate(obj).model_dump() if task=="advice" else PoseGuide.model_validate(obj).model_dump()
    try:
        return _parse_kv_fallback(task, raw)
    except:
        return _parse_prefixed_lines(task, raw)


def _image_stats(img):
    try:
        g = img.convert("L").resize((128,128))
        ps = list(g.getdata())
        avg = sum(ps)/len(ps)
        dev = (sum((p-avg)**2 for p in ps)/len(ps))**0.5
        return avg, dev
    except:
        return 127, 0


def _fallback_seed(img):
    try:
        return int(hashlib.sha256(img.tobytes()).hexdigest()[:8],16)
    except:
        return hash(img.size)


def _fallback_advice(img):
    avg, dev = _image_stats(img)
    seed = _fallback_seed(img)
    comp = "构图优化：将主体放在三分线位置，适当留白，画面更平衡。"
    focus = "焦点调整：对准主体关键部位，确保清晰，背景适度虚化。"
    atm = "氛围强化：光线自然柔和，色彩适中，整体干净通透。"
    if avg < 80:
        atm = "氛围强化：画面偏暗，可适当提亮，保留细节更清晰。"
    elif avg > 175:
        atm = "氛围强化：画面偏亮，略微压暗，层次更明显。"
    return {"composition": comp, "focus": focus, "atmosphere": atm}


def _fallback_pose(img):
    return {
        "pose_title": "✨ 推荐姿势：自然站姿",
        "instructions": ["身体微侧，放松肩膀", "双手自然摆放", "眼神柔和看向前方"]
    }


def _run_generate_json(image: Image.Image, path: str, task: str) -> dict:
    _lazy_init()
    system = _system_prompt_for(task)
    user = _build_user_prompt(task)

    def gen(extra=None):
        if _backend == "qwen-vl-chat":
            q = system + "\n\n" + (user if extra is None else extra)
            msg = _processor.from_list_format([{"image": path},{"text": q}])
            return _model.chat(_processor, query=msg, history=None)[0]
        msgs = [
            {"role": "system", "content": system},
            {"role": "user", "content": [{"type": "image", "image": image}, {"type": "text", "text": user if extra is None else extra}]}
        ]
        ipt = _processor(
            text=[_processor.apply_chat_template(msgs, add_generation_prompt=True)],
            images=[image], padding=True, return_tensors="pt"
        ).to(next(_model.parameters()).device)
        with torch.no_grad():
            out = _model.generate(**ipt, max_new_tokens=MAX_NEW_TOKENS, temperature=TEMPERATURE, top_p=TOP_P, do_sample=TEMPERATURE>0)
        return _processor.decode(out[0][ipt.input_ids.shape[1]:], skip_special_tokens=True).strip()

    # 稳定速度：最多重试1次
    for att in range(2):
        try:
            res = _validate_and_normalize(task, gen() if att==0 else gen("只输出合法JSON，不要任何多余文字。"))
            res["__source"] = "model"
            return res
        except Exception as e:
            if att == 1: break
    if FAIL_OPEN:
        fb = _fallback_advice(image) if task=="advice" else _fallback_pose(image)
        fb["__source"] = "fallback"
        return fb
    raise HTTPException(500, "inference failed")


app = FastAPI(title="VLM API")

@app.get("/health")
def health():
    return {"status":"ok","model":MODEL_ID}

@app.get("/model/status")
def status():
    return {
        "model":MODEL_ID, "loaded":_model is not None,
        "cuda":torch.cuda.is_available(), "device":torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
    }

@app.post("/vlm/infer")
async def infer(file:Optional[UploadFile]=File(None), image:Optional[UploadFile]=File(None), task:str=Form(...)):
    t0 = time.time()
    up = file or image
    if not up: raise HTTPException(422, "missing image")
    raw = await up.read()
    sha = hashlib.sha256(raw).hexdigest()[:16]
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(suffix=".jpg")
        os.close(fd)
        with open(tmp,"wb") as f: f.write(raw)
        im = Image.open(io.BytesIO(raw)).convert("RGB")
        if MAX_IMAGE_SIDE and max(im.size)>MAX_IMAGE_SIDE:
            r = MAX_IMAGE_SIDE/max(im.size)
            im = im.resize((round(im.width*r), round(im.height*r)), Image.Resampling.LANCZOS)
            im.save(tmp, "JPEG", quality=90)
        async with _sema:
            data = await asyncio.to_thread(_run_generate_json, im, tmp, task)
    finally:
        if tmp and os.path.exists(tmp): os.remove(tmp)
    if not RETURN_META:
        for k in list(data.keys()):
            if k.startswith("__"): del data[k]
    return JSONResponse(data)

@app.on_event("startup")
def startup():
    if not DRY_RUN:
        _lazy_init()