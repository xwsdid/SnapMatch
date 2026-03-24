package controller

import (
	"net/http"

	"github.com/gin-gonic/gin"
	"photo_backend/service"
)

// SyncDraftRequest 定义前端传来的 JSON 结构
type SyncDraftRequest struct {
	UserID uint   `json:"user_id" binding:"required"`
	URL    string `json:"url" binding:"required"`
}

// UploadDraft 处理草稿上传请求
func UploadDraft(c *gin.Context) {
	var req SyncDraftRequest

	// 1. 解析参数
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"code": 400,
			"msg":  "参数不完整或格式错误",
		})
		return
	}

	// 2. 调用 Service 层落库
	err := service.CreateDraft(req.UserID, req.URL)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{
			"code": 500,
			"msg":  "数据库写入失败",
			"error": err.Error(),
		})
		return
	}

	// 3. 返回成功响应
	c.JSON(http.StatusOK, gin.H{
		"code": 200,
		"msg":  "✅ 草稿同步成功",
	})
}