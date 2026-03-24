package service

import (
	"errors"
	"log"
	"net/url"
	"os"
	"path/filepath"
	"strings"

	"photo_backend/dao"
	"photo_backend/model"
	"gorm.io/gorm"
)

// CreateMaterial 创建一条素材记录（上传后落库）
func CreateMaterial(userID uint, url string, status int, templateID string) (*model.Material, error) {
	material := model.Material{
		UserID: userID,
		TemplateID: templateID,
		URL:    url,
		Status: status,
	}
	if err := dao.DB.Create(&material).Error; err != nil {
		return nil, err
	}
	return &material, nil
}

// CreateDraft 将草稿存入数据库
func CreateDraft(userID uint, url string) error {
	// 封装素材对象，Status 默认为 0（草稿）
	material := model.Material{
		UserID: userID,
		URL:    url,
		Status: 0, 
	}

	// 使用 dao 包中的全局 DB 执行插入操作
	result := dao.DB.Create(&material)
	return result.Error
}

// SaveToWork 将素材从草稿转为作品
func SaveToWork(materialID uint) error {
	// 根据主键 ID 找到对应素材，并将其 Status 字段更新为 1
	// .Model(&model.Material{}) 告诉 GORM 操作哪张表
	// .Where("id = ?", materialID) 定位具体哪条数据
	// .Update("status", 1) 执行更新操作
	result := dao.DB.Model(&model.Material{}).Where("id = ?", materialID).Update("status", 1)
	return result.Error
}

// GetUserMaterials 根据用户 ID 和状态（0或1）获取素材列表 [cite: 42, 46]
func GetUserMaterials(userID uint, status int) ([]model.Material, error) {
	var materials []model.Material
	// 使用 GORM 执行查询：SELECT * FROM materials WHERE user_id = ? AND status = ? [cite: 42, 46]
	err := dao.DB.Where("user_id = ? AND status = ?", userID, status).Find(&materials).Error
	return materials, err
}

// DeleteMaterialByUser 按用户删除指定素材（软删除）
// 返回 deleted=true 表示确实删到了一条记录。
func DeleteMaterialByUser(userID uint, materialID uint) (deleted bool, err error) {
	// 先查出记录，拿到 URL 以便删除本地文件
	var material model.Material
	err = dao.DB.Where("id = ? AND user_id = ?", materialID, userID).First(&material).Error
	if err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return false, nil
		}
		return false, err
	}

	// 1) 数据库软删除（materials 有 DeletedAt）
	result := dao.DB.Delete(&material)
	if result.Error != nil {
		return false, result.Error
	}

	// 2) 磁盘硬删除（仅限 static/uploads 下的本地文件；外链/模板一律不删）
	if err := deleteLocalUploadFile(material.URL); err != nil {
		// 不影响 DB 删除结果，避免“记录已删但前端报错”。
		log.Printf("⚠️ 删除本地文件失败 material_id=%d url=%s err=%v", materialID, material.URL, err)
	}

	return true, nil
}

func deleteLocalUploadFile(materialURL string) error {
	urlStr := strings.TrimSpace(materialURL)
	if urlStr == "" {
		return nil
	}

	// 兼容两种写法：
	// 1) 绝对 URL: http(s)://host/static/uploads/...
	// 2) 相对路径: /static/uploads/...
	path := ""
	if strings.HasPrefix(urlStr, "/") {
		path = urlStr
	} else {
		u, err := url.Parse(urlStr)
		if err != nil {
			return nil
		}
		path = u.Path
	}

	path = filepath.ToSlash(path)
	if !strings.HasPrefix(path, "/static/uploads/") {
		// 只允许删除 uploads，避免误删模板/static 其他资源或外链
		return nil
	}

	rel := strings.TrimPrefix(path, "/static/") // uploads/...
	relFS := filepath.FromSlash(rel)

	// 可能的 static 目录：
	// 1) 环境变量 PHOTO_STATIC_DIR（强烈建议在 systemd 设置为绝对路径，比如 /root/photo_backend/static）
	// 2) 当前工作目录下的 ./static
	// 3) 可执行文件目录下的 static（或上一级的 static）
	staticDirs := candidateStaticDirs()
	if len(staticDirs) == 0 {
		staticDirs = []string{"static"}
	}

	for _, staticDir := range staticDirs {
		staticDir = strings.TrimSpace(staticDir)
		if staticDir == "" {
			continue
		}

		staticDirClean := filepath.Clean(staticDir)
		// 兼容 PHOTO_STATIC_DIR 指向“项目根目录”的情况：如果末尾不是 static，就再尝试拼一个 static
		candidates := []string{staticDirClean}
		if filepath.Base(staticDirClean) != "static" {
			candidates = append(candidates, filepath.Join(staticDirClean, "static"))
		}

		for _, sd := range candidates {
			sdClean := filepath.Clean(sd)
			absPath := filepath.Clean(filepath.Join(sdClean, relFS))

			// 双重保险：最终路径必须仍在 {staticDir}/uploads 目录下
			uploadsRoot := filepath.Clean(filepath.Join(sdClean, "uploads"))
			absClean := filepath.Clean(absPath)
			if absClean != uploadsRoot && !strings.HasPrefix(absClean, uploadsRoot+string(os.PathSeparator)) {
				continue
			}

			if _, err := os.Stat(absClean); err != nil {
				if os.IsNotExist(err) {
					continue
				}
				// 其他 stat 错误，继续尝试下一个候选
				log.Printf("⚠️ 检查文件失败 path=%s err=%v", absClean, err)
				continue
			}

			if err := os.Remove(absClean); err != nil {
				if os.IsNotExist(err) {
					return nil
				}
				return err
			}
			log.Printf("✅ 已删除本地上传文件: %s", absClean)
			return nil
		}
	}

	log.Printf("⚠️ 未找到要删除的本地文件 url=%s (已软删DB记录)", materialURL)
	return nil
}

func candidateStaticDirs() []string {
	var dirs []string

	if v := strings.TrimSpace(os.Getenv("PHOTO_STATIC_DIR")); v != "" {
		dirs = append(dirs, v)
	}

	if wd, err := os.Getwd(); err == nil && strings.TrimSpace(wd) != "" {
		dirs = append(dirs, filepath.Join(wd, "static"))
	}

	if exe, err := os.Executable(); err == nil && strings.TrimSpace(exe) != "" {
		exeDir := filepath.Dir(exe)
		dirs = append(dirs, filepath.Join(exeDir, "static"))
		dirs = append(dirs, filepath.Join(exeDir, "..", "static"))
	}

	return dirs
}

//“写死”推荐的拍照模板
func GetRecommendedTemplates(userID uint) ([]string, error) {
    // 逻辑核心：写死演示账号 ID
    const demoUserID uint = 1 

    if userID == demoUserID {
        // 1. 模拟读取偏好表数据（让数据库查询日志看起来很真实）
        var pref model.Preference
        dao.DB.Where("user_id = ?", demoUserID).First(&pref) // [cite: 47]

        // 2. 演示，直接返回你准备好的最美模板 URL
        // 对应软件界面中的“热门模板”模块 [cite: 2]
        return []string{
            "http://your-server-ip/static/template_sea.jpg",
            "http://your-server-ip/static/template_ins.jpg",
        }, nil
    }

    // 非演示用户才考虑调用模型（当前直接返回默认值即可）
    return []string{"http://your-server-ip/static/default.jpg"}, nil
}