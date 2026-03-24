package controller

import (
	"net/http"
	"strconv"
	"strings"

	"github.com/gin-gonic/gin"
	"photo_backend/service"
)

type preferenceTagsReq struct {
	UserID uint     `json:"user_id" binding:"required"`
	Tags   []string `json:"tags"`
	// 兼容：也支持传一个逗号分隔字符串
	TagsText string `json:"tags_text"`
}

// GetPreferenceTags GET /api/preferences/tags?user_id=1
func GetPreferenceTags(c *gin.Context) {
	userIDStr := strings.TrimSpace(c.Query("user_id"))
	userID64, err := strconv.ParseUint(userIDStr, 10, 32)
	if err != nil {
		c.JSON(http.StatusOK, gin.H{"code": 400, "msg": "user_id 格式错误"})
		return
	}

	tags, err := service.GetPreferenceTags(uint(userID64))
	if err != nil {
		c.JSON(http.StatusOK, gin.H{"code": 500, "msg": "查询失败", "error": err.Error()})
		return
	}

	c.JSON(http.StatusOK, gin.H{"code": 200, "msg": "获取成功", "data": gin.H{"tags": tags}})
}

// UpsertPreferenceTags POST /api/preferences/tags
// JSON: {"user_id":1, "tags":["秋日氛围感","人像"]}
// 或: {"user_id":1, "tags_text":"秋日氛围感,人像"}
func UpsertPreferenceTags(c *gin.Context) {
	var req preferenceTagsReq
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusOK, gin.H{"code": 400, "msg": "参数错误"})
		return
	}

	tags := req.Tags
	if len(tags) == 0 && strings.TrimSpace(req.TagsText) != "" {
		tags = service.SplitTagsParam(req.TagsText)
	}

	if err := service.UpsertPreferenceTags(req.UserID, tags); err != nil {
		c.JSON(http.StatusOK, gin.H{"code": 500, "msg": "保存失败", "error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"code": 200, "msg": "保存成功"})
}
