package router

import (
	"github.com/gin-contrib/cors"
	"github.com/gin-gonic/gin"
	"photo_backend/controller"
)

func SetupRouter() *gin.Engine {
	r := gin.Default()

	// 静态资源访问：用于返回/访问上传图片、模板等
	// 访问示例：GET /static/uploads/xxx.jpg
	r.Static("/static", "./static")

	// 配置 CORS
	r.Use(cors.New(cors.Config{
		AllowOrigins:     []string{"*"},
		AllowMethods:     []string{"GET", "POST", "PUT", "DELETE", "OPTIONS"},
		AllowHeaders:     []string{"Origin", "Content-Type", "Authorization"},
		ExposeHeaders:    []string{"Content-Length"},
		AllowCredentials: true,
		MaxAge:           12 * 3600,
	}))

	// 设置最大上传大小为 10MB
	r.MaxMultipartMemory = 10 << 20

	api := r.Group("/api")
	{
		// 用户模块
		api.POST("/register", controller.Register)
		api.POST("/login", controller.Login)
		api.GET("/user/me", controller.GetMe)
		api.PUT("/user/username", controller.UpdateUsername)
		api.PUT("/user/password", controller.UpdatePassword)
		api.POST("/user/avatar", controller.UploadUserAvatar)

		// 素材模块
		api.POST("/drafts/upload", controller.UploadDraft)
		api.POST("/materials/upload", controller.UploadMaterial)

		//草稿转作品接口。使用 POST 请求，路径带上素材 ID
		api.POST("/materials/work/:id", controller.ConvertToWork)

		// 删除素材（草稿/作品）
		api.DELETE("/materials/:id", controller.DeleteMaterial)

		// 使用 GET 请求拉取列表
		api.GET("/materials/list", controller.GetMaterials)

		// 构图分析模块
		api.POST("/composition/analyze", controller.AnalyzeComposition)

		// VLM 拍摄建议/人像姿势引导
		api.POST("/vlm/infer", controller.VLMInfer)

		// 模板推荐模块（热门模板）
		api.GET("/templates/hot", controller.GetHotTemplates)
		api.GET("/templates/list", controller.GetTemplateList)
		api.GET("/templates/recommend", controller.GetRecommendTemplates)
		api.GET("/templates/detail", controller.GetTemplateDetail)
		api.GET("/templates/search", controller.SearchTemplates)

		// 模板收藏
		api.POST("/templates/favorites", controller.AddTemplateFavorite)
		api.DELETE("/templates/favorites", controller.RemoveTemplateFavorite)
		api.GET("/templates/favorites", controller.ListTemplateFavorites)

		// 偏好 tags
		api.GET("/preferences/tags", controller.GetPreferenceTags)
		api.POST("/preferences/tags", controller.UpsertPreferenceTags)
	}

	return r
}
