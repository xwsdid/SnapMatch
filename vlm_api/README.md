# VLM API (阶段一)

## 接口

- `GET /health`
- `GET /model/status`：查看是否已加载模型、是否启用 CUDA
- `POST /vlm/infer`
  - form-data:
    - `file`: 图片文件
    - `task`: `advice` | `pose`

阶段一先返回 `{ output: "..." }` 的原始文本；阶段二会改为强约束 JSON。

## 模型选择

通过环境变量 `VLM_MODEL_ID` 指定模型：

- Qwen2-VL（默认，小参数，推荐先跑通）：`Qwen/Qwen2-VL-2B-Instruct`
- 旧版 Qwen-VL-Chat：`Qwen/Qwen-VL-Chat`

服务会根据 `VLM_MODEL_ID` 自动选择推理后端。

## 常用环境变量

- `VLM_DRY_RUN=1`：不加载/不运行模型，直接返回固定文本（便于先联调链路）
- `VLM_EAGER_LOAD=1`：启动时预加载模型（生产建议）
- `VLM_BACKGROUND_LOAD=1`：启动后后台加载模型（开发机推荐，不会卡住一次请求）
- `VLM_MAX_CONCURRENT=1`：限制并发，避免 OOM
- `VLM_TORCH_DTYPE=auto|float16|bfloat16|float32`
- `VLM_DEVICE_MAP=auto|cpu|cuda`

下载加速（可选）：

- `HF_TOKEN=...`：提高 HuggingFace 下载限速
- Windows 下看到 symlink 警告可忽略，或开启“开发者模式/管理员”以支持 symlink
