import os
import json
import faiss
import torch
import numpy as np
from PIL import Image
import open_clip


INDEX_PATH = "index/template.index"
META_PATH = "index/metadata.json"

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

    return feature.cpu().numpy().astype("float32")


class ClipSearcher:
    def __init__(self, index_path=INDEX_PATH, meta_path=META_PATH):
        self.index_path = index_path
        self.meta_path = meta_path
        self.model = None
        self.preprocess = None
        self.device = None
        self.index = None
        self.metadata = None

    def load(self):
        if self.model is None:
            self.model, self.preprocess, self.device = load_model()
            print(f"Using device: {self.device}")
        if self.index is None:
            self.index = faiss.read_index(self.index_path)
        if self.metadata is None:
            with open(self.meta_path, "r", encoding="utf-8") as f:
                self.metadata = json.load(f)

    def search(self, query_path, top_k=5):
        self.load()
        query_emb = encode_image(self.model, self.preprocess, self.device, query_path)
        scores, ids = self.index.search(query_emb, top_k)

        results = []
        for score, idx in zip(scores[0], ids[0]):
            if idx < 0:
                continue
            item = self.metadata[int(idx)]
            results.append({
                "score": float(score),
                "template_id": item["template_id"],
                "file_name": item["file_name"],
                "path": item["path"],
                "cover_url_path": item["cover_url_path"],
            })

        return results


def search(query_path, top_k=5):
    return ClipSearcher().search(query_path, top_k=top_k)


if __name__ == "__main__":
    query_path = "queries/query_004.jpg"
    results = search(query_path, top_k=5)

    for i, item in enumerate(results, start=1):
        print(
            f"Top {i}: {item['template_id']} | {item['file_name']} | "
            f"score={item['score']:.4f} | {item['cover_url_path']}"
        )
