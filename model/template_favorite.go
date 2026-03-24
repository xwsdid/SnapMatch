package model

import "time"

// TemplateFavorite 用户收藏的模板（模板本体存放在 static/templates，元数据可由文件名/配置文件提供）
//
// 设计要点：
// - 模板 ID 为字符串（通常来自文件名去后缀）
// - 对 (user_id, template_id) 做唯一约束，避免重复收藏
// - 只记录收藏关系，不强依赖模板表
//
// 表名默认：template_favorites
// 如需改表名可实现 TableName() 方法
//
// 注意：目前项目无鉴权，客户端需要传 user_id。
//
// 业务约定：收藏用于推荐算法的偏好信号之一。
//
// CreatedAt 用于按最近收藏排序。
type TemplateFavorite struct {
	ID         uint      `gorm:"primaryKey;autoIncrement" json:"id"`
	UserID     uint      `gorm:"index;not null;uniqueIndex:uid_tid" json:"user_id"`
	TemplateID string    `gorm:"type:varchar(128);not null;uniqueIndex:uid_tid" json:"template_id"`
	CreatedAt  time.Time `json:"created_at"`
}
