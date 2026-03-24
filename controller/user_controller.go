package controller

import (
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"github.com/gin-gonic/gin"
	"net/url"
	"net/http"
	"os"
	"path/filepath"
	"photo_backend/service"
	"strconv"
	"strings"
	"time"
)

func avatarURLToLocalPath(avatarURL string) (string, bool) {
	avatarURL = strings.TrimSpace(avatarURL)
	if avatarURL == "" {
		return "", false
	}

	pathPart := avatarURL
	if u, err := url.Parse(avatarURL); err == nil && u != nil && u.Path != "" {
		pathPart = u.Path
	}

	pathPart = strings.TrimSpace(pathPart)
	if pathPart == "" {
		return "", false
	}

	if strings.HasPrefix(pathPart, "/static/") {
		pathPart = strings.TrimPrefix(pathPart, "/")
	}

	cleaned := filepath.Clean(pathPart)
	cleanedSlash := filepath.ToSlash(cleaned)
	if !strings.HasPrefix(cleanedSlash, "static/avatars/") {
		return "", false
	}

	return cleaned, true
}

type UserRequest struct {
	Username string `json:"username" binding:"required"`
	Password string `json:"password" binding:"required"`
}

type UserUsernameChangeRequest struct {
	UserID    uint   `json:"user_id" binding:"required"`
	Username  string `json:"username" binding:"required"`
}

type UserPasswordChangeRequest struct {
	UserID      uint   `json:"user_id" binding:"required"`
	OldPassword string `json:"old_password" binding:"required"`
	NewPassword string `json:"new_password" binding:"required"`
}

// Register 注册接口
func Register(c *gin.Context) {
	var req UserRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		// 业务侧更容易统一处理：用 HTTP 200 + code
		c.JSON(http.StatusOK, gin.H{"code": 400, "msg": "参数错误"})
		return
	}

	if err := service.Register(req.Username, req.Password); err != nil {
		if errors.Is(err, service.ErrUsernameExists) {
			c.JSON(http.StatusOK, gin.H{"code": 409, "msg": "该用户名已存在，换一个试试吧~"})
			return
		}
		c.JSON(http.StatusOK, gin.H{"code": 500, "msg": "注册失败", "error": err.Error()})
		return
	}

	c.JSON(http.StatusOK, gin.H{"code": 200, "msg": "注册成功"})
}

// Login 登录接口
func Login(c *gin.Context) {
	var req UserRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusOK, gin.H{"code": 400, "msg": "参数错误"})
		return
	}

	user, err := service.Login(req.Username, req.Password)
	if err != nil {
		if errors.Is(err, service.ErrUserNotFound) {
			c.JSON(http.StatusOK, gin.H{"code": 401, "msg": "用户不存在"})
			return
		}
		if errors.Is(err, service.ErrWrongPassword) {
			c.JSON(http.StatusOK, gin.H{"code": 401, "msg": "密码错误"})
			return
		}
		c.JSON(http.StatusOK, gin.H{"code": 500, "msg": "登录失败", "error": err.Error()})
		return
	}

	// 登录成功，返回用户信息及 ID [cite: 39]
	c.JSON(http.StatusOK, gin.H{
		"code": 200,
		"msg":  "登录成功",
		"data": gin.H{
			"user_id":    user.ID,
			"username":   user.Username,
			"avatar_url": user.AvatarURL,
		},
	})
}

// GetMe 获取用户信息（“我”页展示）
// GET /api/user/me?user_id=1
func GetMe(c *gin.Context) {
	userIDStr := strings.TrimSpace(c.Query("user_id"))
	userID64, err := strconv.ParseUint(userIDStr, 10, 32)
	if err != nil {
		c.JSON(http.StatusOK, gin.H{"code": 400, "msg": "user_id 格式错误"})
		return
	}

	user, err := service.GetUserByID(uint(userID64))
	if err != nil {
		if errors.Is(err, service.ErrUserNotFound) {
			c.JSON(http.StatusOK, gin.H{"code": 404, "msg": "用户不存在"})
			return
		}
		c.JSON(http.StatusOK, gin.H{"code": 500, "msg": "查询失败", "error": err.Error()})
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"code": 200,
		"msg":  "获取成功",
		"data": gin.H{
			"user_id":    user.ID,
			"username":   user.Username,
			"avatar_url": user.AvatarURL,
		},
	})
}

// UpdateUsername 修改用户名（登录账号，唯一）
// PUT /api/user/username  JSON: {"user_id":1,"username":"new"}
func UpdateUsername(c *gin.Context) {
	var req UserUsernameChangeRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusOK, gin.H{"code": 400, "msg": "参数错误"})
		return
	}

	newUsername := strings.TrimSpace(req.Username)

	user, err := service.UpdateUsername(req.UserID, newUsername)
	if err != nil {
		if errors.Is(err, service.ErrUserNotFound) {
			c.JSON(http.StatusOK, gin.H{"code": 404, "msg": "用户不存在"})
			return
		}
		if errors.Is(err, service.ErrUsernameExists) {
			c.JSON(http.StatusOK, gin.H{"code": 409, "msg": "该用户名已存在，换一个试试吧~"})
			return
		}
		if errors.Is(err, service.ErrInvalidUsername) {
			c.JSON(http.StatusOK, gin.H{"code": 400, "msg": "用户名不合法"})
			return
		}
		c.JSON(http.StatusOK, gin.H{"code": 500, "msg": "修改失败", "error": err.Error()})
		return
	}

	c.JSON(http.StatusOK, gin.H{"code": 200, "msg": "修改成功", "data": gin.H{"username": user.Username}})
}

// UpdatePassword 修改用户登录密码
// PUT /api/user/password JSON: {"user_id":1,"old_password":"123","new_password":"abc123"}
func UpdatePassword(c *gin.Context) {
	var req UserPasswordChangeRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusOK, gin.H{"code": 400, "msg": "参数错误"})
		return
	}

	err := service.UpdatePassword(req.UserID, req.OldPassword, req.NewPassword)
	if err != nil {
		if errors.Is(err, service.ErrUserNotFound) {
			c.JSON(http.StatusOK, gin.H{"code": 404, "msg": "用户不存在"})
			return
		}
		if errors.Is(err, service.ErrWrongOldPassword) {
			c.JSON(http.StatusOK, gin.H{"code": 401, "msg": "旧密码错误"})
			return
		}
		if errors.Is(err, service.ErrInvalidPassword) {
			c.JSON(http.StatusOK, gin.H{"code": 400, "msg": "新密码不合法（至少 6 位）"})
			return
		}
		c.JSON(http.StatusOK, gin.H{"code": 500, "msg": "修改失败", "error": err.Error()})
		return
	}

	c.JSON(http.StatusOK, gin.H{"code": 200, "msg": "修改成功"})
}

// UploadUserAvatar 上传并更新用户头像
// POST /api/user/avatar  multipart/form-data
// - user_id: 用户ID（必填）
// - avatar/image/file: 图片文件（jpg/jpeg/png）
func UploadUserAvatar(c *gin.Context) {
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

	// 先读取旧头像：用于更新成功后删除旧文件
	oldUser, err := service.GetUserByID(userID)
	if err != nil {
		if errors.Is(err, service.ErrUserNotFound) {
			c.JSON(http.StatusOK, gin.H{"code": 404, "msg": "用户不存在"})
			return
		}
		c.JSON(http.StatusOK, gin.H{"code": 500, "msg": "查询失败", "error": err.Error()})
		return
	}
	oldAvatarURL := strings.TrimSpace(oldUser.AvatarURL)

	file, err := c.FormFile("avatar")
	if err != nil {
		file, err = c.FormFile("image")
		if err != nil {
			file, err = c.FormFile("file")
			if err != nil {
				c.JSON(http.StatusOK, gin.H{"code": 400, "msg": "请上传头像文件（字段名 avatar 或 image 或 file）"})
				return
			}
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

	dateDir := time.Now().Format("20060102")
	relDir := filepath.Join("avatars", fmt.Sprintf("u%d", userID), dateDir)
	absDir := filepath.Join("static", relDir)
	if err := os.MkdirAll(absDir, 0o755); err != nil {
		c.JSON(http.StatusOK, gin.H{"code": 500, "msg": "创建上传目录失败", "error": err.Error()})
		return
	}

	rnd := make([]byte, 12)
	if _, err := rand.Read(rnd); err != nil {
		c.JSON(http.StatusOK, gin.H{"code": 500, "msg": "生成文件名失败", "error": err.Error()})
		return
	}
	filename := fmt.Sprintf("%d_%s%s", time.Now().UnixMilli(), hex.EncodeToString(rnd), ext)
	absPath := filepath.Join(absDir, filename)

	if err := c.SaveUploadedFile(file, absPath); err != nil {
		c.JSON(http.StatusOK, gin.H{"code": 500, "msg": "保存头像失败", "error": err.Error()})
		return
	}

	urlPath := "/static/" + filepath.ToSlash(filepath.Join(relDir, filename))
	scheme := "http"
	if c.Request.TLS != nil {
		scheme = "https"
	}
	publicURL := fmt.Sprintf("%s://%s%s", scheme, c.Request.Host, urlPath)

	user, err := service.UpdateAvatarURL(userID, publicURL)
	if err != nil {
		_ = os.Remove(absPath) // DB 更新失败：回滚删除新上传文件（best-effort）
		if errors.Is(err, service.ErrUserNotFound) {
			c.JSON(http.StatusOK, gin.H{"code": 404, "msg": "用户不存在"})
			return
		}
		c.JSON(http.StatusOK, gin.H{"code": 500, "msg": "更新失败", "error": err.Error()})
		return
	}

	// 更新成功：删除旧头像文件（只删除本项目生成的 static/avatars 下文件）
	if oldLocal, ok := avatarURLToLocalPath(oldAvatarURL); ok {
		newLocal := filepath.ToSlash(filepath.Clean(absPath))
		oldLocalSlash := filepath.ToSlash(filepath.Clean(oldLocal))
		if oldLocalSlash != "" && oldLocalSlash != newLocal {
			_ = os.Remove(oldLocal)
		}
	}

	c.JSON(http.StatusOK, gin.H{"code": 200, "msg": "上传成功", "data": gin.H{"avatar_url": user.AvatarURL}})
}
