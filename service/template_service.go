package service

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
)

type TemplateItem struct {
	ID         string         `json:"template_id"`
	Name       string         `json:"name"`
	Title      string         `json:"title,omitempty"`
	URL        string         `json:"url"` // 兼容旧前端：默认等同 cover
	CoverURL   string         `json:"cover_url,omitempty"`
	ExampleURL string         `json:"example_url,omitempty"`
	OverlayURL string         `json:"overlay_url,omitempty"`
	Guides     []TemplateGuide `json:"guides,omitempty"`
	Tags       []string       `json:"tags"`
	Hot        int            `json:"hot"`
	UsedCount  int            `json:"used_count"`
	Favored    bool           `json:"favored"`
	Description string        `json:"description,omitempty"`
}

// TemplateGuide 拍摄引导（结构化文本 + 归一化坐标）
//
// 坐标建议使用 0~1 的归一化比例（相对于预览画面宽高），便于适配不同分辨率。
type TemplateGuide struct {
	Text  string  `json:"text"`
	X     float64 `json:"x"`
	Y     float64 `json:"y"`
	Align string  `json:"align,omitempty"` // 可选：left/center/right
}

type templateMeta struct {
	// 旧字段（兼容）
	File       string   `json:"file"`
	TemplateID string   `json:"template_id"`
	Name       string   `json:"name"`

	// 新字段（推荐）
	Title   string         `json:"title"`
	Cover   string         `json:"cover"`
	Example string         `json:"example"`
	Overlay string         `json:"overlay"`
	Guides  []TemplateGuide `json:"guides"`

	Tags []string `json:"tags"`
	Hot  int      `json:"hot"`
	Description string `json:"description,omitempty"`
}

func normalizeTags(tags []string) []string {
	seen := map[string]struct{}{}
	out := make([]string, 0, len(tags))
	for _, t := range tags {
		v := strings.TrimSpace(t)
		if v == "" {
			continue
		}
		if _, ok := seen[v]; ok {
			continue
		}
		seen[v] = struct{}{}
		out = append(out, v)
	}
	sort.Strings(out)
	return out
}

// loadTemplateMeta 读取 templates.json（可选）。
// 文件建议放在：static/templates/templates.json
// 格式（数组）：[{"file":"autumn_01.jpg","template_id":"autumn_01","name":"秋日氛围感-1","tags":["秋日氛围感","人像"],"hot":100}]
func loadTemplateMeta(dir string) (map[string]templateMeta, map[string]templateMeta) {
	metaByFile := map[string]templateMeta{}
	metaByID := map[string]templateMeta{}
	metaPath := filepath.Join(dir, "templates.json")
	b, err := os.ReadFile(metaPath)
	if err != nil {
		return metaByFile, metaByID
	}
	var arr []templateMeta
	if err := json.Unmarshal(b, &arr); err != nil {
		return metaByFile, metaByID
	}
	for _, m := range arr {
		m.Tags = normalizeTags(m.Tags)
		// 兼容：title/name 二选一
		if strings.TrimSpace(m.Title) == "" {
			m.Title = m.Name
		}
		// 兼容：cover 优先，其次 file
		if strings.TrimSpace(m.Cover) == "" {
			m.Cover = m.File
		}
		// 一些用户可能把 example/overlay 写成空；允许为空（前端按需处理）
		if m.File != "" {
			metaByFile[m.File] = m
		}
		if m.TemplateID != "" {
			metaByID[m.TemplateID] = m
		}
	}
	return metaByFile, metaByID
}

func toURLPath(templatesDir string, p string) string {
	p = strings.TrimSpace(p)
	if p == "" {
		return ""
	}
	// 如果 meta 里已经给了绝对 URL，则直接返回（不做版本处理）
	if strings.HasPrefix(p, "http://") || strings.HasPrefix(p, "https://") {
		return p
	}

	// 允许 meta 里写相对路径（如: autumn_01/cover.jpg 或 cover.jpg）
	// 也兼容误写成 /static/templates/... 或 static/templates/...
	p = strings.TrimPrefix(p, "/")
	p = strings.TrimPrefix(p, "static/templates/")
	p = strings.TrimPrefix(p, "/static/templates/")
	p = strings.TrimPrefix(p, "/")

	abs := filepath.Join(templatesDir, filepath.FromSlash(p))
	fi, err := os.Stat(abs)
	if err != nil {
		// 文件不存在则不返回 URL，避免前端加载到 404
		return ""
	}
	url := "/static/templates/" + filepath.ToSlash(p)
	return fmt.Sprintf("%s?v=%s", url, strconv.FormatInt(fi.ModTime().Unix(), 10))
}

// ListTemplates 从静态目录扫描模板图片并返回（URL 为相对路径：/static/templates/xxx.jpg）。
//
// 支持 templates.json 元数据：为模板提供 name/tags/hot。

func ListTemplates(dir string, limit int) ([]TemplateItem, error) {
	entries, err := os.ReadDir(dir)
	if err != nil {
		// 目录不存在时按“无模板”处理
		if os.IsNotExist(err) {
			return []TemplateItem{}, nil
		}
		return nil, err
	}

	metaByFile, metaByID := loadTemplateMeta(dir)

	// 优先：如果 templates.json 提供了 template_id，则以 meta 为准（支持三图模板）
	if len(metaByID) > 0 {
		ids := make([]string, 0, len(metaByID))
		for id := range metaByID {
			ids = append(ids, id)
		}
		sort.Strings(ids)
		items := make([]TemplateItem, 0, len(ids))
		for _, id := range ids {
			m := metaByID[id]
			title := strings.TrimSpace(m.Title)
			if title == "" {
				title = id
			}
			cover := toURLPath(dir, m.Cover)
			// cover 缺失时跳过，避免把“未放素材”的模板展示给前端
			if strings.TrimSpace(cover) == "" {
				continue
			}
			example := toURLPath(dir, m.Example)
			// 产品升级：模板按“两张图”使用。
			// - 第 1 张：cover（列表封面/详情大图/进入拍同款页的模板图）
			// - 第 2 张：overlay（手绘图稿 + 文案已直接画在图片上）
			// 为了尽量不让前端改动，example_url 为空时自动回退为 cover。
			if strings.TrimSpace(example) == "" {
				example = cover
			}
			       item := TemplateItem{
				       ID:         id,
				       Name:       title, // 兼容旧字段
				       Title:      title,
				       URL:        cover,
				       CoverURL:   cover,
				       ExampleURL: example,
				       OverlayURL: toURLPath(dir, m.Overlay),
				       Guides: nil,
				       Tags:       normalizeTags(m.Tags),
				       Hot:        m.Hot,
				       Description: m.Description,
			       }
			items = append(items, item)
		}

		sort.SliceStable(items, func(i, j int) bool {
			if items[i].Hot != items[j].Hot {
				return items[i].Hot > items[j].Hot
			}
			return items[i].Name < items[j].Name
		})

		if limit > 0 && len(items) > limit {
			items = items[:limit]
		}
		return items, nil
	}

	names := make([]string, 0, len(entries))
	for _, e := range entries {
		if e.IsDir() {
			continue
		}
		n := e.Name()
		ext := strings.ToLower(filepath.Ext(n))
		switch ext {
		case ".jpg", ".jpeg", ".png", ".webp":
			names = append(names, n)
		}
	}

	sort.Strings(names)

	items := make([]TemplateItem, 0, len(names))
	for _, n := range names {
		id := strings.TrimSuffix(n, filepath.Ext(n))
		m := metaByFile[n]
		if m.TemplateID == "" {
			if m2, ok := metaByID[id]; ok {
				m = m2
			}
		}
		name := id
		title := strings.TrimSpace(m.Title)
		if title == "" {
			title = strings.TrimSpace(m.Name)
		}
		if title != "" {
			name = title
		}
		tags := normalizeTags(m.Tags)
		hot := m.Hot
		if m.TemplateID != "" {
			id = m.TemplateID
		}
		cover := toURLPath(dir, n)
		items = append(items, TemplateItem{
			ID:   id,
			Name: name,
			Title: name,
			URL:  cover,
			CoverURL: cover,
			Tags: tags,
			Hot:  hot,
		})
	}

	// 默认按 hot 降序，其次 name
	sort.SliceStable(items, func(i, j int) bool {
		if items[i].Hot != items[j].Hot {
			return items[i].Hot > items[j].Hot
		}
		return items[i].Name < items[j].Name
	})

	if limit > 0 && len(items) > limit {
		items = items[:limit]
	}

	return items, nil
}
