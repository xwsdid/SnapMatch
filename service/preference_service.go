package service

import (
	"errors"
	"photo_backend/dao"
	"photo_backend/model"
	"strings"

	"gorm.io/gorm"
)

func parseTagsCSV(s string) []string {
	parts := strings.FieldsFunc(s, func(r rune) bool {
		return r == ',' || r == '，' || r == ';' || r == '；' || r == '|' || r == '\n' || r == '\t'
	})
	seen := map[string]struct{}{}
	out := make([]string, 0, len(parts))
	for _, p := range parts {
		v := strings.TrimSpace(p)
		if v == "" {
			continue
		}
		if _, ok := seen[v]; ok {
			continue
		}
		seen[v] = struct{}{}
		out = append(out, v)
	}
	return out
}

func tagsToCSV(tags []string) string {
	clean := make([]string, 0, len(tags))
	seen := map[string]struct{}{}
	for _, t := range tags {
		v := strings.TrimSpace(t)
		if v == "" {
			continue
		}
		if _, ok := seen[v]; ok {
			continue
		}
		seen[v] = struct{}{}
		clean = append(clean, v)
	}
	return strings.Join(clean, ",")
}

// GetPreferenceTags 获取用户偏好 tags（逗号分隔存储）
func GetPreferenceTags(userID uint) ([]string, error) {
	var pref model.Preference
	err := dao.DB.Where("user_id = ?", userID).First(&pref).Error
	if err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return []string{}, nil
		}
		return nil, err
	}
	return parseTagsCSV(pref.Tags), nil
}

// UpsertPreferenceTags 写入用户偏好 tags（不存在则创建）
func UpsertPreferenceTags(userID uint, tags []string) error {
	csv := tagsToCSV(tags)
	var pref model.Preference
	err := dao.DB.Where("user_id = ?", userID).First(&pref).Error
	if err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			pref = model.Preference{UserID: userID, Tags: csv}
			return dao.DB.Create(&pref).Error
		}
		return err
	}
	pref.Tags = csv
	return dao.DB.Save(&pref).Error
}
