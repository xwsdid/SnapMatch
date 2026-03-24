package model

import (
	"time"
	"gorm.io/gorm"
)



// Material 对应数据库中的 materials 表
type Material struct {
	ID        uint           `gorm:"primaryKey;autoIncrement" json:"material_id"` // 素材 ID 
	UserID    uint           `gorm:"index;not null" json:"user_id"`               // 用户外键 ID，建立索引提高查询速度 
	TemplateID string        `gorm:"type:varchar(128);default:''" json:"template_id"` // 使用的模板ID（可选，用于推荐/统计）
	URL       string         `gorm:"type:varchar(255);not null" json:"url"`       // 素材存储路径/URL 
	Status    int            `gorm:"type:tinyint;default:0" json:"status"`        // 状态：0 代表草稿，1 代表作品
	ShotTime  time.Time      `gorm:"autoCreateTime" json:"shot_time"`             // 拍摄时间，自动记录创建时间 
	CreatedAt time.Time      `json:"created_at"`
	UpdatedAt time.Time      `json:"updated_at"`
	DeletedAt gorm.DeletedAt `gorm:"index" json:"-"`

	// 定义外键关联，方便 GORM 预加载(Preload)用户信息
	User      User           `gorm:"foreignKey:UserID" json:"-"` 
}