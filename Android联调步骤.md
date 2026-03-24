# Android（真机）联调 photo_backend（场景A：后端跑在远程服务器）

你已验证：在同一 Wi‑Fi 下，同学电脑浏览器访问

- `http://8.130.157.142:8080/api/materials/list?user_id=1&status=0`

返回 200。

这说明：**服务器公网 IP + 8080 端口已通**。接下来要做的就是：让 Android App 用同一个地址发 HTTP 请求到后端。

---

## 1. 你们要用的 baseURL（唯一正确）

- BaseURL：`http://8.130.157.142:8080/api/`

说明：

- Retrofit 的 `baseUrl()` **通常必须以 `/` 结尾**。
- 你后端所有路由都挂在 `/api` 下（例如 `/api/register`、`/api/login`）。

---

## 2. Android 必备配置（否则请求会失败）

### 2.1 Manifest 加网络权限

在 `AndroidManifest.xml`：

```xml
<uses-permission android:name="android.permission.INTERNET" />
```

### 2.2 允许明文 HTTP（Android 9+ 常见坑）

因为你的后端是 `http://` 而不是 `https://`，如果 App 的 `targetSdkVersion >= 28`，默认会拦截明文请求。

最省事（开发联调期）方式：

```xml
<application
    android:usesCleartextTraffic="true"
    ...>
</application>
```

如果你们更想“只放行这个 IP”，用 `network_security_config` 也行（需要额外 XML 文件）。

---

## 3. 后端注册/登录接口（按你项目真实代码）

### 3.1 注册

- `POST /api/register`
- JSON：

```json
{"username":"张三","password":"123456"}
```

- 成功返回：

```json
{"code":200,"msg":"注册成功"}
```

### 3.2 登录

- `POST /api/login`
- JSON 同上
- 成功返回：

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

注意：当前后端**没有 token/session**，所以前端登录成功后，先保存 `user_id` 就能继续调后续接口。

---

## 4. Retrofit（Kotlin）最小可跑示例

> 下面代码目标：**真机上点按钮 → 调 /register 或 /login → Toast 显示结果**。

### 4.1 依赖（Gradle）

`app/build.gradle`（或 `build.gradle.kts`）添加：

- Retrofit
- Gson 转换器
- OkHttp

示例（Groovy）：

```gradle
dependencies {
    implementation 'com.squareup.retrofit2:retrofit:2.11.0'
    implementation 'com.squareup.retrofit2:converter-gson:2.11.0'
    implementation 'com.squareup.okhttp3:okhttp:4.12.0'
    implementation 'com.squareup.okhttp3:logging-interceptor:4.12.0'
}
```

> 版本如果你们项目已有统一版本管理，就按你们现有的来。

### 4.2 数据结构

```kotlin
data class UserRequest(
    val username: String,
    val password: String
)

data class LoginData(
    val user_id: Long,
    val username: String
)

data class ApiResponse<T>(
    val code: Int,
    val msg: String,
    val data: T? = null
)
```

### 4.3 API 定义

```kotlin
import retrofit2.http.Body
import retrofit2.http.POST

interface PhotoApi {
    @POST("register")
    suspend fun register(@Body req: UserRequest): ApiResponse<Unit>

    @POST("login")
    suspend fun login(@Body req: UserRequest): ApiResponse<LoginData>
}
```

关键点：

- 因为 baseURL 已经是 `.../api/`，所以这里路径写 `register`、`login` 即可。

### 4.4 Retrofit 初始化

```kotlin
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory

object ApiClient {
    private const val BASE_URL = "http://8.130.157.142:8080/api/"

    private val okHttp: OkHttpClient by lazy {
        val log = HttpLoggingInterceptor().apply {
            level = HttpLoggingInterceptor.Level.BODY
        }
        OkHttpClient.Builder()
            .addInterceptor(log)
            .build()
    }

    val api: PhotoApi by lazy {
        Retrofit.Builder()
            .baseUrl(BASE_URL)
            .client(okHttp)
            .addConverterFactory(GsonConverterFactory.create())
            .build()
            .create(PhotoApi::class.java)
    }
}
```

### 4.5 调用示例（Activity / ViewModel 里）

你们用协程（推荐）：

```kotlin
import android.widget.Toast
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

fun doRegister(username: String, password: String) {
    lifecycleScope.launch {
        try {
            val resp = ApiClient.api.register(UserRequest(username, password))
            withContext(Dispatchers.Main) {
                Toast.makeText(this@MainActivity, "${resp.code} ${resp.msg}", Toast.LENGTH_LONG).show()
            }
        } catch (e: Exception) {
            withContext(Dispatchers.Main) {
                Toast.makeText(this@MainActivity, "请求失败: ${e.message}", Toast.LENGTH_LONG).show()
            }
        }
    }
}

fun doLogin(username: String, password: String) {
    lifecycleScope.launch {
        try {
            val resp = ApiClient.api.login(UserRequest(username, password))
            val userId = resp.data?.user_id
            withContext(Dispatchers.Main) {
                Toast.makeText(this@MainActivity, "${resp.code} ${resp.msg}, user_id=$userId", Toast.LENGTH_LONG).show()
            }
            // TODO: 把 userId 存到 SharedPreferences 里，后续拉列表要用
        } catch (e: Exception) {
            withContext(Dispatchers.Main) {
                Toast.makeText(this@MainActivity, "请求失败: ${e.message}", Toast.LENGTH_LONG).show()
            }
        }
    }
}
```

---

## 5. 真机联调排错清单（最常见 5 个坑）

1) **Cleartext 拦截**：报错常见关键词 `CLEARTEXT communication not permitted`

   - 解决：`android:usesCleartextTraffic="true"`
2) **没加网络权限**：请求直接失败

   - 解决：`INTERNET` 权限
3) **服务器端口/安全组没放行**：手机和电脑都访问不到

   - 解决：服务器安全组/防火墙放行 8080
4) **Retrofit baseUrl 少了结尾的 `/`**：初始化直接报错

   - 解决：确保 `http://8.130.157.142:8080/api/`
5) **后端连不上数据库导致 500**：手机能连上但接口返回 500

   - 解决：看服务器端日志；确认 MySQL 与 `dao/db.go` 的 DSN 密码一致

---

## 6. 你们下一步怎么“在手机上看到效果”（最短路径）

- 先做 2 个按钮：注册、登录
- 输入用户名/密码
- 点注册 → Toast 显示 `200 注册成功`
- 点登录 → Toast 显示 `200 登录成功 user_id=...`

做到这一步，就说明：**真机 ⇄ 远程后端 联通 + JSON 解析 OK**。

如果你们希望我把“SharedPreferences 保存 user_id + 拉取草稿/作品列表”也写成可直接粘贴的代码，告诉我你们当前用的是 Activity 直写、还是 MVVM + ViewModel。
