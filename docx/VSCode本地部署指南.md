# VS Code 本地部署指南

## 📋 快速部署流程

### 步骤 1：下载项目到本地

#### 方法 A：使用 VS Code 远程同步（推荐）

1. **在 VS Code 中打开远程服务器**
   - 按 `F1` 或 `Ctrl+Shift+P`
   - 输入 `Remote-SSH: Connect to Host`
   - 选择你的服务器

2. **下载项目到本地**
   - 在 VS Code 中，右键点击 `/root/photo_backend` 文件夹
   - 选择 `Download...`
   - 选择本地保存位置（如 `~/Projects/`）

3. **在本地打开项目**
   - 关闭远程连接
   - `File` → `Open Folder`
   - 选择刚下载的 `photo_backend` 文件夹

#### 方法 B：使用 SCP 命令

```bash
# 在本地终端执行
scp -r root@your-server-ip:/root/photo_backend ~/Projects/

# 然后用 VS Code 打开
code ~/Projects/photo_backend
```

#### 方法 C：使用 Git（最规范）

```bash
# 在服务器上初始化 Git 仓库
cd /root/photo_backend
git init
git add .
git commit -m "Initial commit"

# 在本地克隆
cd ~/Projects
git clone root@your-server-ip:/root/photo_backend.git
```

---

## 步骤 2：安装本地 Go 环境

### Windows 系统

1. **下载 Go**
   - 访问：https://go.dev/dl/
   - 下载 `go1.25.0.windows-amd64.msi`
   - 双击安装

2. **验证安装**
   ```powershell
   go version
   # 应该显示：go version go1.25.0 windows/amd64
   ```

### macOS 系统

1. **使用 Homebrew 安装**
   ```bash
   brew install go@1.25
   ```

2. **验证**
   ```bash
   go version
   ```

### Linux 系统

1. **手动安装**
   ```bash
   wget https://go.dev/dl/go1.25.0.linux-amd64.tar.gz
   sudo tar -C /usr/local -xzf go1.25.0.linux-amd64.tar.gz
   
   # 添加到 PATH
   echo 'export PATH=$PATH:/usr/local/go/bin' >> ~/.bashrc
   source ~/.bashrc
   ```

2. **验证**
   ```bash
   go version
   ```

---

## 步骤 3：安装 VS Code 扩展

在 VS Code 中安装以下扩展：

1. **Go 扩展**（必装）
   - 扩展 ID：`golang.Go`
   - 按 `Ctrl+Shift+X` 打开扩展面板
   - 搜索 "Go"
   - 点击安装

2. **GitLens**（可选，推荐）
   - 扩展 ID：`eamodio.gitlens`
   - 用于 Git 版本控制

---

## 步骤 4：配置项目依赖

### 1. 打开终端

在 VS Code 中：
- `Terminal` → `New Terminal`
- 或按 `` Ctrl+` ``

### 2. 下载依赖

```bash
# 进入项目目录
cd ~/Projects/photo_backend

# 配置国内镜像（如果在中国）
go env -w GOPROXY=https://goproxy.cn,direct

# 下载所有依赖
go mod download

# 验证依赖
go mod verify

# 整理依赖
go mod tidy
```

### 3. 验证版本一致性

```bash
# 检查关键依赖版本
go list -m all | grep -E "(onnxruntime_go|gin|gorm)"

# 应该显示：
# github.com/yalue/onnxruntime_go v1.27.0
# github.com/gin-gonic/gin v1.12.0
# gorm.io/gorm v1.31.1
```

---

## 步骤 5：配置 MySQL 数据库

### 1. 安装 MySQL

#### Windows
- 下载：https://dev.mysql.com/downloads/installer/
- 安装 MySQL Installer
- 记住 root 密码

#### macOS
```bash
brew install mysql@8.0
brew services start mysql@8.0
```

#### Linux
```bash
# Ubuntu/Debian
sudo apt install mysql-server -y
sudo systemctl start mysql

# CentOS/RHEL
sudo yum install mysql-community-server -y
sudo systemctl start mysqld
```

### 2. 创建数据库

```bash
mysql -u root -p
```

```sql
-- 创建数据库
CREATE DATABASE photography_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- 验证
SHOW DATABASES;
EXIT;
```

### 3. 修改数据库配置

编辑 `dao/db.go` 文件：

```go
// 找到第 15 行，修改为你的本地配置
dsn := "root:你的 MySQL 密码@tcp(127.0.0.1:3306)/photography_db?charset=utf8mb4&parseTime=True&loc=Local"
```

---

## 步骤 6：配置 ONNX Runtime

**好消息**：`onnxruntime_go` 会自动下载动态库，不需要手动安装！

```bash
# 只需要确保网络畅通，Go 会自动下载
go get github.com/yalue/onnxruntime_go@v1.27.0
go mod tidy
```

如果下载失败，配置代理：
```bash
go env -w GOPROXY=https://goproxy.cn,direct
go mod tidy
```

---

## 步骤 7：运行项目

### 方法 1：直接在 VS Code 中运行

```bash
# 在 VS Code 终端中
go run main.go
```

### 方法 2：编译后运行

```bash
# 编译
go build -o photo_backend.exe .    # Windows
go build -o photo_backend .         # macOS/Linux

# 运行
./photo_backend.exe    # Windows
./photo_backend        # macOS/Linux
```

### 方法 3：使用 VS Code 的 Run and Debug

1. 按 `F5` 或点击左侧运行图标
2. 选择 `Go: Launch main package`
3. 程序会在调试模式下运行

---

## 步骤 8：验证运行

### 检查启动日志

成功启动后应该看到：

```
✅ 数据库连接与自动迁移成功！
✅ 构图模型加载成功
🚀 服务启动于 http://localhost:8080
```

### 测试 API

打开浏览器或使用 curl：

```bash
# 测试健康检查
curl http://localhost:8080/api/register -X POST \
  -H "Content-Type: application/json" \
  -d '{"username":"test","password":"123456"}'
```

---

## 🔧 常见问题

### 问题 1：Go 版本过低

**错误**：
```
package photo_backend requires Go 1.25.0 or later
```

**解决**：
```bash
# 检查版本
go version

# 如果低于 1.25.0，需要升级
# 下载地址：https://go.dev/dl/
```

### 问题 2：依赖下载失败

**错误**：
```
dial tcp: lookup github.com: no such host
```

**解决**：
```bash
# 配置国内镜像
go env -w GOPROXY=https://goproxy.cn,direct

# 清除缓存重试
go clean -modcache
go mod tidy
```

### 问题 3：MySQL 连接失败

**错误**：
```
dial tcp 127.0.0.1:3306: connect: connection refused
```

**解决**：
```bash
# Windows：检查服务
sc query MySQL80
net start MySQL80

# macOS：
brew services start mysql@8.0

# Linux：
sudo systemctl start mysql
```

### 问题 4：端口被占用

**错误**：
```
bind: address already in use
```

**解决**：
```bash
# Windows
netstat -ano | findstr :8080
taskkill /F /PID 进程 ID

# macOS/Linux
lsof -i :8080
kill -9 进程 ID

# 或修改端口
# 编辑 main.go，将 :8080 改为 :8081
```

### 问题 5：模型文件找不到

**错误**：
```
创建会话失败：no such file
```

**解决**：
```bash
# 检查模型文件
ls -lh models/comp_model.onnx

# 如果文件不存在，从服务器重新下载
scp root@server:/root/photo_backend/models/comp_model.onnx ./models/
```

---

## 📝 关于 Conda 的说明

### ❌ 为什么不推荐使用 Conda？

1. **Conda 是 Python 环境管理工具**
   - Go 有自己的包管理系统（go mod）
   - Go 不需要虚拟环境

2. **Go 的环境管理方式**
   - Go 版本：使用官方安装包或版本管理工具（如 gvm）
   - 依赖管理：`go.mod` 和 `go.sum`
   - 跨平台：Go 自动处理

3. **正确的工具选择**
   ```
   Python 项目 → Conda / venv / poetry
   Go 项目     → go mod（内置）
   Node.js 项目 → npm / yarn
   ```

### ✅ 如果你坚持要用 Conda（不推荐）

```bash
# 只能管理 Python 相关依赖，对 Go 项目帮助不大
conda create -n photo_backend python=3.9
conda activate photo_backend

# Go 项目仍然需要单独配置
# 这个 Conda 环境对 Go 代码没有任何作用
```

---

## 🎯 最佳实践建议

### 1. 使用 Git 管理版本

```bash
# 初始化 Git
git init
git add .
git commit -m "Initial commit"

# 推送到远程仓库（可选）
git remote add origin https://github.com/yourname/photo_backend.git
git push -u origin main
```

### 2. 创建本地配置文件

创建 `.env.local` 文件（不要提交到 Git）：

```bash
# .env.local
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=root
DB_PASSWORD=你的本地密码
DB_NAME=photography_db
SERVER_PORT=8080
```

### 3. 使用 VS Code 工作区

```bash
# 创建工作区配置
# File -> Save Workspace As...
# 保存为 photo_backend.code-workspace
```

### 4. 配置 VS Code 设置

创建 `.vscode/settings.json`：

```json
{
    "go.gopath": "${env:GOPATH}",
    "go.toolsManagement.autoUpdate": true,
    "go.lintOnSave": "workspace",
    "go.formatOnSave": true,
    "go.buildOnSave": true,
    "go.testOnSave": false,
    "files.exclude": {
        "**/.git": true,
        "**/.DS_Store": true,
        "**/photo_backend.exe": true
    }
}
```

---

## 📊 部署检查清单

完成以下检查确保部署成功：

- [ ] Go 1.25.0+ 已安装
- [ ] VS Code Go 扩展已安装
- [ ] 项目已下载到本地
- [ ] `go mod download` 成功执行
- [ ] MySQL 8.0 已安装并运行
- [ ] 数据库 `photography_db` 已创建
- [ ] `dao/db.go` 中的数据库密码已修改
- [ ] `models/comp_model.onnx` 文件存在
- [ ] `go run main.go` 成功启动
- [ ] 能看到 "✅ 数据库连接与自动迁移成功！" 日志
- [ ] 能看到 "✅ 构图模型加载成功" 日志
- [ ] API 接口可以访问（http://localhost:8080）

---

## 🎉 总结

**正确的部署流程**：

1. ✅ 下载项目文件夹到本地
2. ✅ VS Code 打开项目
3. ✅ 安装 Go 1.25.0（**不是 Conda**）
4. ✅ 安装 VS Code Go 扩展
5. ✅ 执行 `go mod download`
6. ✅ 安装 MySQL 8.0
7. ✅ 创建数据库并修改配置
8. ✅ 运行 `go run main.go`

**关键点**：
- ❌ 不要用 Conda 管理 Go 环境
- ✅ 使用 Go 原生的 `go mod`
- ✅ 确保 Go 版本 ≥ 1.25.0
- ✅ 确保依赖版本与服务器一致

祝你部署成功！🚀
