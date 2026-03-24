package service

import (
	"errors"
	"photo_backend/dao"
	"photo_backend/model"
	"strings"

	mysqlDriver "github.com/go-sql-driver/mysql"
	"gorm.io/gorm"
)

var (
	ErrTemplateAlreadyFavored = errors.New("TEMPLATE_ALREADY_FAVORED")
	ErrTemplateNotFavored     = errors.New("TEMPLATE_NOT_FAVORED")
)

func isDuplicateKeyErrorTemplateFavorite(err error) bool {
	if err == nil {
		return false
	}
	var myErr *mysqlDriver.MySQLError
	if errors.As(err, &myErr) {
		return myErr.Number == 1062
	}
	msg := err.Error()
	return strings.Contains(msg, "Duplicate entry") || strings.Contains(msg, "1062")
}

func AddTemplateFavorite(userID uint, templateID string) error {
	fav := model.TemplateFavorite{UserID: userID, TemplateID: templateID}
	err := dao.DB.Create(&fav).Error
	if err != nil {
		// 唯一键冲突视为已收藏
		if isDuplicateKeyErrorTemplateFavorite(err) {
			return ErrTemplateAlreadyFavored
		}
		return err
	}
	return nil
}

func RemoveTemplateFavorite(userID uint, templateID string) error {
	res := dao.DB.Where("user_id = ? AND template_id = ?", userID, templateID).Delete(&model.TemplateFavorite{})
	if res.Error != nil {
		return res.Error
	}
	if res.RowsAffected == 0 {
		return ErrTemplateNotFavored
	}
	return nil
}

func ListTemplateFavorites(userID uint, limit int) ([]model.TemplateFavorite, error) {
	if limit <= 0 {
		limit = 100
	}
	var favs []model.TemplateFavorite
	err := dao.DB.Where("user_id = ?", userID).
		Order("created_at desc").
		Limit(limit).
		Find(&favs).Error
	if err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return []model.TemplateFavorite{}, nil
		}
		return nil, err
	}
	return favs, nil
}
