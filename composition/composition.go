package composition

import (
	"fmt"
	"image"
	"image/color"
	"image/draw"
	_ "image/jpeg"
	_ "image/png"
	"math"
	"os"
	"strings"

	ort "github.com/yalue/onnxruntime_go"
)

// CompositionResult 构图推荐结果
type CompositionResult struct {
	Name       string  `json:"name"`       // 构图名称
	Confidence float64 `json:"confidence"` // 置信度 (0-100)
}

// CompositionModel 构图推荐模型
type CompositionModel struct {
	session      *ort.AdvancedSession
	inputTensor  *ort.Tensor[float32]
	outputTensor *ort.Tensor[float32]
}

// 构图类别名称
var classNames = []string{
	"三分法构图",
	"垂直线构图",
	"水平线构图",
	"对角线构图",
	"曲线构图",
	"三角形构图",
	"中心构图",
	"对称构图",
	"框架/图案构图",
}

// InitCompositionModel 初始化构图模型
func InitCompositionModel(modelPath string) (*CompositionModel, error) {
	// 初始化环境
	err := ort.InitializeEnvironment()
	if err != nil {
		errMsg := err.Error()
		// 典型：二进制在编译时禁用了 onnxruntime_go（常见原因：CGO_ENABLED=0、缺少 cgo 工具链/编译器，导致走了 stub 实现）
		if strings.Contains(errMsg, "ONNXRUNTIME_DISABLED") {
			return nil, fmt.Errorf("环境初始化失败：ONNXRUNTIME_DISABLED（ONNX Runtime 在编译时被禁用，构图分析不可用）。请在服务器上用 CGO 启用方式重新编译（例如安装 gcc 后用 CGO_ENABLED=1 go build），并确保运行时的 ONNXRUNTIME_SHARED_LIBRARY_PATH 指向可加载的 libonnxruntime.so")
		}
		// 常见：onnxruntime_go 绑定版本与服务器上的 libonnxruntime.so 版本不匹配，会导致 ORT API version/base 设置失败
		if strings.Contains(errMsg, "Error setting ORT API") || strings.Contains(errMsg, "requested API version") {
			return nil, fmt.Errorf("环境初始化失败（可能是 ONNX Runtime 动态库版本与 onnxruntime_go 不匹配）：%v；请升级服务器上的 libonnxruntime.so，或将 github.com/yalue/onnxruntime_go 降级到匹配的版本，并确保 ONNXRUNTIME_SHARED_LIBRARY_PATH 指向正确的 libonnxruntime.so", err)
		}
		return nil, fmt.Errorf("环境初始化失败：%v", err)
	}

	// 创建输入张量占位符 (Shape: 1x3x224x224)
	inputShape := ort.NewShape(1, 3, 224, 224)
	inputData := make([]float32, 1*3*224*224)
	inputTensor, err := ort.NewTensor(inputShape, inputData)
	if err != nil {
		return nil, fmt.Errorf("创建输入 Tensor 失败：%v", err)
	}

	// 创建输出张量占位符 (Shape: 1x9)
	outputShape := ort.NewShape(1, 9)
	outputTensor, err := ort.NewEmptyTensor[float32](outputShape)
	if err != nil {
		inputTensor.Destroy()
		return nil, fmt.Errorf("创建输出 Tensor 失败：%v", err)
	}

	// 创建推理会话，传入输入输出张量
	session, err := ort.NewAdvancedSession(
		modelPath,
		[]string{"input"},
		[]string{"output"},
		[]ort.Value{inputTensor},
		[]ort.Value{outputTensor},
		nil,
	)
	if err != nil {
		inputTensor.Destroy()
		outputTensor.Destroy()
		return nil, fmt.Errorf("创建会话失败：%v", err)
	}

	return &CompositionModel{
		session:      session,
		inputTensor:  inputTensor,
		outputTensor: outputTensor,
	}, nil
}

// Destroy 销毁模型会话
func (m *CompositionModel) Destroy() {
	if m.session != nil {
		m.session.Destroy()
	}
	if m.inputTensor != nil {
		m.inputTensor.Destroy()
	}
	if m.outputTensor != nil {
		m.outputTensor.Destroy()
	}
	ort.DestroyEnvironment()
}

// Predict 执行推理，返回构图推荐结果
func (m *CompositionModel) Predict(imagePath string) ([]CompositionResult, error) {
	// 1. 加载并预处理图片，更新输入张量数据
	inputData, err := preprocessImage(imagePath)
	if err != nil {
		return nil, fmt.Errorf("图片预处理失败：%v", err)
	}

	// 更新输入张量的数据（直接复制到 GetData() 返回的 slice 中）
	tensorData := m.inputTensor.GetData()
	copy(tensorData, inputData)

	// 2. 执行推理
	err = m.session.Run()
	if err != nil {
		return nil, fmt.Errorf("推理执行失败：%v", err)
	}

	// 3. 获取输出结果并应用 Sigmoid
	outputData := m.outputTensor.GetData()
	results := make([]CompositionResult, 0)
	threshold := 0.35

	for i, val := range outputData {
		// 应用 Sigmoid 函数将 Logits 转为概率
		prob := 1.0 / (1.0 + math.Exp(float64(-val)))

		if prob >= threshold {
			results = append(results, CompositionResult{
				Name:       classNames[i],
				Confidence: prob * 100,
			})
		}
	}

	// 如果没有超过阈值的结果，返回置信度最高的
	if len(results) == 0 && len(outputData) > 0 {
		maxIdx := 0
		maxProb := 0.0
		for i, val := range outputData {
			prob := 1.0 / (1.0 + math.Exp(float64(-val)))
			if prob > maxProb {
				maxProb = prob
				maxIdx = i
			}
		}
		results = append(results, CompositionResult{
			Name:       classNames[maxIdx],
			Confidence: maxProb * 100,
		})
	}

	return results, nil
}

// preprocessImage 加载并预处理图片
// 将图片调整为 224x224，转换为 RGB，归一化
func preprocessImage(imagePath string) ([]float32, error) {
	// 打开图片文件
	file, err := os.Open(imagePath)
	if err != nil {
		return nil, err
	}
	defer file.Close()

	// 解码图片
	img, _, err := image.Decode(file)
	if err != nil {
		return nil, err
	}

	// 调整图片大小为 224x224（保持纵横比，边缘补黑）
	resized := letterbox(img, 224, 224)

	// 转换为 RGB 并归一化
	// 输出格式：[Batch, Channels, Height, Width] = [1, 3, 224, 224]
	inputData := make([]float32, 3*224*224)

	// 训练侧使用的 ImageNet 归一化参数：
	// Normalize(mean=[0.485,0.456,0.406], std=[0.229,0.224,0.225])
	mean := [3]float32{0.485, 0.456, 0.406}
	std := [3]float32{0.229, 0.224, 0.225}

	// 分别处理 R、G、B 通道
	for y := 0; y < 224; y++ {
		for x := 0; x < 224; x++ {
			r, g, b, _ := resized.At(x, y).RGBA()

			// RGBA() 返回的是 0-65535 的值，需要转换到 0-1
			r8 := float32(r>>8) / 255.0
			g8 := float32(g>>8) / 255.0
			b8 := float32(b>>8) / 255.0

			// 按训练时的 Normalize 做标准化
			r8 = (r8 - mean[0]) / std[0]
			g8 = (g8 - mean[1]) / std[1]
			b8 = (b8 - mean[2]) / std[2]

			// 按通道顺序存储：R 通道、G 通道、B 通道
			idx := y*224 + x
			inputData[idx] = r8           // R 通道
			inputData[224*224+idx] = g8   // G 通道
			inputData[2*224*224+idx] = b8 // B 通道
		}
	}

	return inputData, nil
}

// letterbox 等比例缩放并补黑边到固定尺寸，避免拉伸破坏构图比例
func letterbox(img image.Image, width, height int) image.Image {
	bounds := img.Bounds()
	srcW := bounds.Dx()
	srcH := bounds.Dy()
	if srcW <= 0 || srcH <= 0 {
		return resizeImage(img, width, height)
	}

	scale := math.Min(float64(width)/float64(srcW), float64(height)/float64(srcH))
	newW := int(math.Round(float64(srcW) * scale))
	newH := int(math.Round(float64(srcH) * scale))
	if newW < 1 {
		newW = 1
	}
	if newH < 1 {
		newH = 1
	}

	resized := resizeImage(img, newW, newH)
	out := image.NewRGBA(image.Rect(0, 0, width, height))

	// 填充黑色背景
	draw.Draw(out, out.Bounds(), &image.Uniform{C: color.RGBA{R: 0, G: 0, B: 0, A: 255}}, image.Point{}, draw.Src)

	// 居中贴图
	offX := (width - newW) / 2
	offY := (height - newH) / 2
	dstRect := image.Rect(offX, offY, offX+newW, offY+newH)
	draw.Draw(out, dstRect, resized, image.Point{}, draw.Over)

	return out
}

// resizeImage 调整图片大小（双线性插值）
func resizeImage(img image.Image, width, height int) image.Image {
	resized := image.NewRGBA(image.Rect(0, 0, width, height))
	bounds := img.Bounds()

	for y := 0; y < height; y++ {
		for x := 0; x < width; x++ {
			// 计算原图坐标
			srcX := float64(x) * float64(bounds.Dx()) / float64(width)
			srcY := float64(y) * float64(bounds.Dy()) / float64(height)

			// 双线性插值
			clr := bilinearInterpolate(img, srcX, srcY)
			resized.Set(x, y, clr)
		}
	}

	return resized
}

// bilinearInterpolate 双线性插值
func bilinearInterpolate(img image.Image, x, y float64) color.Color {
	x0 := int(math.Floor(x))
	y0 := int(math.Floor(y))
	x1 := x0 + 1
	y1 := y0 + 1

	bounds := img.Bounds()

	// 边界检查
	if x1 >= bounds.Dx() {
		x1 = bounds.Dx() - 1
	}
	if y1 >= bounds.Dy() {
		y1 = bounds.Dy() - 1
	}
	if x0 < 0 {
		x0 = 0
	}
	if y0 < 0 {
		y0 = 0
	}

	// 获取四个点的颜色
	c00 := img.At(x0, y0)
	c01 := img.At(x0, y1)
	c10 := img.At(x1, y0)
	c11 := img.At(x1, y1)

	// 计算插值权重
	wx1 := x - float64(x0)
	wx0 := 1.0 - wx1
	wy1 := y - float64(y0)
	wy0 := 1.0 - wy1

	// 分别对 R、G、B 通道进行插值
	r00, g00, b00, _ := c00.RGBA()
	r01, g01, b01, _ := c01.RGBA()
	r10, g10, b10, _ := c10.RGBA()
	r11, g11, b11, _ := c11.RGBA()

	// 插值
	r := uint16(float64(r00)*wx0*wy0 + float64(r10)*wx1*wy0 + float64(r01)*wx0*wy1 + float64(r11)*wx1*wy1)
	g := uint16(float64(g00)*wx0*wy0 + float64(g10)*wx1*wy0 + float64(g01)*wx0*wy1 + float64(g11)*wx1*wy1)
	b := uint16(float64(b00)*wx0*wy0 + float64(b10)*wx1*wy0 + float64(b01)*wx0*wy1 + float64(b11)*wx1*wy1)

	return color.RGBA{
		R: uint8(r >> 8),
		G: uint8(g >> 8),
		B: uint8(b >> 8),
		A: 255,
	}
}
