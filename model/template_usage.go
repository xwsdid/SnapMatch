package model

import "time"

// TemplateUsage 模板使用量统计
//
// used_count: 全局累计使用量（用于列表展示/热门/推荐排序）
//
// 说明：模板本体是静态资源（static/templates），此表只记录统计数据。
// 对 template_id 做唯一约束，便于 upsert + 自增。
//
// 表名默认：template_usages
// 如需改表名可实现 TableName() 方法。
type TemplateUsage struct {
	ID        uint      `gorm:"primaryKey;autoIncrement" json:"id"`
	TemplateID string   `gorm:"type:varchar(128);not null;uniqueIndex" json:"template_id"`
	UsedCount int       `gorm:"not null;default:0" json:"used_count"`
	UpdatedAt time.Time `json:"updated_at"`
	CreatedAt time.Time `json:"created_at"`
}
