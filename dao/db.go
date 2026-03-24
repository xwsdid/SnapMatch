package dao

import (
	"log"
	"os"
	"strings"

	"gorm.io/driver/mysql"
	"gorm.io/gorm"
	"photo_backend/model"
)

// 全局的数据库实例
var DB *gorm.DB

func InitDB() {
	dsn := strings.TrimSpace(os.Getenv("PHOTO_DB_DSN"))
	if dsn == "" {
		// 默认保持与当前项目一致（便于无配置快速启动）
		dsn = "root:123456@tcp(127.0.0.1:3306)/photography_db?charset=utf8mb4&parseTime=True&loc=Local"
	}
	var err error
	DB, err = gorm.Open(mysql.Open(dsn), &gorm.Config{})
	if err != nil {
		log.Fatalf("❌ 数据库连接失败: %v", err)
	}

	// 自动迁移表结构
	err = DB.AutoMigrate(&model.User{}, &model.Material{}, &model.Preference{}, &model.TemplateFavorite{}, &model.TemplateUsage{})
	if err != nil {
		log.Fatalf("❌ 自动迁移失败: %v", err)
	}
	log.Println("✅ 数据库连接与自动迁移成功！")
}