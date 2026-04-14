# 模板前端接入说明（Android / Kotlin）

面向你描述的产品形态：

- 登录后进入“模板流式瀑布流”（封面图）。
- 点击模板进入详情页（同封面图，尽量少改动）。
- 进入拍摄页（叠加手绘图稿 overlay，**文字已直接画在 overlay 图片上**，不再需要 guides 坐标）。
- 模板卡片右下角显示“使用量 used_count”。

> 结论：后端给前端传的是 **JSON**（模板列表/详情等接口返回），图片本体不在 JSON 里传二进制，而是返回 **可访问的图片 URL**，前端用 Glide/Coil 加载。

---

## 1. 静态资源与 URL 规则

后端把项目目录 `./static` 映射到 URL 前缀 `/static`。

模板资源建议放：

- `static/templates/<template_id>/cover.jpg`（第 1 页：模板封面）
- `static/templates/<template_id>/overlay.png`（第 2 张：手绘图稿叠加图，建议透明 PNG，**文字也画在这张图里**）

> 说明：为了兼容旧前端字段，后端仍可能返回 `example_url`，但默认会回退为 `cover_url`（即：详情页显示封面图即可）。

因此前端最终拿到的 URL 形如：

- `http://8.130.157.142:8080/static/templates/<template_id>/cover.jpg`
- `http://8.130.157.142:8080/static/templates/<template_id>/overlay.png`

---

## 2. 后端到底“传了什么”？

### 2.1 模板列表/详情接口返回：JSON

所有模板相关接口返回结构一致：

```json
{
  "code": 200,
  "msg": "获取成功",
  "data": ...
}
```

注意：本项目是 **HTTP 状态码常为 200**，业务成功与否看 JSON 里的 `code`。

### 2.2 `TemplateItem` 字段（直接对应三页 UI）

后端返回的每个模板对象是 `TemplateItem`，关键字段：

- `template_id`：模板唯一 ID（目录名 / 收藏 / 使用量 / 拍同款上传都用它）
- 第 1 页封面：
  - `url`（兼容旧前端，等同 `cover_url`）
  - `cover_url`
- 第 2 页详情大图：`example_url`（现在默认等同 `cover_url`，尽量不让前端改动）
- 拍同款叠加图：`overlay_url`（手绘图稿 + **文字已内嵌**）
- 右下角使用量：`used_count`（已包含在返回里）
- 收藏状态：`favored`（如果传了 `user_id` 且后端可判断）

示例（字段可能因你的模板 meta 配置不同而略有差异）：

```json
{
  "template_id": "sea_bigshot_01",
  "name": "海边出大片",
  "title": "海边出大片",
  "url": "http://8.130.157.142:8080/static/templates/sea_bigshot_01/cover.jpg",
  "cover_url": "http://8.130.157.142:8080/static/templates/sea_bigshot_01/cover.jpg",
  "example_url": "http://8.130.157.142:8080/static/templates/sea_bigshot_01/cover.jpg",
  "overlay_url": "http://8.130.157.142:8080/static/templates/sea_bigshot_01/overlay.png",
  "tags": ["海边", "旅行"],
  "hot": 80,
  "used_count": 28765,
  "favored": false
}
```

---

## 3. 接口清单（前端页面怎么调用）

Retrofit baseUrl（末尾必须有 `/`）：

- `http://8.130.157.142:8080/api/`

### 3.1 登录后“瀑布流模板封面”（第 1 页）

推荐用热门接口：

- `GET /api/templates/hot?limit=20&user_id=<可选>`

前端展示：

- 瀑布流卡片图片：优先用 `cover_url`（或兼容用 `url`）
- 右下角使用量：`used_count`
- 标题：`title`（或 `name`）

> 如果你希望能显示“是否收藏”的小图标/高亮，需要传 `user_id`（且后端能查到收藏关系时会返回 `favored`）。

### 3.2 点击进入“模板详情页”（第 2 页）

- `GET /api/templates/detail?template_id=<id>&user_id=<可选>`

前端展示：

- 大图：优先 `example_url`，没有就用 `cover_url`（当前后端默认让 `example_url == cover_url`，所以前端基本不用改）
- 文字信息：`title`、`tags`、`used_count`、`favored`

### 3.3 进入“拍同款页”（第 3 页）

同样复用模板详情接口拿数据：

- `GET /api/templates/detail?template_id=<id>&user_id=<可选>`

前端做两件事：

1) 叠加手绘图稿：加载 `overlay_url`，覆盖到相机预览之上（透明 PNG 效果最好）。
2) 不再渲染 guides：文字已直接画在 `overlay.png` 中，前端只需要显示这张叠加图即可。

> 注意：为了避免 overlay 跟相机预览对不齐，overlay 的缩放策略要和相机预览保持一致（同 Fit 或同 Crop）。

---

## 4. “使用量 used_count”是怎么来的？前端要做什么？

- 后端在模板接口里会把 `used_count` 带给前端（你不用自己算）。
- 但要想让使用量增长、并让“作品信号”参与推荐，你在上传作品时必须把 `template_id` 一起传给后端。

作品/草稿上传：

- `POST /api/materials/upload`（multipart/form-data）
  - `image`：图片文件（字段名也兼容 `file`）
  - `user_id`：必填
  - `status`：`1` 表示作品（可选）
  - `template_id`：拍同款时必填（非常建议传）

这样后端会：

- 记录该作品使用了哪个模板（materials.template_id）
- 自动给该模板 `used_count + 1`
- 后续推荐中把“作品使用过的模板 tags”作为兴趣信号

---

## 5. Kotlin 数据结构（建议直接照用）

```kotlin
interface TemplateApi {
    @GET("templates/hot")
    suspend fun hotTemplates(
        @Query("limit") limit: Int = 20,
        @Query("user_id") userId: Long? = null
    ): ApiResponse<List<TemplateItem>>

    @GET("templates/detail")
    suspend fun templateDetail(
        @Query("template_id") templateId: String,
        @Query("user_id") userId: Long? = null
    ): ApiResponse<TemplateItem>

    @GET("templates/search")
    suspend fun searchTemplates(
        @Query("q") q: String,
        @Query("user_id") userId: Long? = null,
        @Query("limit") limit: Int = 50,
        @Query("recommend_limit") recommendLimit: Int = 10
    ): ApiResponse<SearchData>
}

data class ApiResponse<T>(val code: Int, val msg: String, val data: T? = null)

data class TemplateItem(
    val template_id: String,
    val name: String,
    val title: String? = null,
    val url: String,
    val cover_url: String? = null,
    val example_url: String? = null,
    val overlay_url: String? = null,
    // guides 已弃用：文字引导已烘焙到 overlay 图片里
    val guides: List<TemplateGuide>? = null,
    val tags: List<String> = emptyList(),
    val hot: Int = 0,
    val used_count: Int = 0,
    val favored: Boolean = false
)

data class TemplateGuide(
    val text: String,
    val x: Double,
    val y: Double,
    val align: String? = null
)

data class SearchData(
    val matches: List<TemplateItem> = emptyList(),
    val recommended: List<TemplateItem> = emptyList()
)
```

---

## 6. 你可能会用到的扩展（已实现，但不是必须）

- 收藏：`POST/DELETE/GET /api/templates/favorites`
- 偏好 tags：`GET/POST /api/preferences/tags`
- 个性化推荐：`GET /api/templates/recommend?user_id=...`

如果你先只做“瀑布流 + 详情 + 拍同款叠加 overlay + 上传带 template_id”，就已经能跑通核心闭环。
