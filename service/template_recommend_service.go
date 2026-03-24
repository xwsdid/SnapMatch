package service

import (
	"errors"
	"math"
	"photo_backend/dao"
	"photo_backend/model"
	"sort"
	"strings"
)

// UserContext 可选的用户上下文：用于 favored/偏好/推荐等个性化字段。
type UserContext struct {
	UserID  uint
	HasUser bool
}

// SearchRecommendParams 搜索 + 推荐参数
type SearchRecommendParams struct {
	TemplatesDir    string
	Query           string
	Limit           int
	RecommendLimit  int
	IncludeFavored  bool
	User            UserContext
}

type SearchRecommendResult struct {
	Matches     []TemplateItem
	Recommended []TemplateItem
}

var ErrTemplateNotFound = errors.New("TEMPLATE_NOT_FOUND")

type scoredTemplate struct {
	Item  TemplateItem
	Score int
}

func splitTagsParam(s string) []string {
	if strings.TrimSpace(s) == "" {
		return []string{}
	}
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

func usageBoost(usedCount int) int {
	if usedCount <= 0 {
		return 0
	}
	// 对数缩放，避免 used_count 太大直接碾压其他信号
	return int(math.Log10(float64(usedCount)+1) * 50)
}

func normalizeQueryTokens(q string) []string {
	q = strings.TrimSpace(q)
	if q == "" {
		return []string{}
	}
	parts := strings.Fields(q)
	if len(parts) == 0 {
		return []string{q}
	}
	return parts
}

func templateMatchesTokens(t TemplateItem, tokens []string) bool {
	if len(tokens) == 0 {
		return true
	}
	field := strings.ToLower(t.ID + " " + t.Name + " " + t.Title)
	for _, tag := range t.Tags {
		field += " " + strings.ToLower(tag)
	}
	for _, tok := range tokens {
		if tok == "" {
			continue
		}
		if strings.Contains(field, strings.ToLower(tok)) {
			return true
		}
		// 中文/大小写不敏感时，上面已 cover；这里保留原样匹配
		if strings.Contains(t.ID+t.Name+t.Title, tok) {
			return true
		}
		for _, tag := range t.Tags {
			if strings.Contains(tag, tok) {
				return true
			}
		}
	}
	return false
}

// DecorateTemplates 为模板列表补充 used_count 与 favored（如有 user_id）。
func DecorateTemplates(items []TemplateItem, user UserContext) ([]TemplateItem, error) {
	ids := make([]string, 0, len(items))
	for _, t := range items {
		ids = append(ids, t.ID)
	}

	usageMap, err := GetTemplateUsageMap(ids)
	if err != nil {
		return nil, err
	}

	favoredSet := map[string]struct{}{}
	if user.HasUser {
		favs, err := ListTemplateFavorites(user.UserID, 2000)
		if err != nil {
			return nil, err
		}
		for _, f := range favs {
			favoredSet[f.TemplateID] = struct{}{}
		}
	}

	out := make([]TemplateItem, 0, len(items))
	for _, t := range items {
		t.UsedCount = usageMap[t.ID]
		if user.HasUser {
			_, t.Favored = favoredSet[t.ID]
		}
		out = append(out, t)
	}
	return out, nil
}

// ListHotTemplates 热门模板：综合 hot + used_count（对数缩放）排序。
func ListHotTemplates(templatesDir string, limit int, user UserContext) ([]TemplateItem, error) {
	items, err := ListTemplates(templatesDir, 0)
	if err != nil {
		return nil, err
	}
	items, err = DecorateTemplates(items, user)
	if err != nil {
		return nil, err
	}
	// 热门排序：hot + usageBoost
	sort.SliceStable(items, func(i, j int) bool {
		si := items[i].Hot + usageBoost(items[i].UsedCount)
		sj := items[j].Hot + usageBoost(items[j].UsedCount)
		if si != sj {
			return si > sj
		}
		return items[i].Name < items[j].Name
	})
	if limit > 0 && len(items) > limit {
		items = items[:limit]
	}
	return items, nil
}

// GetTemplateDetail 获取单个模板详情（含三图/结构化 guides/used_count/favored）。
func GetTemplateDetail(templatesDir string, templateID string, user UserContext) (TemplateItem, error) {
	items, err := ListTemplates(templatesDir, 0)
	if err != nil {
		return TemplateItem{}, err
	}
	var found *TemplateItem
	for i := range items {
		if items[i].ID == templateID {
			found = &items[i]
			break
		}
	}
	if found == nil {
		return TemplateItem{}, ErrTemplateNotFound
	}
	decorated, err := DecorateTemplates([]TemplateItem{*found}, user)
	if err != nil {
		return TemplateItem{}, err
	}
	return decorated[0], nil
}

// RecommendTemplates 推荐模板（标签+偏好）
//
// 数据来源：
// - 模板本体：static/templates 目录扫描 + templates.json 元数据（tags/hot）
// - 用户偏好：preferences.tags（逗号分隔）
// - 用户收藏：template_favorites 表
//
// 评分策略（可根据你们论文/需求再调）：
// - base：template.Hot
// - 如果模板 tag 命中用户偏好 tags：每个 tag +1
// - 如果模板 tag 命中“收藏模板”出现过的 tags：每个 tag +3
func RecommendTemplates(userID uint, templatesDir string, limit int, includeFavored bool) ([]TemplateItem, error) {
	if limit <= 0 {
		limit = 20
	}

	all, err := ListTemplates(templatesDir, 0)
	if err != nil {
		return nil, err
	}
	if len(all) == 0 {
		return []TemplateItem{}, nil
	}

	// used_count
	{
		ids := make([]string, 0, len(all))
		for _, t := range all {
			ids = append(ids, t.ID)
		}
		usageMap, err := GetTemplateUsageMap(ids)
		if err != nil {
			return nil, err
		}
		for i := range all {
			all[i].UsedCount = usageMap[all[i].ID]
		}
	}

	idToTemplate := make(map[string]TemplateItem, len(all))
	for _, t := range all {
		idToTemplate[t.ID] = t
	}

	favs, err := ListTemplateFavorites(userID, 1000)
	if err != nil {
		return nil, err
	}

	favoredSet := map[string]struct{}{}
	favTagWeight := map[string]int{}
	for _, f := range favs {
		favoredSet[f.TemplateID] = struct{}{}
		t, ok := idToTemplate[f.TemplateID]
		if !ok {
			continue
		}
		for _, tag := range t.Tags {
			favTagWeight[tag] += 3
		}
	}

	prefTags, err := GetPreferenceTags(userID)
	if err != nil {
		return nil, err
	}
	prefTagWeight := map[string]int{}
	for _, tag := range prefTags {
		prefTagWeight[tag] = 1
	}

	// 作品信号：用户作品使用过的模板（materials.status=1 且 template_id 非空）
	workTagWeight := map[string]int{}
	{
		type row struct{ TemplateID string }
		var rows []row
		_ = dao.DB.Model(&model.Material{}).
			Select("template_id").
			Where("user_id = ? AND status = 1 AND template_id <> ''", userID).
			Order("created_at desc").
			Limit(200).
			Find(&rows).Error
		for _, r := range rows {
			t, ok := idToTemplate[r.TemplateID]
			if !ok {
				continue
			}
			for _, tag := range t.Tags {
				workTagWeight[tag] += 2
			}
		}
	}

	scored := make([]scoredTemplate, 0, len(all))
	for _, t := range all {
		if !includeFavored {
			if _, ok := favoredSet[t.ID]; ok {
				continue
			}
		}
		score := t.Hot + usageBoost(t.UsedCount)
		for _, tag := range t.Tags {
			score += favTagWeight[tag]
			score += prefTagWeight[tag]
			score += workTagWeight[tag]
		}
		scored = append(scored, scoredTemplate{Item: t, Score: score})
	}

	sort.SliceStable(scored, func(i, j int) bool {
		if scored[i].Score != scored[j].Score {
			return scored[i].Score > scored[j].Score
		}
		if scored[i].Item.Hot != scored[j].Item.Hot {
			return scored[i].Item.Hot > scored[j].Item.Hot
		}
		return scored[i].Item.Name < scored[j].Item.Name
	})

	if len(scored) > limit {
		scored = scored[:limit]
	}

	out := make([]TemplateItem, 0, len(scored))
	for _, s := range scored {
		item := s.Item
		if _, ok := favoredSet[item.ID]; ok {
			item.Favored = true
		}
		out = append(out, item)
	}
	return out, nil
}

// FilterTemplates 按 tags 筛选模板。
// matchAll=true 表示必须包含所有 tags；false 表示包含任意一个 tag 即可。
func FilterTemplates(all []TemplateItem, tags []string, matchAll bool) []TemplateItem {
	if len(tags) == 0 {
		return all
	}

	tagSet := make(map[string]struct{}, len(tags))
	for _, t := range tags {
		v := strings.TrimSpace(t)
		if v == "" {
			continue
		}
		tagSet[v] = struct{}{}
	}
	if len(tagSet) == 0 {
		return all
	}

	out := make([]TemplateItem, 0, len(all))
	for _, item := range all {
		if len(item.Tags) == 0 {
			continue
		}
		itemTagSet := map[string]struct{}{}
		for _, t := range item.Tags {
			itemTagSet[t] = struct{}{}
		}

		if matchAll {
			ok := true
			for t := range tagSet {
				if _, exist := itemTagSet[t]; !exist {
					ok = false
					break
				}
			}
			if ok {
				out = append(out, item)
			}
		} else {
			for t := range tagSet {
				if _, exist := itemTagSet[t]; exist {
					out = append(out, item)
					break
				}
			}
		}
	}

	return out
}

// SplitTagsParam 供 controller 复用（query tags=...）
func SplitTagsParam(s string) []string { return splitTagsParam(s) }

// SearchAndRecommendTemplates 搜索 + 推荐（用于顶部搜索框页面）
func SearchAndRecommendTemplates(p SearchRecommendParams) (SearchRecommendResult, error) {
	if p.TemplatesDir == "" {
		p.TemplatesDir = "static/templates"
	}
	if p.Limit <= 0 {
		p.Limit = 50
	}
	if p.RecommendLimit <= 0 {
		p.RecommendLimit = 10
	}

	all, err := ListTemplates(p.TemplatesDir, 0)
	if err != nil {
		return SearchRecommendResult{}, err
	}
	if len(all) == 0 {
		return SearchRecommendResult{Matches: []TemplateItem{}, Recommended: []TemplateItem{}}, nil
	}

	// 推荐列表（可无 user_id，此时退化为热门排序）
	var recommended []TemplateItem
	if p.User.HasUser {
		recommended, err = RecommendTemplates(p.User.UserID, p.TemplatesDir, p.RecommendLimit, p.IncludeFavored)
		if err != nil {
			return SearchRecommendResult{}, err
		}
	} else {
		recommended, err = ListHotTemplates(p.TemplatesDir, p.RecommendLimit, p.User)
		if err != nil {
			return SearchRecommendResult{}, err
		}
	}

	// 搜索命中：按关键词过滤，然后按“推荐得分”排序
	tokens := normalizeQueryTokens(p.Query)
	matched := make([]TemplateItem, 0, len(all))
	for _, t := range all {
		if templateMatchesTokens(t, tokens) {
			matched = append(matched, t)
		}
	}

	// 复用推荐打分：有 user 就按个性化；无 user 就按热门
	if p.User.HasUser {
		// 获取一个足够大的推荐排序列表，然后做一个 id->rank
		ranked, err := RecommendTemplates(p.User.UserID, p.TemplatesDir, 5000, true)
		if err != nil {
			return SearchRecommendResult{}, err
		}
		rank := map[string]int{}
		for i, t := range ranked {
			rank[t.ID] = i
		}
		// 补充 used_count/favored
		matched, err = DecorateTemplates(matched, p.User)
		if err != nil {
			return SearchRecommendResult{}, err
		}
		sort.SliceStable(matched, func(i, j int) bool {
			ri, iok := rank[matched[i].ID]
			rj, jok := rank[matched[j].ID]
			if iok && jok {
				return ri < rj
			}
			if iok != jok {
				return iok
			}
			return matched[i].Name < matched[j].Name
		})
	} else {
		matched, err = DecorateTemplates(matched, p.User)
		if err != nil {
			return SearchRecommendResult{}, err
		}
		sort.SliceStable(matched, func(i, j int) bool {
			si := matched[i].Hot + usageBoost(matched[i].UsedCount)
			sj := matched[j].Hot + usageBoost(matched[j].UsedCount)
			if si != sj {
				return si > sj
			}
			return matched[i].Name < matched[j].Name
		})
	}

	if len(matched) > p.Limit {
		matched = matched[:p.Limit]
	}

	// 推荐列表补充 used_count/favored（RecommendTemplates 已带 used_count/favored；热门也已带）
	return SearchRecommendResult{Matches: matched, Recommended: recommended}, nil
}
