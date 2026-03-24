package controller

import (
	"net/http"
	"strconv"
	"strings"

	"github.com/gin-gonic/gin"
	"photo_backend/service"
)

func buildBaseURL(c *gin.Context) string {
	scheme := "http"
	if c.Request.TLS != nil {
		scheme = "https"
	}
	return scheme + "://" + c.Request.Host
}

func withPublicURL(base string, templates []service.TemplateItem) []service.TemplateItem {
	data := make([]service.TemplateItem, 0, len(templates))
	for _, t := range templates {
		// 兼容：如果字段已经是绝对 URL 则不再拼接
		if t.URL != "" && !(strings.HasPrefix(t.URL, "http://") || strings.HasPrefix(t.URL, "https://")) {
			t.URL = base + t.URL
		}
		if t.CoverURL != "" && !(strings.HasPrefix(t.CoverURL, "http://") || strings.HasPrefix(t.CoverURL, "https://")) {
			t.CoverURL = base + t.CoverURL
		}
		if t.ExampleURL != "" && !(strings.HasPrefix(t.ExampleURL, "http://") || strings.HasPrefix(t.ExampleURL, "https://")) {
			t.ExampleURL = base + t.ExampleURL
		}
		if t.OverlayURL != "" && !(strings.HasPrefix(t.OverlayURL, "http://") || strings.HasPrefix(t.OverlayURL, "https://")) {
			t.OverlayURL = base + t.OverlayURL
		}
		data = append(data, t)
	}
	return data
}

func parseOptionalUserID(c *gin.Context) (uint, bool) {
	userIDStr := strings.TrimSpace(c.Query("user_id"))
	if userIDStr == "" {
		return 0, false
	}
	userID64, err := strconv.ParseUint(userIDStr, 10, 32)
	if err != nil {
		return 0, false
	}
	return uint(userID64), true
}

// GetHotTemplates 热门模板列表
//
// GET /api/templates/hot?limit=20
// 返回模板图片的可访问 URL 列表（从 static/templates 目录扫描得到）
func GetHotTemplates(c *gin.Context) {
	limit := 20
	limitStr := strings.TrimSpace(c.Query("limit"))
	if limitStr != "" {
		if v, err := strconv.Atoi(limitStr); err == nil && v > 0 {
			limit = v
		}
	}

	userID, hasUser := parseOptionalUserID(c)

	templates, err := service.ListHotTemplates("static/templates", limit, service.UserContext{UserID: userID, HasUser: hasUser})
	if err != nil {
		c.JSON(http.StatusOK, gin.H{"code": 500, "msg": "读取模板失败", "error": err.Error()})
		return
	}

	base := buildBaseURL(c)
	data := withPublicURL(base, templates)

	if len(data) == 0 {
		c.JSON(http.StatusOK, gin.H{"code": 200, "msg": "暂无热门模板", "data": []interface{}{}})
		return
	}

	c.JSON(http.StatusOK, gin.H{"code": 200, "msg": "获取成功", "data": data})
}

// GetTemplateList 模板列表（支持按 tag 筛选）
//
// GET /api/templates/list?limit=50&tags=秋日氛围感,人像&match=any|all
func GetTemplateList(c *gin.Context) {
	limit := 50
	if v, err := strconv.Atoi(strings.TrimSpace(c.Query("limit"))); err == nil && v > 0 {
		limit = v
	}

	tags := service.SplitTagsParam(c.Query("tags"))
	matchAll := strings.EqualFold(strings.TrimSpace(c.Query("match")), "all")

	userID, hasUser := parseOptionalUserID(c)

	all, err := service.ListTemplates("static/templates", 0)
	if err != nil {
		c.JSON(http.StatusOK, gin.H{"code": 500, "msg": "读取模板失败", "error": err.Error()})
		return
	}

	filtered := service.FilterTemplates(all, tags, matchAll)
	if limit > 0 && len(filtered) > limit {
		filtered = filtered[:limit]
	}

	filtered, err = service.DecorateTemplates(filtered, service.UserContext{UserID: userID, HasUser: hasUser})
	if err != nil {
		c.JSON(http.StatusOK, gin.H{"code": 500, "msg": "读取模板失败", "error": err.Error()})
		return
	}

	base := buildBaseURL(c)
	data := withPublicURL(base, filtered)

	c.JSON(http.StatusOK, gin.H{"code": 200, "msg": "获取成功", "data": data})
}

// GetRecommendTemplates 推荐模板（偏好 tags + 收藏信号）
//
// GET /api/templates/recommend?user_id=1&limit=20&include_favored=0
func GetRecommendTemplates(c *gin.Context) {
	userIDStr := strings.TrimSpace(c.Query("user_id"))
	userID64, err := strconv.ParseUint(userIDStr, 10, 32)
	if err != nil {
		c.JSON(http.StatusOK, gin.H{"code": 400, "msg": "user_id 格式错误"})
		return
	}

	limit := 20
	if v, err := strconv.Atoi(strings.TrimSpace(c.Query("limit"))); err == nil && v > 0 {
		limit = v
	}

	includeFavored := false
	incStr := strings.TrimSpace(c.Query("include_favored"))
	if incStr != "" {
		includeFavored = incStr == "1" || strings.EqualFold(incStr, "true")
	}

	templates, err := service.RecommendTemplates(uint(userID64), "static/templates", limit, includeFavored)
	if err != nil {
		c.JSON(http.StatusOK, gin.H{"code": 500, "msg": "推荐失败", "error": err.Error()})
		return
	}

	base := buildBaseURL(c)
	data := withPublicURL(base, templates)
	c.JSON(http.StatusOK, gin.H{"code": 200, "msg": "获取成功", "data": data})
}

// GetTemplateDetail 模板详情（返回封面/示例/overlay 及结构化引导文案坐标）
//
// GET /api/templates/detail?template_id=xxx&user_id=1(optional)
func GetTemplateDetail(c *gin.Context) {
	templateID := strings.TrimSpace(c.Query("template_id"))
	if templateID == "" {
		c.JSON(http.StatusOK, gin.H{"code": 400, "msg": "template_id 不能为空"})
		return
	}

	userID, hasUser := parseOptionalUserID(c)
	item, err := service.GetTemplateDetail("static/templates", templateID, service.UserContext{UserID: userID, HasUser: hasUser})
	if err != nil {
		if err == service.ErrTemplateNotFound {
			c.JSON(http.StatusOK, gin.H{"code": 404, "msg": "模板不存在"})
			return
		}
		c.JSON(http.StatusOK, gin.H{"code": 500, "msg": "获取失败", "error": err.Error()})
		return
	}

	base := buildBaseURL(c)
	data := withPublicURL(base, []service.TemplateItem{item})
	c.JSON(http.StatusOK, gin.H{"code": 200, "msg": "获取成功", "data": data[0]})
}

// SearchTemplates 关键词搜索 + 推荐模板
//
// GET /api/templates/search?user_id=1&q=ins&limit=50&recommend_limit=10
// - matches: 与关键词相关的模板（按推荐得分排序）
// - recommended: 推荐算法得到的模板
func SearchTemplates(c *gin.Context) {
	q := strings.TrimSpace(c.Query("q"))
	limit := 50
	if v, err := strconv.Atoi(strings.TrimSpace(c.Query("limit"))); err == nil && v > 0 {
		limit = v
	}
	recLimit := 10
	if v, err := strconv.Atoi(strings.TrimSpace(c.Query("recommend_limit"))); err == nil && v > 0 {
		recLimit = v
	}

	userID, hasUser := parseOptionalUserID(c)

	res, err := service.SearchAndRecommendTemplates(service.SearchRecommendParams{
		TemplatesDir:    "static/templates",
		Query:           q,
		Limit:           limit,
		RecommendLimit:  recLimit,
		IncludeFavored:  false,
		User:            service.UserContext{UserID: userID, HasUser: hasUser},
	})
	if err != nil {
		c.JSON(http.StatusOK, gin.H{"code": 500, "msg": "搜索失败", "error": err.Error()})
		return
	}

	base := buildBaseURL(c)
	res.Matches = withPublicURL(base, res.Matches)
	res.Recommended = withPublicURL(base, res.Recommended)

	c.JSON(http.StatusOK, gin.H{
		"code": 200,
		"msg":  "获取成功",
		"data": gin.H{"matches": res.Matches, "recommended": res.Recommended},
	})
}
