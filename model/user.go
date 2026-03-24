package model

import (
	"gorm.io/gorm"
	"time"
)

// User 对应数据库中的 users 表
type User struct {
	ID        uint           `gorm:"primaryKey;autoIncrement" json:"id"`                    // 唯一 ID 作为主键
	Username  string         `gorm:"type:varchar(50);uniqueIndex;not null" json:"username"` // 用户名（登录账号），设置唯一索引
	AvatarURL string         `gorm:"type:varchar(255);default:''" json:"avatar_url"`        // 头像 URL
	Password  string         `gorm:"type:varchar(255);not null" json:"-"`                   // 密码（加密存储，json返回时忽略）
	CreatedAt time.Time      `json:"created_at"`
	UpdatedAt time.Time      `json:"updated_at"`
	DeletedAt gorm.DeletedAt `gorm:"index" json:"-"` // GORM 软删除
}
