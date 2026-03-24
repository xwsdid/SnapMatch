package controller

import (
	"errors"
	"net/http"
	"photo_backend/service"
	"strings"

	"github.com/gin-gonic/gin"
)

// VLMInfer 接收图片并转发到 Python VLM 服务，返回强结构化 JSON。
// POST /api/vlm/infer
// multipart/form-data:
// - image 或 file: 图片文件
// - task: advice | pose
func VLMInfer(c *gin.Context) {
	task := strings.TrimSpace(c.PostForm("task"))
	if task == "" {
		c.JSON(http.StatusOK, gin.H{"code": 400, "msg": "缺少 task（advice 或 pose）"})
		return
	}

	file, err := c.FormFile("image")
	if err != nil {
		file, err = c.FormFile("file")
		if err != nil {
			c.JSON(http.StatusOK, gin.H{"code": 400, "msg": "请上传图片文件（字段名 image 或 file）", "error": err.Error()})
			return
		}
	}

	if !isValidImageType(file.Filename) {
		c.JSON(http.StatusOK, gin.H{"code": 400, "msg": "仅支持 JPG、JPEG、PNG 格式的图片"})
		return
	}

	data, err := service.InferVLM(file, task)
	if err != nil {
		if errors.Is(err, service.ErrVLMInvalidTask) {
			c.JSON(http.StatusOK, gin.H{"code": 400, "msg": "task 只能是 advice 或 pose"})
			return
		}
		c.JSON(http.StatusOK, gin.H{"code": 500, "msg": "VLM 推理失败", "error": err.Error()})
		return
	}

	c.JSON(http.StatusOK, gin.H{"code": 200, "msg": "ok", "data": data})
}
