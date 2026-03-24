package service

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"mime/multipart"
	"net"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

type ShootingAdvice struct {
	Composition string `json:"composition"`
	Focus       string `json:"focus"`
	Atmosphere  string `json:"atmosphere"`
}

type PoseGuide struct {
	PoseTitle    string   `json:"pose_title"`
	Instructions []string `json:"instructions"`
}

var (
	ErrVLMInvalidTask = errors.New("VLM_INVALID_TASK")
)

func vlmAPIURL() string {
	full := strings.TrimSpace(os.Getenv("VLM_API_URL"))
	if full != "" {
		return full
	}

	base := strings.TrimSpace(os.Getenv("VLM_API_BASE_URL"))
	if base != "" {
		base = strings.TrimRight(base, "/")
		return base + "/vlm/infer"
	}

	return "http://127.0.0.1:8000/vlm/infer"
}

func vlmProxyFunc(req *http.Request) (*url.URL, error) {
	host := req.URL.Hostname()
	if host == "localhost" {
		return nil, nil
	}
	if ip := net.ParseIP(host); ip != nil {
		if ip.IsLoopback() {
			return nil, nil
		}
	}
	return http.ProxyFromEnvironment(req)
}

func vlmHTTPTimeout() time.Duration {
	secStr := strings.TrimSpace(os.Getenv("VLM_HTTP_TIMEOUT_SECONDS"))
	if secStr == "" {
		return 120 * time.Second
	}
	sec, err := strconv.Atoi(secStr)
	if err != nil || sec <= 0 {
		return 120 * time.Second
	}
	return time.Duration(sec) * time.Second
}

func forwardToVLM(file *multipart.FileHeader, task string) ([]byte, error) {
	url := vlmAPIURL()
	transport := http.DefaultTransport.(*http.Transport).Clone()
	transport.Proxy = vlmProxyFunc
	client := &http.Client{Timeout: vlmHTTPTimeout(), Transport: transport}

	// Build multipart body synchronously so file errors are surfaced (avoid silent pipe/goroutine failures).
	var buf bytes.Buffer
	writer := multipart.NewWriter(&buf)
	if err := writer.WriteField("task", task); err != nil {
		_ = writer.Close()
		return nil, err
	}
	part, err := writer.CreateFormFile("file", filepath.Base(file.Filename))
	if err != nil {
		_ = writer.Close()
		return nil, err
	}
	src, err := file.Open()
	if err != nil {
		_ = writer.Close()
		return nil, err
	}
	if _, err := io.Copy(part, src); err != nil {
		_ = src.Close()
		_ = writer.Close()
		return nil, err
	}
	_ = src.Close()
	if err := writer.Close(); err != nil {
		return nil, err
	}

	req, err := http.NewRequest(http.MethodPost, url, &buf)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", writer.FormDataContentType())

	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer func() { _ = resp.Body.Close() }()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}

	if resp.StatusCode != http.StatusOK {
		// Try to surface FastAPI error payload if any.
		trimmed := bytes.TrimSpace(body)
		if len(trimmed) > 0 {
			return nil, fmt.Errorf("vlm http status=%d body=%s", resp.StatusCode, string(trimmed))
		}
		return nil, fmt.Errorf("vlm http status=%d", resp.StatusCode)
	}

	return body, nil
}

func InferShootingAdvice(file *multipart.FileHeader) (*ShootingAdvice, error) {
	body, err := forwardToVLM(file, "advice")
	if err != nil {
		return nil, err
	}

	var out ShootingAdvice
	if err := json.Unmarshal(body, &out); err != nil {
		return nil, fmt.Errorf("invalid advice json: %w", err)
	}
	if strings.TrimSpace(out.Composition) == "" || strings.TrimSpace(out.Focus) == "" || strings.TrimSpace(out.Atmosphere) == "" {
		return nil, fmt.Errorf("advice json missing fields")
	}

	return &out, nil
}

func InferPoseGuide(file *multipart.FileHeader) (*PoseGuide, error) {
	body, err := forwardToVLM(file, "pose")
	if err != nil {
		return nil, err
	}

	var out PoseGuide
	if err := json.Unmarshal(body, &out); err != nil {
		return nil, fmt.Errorf("invalid pose json: %w", err)
	}
	if strings.TrimSpace(out.PoseTitle) == "" || len(out.Instructions) == 0 {
		return nil, fmt.Errorf("pose json missing fields")
	}

	return &out, nil
}

func InferVLM(file *multipart.FileHeader, task string) (any, error) {
	task = strings.TrimSpace(task)
	switch task {
	case "advice":
		return InferShootingAdvice(file)
	case "pose":
		return InferPoseGuide(file)
	default:
		return nil, ErrVLMInvalidTask
	}
}
