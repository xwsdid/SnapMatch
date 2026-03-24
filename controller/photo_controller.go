package controller

import (
	"net/http"
	"strconv"
	"strings"

	"github.com/gin-gonic/gin"
	"photo_backend/service"
)

// ConvertToWork 处理“保存到相册”的请求
func ConvertToWork(c *gin.Context) {
	// 从 URL 参数或 JSON 中获取素材 ID
	// 假设我们通过路径参数获取，例如 /api/materials/work/12
	idStr := c.Param("id")
	materialID, err := strconv.ParseUint(idStr, 10, 32)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"code": 400, "msg": "无效的素材ID"})
		return
	}

	// 调用 Service 层更新状态
	if err := service.SaveToWork(uint(materialID)); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"code": 500, "msg": "更新失败", "error": err.Error()})
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"code": 200,
		"msg":  "✅ 已成功保存至作品集",
	})
}

// GetMaterials 处理获取素材列表的请求 (GET /api/materials/list?user_id=1&status=1) 
func GetMaterials(c *gin.Context) {
	// 1. 从 Query String 中获取参数
	userIDStr := c.Query("user_id")
	statusStr := c.Query("status")
	
	// 2. 转换数据类型
	userID, _ := strconv.ParseUint(userIDStr, 10, 32)
	status, _ := strconv.Atoi(statusStr)

	// 3. 调用 Service 层查询数据 [cite: 39, 42]
	materials, err := service.GetUserMaterials(uint(userID), status)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{
			"code": 500,
			"msg":  "查询失败",
		})
		return
	}

	// 4. 返回统一格式的 JSON 
	c.JSON(http.StatusOK, gin.H{
		"code": 200,
		"data": materials,
	})
}

// DeleteMaterial 删除素材（草稿/作品）
//
// DELETE /api/materials/:id?user_id=1
//
// 说明：materials 表包含 DeletedAt，GORM Delete 会执行软删除。
func DeleteMaterial(c *gin.Context) {
	// 1) material_id from path
	idStr := strings.TrimSpace(c.Param("id"))
	if idStr == "" {
		c.JSON(http.StatusOK, gin.H{"code": 400, "msg": "缺少素材ID"})
		return
	}
	materialID64, err := strconv.ParseUint(idStr, 10, 32)
	if err != nil {
		c.JSON(http.StatusOK, gin.H{"code": 400, "msg": "无效的素材ID"})
		return
	}
	materialID := uint(materialID64)

	// 2) user_id from query (project currently has no auth)
	userIDStr := strings.TrimSpace(c.Query("user_id"))
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

	// 3) delete (soft delete)
	deleted, err := service.DeleteMaterialByUser(userID, materialID)
	if err != nil {
		c.JSON(http.StatusOK, gin.H{"code": 500, "msg": "删除失败", "error": err.Error()})
		return
	}
	if !deleted {
		c.JSON(http.StatusOK, gin.H{"code": 404, "msg": "素材不存在或无权限"})
		return
	}

	c.JSON(http.StatusOK, gin.H{"code": 200, "msg": "删除成功"})
}