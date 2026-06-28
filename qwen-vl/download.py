from modelscope import snapshot_download

# 下载 7B 最强版（双 32G 显卡完美运行）
model_dir = snapshot_download(
    "qwen/Qwen2.5-VL-7B-Instruct",
    cache_dir="./qwen_vl_model"  # 模型会保存到这个文件夹
)
print("模型下载完成，路径：", model_dir)
