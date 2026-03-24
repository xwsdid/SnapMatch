import torch
from torchvision import models, transforms
from PIL import Image
import torch.nn as nn


class CompositionRecommender:
    def __init__(self, model_path):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.class_names = ['三分法构图', '垂直线构图', '水平线构图', '对角线构图',
                            '曲线构图', '三角形构图', '中心构图', '对称构图', '框架/图案构图']

        # 加载结构
        self.model = models.mobilenet_v3_large()
        self.model.classifier[3] = nn.Linear(self.model.classifier[3].in_features, 9)

        # 加载权重
        self.model.load_state_dict(torch.load(model_path, map_location=self.device))
        self.model.to(self.device).eval()

        self.transform = transforms.Compose([
            transforms.Resize(256),
            transforms.CenterCrop(224),
            transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
        ])

    def recommend(self, img_path, threshold=0.35):
        img = Image.open(img_path).convert("RGB")
        img_t = self.transform(img).unsqueeze(0).to(self.device)

        with torch.no_grad():
            logits = self.model(img_t)
            probs = torch.sigmoid(logits).squeeze().cpu().numpy()

        results = []
        for i, p in enumerate(probs):
            if p >= threshold:
                results.append({"type": self.class_names[i], "score": float(p)})

        # 按分数排序
        return sorted(results, key=lambda x: x['score'], reverse=True)


# 示例使用
if __name__ == "__main__":
    recommender = CompositionRecommender("comp_model_best.pth")
    test_img = "./data/test_img/0333.jpg"  # 替换为你的测试图片路径

    recommendations = recommender.recommend(test_img)

    print(f"\n--- 图片 {test_img} 的构图推荐 ---")
    if not recommendations:
        print("未检测到明显构图特征，建议参考常规三分法。")
    for rec in recommendations:
        print(f"推荐方案: {rec['type']} (置信度: {rec['score']:.2%})")