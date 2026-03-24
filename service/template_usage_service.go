package service

import (
	"photo_backend/dao"
	"photo_backend/model"

	"gorm.io/gorm"
	"gorm.io/gorm/clause"
)

// IncrementTemplateUsage 累加模板使用量（template_id 维度，全局计数）
func IncrementTemplateUsage(templateID string, delta int) error {
	if templateID == "" || delta == 0 {
		return nil
	}
	// upsert: insert if not exists else used_count += delta
	usage := model.TemplateUsage{TemplateID: templateID, UsedCount: delta}
	return dao.DB.Clauses(clause.OnConflict{
		Columns:   []clause.Column{{Name: "template_id"}},
		DoUpdates: clause.Assignments(map[string]interface{}{"used_count": gorm.Expr("used_count + ?", delta)}),
	}).Create(&usage).Error
}

// GetTemplateUsageMap 批量查询模板使用量
func GetTemplateUsageMap(templateIDs []string) (map[string]int, error) {
	out := map[string]int{}
	if len(templateIDs) == 0 {
		return out, nil
	}

	var rows []model.TemplateUsage
	err := dao.DB.Where("template_id IN ?", templateIDs).Find(&rows).Error
	if err != nil {
		return nil, err
	}
	for _, r := range rows {
		out[r.TemplateID] = r.UsedCount
	}
	return out, nil
}
