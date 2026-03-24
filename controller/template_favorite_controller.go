package controller

import (
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"photo_backend/service"
)

type templateFavoriteReq struct {
	// 注意：为了兼容不同前端传参方式（JSON number / JSON string / form / query），这里用 any 手动解析
	UserID     any    `json:"user_id" form:"user_id"`
	TemplateID string `json:"template_id" form:"template_id"`
}

func parseUserIDAny(v any) (uint, bool) {
	switch t := v.(type) {
	case nil:
		return 0, false
	case float64:
		if t <= 0 {
			return 0, false
		}
		return uint(t), true
	case int:
		if t <= 0 {
			return 0, false
		}
		return uint(t), true
	case int64:
		if t <= 0 {
			return 0, false
		}
		return uint(t), true
	case uint:
		if t == 0 {
			return 0, false
		}
		return t, true
	case uint64:
		if t == 0 {
			return 0, false
		}
		return uint(t), true
	case string:
		s := strings.TrimSpace(t)
		if s == "" {
			return 0, false
		}
		u64, err := strconv.ParseUint(s, 10, 32)
		if err != nil || u64 == 0 {
			return 0, false
		}
		return uint(u64), true
	default:
		// 兜底：把任意类型转成字符串再 parse
		s := strings.TrimSpace(fmt.Sprint(t))
		if s == "" {
			return 0, false
		}
		u64, err := strconv.ParseUint(s, 10, 32)
		if err != nil || u64 == 0 {
			return 0, false
		}
		return uint(u64), true
	}
}

func parseUserIDFromString(s string) (uint, bool) {
	s = strings.TrimSpace(s)
	if s == "" {
		return 0, false
	}
	u64, err := strconv.ParseUint(s, 10, 32)
	if err != nil || u64 == 0 {
		return 0, false
	}
	return uint(u64), true
}

// AddTemplateFavorite POST /api/templates/favorites
func AddTemplateFavorite(c *gin.Context) {
	// 1) 先尝试 query/form（很多前端会这样传）
	userIDStr := strings.TrimSpace(c.Query("user_id"))
	templateID := strings.TrimSpace(c.Query("template_id"))
	if userIDStr == "" {
		userIDStr = strings.TrimSpace(c.PostForm("user_id"))
	}
	if templateID == "" {
		templateID = strings.TrimSpace(c.PostForm("template_id"))
	}

	var userID uint
	var ok bool
	if userIDStr != "" {
		userID, ok = parseUserIDFromString(userIDStr)
	}

	// 2) 再尝试 JSON body（标准方式）
	if !ok || templateID == "" {
		var req templateFavoriteReq
		if err := c.ShouldBindJSON(&req); err == nil {
			if !ok {
				if uid, ok2 := parseUserIDAny(req.UserID); ok2 {
					userID = uid
					ok = true
				}
			}
			if templateID == "" {
				templateID = strings.TrimSpace(req.TemplateID)
			}
		}
	}

	if !ok {
		c.JSON(http.StatusOK, gin.H{"code": 400, "msg": "缺少或非法 user_id"})
		return
	}
	if strings.TrimSpace(templateID) == "" {
		c.JSON(http.StatusOK, gin.H{"code": 400, "msg": "template_id 不能为空"})
		return
	}

	err := service.AddTemplateFavorite(userID, templateID)
	if err != nil {
		if err == service.ErrTemplateAlreadyFavored {
			// 幂等：重复收藏视为成功，避免前端把 409 当“网络错误”
			c.JSON(http.StatusOK, gin.H{"code": 200, "msg": "已收藏", "data": gin.H{"favored": true}})
			return
		}
		c.JSON(http.StatusOK, gin.H{"code": 500, "msg": "收藏失败", "error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"code": 200, "msg": "收藏成功", "data": gin.H{"favored": true}})
}

// RemoveTemplateFavorite DELETE /api/templates/favorites
// 支持 JSON body 或 query：?user_id=1&template_id=xxx
func RemoveTemplateFavorite(c *gin.Context) {
	userIDStr := strings.TrimSpace(c.Query("user_id"))
	templateID := strings.TrimSpace(c.Query("template_id"))
	if userIDStr == "" {
		userIDStr = strings.TrimSpace(c.PostForm("user_id"))
	}
	if templateID == "" {
		templateID = strings.TrimSpace(c.PostForm("template_id"))
	}

	var userID uint
	ok := false
	if userIDStr != "" {
		if uid, ok2 := parseUserIDFromString(userIDStr); ok2 {
			userID = uid
			ok = true
		}
	}

	var req templateFavoriteReq
	if (!ok || templateID == "") && c.ShouldBindJSON(&req) == nil {
		if !ok {
			if uid, ok2 := parseUserIDAny(req.UserID); ok2 {
				userID = uid
				ok = true
			}
		}
		if templateID == "" {
			templateID = strings.TrimSpace(req.TemplateID)
		}
	}

	if !ok {
		c.JSON(http.StatusOK, gin.H{"code": 400, "msg": "user_id 格式错误"})
		return
	}
	if templateID == "" {
		c.JSON(http.StatusOK, gin.H{"code": 400, "msg": "template_id 不能为空"})
		return
	}

	err := service.RemoveTemplateFavorite(userID, templateID)
	if err != nil {
		if err == service.ErrTemplateNotFavored {
			// 幂等：取消一个未收藏的模板视为成功
			c.JSON(http.StatusOK, gin.H{"code": 200, "msg": "未收藏", "data": gin.H{"favored": false}})
			return
		}
		c.JSON(http.StatusOK, gin.H{"code": 500, "msg": "取消收藏失败", "error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"code": 200, "msg": "已取消收藏", "data": gin.H{"favored": false}})
}

// ListTemplateFavorites GET /api/templates/favorites?user_id=1&limit=100
func ListTemplateFavorites(c *gin.Context) {
	userIDStr := strings.TrimSpace(c.Query("user_id"))
	userID64, err := strconv.ParseUint(userIDStr, 10, 32)
	if err != nil {
		c.JSON(http.StatusOK, gin.H{"code": 400, "msg": "user_id 格式错误"})
		return
	}

	limit := 100
	limitStr := strings.TrimSpace(c.Query("limit"))
	if limitStr != "" {
		if v, err := strconv.Atoi(limitStr); err == nil && v > 0 {
			limit = v
		}
	}

	favs, err := service.ListTemplateFavorites(uint(userID64), limit)
	if err != nil {
		c.JSON(http.StatusOK, gin.H{"code": 500, "msg": "查询失败", "error": err.Error()})
		return
	}

	// 方案A：返回收藏记录 + template_info（模板完整信息，便于“喜欢”页直接渲染卡片）
	// 说明：
	// - favs 里只有 template_id，模板详情来自静态目录 + templates.json + 使用量统计表
	// - 若模板被删除/不存在，也返回一个兜底 template_info（避免前端严格解析时报错）
	type favoriteWithInfo struct {
		ID           uint               `json:"id"`
		UserID       uint               `json:"user_id"`
		TemplateID   string             `json:"template_id"`
		TemplateInfo service.TemplateItem `json:"template_info"`
		CreatedAt    time.Time          `json:"created_at"`
	}

	if len(favs) == 0 {
		c.JSON(http.StatusOK, gin.H{"code": 200, "msg": "获取成功", "data": []interface{}{}})
		return
	}

	// 1) 拉取所有模板并按 template_id 建索引
	all, err := service.ListTemplates("static/templates", 0)
	if err != nil {
		c.JSON(http.StatusOK, gin.H{"code": 500, "msg": "读取模板失败", "error": err.Error()})
		return
	}
	byID := map[string]service.TemplateItem{}
	for _, t := range all {
		byID[t.ID] = t
	}

	// 2) 取出收藏到的模板列表（用于批量补 used_count/favored/绝对URL）
	need := make([]service.TemplateItem, 0, len(favs))
	seen := map[string]struct{}{}
	for _, f := range favs {
		id := strings.TrimSpace(f.TemplateID)
		if id == "" {
			continue
		}
		if _, ok := seen[id]; ok {
			continue
		}
		seen[id] = struct{}{}
		if t, ok := byID[id]; ok {
			need = append(need, t)
		} else {
			// 模板不存在也保留一个最小信息，便于前端做兜底展示
			need = append(need, service.TemplateItem{ID: id, Name: id, Title: id, Tags: []string{}})
		}
	}

	// 3) 补齐 used_count/favored 等（favored 对于收藏列表而言应为 true）
	need, err = service.DecorateTemplates(need, service.UserContext{UserID: uint(userID64), HasUser: true})
	if err != nil {
		c.JSON(http.StatusOK, gin.H{"code": 500, "msg": "读取模板失败", "error": err.Error()})
		return
	}
	base := buildBaseURL(c)
	need = withPublicURL(base, need)
	infoByID := map[string]service.TemplateItem{}
	for _, t := range need {
		t.Favored = true
		infoByID[t.ID] = t
	}

	data := make([]favoriteWithInfo, 0, len(favs))
	for _, f := range favs {
		info, ok := infoByID[f.TemplateID]
		if !ok {
			// 兜底：至少把 template_id 透出，前端能展示占位卡片
			info = service.TemplateItem{
				ID:    f.TemplateID,
				Name:  f.TemplateID,
				Title: f.TemplateID,
				Tags:  []string{},
				Hot:   0,
				// URL/CoverURL/ExampleURL/OverlayURL 留空
				UsedCount: 0,
				Favored:   true,
			}
		}
		data = append(data, favoriteWithInfo{
			ID:           f.ID,
			UserID:       f.UserID,
			TemplateID:   f.TemplateID,
			TemplateInfo: info,
			CreatedAt:    f.CreatedAt,
		})
	}

	c.JSON(http.StatusOK, gin.H{"code": 200, "msg": "获取成功", "data": data})
}
