# 摄影后端项目完整说明文档

## 📋 项目概览

这是一个基于 **Go + Gin + GORM** 开发的摄影管理后端服务，名为 `photo_backend`。项目实现了用户管理、素材管理以及基于 AI 的构图推荐功能。

---

## 🏗️ 项目架构

### 技术栈
- **Web 框架**: Gin v1.12.0
- **ORM**: GORM v1.31.1
- **数据库**: MySQL
- **AI 推理**: ONNX Runtime (onnxruntime_go v1.27.0)
- **密码加密**: bcrypt
- **CORS**: gin-contrib/cors

### 目录结构

```
photo_backend/
├── main.go                      # 应用入口
├── go.mod                       # 依赖管理
├── go.sum                       # 依赖锁定
├── explain.md                   # 项目说明文档
├── composition/                 # 构图分析模块（新增）
│   └── composition.go           # ONNX 模型推理核心
├── controller/                  # 控制器层
│   ├── user_controller.go       # 用户相关接口
│   ├── photo_controller.go      # 素材相关接口
│   ├── sync_controller.go       # 草稿同步接口
│   └── composition_controller.go # 构图分析接口（新增）
├── service/                     # 业务逻辑层
│   ├── user_service.go          # 用户注册/登录
│   ├── material_service.go      # 素材 CRUD 操作
│   └── composition_service.go   # 构图分析服务（新增）
├── dao/                         # 数据访问层
│   └── db.go                    # 数据库初始化
├── model/                       # 数据模型层
│   ├── user.go                  # 用户模型
│   ├── material.go              # 素材模型
│   └── preference.go            # 偏好模型
├── router/                      # 路由配置
│   └── router.go                # API 路由定义
└── models/                      # 机器学习模型
    └── comp_model.onnx          # ONNX 格式构图模型
```

---

## ✅ 已完成的功能模块

### 1. 项目基础架构 ✅
- [x] Go 模块配置 (`go.mod`)
- [x] 主入口文件 (`main.go`)
- [x] 数据库连接与自动迁移 (`dao/db.go`)
- [x] 路由配置 (`router/router.go`)
- [x] CORS 跨域支持
- [x] 文件上传大小限制（10MB）

### 2. 数据模型层 (Model) ✅

#### User 用户模型
```go
type User struct {
    ID        uint           // 唯一 ID 主键
    Username  string         // 用户名（唯一）
    Password  string         // 密码（bcrypt 加密）
    CreatedAt time.Time      // 创建时间
    UpdatedAt time.Time      // 更新时间
    DeletedAt gorm.DeletedAt // 软删除
}
```

#### Material 素材模型
```go
type Material struct {
    ID        uint           // 素材 ID 主键
    UserID    uint           // 用户外键 ID
    URL       string         // 素材存储路径/URL
    Status    int            // 状态：0=草稿，1=作品
    ShotTime  time.Time      // 拍摄时间
    CreatedAt time.Time      // 创建时间
    UpdatedAt time.Time      // 更新时间
    DeletedAt gorm.DeletedAt // 软删除
}
```

#### Preference 用户偏好模型
```go
type Preference struct {
    ID         uint      // 偏好 ID
    UserID     uint      // 用户外键 ID
    BitmapData []byte    // 位图数据
    Tags       string    // 偏好标签
    CreatedAt  time.Time // 创建时间
    UpdatedAt  time.Time // 更新时间
}
```

### 3. 用户系统 ✅
- [x] 用户注册接口 (`POST /api/register`)
- [x] 用户登录接口 (`POST /api/login`)
- [x] 密码 bcrypt 加密存储
- [x] 用户名唯一性校验
- [x] 登录返回用户信息和 ID

### 4. 素材管理功能 ✅
- [x] 草稿上传接口 (`POST /api/drafts/upload`)
- [x] 草稿转作品接口 (`POST /api/materials/work/:id`)
- [x] 素材列表获取接口 (`GET /api/materials/list?user_id=&status=`)
- [x] 状态管理：0=草稿，1=作品

### 5. 构图推荐功能（AI）✅ 【新增】

#### 核心功能
- [x] ONNX 模型加载与推理
- [x] 图片预处理（调整大小 224x224）
- [x] RGB 通道归一化
- [x] 双线性插值算法
- [x] Sigmoid 激活函数
- [x] 9 种构图类型识别
- [x] 置信度阈值过滤
- [x] 最佳推荐兜底逻辑

#### 支持的构图类型
1. 三分法
2. 中心构图
3. 水平构图
4. 对称构图
5. 对角线
6. 曲线构图
7. 垂直构图
8. 三角形
9. 重复图案

#### 实现文件
- `composition/composition.go` - ONNX 推理核心
- `service/composition_service.go` - 服务层封装
- `controller/composition_controller.go` - API 控制器

---

## 🎯 API 接口文档

### 基础信息
- **基础 URL**: `http://localhost:8080/api`
- **数据格式**: JSON
- **跨域**: 已启用 CORS（允许所有来源）

---

### 1. 用户注册

**接口**: `POST /api/register`

**请求参数**:
```json
{
  "username": "张三",
  "password": "123456"
}
```

**响应示例**:
```json
{
  "code": 200,
  "msg": "注册成功"
}
```

**错误响应**:
```json
{
  "code": 400,
  "msg": "参数错误"
}
```
或
```json
{
  "code": 500,
  "msg": "用户名已存在"
}
```

---

### 2. 用户登录

**接口**: `POST /api/login`

**请求参数**:
```json
{
  "username": "张三",
  "password": "123456"
}
```

**响应示例**:
```json
{
  "code": 200,
  "msg": "登录成功",
  "data": {
    "user_id": 1,
    "username": "张三"
  }
}
```

**错误响应**:
```json
{
  "code": 401,
  "msg": "用户不存在"
}
```
或
```json
{
  "code": 401,
  "msg": "密码错误"
}
```

---

### 3. 上传草稿

**接口**: `POST /api/drafts/upload`

**请求参数**:
```json
{
  "user_id": 1,
  "url": "http://example.com/photo.jpg"
}
```

**响应示例**:
```json
{
  "code": 200,
  "msg": "✅ 草稿同步成功"
}
```

**错误响应**:
```json
{
  "code": 400,
  "msg": "参数不完整或格式错误"
}
```

---

### 4. 草稿转作品

**接口**: `POST /api/materials/work/:id`

**路径参数**:
- `id`: 素材 ID

**示例**: `POST /api/materials/work/12`

**响应示例**:
```json
{
  "code": 200,
  "msg": "✅ 已成功保存至作品集"
}
```

**错误响应**:
```json
{
  "code": 400,
  "msg": "无效的素材 ID"
}
```

---

### 5. 获取素材列表

**接口**: `GET /api/materials/list`

**查询参数**:
- `user_id`: 用户 ID
- `status`: 状态（0=草稿，1=作品）

**示例**: `GET /api/materials/list?user_id=1&status=1`

**响应示例**:
```json
{
  "code": 200,
  "data": [
    {
      "material_id": 1,
      "user_id": 1,
      "url": "http://example.com/photo1.jpg",
      "status": 1,
      "shot_time": "2024-01-01T10:00:00Z",
      "created_at": "2024-01-01T10:00:00Z",
      "updated_at": "2024-01-01T10:00:00Z"
    }
  ]
}
```

---

### 6. 构图分析（AI 推荐）【新增】

**接口**: `POST /api/composition/analyze`

**请求类型**: `multipart/form-data`

**表单参数**:
- `image`: 图片文件（支持 JPG/JPEG/PNG，最大 10MB）

**请求示例** (使用 FormData):
```javascript
const formData = new FormData();
formData.append('image', imageFile);

fetch('http://localhost:8080/api/composition/analyze', {
  method: 'POST',
  body: formData
});
```

**成功响应**:
```json
{
  "code": 200,
  "msg": "构图分析成功",
  "data": [
    {
      "name": "三分法",
      "confidence": 85.6
    },
    {
      "name": "水平构图",
      "confidence": 72.3
    }
  ]
}
```

**无构图特征响应**:
```json
{
  "code": 200,
  "msg": "未检测到明显的构图特征",
  "data": []
}
```

**错误响应**:
```json
{
  "code": 400,
  "msg": "请上传图片文件"
}
```
或
```json
{
  "code": 400,
  "msg": "仅支持 JPG、JPEG、PNG 格式的图片"
}
```
或
```json
{
  "code": 500,
  "msg": "构图分析失败",
  "error": "详细错误信息"
}
```

---

## 🔧 部署指南

### 1. 环境要求

- Go 1.25.0+
- MySQL 5.7+ 或 8.0+
- ONNX Runtime 动态库

### 2. 安装依赖

#### 安装 ONNX Runtime (Linux)

```bash
# 方法 1: 使用包管理器
sudo apt-get update
sudo apt-get install -y libonnxruntime

# 方法 2: 下载预编译二进制
wget https://github.com/microsoft/onnxruntime/releases/download/v1.16.0/onnxruntime-linux-x64-1.16.0.tgz
tar -xzf onnxruntime-linux-x64-1.16.0.tgz
export LD_LIBRARY_PATH=$PWD/onnxruntime-linux-x64-1.16.0/lib:$LD_LIBRARY_PATH
```

#### 安装 Go 依赖

```bash
cd /root/photo_backend
go mod download
```

### 3. 数据库配置

#### 创建数据库

```sql
CREATE DATABASE photography_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

#### 修改数据库连接字符串

编辑 `dao/db.go`:
```go
dsn := "root:你的密码@tcp(127.0.0.1:3306)/photography_db?charset=utf8mb4&parseTime=True&loc=Local"
```

### 4. 编译与运行

```bash
cd /root/photo_backend

# 编译
go build -o photo_backend .

# 运行
./photo_backend
```

### 5. 验证启动

成功启动后应看到以下日志：

```
✅ 数据库连接与自动迁移成功！
✅ 构图模型加载成功
🚀 服务启动于 http://localhost:8080
```

---

## 🧪 测试方法

### 使用 curl 测试

#### 测试用户注册
```bash
curl -X POST http://localhost:8080/api/register \
  -H "Content-Type: application/json" \
  -d '{"username":"testuser","password":"123456"}'
```

#### 测试用户登录
```bash
curl -X POST http://localhost:8080/api/login \
  -H "Content-Type: application/json" \
  -d '{"username":"testuser","password":"123456"}'
```

#### 测试构图分析
```bash
curl -X POST http://localhost:8080/api/composition/analyze \
  -F "image=@/path/to/your/test_image.jpg"
```

#### 测试素材列表
```bash
curl "http://localhost:8080/api/materials/list?user_id=1&status=1"
```

### 使用 Postman 测试

1. 导入 API 接口配置
2. 设置请求方法和 URL
3. 添加请求头（Content-Type）
4. 添加请求体（JSON 或 FormData）
5. 发送请求并查看响应

---

## 📝 前端集成示例

### Vue 3 示例

```vue
<template>
  <div>
    <input type="file" @change="handleImageUpload" accept="image/*" />
    <div v-if="compositionResults">
      <h3>构图推荐结果</h3>
      <ul>
        <li v-for="item in compositionResults" :key="item.name">
          {{ item.name }} - {{ item.confidence.toFixed(1) }}%
        </li>
      </ul>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'

const compositionResults = ref([])

async function handleImageUpload(event) {
  const file = event.target.files[0]
  if (!file) return

  const formData = new FormData()
  formData.append('image', file)

  try {
    const response = await fetch('http://localhost:8080/api/composition/analyze', {
      method: 'POST',
      body: formData
    })

    const result = await response.json()
    if (result.code === 200) {
      compositionResults.value = result.data
    }
  } catch (error) {
    console.error('构图分析失败:', error)
  }
}
</script>
```

### React 示例

```jsx
import { useState } from 'react'

function CompositionAnalyzer() {
  const [results, setResults] = useState([])

  const handleImageUpload = async (event) => {
    const file = event.target.files[0]
    if (!file) return

    const formData = new FormData()
    formData.append('image', file)

    try {
      const response = await fetch('http://localhost:8080/api/composition/analyze', {
        method: 'POST',
        body: formData
      })

      const result = await response.json()
      if (result.code === 200) {
        setResults(result.data)
      }
    } catch (error) {
      console.error('构图分析失败:', error)
    }
  }

  return (
    <div>
      <input type="file" onChange={handleImageUpload} accept="image/*" />
      {results.length > 0 && (
        <div>
          <h3>构图推荐结果</h3>
          <ul>
            {results.map((item, index) => (
              <li key={index}>
                {item.name} - {item.confidence.toFixed(1)}%
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
```

---

## ⚙️ 配置说明

### 1. 数据库配置

文件：`dao/db.go`

```go
dsn := "root:123456@tcp(127.0.0.1:3306)/photography_db?charset=utf8mb4&parseTime=True&loc=Local"
```

**参数说明**:
- `root`: 数据库用户名
- `123456`: 数据库密码
- `127.0.0.1`: 数据库地址
- `3306`: 数据库端口
- `photography_db`: 数据库名称

### 2. 模型路径配置

文件：`main.go`

```go
err := service.InitCompositionService("models/comp_model.onnx")
```

**说明**: 确保 `comp_model.onnx` 文件存在于 `models/` 目录下

### 3. 置信度阈值

文件：`composition/composition.go`

```go
threshold := 0.35  // 默认 35% 置信度
```

**调整建议**:
- 提高阈值（如 0.5）：减少推荐数量，提高准确性
- 降低阈值（如 0.2）：增加推荐数量，可能包含更多可能性

### 4. 上传大小限制

文件：`router/router.go`

```go
r.MaxMultipartMemory = 10 << 20  // 10MB
```

### 5. CORS 配置

文件：`router/router.go`

```go
r.Use(cors.New(cors.Config{
    AllowOrigins:     []string{"*"},
    AllowMethods:     []string{"GET", "POST", "PUT", "DELETE", "OPTIONS"},
    AllowHeaders:     []string{"Origin", "Content-Type", "Authorization"},
    ExposeHeaders:    []string{"Content-Length"},
    AllowCredentials: true,
    MaxAge:           12 * 3600,
}))
```

**生产环境建议**:
```go
AllowOrigins: []string{"https://your-domain.com"}
```

---

## 🐛 常见问题与解决方案

### 1. 数据库连接失败

**错误**: `❌ 数据库连接失败：dial tcp 127.0.0.1:3306: connect: connection refused`

**解决方案**:
- 检查 MySQL 服务是否启动：`systemctl status mysql`
- 验证用户名密码是否正确
- 确认数据库 `photography_db` 已创建

### 2. ONNX Runtime 库找不到

**错误**: `error while loading shared libraries: libonnxruntime.so: cannot open shared object file`

**解决方案**:
```bash
# 设置动态库路径
export LD_LIBRARY_PATH=/path/to/onnxruntime/lib:$LD_LIBRARY_PATH

# 或者复制到系统库目录
sudo cp /path/to/onnxruntime/lib/libonnxruntime.so /usr/lib/
```

### 3. 模型加载失败

**错误**: `⚠️ 构图模型初始化失败：创建会话失败：no such file`

**解决方案**:
- 确认 `models/comp_model.onnx` 文件存在
- 检查文件路径是否正确（相对于可执行文件位置）
- 验证文件权限：`chmod 644 models/comp_model.onnx`

### 4. CORS 错误

**错误**: `Access to fetch at '...' from origin '...' has been blocked by CORS policy`

**解决方案**:
- 确认 `router/router.go` 中已配置 CORS 中间件
- 检查前端请求的域名是否在 `AllowOrigins` 列表中

### 5. 上传文件大小超限

**错误**: `http: request body too large`

**解决方案**:
- 在 `router/router.go` 中增加 `MaxMultipartMemory` 限制
- 或者在前端压缩图片后再上传

---

## 📊 性能优化建议

### 1. 数据库优化

```go
// 添加索引（已自动迁移）
// User: username 唯一索引
// Material: user_id 索引，deleted_at 索引
// Preference: user_id 唯一索引
```

### 2. 连接池配置

```go
// 在 dao/db.go 中添加
DB.SetMaxIdleConns(10)
DB.SetMaxOpenConns(100)
DB.SetConnMaxLifetime(time.Hour)
```

### 3. 图片处理优化

- 考虑使用图片处理服务（如 imgproxy）进行预处理
- 实现图片压缩和缩略图生成
- 使用 CDN 存储静态资源

### 4. 模型推理优化

- 考虑使用 ONNX Runtime 的 GPU 加速
- 实现模型推理结果缓存
- 批量推理优化

---

## 🔐 安全建议

### 1. 密码安全
- ✅ 已使用 bcrypt 加密
- 建议添加密码强度校验

### 2. 文件上传安全
- ✅ 已限制文件类型
- 建议添加文件内容校验（魔数检查）
- 建议限制上传频率

### 3. API 安全
- 建议添加 JWT 认证
- 建议实现请求限流
- 建议添加 CSRF 保护

### 4. 数据库安全
- 使用环境变量存储数据库凭证
- 不要将敏感信息提交到版本控制

---

## 📈 后续扩展建议

### 功能扩展
1. 用户头像上传
2. 素材分类和标签
3. 素材搜索功能
4. 用户偏好学习
5. 批量处理接口
6. 图片编辑功能

### 技术优化
1. Redis 缓存
2. 消息队列（异步处理）
3. Docker 容器化
4. Kubernetes 编排
5. CI/CD 流水线
6. 监控和日志系统

---

## 📞 技术支持

### 开发环境
- Go: 1.25.0
- 操作系统：Linux
- 数据库：MySQL 8.0

### 相关文档
- [Gin 框架文档](https://gin-gonic.com/zh-cn/docs/)
- [GORM 文档](https://gorm.io/zh_CN/docs/index.html)
- [ONNX Runtime 文档](https://onnxruntime.ai/)

---

## 📝 更新日志

### v1.0.0 (2024-01-01)
- ✅ 实现用户注册登录功能
- ✅ 实现素材管理功能
- ✅ 实现草稿 - 作品状态转换
- ✅ 集成 ONNX 构图分析模型
- ✅ 实现图片预处理和推理
- ✅ 添加 CORS 跨域支持
- ✅ 完善 API 接口文档

---

## 🎉 总结

本项目是一个功能完整的摄影管理后端系统，已实现：

- ✅ **完整的 MVC 架构**：清晰的代码分层
- ✅ **用户认证系统**：安全的注册/登录流程
- ✅ **素材全生命周期管理**：从草稿到作品
- ✅ **AI 构图推荐**：基于 ONNX 的深度学习模型
- ✅ **数据库自动迁移**：便捷的表结构管理
- ✅ **安全的密码加密**：bcrypt 算法
- ✅ **规范的 API 设计**：RESTful 风格
- ✅ **跨域支持**：方便前端集成

**项目完成度：核心功能 100% 完成** 🎊

可以直接与前端对接使用！
