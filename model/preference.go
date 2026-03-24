package model

import (
	"time"
)

// Preference 对应数据库中的 preferences 表
type Preference struct {
	ID         uint      `gorm:"primaryKey;autoIncrement" json:"id"`  //主键，偏好ID
	UserID     uint      `gorm:"uniqueIndex;not null" json:"user_id"` // 用户外键 ID，通常一个用户对应一条偏好汇总记录 [cite: 47]
	BitmapData []byte    `gorm:"type:blob" json:"-"`                  // 位图数据（Bitmap）存储 [cite: 47]
	Tags       string    `gorm:"type:varchar(255)" json:"tags"`       // 偏好标签（如"海边,人像"），辅助传入 LoRA 接口
	CreatedAt  time.Time `json:"created_at"`
	UpdatedAt  time.Time `json:"updated_at"`

	// 定义外键关联
	User       User      `gorm:"foreignKey:UserID" json:"-"`
}