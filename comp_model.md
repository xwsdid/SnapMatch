# comp_model.onnx 说明（构图识别/推荐）

本文档说明 `models/comp_model.onnx` 是什么、怎么训练/导出、后端如何调用推理、接口如何对接前端。

---

## 1. 这是什么东西（ONNX / comp_model.onnx）

- **ONNX**（Open Neural Network Exchange）是一种“跨框架的模型文件格式”。你可以用 PyTorch 训练模型，然后导出成 `.onnx`，再在 Go / Java / C++ 等环境里用 ONNX Runtime 做推理。
- 你们仓库里：
  - 模型文件：`models/comp_model.onnx`
  - 训练脚本：`comp_model/train.py`
  - 导出脚本（PyTorch → ONNX）：`comp_model/exp.py`
  - Python 端推理验证脚本：`comp_model/test.py`

在后端运行时：前端上传一张图片 → 后端做图片预处理 → 把图片变成张量（Tensor）喂给 `.onnx` → 得到 9 个输出值（logits）→ 转成概率 → 返回构图类型 + 置信度。

---

## 2. 模型做的任务是什么（9 个构图“标签”）

从训练脚本 [comp_model/train.py](comp_model/train.py) 可以看出：

- 基础网络：`mobilenet_v3_large`
- 最后分类层输出维度：9
- 损失函数：`BCEWithLogitsLoss`

**结论：这是一个“多标签分类”（multi-label）模型**：

- 同一张图可能同时命中多个构图特征（例如同时有“对称 + 中心”）。
- 推理时用 `sigmoid` 把每个类别的 logit 转成概率，然后用阈值筛选。

---

## 3. 训练 / 导出流程（PyTorch → comp_model.onnx）

### 3.1 训练

- 入口：`python comp_model/train.py`
- 产物：`comp_model_best.pth`（PyTorch 权重）

训练数据读取方式：

- `train_label.txt` 每行 9 个数（0/1 或 0/1 浮点），对应 9 个标签。
- 图片来自 `./data/train_img`，标签来自 `./data/train_label.txt`。

### 3.2 导出 ONNX

- 入口：`python comp_model/exp.py`
- 产物：`comp_model.onnx`

导出关键约定（非常重要）：

- 输入节点名：`input`
- 输出节点名：`output`
- 输入形状：`[1, 3, 224, 224]`（NCHW）
- 输出形状：`[1, 9]`

这些约定与后端 [composition/composition.go](composition/composition.go) 完全对应。

### 3.3 训练原理（详细）

本节对应训练脚本 [comp_model/train.py](comp_model/train.py) 的实现逻辑，解释“模型是怎么学会判断构图的”。

#### 3.3.1 任务定义：多标签分类（Multi-label Classification）

- 你们把“构图类型”做成 **9 个标签**，每张图都有一个 9 维的标签向量，例如：

  ```
  [1, 0, 0, 0, 0, 0, 1, 0, 0]
  ```

  表示该图片同时具备「三分法构图」与「中心构图」特征。

- 这与“单标签分类”（一张图只能属于 9 类中的某一类）不同：
  - 单标签分类常用 softmax
  - 多标签分类对每个标签独立预测，常用 sigmoid

训练脚本采用 `BCEWithLogitsLoss`，说明它是 **多标签**设置。

#### 3.3.2 网络结构：MobileNetV3-Large + 替换最后分类层

- Backbone：`mobilenet_v3_large`（轻量级 CNN，适合端侧/实时推理）
- 训练时加载 ImageNet 预训练权重：

  ```python
  model = models.mobilenet_v3_large(weights=models.MobileNet_V3_Large_Weights.DEFAULT)
  ```

  这意味着：
  - “原始权重”来自 ImageNet 预训练（通用视觉特征）
  - 你们在此基础上继续训练，让它适配“构图标签”任务（fine-tuning）

- 替换最后分类层为 9 维输出：

  ```python
  model.classifier[3] = nn.Linear(model.classifier[3].in_features, 9)
  ```

模型输出是 9 个 **logits**（未经过 sigmoid 的实数）。

#### 3.3.3 损失函数：BCEWithLogitsLoss（数值稳定 + 适配多标签）

训练用：

```python
criterion = nn.BCEWithLogitsLoss(pos_weight=dataset.pos_weight.to(DEVICE))
```

它等价于：
- 先对每个 logit $z$ 做 sigmoid 得到概率 $\sigma(z)$
- 再计算二元交叉熵（BCE）

对单个标签 $y\in\{0,1\}$ 的典型形式：

$$
	ext{BCE}(z,y) = -\big(y\log\sigma(z) + (1-y)\log(1-\sigma(z))\big)
$$

`WithLogits` 的好处是把 sigmoid 和 BCE 融合在一个算子里，数值更稳定。

#### 3.3.4 样本不平衡：pos_weight 的作用

构图数据通常严重不平衡（有的构图出现很多，有的很少）。如果直接训练，模型会偏向预测“常见构图”。

你们在数据集里统计了 9 个类别的正样本次数 `label_counts`，并计算：

$$
	ext{pos\_weight}_c = \frac{N - P_c}{P_c + \epsilon}
$$

其中：
- $N$ = 总样本数
- $P_c$ = 第 $c$ 类正样本数

直观理解：
- 某个类别越稀有（$P_c$ 越小），它的 `pos_weight` 越大
- 训练时对这个类别的“漏报”惩罚更重，帮助模型学到少数类

#### 3.3.5 图片预处理/增强：尽量不破坏构图

你们实现了一个 `CompositionTransform`，核心目标是：**增强泛化能力，同时尽量不改变构图结构**。

关键点：
- `letterbox_image`：等比例缩放并补黑边到 224×224
  - 好处：不拉伸画面比例，避免“构图特征被压扁/拉长”
- `ColorJitter` / `RandomGrayscale`：颜色增强（训练时启用）
  - 主要让模型更关注结构/线条而非颜色
- `Normalize(mean, std)`：按 ImageNet 统计量标准化
  - mean = `[0.485, 0.456, 0.406]`
  - std  = `[0.229, 0.224, 0.225]`

说明：Python 的 [comp_model/test.py](comp_model/test.py) 使用了 `Resize + CenterCrop`，和训练时的 letterbox 不同；你们线上推理建议与训练侧保持一致（letterbox + normalize），否则准确率会受影响。

#### 3.3.6 训练策略：AdamW + 学习率调度 + 保存最佳模型

训练主流程：
- 设备：有 CUDA 用 GPU，否则 CPU
- epoch：100
- 划分：90% 训练、10% 验证
- 优化器：AdamW，学习率 `1e-4`
- 学习率调度：`ReduceLROnPlateau(optimizer, mode='min', patience=3, factor=0.5)`
  - 验证集 loss 连续若干轮不下降，就把学习率乘以 0.5
- 模型保存：以“验证集 loss 最小”为准保存

  ```python
  if curr_v_loss < best_loss:
      torch.save(model.state_dict(), 'comp_model_best.pth')
  ```

这意味着：最终导出 ONNX 的推荐做法是：用 `comp_model_best.pth` 进行导出。

#### 3.3.7 推理阈值为什么是 0.35

推理阶段（后端/测试脚本）会对每一类概率 $p$ 做阈值筛选：
- $p \ge 0.35$：认为该构图标签“命中”
- 否则不返回该标签

阈值越低：
- 返回的标签越多（召回更高），但可能更“乱”

阈值越高：
- 返回更少、更自信的标签（精度更高），但可能漏掉一些弱特征

你们目前取 0.35，是一种偏“多返回一些候选”的设置；后续可以通过标注集统计 PR 曲线来调参。

---

## 4. 后端推理链路（从接口到模型）

### 4.1 启动时加载模型

- 后端入口： [main.go](main.go)
- 初始化：`service.InitCompositionService("models/comp_model.onnx")`
- 若加载失败，只会打印警告日志（后续构图分析功能不可用）。

### 4.2 API 接口（前端怎么传图）

- 路由： [router/router.go](router/router.go)
- 接口：`POST /api/composition/analyze`
- 请求类型：`multipart/form-data`
- 表单字段：`image`（必须叫这个名字）
- 支持格式：JPG/JPEG/PNG
- 上传大小限制：10MB（Gin 里配置）

控制器实现见： [controller/composition_controller.go](controller/composition_controller.go)

### 4.3 服务层：保存临时文件并推理

服务实现见： [service/composition_service.go](service/composition_service.go)

- 把上传文件保存到临时目录（如 `/tmp/photo_upload/xxx.jpg`）
- 调用 `compositionModel.Predict(tempFile)`
- 推理完成后删除临时文件

---

## 5. 输入张量（Tensor）长什么样

后端推理核心见： [composition/composition.go](composition/composition.go)

### 5.1 输入张量形状与类型

- 形状：`[1, 3, 224, 224]`
- 类型：`float32`
- 布局：NCHW（批次、通道、高、宽）

### 5.2 图片预处理（必须和训练尽量一致）

训练脚本的预处理：

- 等比例缩放并补黑边到 224×224（letterbox，尽量不破坏构图比例）
- `ToTensor()`：像素从 0~255 → 0~1
- `Normalize(mean=[0.485,0.456,0.406], std=[0.229,0.224,0.225])`

后端已按上述逻辑实现：

- letterbox：保持纵横比，边缘补黑
- 归一化：按 ImageNet mean/std 标准化

这一步如果不一致，模型准确率会明显下降。

---

## 6. 输出张量怎么解释（logits → 概率 → 结果列表）

### 6.1 输出张量

- 形状：`[1, 9]`
- 类型：`float32`
- 内容：9 个 **logits**（还不是概率）

### 6.2 后端后处理

后端对每个 logit 做：

- `sigmoid(logit)` → 得到每个类别的概率 $p \in (0,1)$
- 阈值：`threshold = 0.35`
- 如果没有任何类别超过阈值：返回“最大概率”的那个类别作为兜底

返回给前端的 `confidence` 是百分比（0~100）。

---

## 7. 类别名称与顺序（非常关键）

后端目前使用的类别名称顺序定义在： [composition/composition.go](composition/composition.go)

当前顺序为：

1. 三分法构图
2. 垂直线构图
3. 水平线构图
4. 对角线构图
5. 曲线构图
6. 三角形构图
7. 中心构图
8. 对称构图
9. 框架/图案构图

Python 验证脚本 [comp_model/test.py](comp_model/test.py) 里定义的 `class_names` 已与后端保持一致（建议以后改动时两边同步更新）。

- 如果你们未来要重新训练/导出并替换 ONNX，请务必统一“标签顺序”与“后端 classNames”。
- 最稳的校验方法：挑 2~3 张你们非常确定构图类型的图片，分别用 Python 脚本和后端接口推理，对照输出是否一致。

---

## 8. API 返回给前端的数据格式

成功示例（来自接口约定）：

```json
{
  "code": 200,
  "msg": "构图分析成功",
  "data": [
    {"name": "三分法", "confidence": 85.6},
    {"name": "水平构图", "confidence": 72.3}
  ]
}
```

无明显特征时：

```json
{
  "code": 200,
  "msg": "未检测到明显的构图特征",
  "data": []
}
```

---

## 9. 常见问题

### 9.1 本地 Windows 无法 `go test ./...`

`onnxruntime_go` 在 Windows 上可能触发 build constraints（不支持/需要额外配置），而你们实际部署在 Linux 服务器上。

- 结论：以服务器环境编译/运行结果为准。

### 9.2 模型加载失败

启动日志出现“构图模型初始化失败”，接口可能返回空结果或失败。

- 检查服务器上 `models/comp_model.onnx` 是否存在
- 检查 ONNX Runtime 依赖与 `onnxruntime_go` 环境

---

## 10. 替换模型（更新 comp_model.onnx）的正确方式

1) 训练得到新的 `comp_model_best.pth`
2) 用 [comp_model/exp.py](comp_model/exp.py) 导出为 `comp_model.onnx`（确保 input/output 名称不变）
3) 用新文件覆盖 `models/comp_model.onnx`
4) 重启后端服务
5) 用 `/api/composition/analyze` 做回归测试（至少 2~3 张样例图）
