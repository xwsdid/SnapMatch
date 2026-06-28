import os
import json
import faiss
import torch
import numpy as np
from PIL import Image
from tqdm import tqdm
import open_clip


TEMPLATE_ROOT = os.environ.get("TEMPLATE_ROOT", "/root/photo_backend/static/templates")
INDEX_DIR = "index"
INDEX_PATH = os.path.join(INDEX_DIR, "template.index")
META_PATH = os.path.join(INDEX_DIR, "metadata.json")

MODEL_NAME = "ViT-L-14"
PRETRAINED = "openai"


def load_model():
    device = "cuda" if torch.cuda.is_available() else "cpu"

    model, _, preprocess = open_clip.create_model_and_transforms(
        MODEL_NAME,
        pretrained=PRETRAINED
    )
    model = model.to(device)
    model.eval()

    return model, preprocess, device


def encode_image(model, preprocess, device, image_path):
    image = Image.open(image_path).convert("RGB")
    image_tensor = preprocess(image).unsqueeze(0).to(device)

    with torch.no_grad():
        feature = model.encode_image(image_tensor)
        feature = feature / feature.norm(dim=-1, keepdim=True)

    return feature.cpu().numpy().astype("float32")[0]


def _static_url_path(relative_path, image_path):
    mtime = int(os.path.getmtime(image_path))
    return f"/static/templates/{relative_path.replace(os.sep, '/')}?v={mtime}"


def resolve_cover_path(template_root, template_id, cover):
    image_path = os.path.join(template_root, *cover.split("/"))
    if os.path.exists(image_path):
        return image_path, cover

    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        fallback = f"{template_id}/cover{ext}"
        fallback_path = os.path.join(template_root, template_id, f"cover{ext}")
        if os.path.exists(fallback_path):
            print(f"Use fallback cover for {template_id}: {fallback}")
            return fallback_path, fallback

    return image_path, cover


def load_template_images(template_root):
    meta_path = os.path.join(template_root, "templates.json")
    with open(meta_path, "r", encoding="utf-8") as f:
        templates = json.load(f)

    image_items = []
    for item in templates:
        template_id = item.get("template_id", "").strip()
        cover = item.get("cover", "").strip()
        if not template_id or not cover:
            continue

        cover = cover.lstrip("/").replace("\\", "/")
        for prefix in ("static/templates/", "/static/templates/"):
            if cover.startswith(prefix):
                cover = cover[len(prefix):]

        image_path, cover = resolve_cover_path(template_root, template_id, cover)
        if not os.path.exists(image_path):
            print(f"Skip missing cover for {template_id}: {image_path}")
            continue

        image_items.append({
            "template_id": template_id,
            "file_name": os.path.basename(image_path),
            "relative_path": cover,
            "path": image_path,
            "cover_url_path": _static_url_path(cover, image_path),
        })

    return image_items


def main():
    os.makedirs(INDEX_DIR, exist_ok=True)

    model, preprocess, device = load_model()
    print(f"Using device: {device}")

    image_items = load_template_images(TEMPLATE_ROOT)

    embeddings = []
    metadata = []

    for idx, item in enumerate(tqdm(image_items)):
        try:
            image_path = item["path"]
            emb = encode_image(model, preprocess, device, image_path)
            embeddings.append(emb)

            metadata.append({
                "id": idx,
                **item,
            })
        except Exception as e:
            print(f"Failed to process {item['path']}: {e}")

    if not embeddings:
        raise RuntimeError(f"No template cover images indexed from {TEMPLATE_ROOT}")

    embeddings = np.array(embeddings).astype("float32")

    dim = embeddings.shape[1]

    # 因为向量已经归一化，所以 Inner Product 等价于 cosine similarity
    index = faiss.IndexFlatIP(dim)
    index.add(embeddings)

    faiss.write_index(index, INDEX_PATH)

    with open(META_PATH, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    print(f"Saved index to {INDEX_PATH}")
    print(f"Saved metadata to {META_PATH}")
    print(f"Template count: {len(metadata)}")


if __name__ == "__main__":
    main()
