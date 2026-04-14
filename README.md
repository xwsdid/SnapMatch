# Photo Backend（4C）

Go + Gin 后端服务，提供用户/素材/模板/偏好等接口，并集成两类推理能力：

- 构图分析：后端本地 ONNX（可选，未配置则自动降级为“功能不可用”但服务可启动）
- VLM 多模态：通过 HTTP 转发到独立的 Python `vlm_api`（可部署在 Windows GPU 机器上，后端在 Linux 服务器上通过 SSH 反向隧道访问）

## 目录结构

- `router/`：Gin 路由与中间件装配（接口统一挂在 `/api`）
- `controller/`：HTTP 入参解析与统一返回
- `service/`：业务逻辑（DB 读写、推荐/统计、推理转发）
- `dao/`：数据库连接与 AutoMigrate
- `model/`：GORM 数据模型
- `composition/`：构图分析相关实现
- `comp_model/`：模型训练/导出脚本（Python）
- `vlm_api/`：Python（FastAPI）推理微服务
- `static/`：静态资源（上传图片、模板等），运行时通过 `/static` 暴露
- `deploy/systemd/`：systemd 示例配置
- `docx/`：更详细的开发/联调/部署文档

## 接口概览

- API 前缀：`/api`
- 静态资源：`/static`（例如：`/static/uploads/...`）

部分路由可在 `router/router.go` 查看（例如 `/api/login`、`/api/templates/*`、`/api/vlm/infer`）。

## 快速启动（本地开发）

### 1）准备依赖

- Go（建议与服务器一致：Go 1.21+）
- MySQL（默认连接 `127.0.0.1:3306/photography_db`，可通过环境变量覆盖）

### 2）配置环境变量（最小集）

- `PHOTO_DB_DSN`：MySQL DSN
	- 默认：`root:123456@tcp(127.0.0.1:3306)/photography_db?charset=utf8mb4&parseTime=True&loc=Local`
- `PORT`：后端监听端口（默认 `8080`）

可选（推理相关）：

- `COMPOSITION_MODEL_PATH`：构图 ONNX 模型路径（默认 `models/comp_model.onnx`）
- `ONNXRUNTIME_SHARED_LIBRARY_PATH`：ONNX Runtime 动态库路径（Linux 常用；未设置时会尝试在常见路径自动探测）
- `VLM_API_BASE_URL`：VLM 服务基础地址（例如 `http://127.0.0.1:18000`）
- `VLM_API_URL`：直接指定完整 VLM 推理 URL（优先级高于 `VLM_API_BASE_URL`，例如 `http://127.0.0.1:18000/vlm/infer`）
- `VLM_HTTP_TIMEOUT_SECONDS`：后端调用 VLM 的超时（默认 120 秒）

### 3）启动

在仓库根目录执行：

```bash
go run .
```

启动后默认监听：`http://0.0.0.0:8080`。

## VLM（Windows GPU）联调方式（推荐：SSH 反向隧道）

典型部署是：

- Linux 服务器：运行本 Go 后端
- Windows（有 GPU）：运行 `vlm_api`（仅监听本机 `127.0.0.1:8000`）
- 通过 SSH 反向隧道把 Windows 的 `127.0.0.1:8000` 映射到服务器的 `127.0.0.1:<端口>`

### 1）在 Windows 启动 `vlm_api`

参考 `vlm_api` 目录下文档：

- `vlm_api/README.md`

示例（仅本机可访问）：

```bash
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

### 2）在 Windows 建立 SSH 反向隧道

建议避免占用冲突，使用一个不常用端口（例如 18000）：

```bash
ssh -N \
	-R 18000:127.0.0.1:8000 \
	root@<server_ip> -p 22 \
	-o ExitOnForwardFailure=yes \
	-o ServerAliveInterval=30 \
	-o ServerAliveCountMax=3
```

### 3）在服务器配置后端指向隧道端口

例如：

```bash
export VLM_API_BASE_URL=http://127.0.0.1:18000
```

然后重启后端服务。

更完整的排障与联调说明见：

- `docx/启动说明.md`

## systemd 部署（服务器）

示例文件在：

- `deploy/systemd/photo-backend.service`
- `deploy/systemd/photo-backend.env.example`

建议做法：

1. 将 `photo-backend.env.example` 复制为实际环境文件（例如 `/etc/photo_backend.env`）并修改其中的 `PHOTO_DB_DSN`、`VLM_API_BASE_URL`、`ONNXRUNTIME_SHARED_LIBRARY_PATH` 等。
2. 安装/启用 systemd service 并启动。

## 常见问题

- VLM 调用超时：可增大 `VLM_HTTP_TIMEOUT_SECONDS`；同时确认隧道仍然在线、端口未被占用。
- 本机访问 `localhost/127.0.0.1` 走代理导致超时：后端对 loopback 已显式禁用代理，但仍建议正确配置 `NO_PROXY=127.0.0.1,localhost`。
- 构图模型不可用：检查 `COMPOSITION_MODEL_PATH` 是否存在、`ONNXRUNTIME_SHARED_LIBRARY_PATH`（Linux）是否正确。