package controller

import (
	"errors"
	"log"
	"net/http"
	"photo_backend/service"
	"strings"
	"github.com/gin-gonic/gin"
)

// AnalyzeComposition 分析图片构图
func AnalyzeComposition(c *gin.Context) {
	// 1. 获取上传的文件
	file, err := c.FormFile("image")
	if err != nil {
		c.JSON(http.StatusOK, gin.H{
			"code": 400,
			"msg":  "请上传图片文件",
			"error": err.Error(),
		})
		return
	}

	log.Printf("[composition] recv image from %s name=%q size=%d", c.ClientIP(), file.Filename, file.Size)

	// 2. 验证文件类型
	if !isValidImageType(file.Filename) {
		c.JSON(http.StatusOK, gin.H{
			"code": 400,
			"msg":  "仅支持 JPG、JPEG、PNG 格式的图片",
		})
		return
	}

	// 3. 调用 Service 进行构图分析
	results, err := service.AnalyzeComposition(file)
	if err != nil {
		if errors.Is(err, service.ErrCompositionModelNotReady) {
			c.JSON(http.StatusOK, gin.H{"code": 503, "msg": "构图模型未加载完成，请稍后再试"})
			return
		}
		c.JSON(http.StatusOK, gin.H{"code": 500, "msg": "构图分析失败", "error": err.Error()})
		return
	}

	log.Printf("[composition] results=%d from %s", len(results), c.ClientIP())

	// 4. 返回结果
	if len(results) == 0 {
		c.JSON(http.StatusOK, gin.H{"code": 200, "msg": "未检测到明显的构图特征", "data": []interface{}{}})
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"code": 200,
		"msg":  "构图分析成功",
		"data": results,
	})
}

// isValidImageType 验证图片类型
func isValidImageType(filename string) bool {
	filename = strings.ToLower(filename)
	validTypes := []string{".jpg", ".jpeg", ".png"}
	for _, ext := range validTypes {
		if len(filename) >= len(ext) && filename[len(filename)-len(ext):] == ext {
			return true
		}
	}
	return false
}
