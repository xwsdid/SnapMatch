package service

import (
	"errors"
	"golang.org/x/crypto/bcrypt" // 需要执行 go get golang.org/x/crypto/bcrypt
	"photo_backend/dao"
	"photo_backend/model"
	"strings"

	mysqlDriver "github.com/go-sql-driver/mysql"
	"gorm.io/gorm"
)

var (
	ErrUsernameExists   = errors.New("USERNAME_EXISTS")
	ErrUserNotFound     = errors.New("USER_NOT_FOUND")
	ErrWrongPassword    = errors.New("WRONG_PASSWORD")
	ErrWrongOldPassword = errors.New("WRONG_OLD_PASSWORD")
	ErrInvalidUsername  = errors.New("INVALID_USERNAME")
	ErrInvalidPassword  = errors.New("INVALID_PASSWORD")
)

func isDuplicateKeyError(err error) bool {
	if err == nil {
		return false
	}
	// MySQL duplicate entry error code: 1062
	var myErr *mysqlDriver.MySQLError
	if errors.As(err, &myErr) {
		return myErr.Number == 1062
	}

	// Fallback: some wrapped errors may only expose message text
	msg := err.Error()
	return strings.Contains(msg, "Duplicate entry") || strings.Contains(msg, "1062")
}

// Register 用户注册
func Register(username, password string) error {
	// 1. 检查用户名是否已存在
	var existingUser model.User
	err := dao.DB.Where("username = ?", username).First(&existingUser).Error
	if err == nil {
		return ErrUsernameExists
	}
	if !errors.Is(err, gorm.ErrRecordNotFound) {
		// 其他数据库错误（连接失败等）
		return err
	}

	// 2. 密码加密 (使用 bcrypt)
	hashedPassword, err := bcrypt.GenerateFromPassword([]byte(password), bcrypt.DefaultCost)
	if err != nil {
		return err
	}

	// 3. 存入数据库
	newUser := model.User{
		Username:  username,
		Password:  string(hashedPassword),
		AvatarURL: "",
	}
	err = dao.DB.Create(&newUser).Error
	if isDuplicateKeyError(err) {
		// 并发注册或未命中预检查时的唯一键冲突
		return ErrUsernameExists
	}
	return err
}

// Login 用户登录
func Login(username, password string) (*model.User, error) {
	var user model.User
	// 1. 根据用户名查找用户 [cite: 51]
	if err := dao.DB.Where("username = ?", username).First(&user).Error; err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return nil, ErrUserNotFound
		}
		return nil, err
	}

	// 2. 校验密码
	err := bcrypt.CompareHashAndPassword([]byte(user.Password), []byte(password))
	if err != nil {
		return nil, ErrWrongPassword
	}

	return &user, nil
}

// GetUserByID 根据 user_id 获取用户（用于“我”页展示/更新后返回）
func GetUserByID(userID uint) (*model.User, error) {
	var user model.User
	if err := dao.DB.First(&user, userID).Error; err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return nil, ErrUserNotFound
		}
		return nil, err
	}
	return &user, nil
}

// UpdateUsername 修改用户名（登录账号）：需要全局唯一
func UpdateUsername(userID uint, newUsername string) (*model.User, error) {
	newUsername = strings.TrimSpace(newUsername)
	if newUsername == "" {
		return nil, ErrInvalidUsername
	}
	if len([]rune(newUsername)) > 50 {
		return nil, ErrInvalidUsername
	}
	if strings.ContainsAny(newUsername, " \t\r\n") {
		return nil, ErrInvalidUsername
	}

	// 1) 检查是否被其他用户占用
	var existingUser model.User
	err := dao.DB.Where("username = ? AND id <> ?", newUsername, userID).First(&existingUser).Error
	if err == nil {
		return nil, ErrUsernameExists
	}
	if !errors.Is(err, gorm.ErrRecordNotFound) {
		return nil, err
	}

	// 2) 更新（并发下仍可能触发唯一键冲突）
	res := dao.DB.Model(&model.User{}).
		Where("id = ?", userID).
		Update("username", newUsername)
	if res.Error != nil {
		if isDuplicateKeyError(res.Error) {
			return nil, ErrUsernameExists
		}
		return nil, res.Error
	}
	if res.RowsAffected == 0 {
		// MySQL 在“新值与旧值相同”时可能返回 0 行受影响；这里按幂等成功处理。
		return GetUserByID(userID)
	}

	return GetUserByID(userID)
}

// UpdatePassword 修改登录密码：需要校验旧密码
func UpdatePassword(userID uint, oldPassword, newPassword string) error {
	oldPassword = strings.TrimSpace(oldPassword)
	newPassword = strings.TrimSpace(newPassword)
	if newPassword == "" || len(newPassword) < 6 {
		return ErrInvalidPassword
	}
	if len(newPassword) > 72 {
		// bcrypt 输入上限约 72 bytes（超长可能导致误判相同）
		return ErrInvalidPassword
	}

	user, err := GetUserByID(userID)
	if err != nil {
		return err
	}

	if err := bcrypt.CompareHashAndPassword([]byte(user.Password), []byte(oldPassword)); err != nil {
		return ErrWrongOldPassword
	}

	hashedPassword, err := bcrypt.GenerateFromPassword([]byte(newPassword), bcrypt.DefaultCost)
	if err != nil {
		return err
	}

	return dao.DB.Model(&model.User{}).Where("id = ?", userID).Update("password", string(hashedPassword)).Error
}

// UpdateAvatarURL 更新用户头像 URL
func UpdateAvatarURL(userID uint, avatarURL string) (*model.User, error) {
	avatarURL = strings.TrimSpace(avatarURL)
	user, err := GetUserByID(userID)
	if err != nil {
		return nil, err
	}
	user.AvatarURL = avatarURL
	if err := dao.DB.Save(user).Error; err != nil {
		return nil, err
	}
	return user, nil
}
