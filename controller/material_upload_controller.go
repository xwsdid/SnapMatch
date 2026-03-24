package controller

import (
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"photo_backend/service"
)

type UploadMaterialResponse struct {
	MaterialID uint   `json:"material_id"`
	URL        string `json:"url"`
}

// UploadMaterial 上传图片到服务器并写入 materials 表
//
// POST /api/materials/upload
// Content-Type: multipart/form-data
// - image: 图片文件（jpg/jpeg/png）
// - user_id: 用户ID（必填）
// - status: 0=草稿(默认), 1=作品（可选）
func UploadMaterial(c *gin.Context) {
	userIDStr := strings.TrimSpace(c.PostForm("user_id"))
	if userIDStr == "" {
		c.JSON(http.StatusOK, gin.H{"code": 400, "msg": "缺少 user_id"})
		return
	}
	userID64, err := strconv.ParseUint(userIDStr, 10, 32)
	if err != nil {
		c.JSON(http.StatusOK, gin.H{"code": 400, "msg": "user_id 格式错误"})
		return
	}
	userID := uint(userID64)

	status := 0
	statusStr := strings.TrimSpace(c.PostForm("status"))
	if statusStr != "" {
		statusParsed, err := strconv.Atoi(statusStr)
		if err != nil || (statusParsed != 0 && statusParsed != 1) {
			c.JSON(http.StatusOK, gin.H{"code": 400, "msg": "status 只能是 0 或 1"})
			return
		}
		status = statusParsed
	}

	templateID := strings.TrimSpace(c.PostForm("template_id"))

	file, err := c.FormFile("image")
	if err != nil {
		// 兼容一些前端字段名叫 file
		file, err = c.FormFile("file")
		if err != nil {
			c.JSON(http.StatusOK, gin.H{"code": 400, "msg": "请上传图片文件（字段名 image 或 file）"})
			return
		}
	}

	if !isValidImageType(file.Filename) {
		c.JSON(http.StatusOK, gin.H{"code": 400, "msg": "仅支持 JPG、JPEG、PNG 格式的图片"})
		return
	}

	ext := strings.ToLower(filepath.Ext(file.Filename))
	if ext == "" {
		ext = ".jpg"
	}

	// 保存目录：static/uploads/u{user_id}/YYYYMMDD/
	dateDir := time.Now().Format("20060102")
	relDir := filepath.Join("uploads", fmt.Sprintf("u%d", userID), dateDir)
	absDir := filepath.Join("static", relDir)
	if err := os.MkdirAll(absDir, 0o755); err != nil {
		c.JSON(http.StatusOK, gin.H{"code": 500, "msg": "创建上传目录失败", "error": err.Error()})
		return
	}

	// 生成文件名：时间戳 + 随机串
	rnd := make([]byte, 12)
	if _, err := rand.Read(rnd); err != nil {
		c.JSON(http.StatusOK, gin.H{"code": 500, "msg": "生成文件名失败", "error": err.Error()})
		return
	}
	filename := fmt.Sprintf("%d_%s%s", time.Now().UnixMilli(), hex.EncodeToString(rnd), ext)
	absPath := filepath.Join(absDir, filename)

	if err := c.SaveUploadedFile(file, absPath); err != nil {
		c.JSON(http.StatusOK, gin.H{"code": 500, "msg": "保存图片失败", "error": err.Error()})
		return
	}

	// 对外 URL：/static/{relDir}/{filename}
	urlPath := "/static/" + filepath.ToSlash(filepath.Join(relDir, filename))
	scheme := "http"
	if c.Request.TLS != nil {
		scheme = "https"
	}
	publicURL := fmt.Sprintf("%s://%s%s", scheme, c.Request.Host, urlPath)

	material, err := service.CreateMaterial(userID, publicURL, status, templateID)
	if err != nil {
		c.JSON(http.StatusOK, gin.H{"code": 500, "msg": "数据库写入失败", "error": err.Error()})
		return
	}

	// 统计：如果本次拍摄使用了模板，则累计使用量（用于热门/推荐排序与 UI 展示）
	if templateID != "" {
		_ = service.IncrementTemplateUsage(templateID, 1)
	}

	c.JSON(http.StatusOK, gin.H{
		"code": 200,
		"msg":  "上传成功",
		"data": UploadMaterialResponse{MaterialID: material.ID, URL: material.URL},
	})
}
