# 构图分析前端对接说明（Android / Kotlin）

本文档说明 Android 前端如何调用后端构图分析接口 `POST /api/composition/analyze`，并在手机端展示“构图类型 + 置信度”。

> 适用场景：后端部署在远程服务器（例如 `8.130.157.142:8080`），手机 App 直接走 HTTP 请求到服务器。

---

## 1. 你需要实现的前端功能清单（最小闭环）

1) 选择图片来源（相册选图 / 拍照后取照片）
2) 将图片作为 `multipart/form-data` 上传到后端
3) 解析后端返回的 `data` 列表
4) 展示结果（建议按 `confidence` 从高到低排序）
5) 错误提示：
   - 未选择图片
   - 图片过大（后端限制 10MB）
   - 不是 JPG/JPEG/PNG
   - 网络异常/超时

---

## 2. 接口信息（与后端实现一致）

### 2.1 baseURL
- `http://8.130.157.142:8080/api/`

> Retrofit 的 `baseUrl()` 建议以 `/` 结尾。

### 2.2 构图分析接口
- Method: `POST`
- Path: `/composition/analyze`
- Content-Type: `multipart/form-data`
- 表单字段：
  - `image`：图片文件

### 2.3 返回格式
成功时：

```json
{
  "code": 200,
  "msg": "构图分析成功",
  "data": [
    {"name": "三分法构图", "confidence": 85.6},
    {"name": "对称构图", "confidence": 72.3}
  ]
}
```

未识别到明显构图特征（或模型未加载成功时）可能返回：

```json
{
  "code": 200,
  "msg": "未检测到明显的构图特征",
  "data": []
}
```

常见错误：
- `code=400 msg=请上传图片文件`
- `code=400 msg=仅支持 JPG、JPEG、PNG 格式的图片`

---

## 3. 一个容易踩坑的点：文件名必须带扩展名

后端校验图片格式的方式是“看文件名后缀名”（.jpg/.jpeg/.png）。

因此前端上传时：
- **必须给 Multipart 的文件名带扩展名**，例如 `upload.jpg` 或 `xxx.png`
- 否则哪怕你传的是 JPEG 数据，也可能被后端判定为“不支持格式”。

---

## 4. Android 必备配置

### 4.1 权限
`AndroidManifest.xml`：

```xml
<uses-permission android:name="android.permission.INTERNET" />
```

### 4.2 允许明文 HTTP（如果你们没上 https）
开发联调期最简单：

```xml
<application
    android:usesCleartextTraffic="true"
    ...>
</application>
```

---

## 5. Retrofit 对接示例（可直接改成你们项目风格）

### 5.1 数据结构

```kotlin
data class CompositionItem(
    val name: String,
    val confidence: Double
)

data class ApiResponse<T>(
    val code: Int,
    val msg: String,
    val data: T? = null
)
```

### 5.2 API 定义

```kotlin
import okhttp3.MultipartBody
import retrofit2.http.Multipart
import retrofit2.http.POST
import retrofit2.http.Part

interface PhotoApi {
    @Multipart
    @POST("composition/analyze")
    suspend fun analyzeComposition(
        @Part image: MultipartBody.Part
    ): ApiResponse<List<CompositionItem>>
}
```

### 5.3 创建 MultipartBody.Part（从 Uri 上传）

推荐做法：直接从 `contentResolver.openInputStream(uri)` 读字节流，避免你必须拿到真实文件路径。

```kotlin
import android.content.ContentResolver
import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.MultipartBody
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody

private fun queryDisplayName(context: Context, uri: Uri): String? {
    val cr: ContentResolver = context.contentResolver
    cr.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { cursor ->
        if (cursor.moveToFirst()) {
            val idx = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
            if (idx >= 0) return cursor.getString(idx)
        }
    }
    return null
}

fun buildImagePart(context: Context, uri: Uri): MultipartBody.Part {
    val bytes = context.contentResolver.openInputStream(uri)!!.use { it.readBytes() }

    // 重要：文件名要带扩展名，保证后端通过后缀校验
    val displayName = queryDisplayName(context, uri)
    val filename = when {
        displayName != null && displayName.contains('.') -> displayName
        else -> "upload.jpg"  // 兜底：至少带 .jpg
    }

    // contentType 不严格依赖，但建议按实际类型
    val body: RequestBody = bytes.toRequestBody("image/*".toMediaTypeOrNull())
    return MultipartBody.Part.createFormData("image", filename, body)
}
```

> 如果你们已经有 File（真实路径），也可以用 `asRequestBody()`，但 Uri 方式兼容性更好。

### 5.4 调用并展示结果（建议排序）

```kotlin
val resp = api.analyzeComposition(buildImagePart(this, uri))
if (resp.code != 200) {
    // 业务错误：直接用 resp.msg 提示用户
} else {
    val list = (resp.data ?: emptyList()).sortedByDescending { it.confidence }
    // 展示 list
}
```

---

## 6. 图片大小限制与压缩建议

后端限制最大上传为 **10MB**。

前端建议：
- 上传前先读取文件大小（OpenableColumns.SIZE）
- 超过 10MB 时：提示用户或在本地压缩（降低分辨率/质量）再上传

---

## 7. 前端联调检查清单（遇到问题按顺序排）

1) 手机能访问服务器吗（同学电脑浏览器已经验证过）
2) Android 是否允许明文 HTTP（否则常见报错：`CLEARTEXT communication not permitted`）
3) 上传字段名是否是 `image`
4) 上传的 filename 是否带 `.jpg/.jpeg/.png`
5) 图片是否超过 10MB
6) 后端日志是否有收到请求、是否报错

---

## 8. 你们下一步可选增强（不影响最小闭环）

- 结果解释：给每种构图加一句说明（例如“三分法：主体放在九宫格交点附近”）
- 本地缓存：最近一次分析的图片与结果
- 将“分析结果 + 图片 URL”写入 materials（如果你们希望列表页能回看）
