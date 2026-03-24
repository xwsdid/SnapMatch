package service

import (
	"crypto/rand"
	"encoding/hex"
	"errors"
	"io"
	"mime/multipart"
	"os"
	"path/filepath"
	"photo_backend/composition"
	"strings"
	"time"
)

var compositionModel *composition.CompositionModel

var ErrCompositionModelNotReady = errors.New("COMPOSITION_MODEL_NOT_READY")

// InitCompositionService 初始化构图推荐服务
func InitCompositionService(modelPath string) error {
	var err error
	compositionModel, err = composition.InitCompositionModel(modelPath)
	if err != nil {
		return err
	}
	return nil
}

// GetCompositionModel 获取构图模型实例
func GetCompositionModel() *composition.CompositionModel {
	return compositionModel
}

// CompositionService 构图推荐服务
type CompositionService struct{}

// AnalyzeComposition 分析图片构图
func AnalyzeComposition(file *multipart.FileHeader) ([]composition.CompositionResult, error) {
	// 1. 保存上传的文件到临时目录
	tempDir := filepath.Join(os.TempDir(), "photo_upload")
	err := os.MkdirAll(tempDir, os.ModePerm)
	if err != nil {
		return nil, err
	}

	// 生成安全的临时文件名（避免 filename 里包含路径、重复覆盖等问题）
	ext := strings.ToLower(filepath.Ext(file.Filename))
	if ext == "" {
		ext = ".jpg"
	}
	rnd := make([]byte, 12)
	if _, err := rand.Read(rnd); err != nil {
		return nil, err
	}
	tempFile := filepath.Join(tempDir, "comp_"+time.Now().Format("20060102_150405.000")+"_"+hex.EncodeToString(rnd)+ext)
	
	// 打开上传的文件
	src, err := file.Open()
	if err != nil {
		return nil, err
	}
	defer src.Close()

	// 保存到临时文件
	dst, err := os.Create(tempFile)
	if err != nil {
		return nil, err
	}
	defer dst.Close()
	defer func() { _ = os.Remove(tempFile) }()

	_, err = io.Copy(dst, src)
	if err != nil {
		return nil, err
	}

	// 2. 使用模型进行推理
	if compositionModel == nil {
		return nil, ErrCompositionModelNotReady
	}

	results, err := compositionModel.Predict(tempFile)
	if err != nil {
		return nil, err
	}

	return results, nil
}
