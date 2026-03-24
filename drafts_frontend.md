# 云端草稿箱（Materials）前端对接说明（Android / Kotlin）

本文档说明：当用户拍摄后“不保存到本地相册”时，如何将图片上传到服务器并在草稿箱展示；当用户“保存到相册”时，是否同时上云由你们产品策略决定（推荐：相册 + 云端都保存）。

> 后端部署在服务器：以 `http://8.130.157.142:8080` 为例。

---

## 1. 你们要实现的交互（建议规则）

### 1.1 不保存到相册
- 手机端：不写入系统相册
- 同时：上传到云端草稿箱（status=0）
- 结果：草稿箱可跨设备同步

### 1.2 保存到相册
两种产品策略二选一：
- 策略 A（推荐，支持云同步）：写入系统相册 + 同时上传到云端
  - 直接上传时传 `status=1`（表示作品）或先传 `status=0` 再转作品
- 策略 B（节省云端空间）：只写入系统相册，不上传云端

> 后端并不会“写入手机相册”；是否写相册是 Android 端逻辑。

### 1.3 作品云同步（跨设备登录可见）

后端已实现“作品集”的云端存储与列表拉取：

- 上传为作品：`POST /api/materials/upload` 传 `status=1`
- 或：先上传草稿 `status=0`，再调用 `POST /api/materials/work/:id` 转作品
- 拉取作品列表：`GET /api/materials/list?user_id=...&status=1`

前端建议：作品页打开时始终以云端 `status=1` 列表为准，这样不同手机登录都能看到一致的作品。

### 1.4 收藏模板云同步（跨设备登录可见）

后端已实现“收藏模板”的云端存储与列表拉取（基于 MySQL 表 `template_favorites`）：

- 收藏：`POST /api/templates/favorites`（JSON：`{"user_id":1,"template_id":"xxx"}`）
- 取消收藏：`DELETE /api/templates/favorites?user_id=1&template_id=xxx`
- 拉取收藏列表：`GET /api/templates/favorites?user_id=1&limit=100`

前端建议：

- 登录成功后先拉一次收藏列表，构建本地 `favoredSet`（template_id 集合）
- 收藏/取消收藏后：先更新本地 UI，再调用后端接口落库，保证跨设备一致

### 1.5 草稿云同步算法（你们前端要做的“同步策略”）

后端目前提供的是“云端存储 + 列表拉取”的能力；真正的“同步体验”取决于前端如何组织状态。推荐前端按下面规则实现：

- **本地草稿状态机**（建议）：
  - `LOCAL_ONLY`：仅本地存在（比如拍完还没上传）
  - `UPLOADING`：正在上传
  - `CLOUD_OK`：已上传，拿到 `material_id` + `url`
  - `FAILED_RETRY`：上传失败，待重试
- **网络恢复时重试**：把 `FAILED_RETRY` 的草稿重新走一次 `/api/materials/upload`。
- **云端对齐**：进入草稿箱页时，拉取 `GET /api/materials/list?status=0`，用 `material_id` 作为云端主键展示。

> 说明：后端当前是“每次上传都会插入一条 materials 记录”。如果你们希望“同一草稿更新覆盖”（比如同一个草稿反复编辑），需要新增一个“更新 material_id 对应 url”的接口；目前后端未提供。

---

## 2. 后端接口列表（与你们当前后端一致）

### 2.1 上传图片到云端并写入 materials
- `POST /api/materials/upload`
- `multipart/form-data`
  - `user_id`：必填
  - `status`：可选，0=草稿(默认)，1=作品
  - `template_id`：可选（如果本次是“拍同款模板”，请传模板 ID，用于使用量统计与推荐）
  - `image`：图片文件（也兼容字段名 `file`）
- 返回：

```json
{
  "code": 200,
  "msg": "上传成功",
  "data": {
    "material_id": 123,
    "url": "http://8.130.157.142:8080/static/uploads/u1/20260314/xxx.jpg"
  }
}
```

### 2.2 拉取草稿箱 / 作品列表
- `GET /api/materials/list?user_id=1&status=0`（草稿）
- `GET /api/materials/list?user_id=1&status=1`（作品）

### 2.3 草稿转作品
- `POST /api/materials/work/:id`

### 2.4 （可选）仅同步一个已存在的 URL

如果你们图片已经上传到别的存储（例如 OSS），也可以只把 URL 同步到后端数据库：

- `POST /api/drafts/upload`
- `Content-Type: application/json`

```json
{"user_id": 1, "url": "https://.../a.jpg"}
```

但如果你们用的是本项目的 `/api/materials/upload`（推荐），通常不需要再调用这个接口。

> 注意：`/api/drafts/upload` 这个接口在参数错误/服务端错误时会返回真实的 HTTP 400/500（不是一律 HTTP 200），前端需要同时处理 HTTP 状态码与 JSON 的 `code/msg`。

---

## 3. Android 必备配置

### 3.1 权限
`AndroidManifest.xml`：

```xml
<uses-permission android:name="android.permission.INTERNET" />
```

### 3.2 明文 HTTP（如果没上 https）

```xml
<application
    android:usesCleartextTraffic="true"
    ...>
</application>
```

---

## 4. Retrofit 示例（上传 + 列表）

> 你们可以把这些接口直接接到草稿箱页面。

### 4.1 API 定义

```kotlin
import okhttp3.MultipartBody
import okhttp3.RequestBody
import retrofit2.http.*

interface PhotoApi {
    @Multipart
    @POST("materials/upload")
    suspend fun uploadMaterial(
        @Part image: MultipartBody.Part,
        @Part("user_id") userId: RequestBody,
        @Part("status") status: RequestBody? = null,
        @Part("template_id") templateId: RequestBody? = null
    ): ApiResponse<UploadMaterialData>

    @GET("materials/list")
    suspend fun listMaterials(
        @Query("user_id") userId: Long,
        @Query("status") status: Int
    ): ApiResponse<List<MaterialItem>>

    @POST("materials/work/{id}")
    suspend fun convertToWork(@Path("id") materialId: Long): ApiResponse<Unit>

    // 收藏模板（云同步）
    @POST("templates/favorites")
    suspend fun addTemplateFavorite(@Body req: TemplateFavoriteReq): ApiResponse<Unit>

    // 注意：部分 Retrofit/OkHttp 对 DELETE + body 支持不一致，优先用 query 方式
    @DELETE("templates/favorites")
    suspend fun removeTemplateFavorite(
        @Query("user_id") userId: Long,
        @Query("template_id") templateId: String
    ): ApiResponse<Unit>

    @GET("templates/favorites")
    suspend fun listTemplateFavorites(
        @Query("user_id") userId: Long,
        @Query("limit") limit: Int = 100
    ): ApiResponse<List<TemplateFavoriteItem>>
}

data class UploadMaterialData(val material_id: Long, val url: String)

data class MaterialItem(
    val material_id: Long,
    val user_id: Long,
    val template_id: String? = null,
    val url: String,
    val status: Int,
    val shot_time: String?,
    val created_at: String?,
    val updated_at: String?
)

data class ApiResponse<T>(val code: Int, val msg: String, val data: T? = null)

data class TemplateFavoriteReq(val user_id: Long, val template_id: String)

data class TemplateFavoriteItem(
    val id: Long,
    val user_id: Long,
    val template_id: String,
    val created_at: String? = null
)
```

### 4.2 把 Uri 变成 Multipart（推荐方式）

```kotlin
fun buildImagePart(context: Context, uri: Uri): MultipartBody.Part {
    val bytes = context.contentResolver.openInputStream(uri)!!.use { it.readBytes() }
    val filename = "upload.jpg" // 确保有 .jpg/.png 后缀，避免后端按后缀校验失败
    val body = bytes.toRequestBody("image/*".toMediaTypeOrNull())
    return MultipartBody.Part.createFormData("image", filename, body)
}

fun textPart(s: String) = s.toRequestBody("text/plain".toMediaTypeOrNull())
```

### 4.3 上传草稿（status=0）

```kotlin
val resp = api.uploadMaterial(
    image = buildImagePart(this, uri),
    userId = textPart(userId.toString()),
    status = textPart("0"),
    templateId = null // 如果本次来自“拍同款模板”，这里传 templateId
)
```

### 4.4 拉取草稿箱列表并展示

```kotlin
val resp = api.listMaterials(userId = userId, status = 0)
val list = resp.data ?: emptyList()
// 用 Glide 加载 item.url
```

---

## 5. 常见问题排查

- 上传失败且 msg 提示格式不支持：确保 filename 带 `.jpg/.jpeg/.png`
- 413/上传失败：图片可能 > 10MB，需要前端压缩
- 显示网络错误：检查 cleartext、服务器端口、安全组
- 列表为空：确认用的是同一个 user_id；确认 status=0/1
