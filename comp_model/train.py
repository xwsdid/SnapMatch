import os
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader, Subset
from torchvision import models, transforms
from PIL import Image
def letterbox_image(image, size=(224, 224)):
    """
    等比例缩放图片，多余部分填充黑色，保证构图比例不变
    """
    iw, ih = image.size
    w, h = size
    scale = min(w / iw, h / ih)
    nw = int(iw * scale)
    nh = int(ih * scale)

    image = image.resize((nw, nh), Image.BICUBIC)
    new_image = Image.new('RGB', size, (0, 0, 0))
    new_image.paste(image, ((w - nw) // 2, (h - nh) // 2))
    return new_image


class CompositionTransform:
    def __init__(self, size=224, training=True):
        self.size = (size, size)
        self.training = training

    def __call__(self, img):
        # 1. 等比例缩放并填充
        img = letterbox_image(img, self.size)

        # 2. 基础变换
        t = [transforms.ToTensor()]

        if self.training:
            # 加入不破坏构图的增强：色彩抖动和随机灰度（强化线条感）
            t.insert(0, transforms.ColorJitter(0.2, 0.2, 0.2))
            t.insert(1, transforms.RandomGrayscale(p=0.1))

        t.append(transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]))
        return transforms.Compose(t)(img)

# --- 1. Dataset (支持文件名和标签映射) ---
class KUPCP9Dataset(Dataset):
    def __init__(self, txt_file, img_dir, transform=None):
        self.img_dir = img_dir
        self.transform = transform
        self.data_list = []

        with open(txt_file, 'r') as f:
            lines = f.readlines()

        # 假设图片按 1.jpg, 2.jpg 顺序排列，或者根据你的目录列表
        all_imgs = sorted([f for f in os.listdir(img_dir) if f.lower().endswith(('.jpg', '.png'))])
        num = min(len(all_imgs), len(lines))

        # 统计类别频率用于计算权重
        self.label_counts = torch.zeros(9)

        for i in range(num):
            parts = lines[i].strip().split()
            if len(parts) == 9:
                labels = [float(x) for x in parts]
                self.label_counts += torch.tensor(labels)
                self.data_list.append((all_imgs[i], labels))

        # 计算 pos_weight: (负样本数 / 正样本数)
        self.pos_weight = (len(self.data_list) - self.label_counts) / (self.label_counts + 1e-6)
        print(f"有效数据: {len(self.data_list)} | 建议权重: {self.pos_weight.tolist()}")

    def __len__(self):
        return len(self.data_list)

    def __getitem__(self, idx):
        img_name, labels = self.data_list[idx]
        img = Image.open(os.path.join(self.img_dir, img_name)).convert("RGB")
        if self.transform: img = self.transform(img)
        return img, torch.tensor(labels, dtype=torch.float32)


# --- 2. 训练主程序 ---
def train():
    DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    EPOCHS = 100

    # 使用自定义的构图保护变换
    train_trans = CompositionTransform(size=224, training=True)

    dataset = KUPCP9Dataset('./data/train_label.txt', './data/train_img', transform=train_trans)
    train_size = int(0.9 * len(dataset))
    train_ds, val_ds = Subset(dataset, range(0, train_size)), Subset(dataset, range(train_size, len(dataset)))

    train_loader = DataLoader(train_ds, batch_size=32, shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=32)

    model = models.mobilenet_v3_large(weights=models.MobileNet_V3_Large_Weights.DEFAULT)
    model.classifier[3] = nn.Linear(model.classifier[3].in_features, 9)
    model.to(DEVICE)

    # 关键点：加入 pos_weight，解决样本不平衡导致的不准
    criterion = nn.BCEWithLogitsLoss(pos_weight=dataset.pos_weight.to(DEVICE))
    optimizer = optim.AdamW(model.parameters(), lr=1e-4)
    scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, 'min', patience=3, factor=0.5)

    best_loss = float('inf')
    for epoch in range(EPOCHS):
        model.train()
        t_loss = 0
        for imgs, labels in train_loader:
            imgs, labels = imgs.to(DEVICE), labels.to(DEVICE)
            optimizer.zero_grad()
            loss = criterion(model(imgs), labels)
            loss.backward()
            optimizer.step()
            t_loss += loss.item()

        model.eval()
        v_loss = 0
        with torch.no_grad():
            for imgs, labels in val_loader:
                v_loss += criterion(model(imgs.to(DEVICE)), labels.to(DEVICE)).item()

        curr_v_loss = v_loss / len(val_loader)
        scheduler.step(curr_v_loss)
        print(f"Epoch {epoch + 1} | Train: {t_loss / len(train_loader):.4f} | Val: {curr_v_loss:.4f}")

        if curr_v_loss < best_loss:
            best_loss = curr_v_loss
            torch.save(model.state_dict(), 'comp_model_best.pth')


if __name__ == "__main__":
    train()