package main

import (
	"log"
	"os"
	"path/filepath"
	"photo_backend/dao"
	"photo_backend/router"
	"photo_backend/service"
	"runtime"
	"strings"

	ort "github.com/yalue/onnxruntime_go"
)

func resolveModelPath(p string) string {
	if p == "" {
		return p
	}
	// 绝对路径直接用
	if filepath.IsAbs(p) {
		return p
	}
	// 1) 优先按当前工作目录解析
	if _, err := os.Stat(p); err == nil {
		if abs, err := filepath.Abs(p); err == nil {
			return abs
		}
		return p
	}
	// 2) 再按可执行文件所在目录解析（systemd/nohup 常见 cwd 不一致）
	if exe, err := os.Executable(); err == nil {
		exeDir := filepath.Dir(exe)
		candidate := filepath.Join(exeDir, p)
		if _, err := os.Stat(candidate); err == nil {
			return candidate
		}
	}
	return p
}

func main() {
	// 1. 初始化数据库 (调用 dao 包)
	dao.InitDB()

	// 2. 配置 ONNX Runtime shared library 路径（Linux 上通常需要显式指定）
	ortSharedLib := strings.TrimSpace(os.Getenv("ONNXRUNTIME_SHARED_LIBRARY_PATH"))
	autoDetected := false
	if ortSharedLib == "" && runtime.GOOS == "linux" {
		// 兜底：尝试探测常见安装位置/当前目录，避免因为忘记 export 环境变量导致启动失败
		candidates := []string{
			"./onnxruntime.so",
			"./libonnxruntime.so",
			"/usr/local/lib/onnxruntime.so",
			"/usr/local/lib/libonnxruntime.so",
			"/usr/lib/libonnxruntime.so",
			"/usr/lib64/libonnxruntime.so",
		}
		for _, c := range candidates {
			if _, err := os.Stat(c); err == nil {
				ortSharedLib = c
				autoDetected = true
				break
			}
		}
		if ortSharedLib == "" {
			log.Printf("⚠️ 未设置 ONNXRUNTIME_SHARED_LIBRARY_PATH，且未在常见路径找到 onnxruntime 动态库；如需构图模型，请 export ONNXRUNTIME_SHARED_LIBRARY_PATH=/path/to/libonnxruntime.so")
		}
	}
	if ortSharedLib != "" {
		ort.SetSharedLibraryPath(ortSharedLib)
		if autoDetected {
			log.Printf("🧩 ONNX Runtime 动态库（自动探测，env 未设置）：%s", ortSharedLib)
		} else {
			log.Printf("🧩 ONNX Runtime 动态库（来自 env ONNXRUNTIME_SHARED_LIBRARY_PATH）：%s", ortSharedLib)
		}
	}

	// 2. 配置 ONNX Runtime shared library 路径
	// - linux+cgo 构建：会真正调用 onnxruntime_go 设置动态库路径
	// - 其他平台/禁用 cgo：该函数为 no-op（Windows 本地不需要 ONNX）
	setupOnnxRuntimeSharedLibrary()

	// 3. 初始化构图推荐模型
	modelPath := strings.TrimSpace(os.Getenv("COMPOSITION_MODEL_PATH"))
	if modelPath == "" {
		modelPath = "models/comp_model.onnx"
	}
	modelPath = resolveModelPath(modelPath)
	log.Printf("🧠 构图模型路径：%s", modelPath)
	err := service.InitCompositionService(modelPath)
	if err != nil {
		log.Printf("⚠️ 构图模型初始化失败：%v，构图分析功能将不可用", err)
	} else {
		log.Println("✅ 构图模型加载成功")
	}

	// 4. 装载路由
	r := router.SetupRouter()

	// 5. 启动服务
	port := strings.TrimSpace(os.Getenv("PORT"))
	if port == "" {
		port = "8080"
	}
	log.Printf("🚀 服务启动于 http://0.0.0.0:%s", port)
	r.Run(":" + port)
}
