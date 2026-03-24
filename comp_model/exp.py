import torch
import torch.nn as nn
from torchvision import models


def export_to_onnx(pth_path, onnx_path):
    # 1. 重新构建模型架构 (必须与训练时完全一致)
    model = models.mobilenet_v3_large()
    model.classifier[3] = nn.Linear(model.classifier[3].in_features, 9)

    # 2. 加载训练好的权重
    device = torch.device("cpu")  # 导出通常在 CPU 上进行
    model.load_state_dict(torch.load(pth_path, map_location=device))
    model.eval()

    # 3. 创建虚拟输入 (Dummy Input)
    # Go 后端通常期望固定尺寸: [Batch_Size, Channels, Height, Width]
    # 我们设定 BatchSize=1, 图片尺寸 224x224
    dummy_input = torch.randn(1, 3, 224, 224)

    # 4. 执行导出
    print(f"正在转换模型 {pth_path} 为 ONNX 格式...")
    torch.onnx.export(
        model,
        dummy_input,
        onnx_path,
        export_params=True,  # 导出模型权重
        opset_version=12,  # 建议使用 v12，兼容性好
        do_constant_folding=True,  # 执行常量折叠优化
        input_names=['input'],  # Go 推理时需要的输入节点名
        output_names=['output'],  # Go 推理时需要的输出节点名
        # 如果需要动态 BatchSize，取消下面注释：
        # dynamic_axes={'input': {0: 'batch_size'}, 'output': {0: 'batch_size'}}
    )
    print(f"导出成功! 文件保存在: {onnx_path}")


if __name__ == "__main__":
    export_to_onnx("comp_model_best.pth", "comp_model.onnx")