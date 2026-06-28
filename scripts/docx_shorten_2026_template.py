from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Dict, Optional

import xml.etree.ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W_NS}


def qn(tag: str) -> str:
    return f"{{{W_NS}}}{tag}"


def unzip_docx(docx_path: Path, out_dir: Path) -> None:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with ZipFile(docx_path, "r") as zf:
        zf.extractall(out_dir)


def zip_dir_to_docx(src_dir: Path, out_docx: Path) -> None:
    if out_docx.exists():
        out_docx.unlink()
    with ZipFile(out_docx, "w", compression=ZIP_DEFLATED) as zf:
        for p in sorted(src_dir.rglob("*")):
            if p.is_dir():
                continue
            arc = p.relative_to(src_dir).as_posix()
            zf.write(p, arc)


def paragraph_has_drawing(p: ET.Element) -> bool:
    return (p.find(".//w:drawing", NS) is not None) or (p.find(".//w:pict", NS) is not None)


def remove_non_drawing_runs(p: ET.Element) -> None:
    # Keep paragraph properties and any runs containing drawings; remove other runs/hyperlinks.
    for child in list(p):
        if child.tag == qn("pPr"):
            continue
        if child.tag == qn("r"):
            if child.find(".//w:drawing", NS) is not None or child.find(".//w:pict", NS) is not None:
                continue
            p.remove(child)
            continue
        if child.tag == qn("hyperlink"):
            # hyperlinks are text-only in this template; remove to simplify.
            p.remove(child)
            continue
        # Leave other structures untouched (bookmarks, etc.)


def append_text_run(p: ET.Element, text: str) -> None:
    if text == "":
        return
    r = ET.SubElement(p, qn("r"))
    t = ET.SubElement(r, qn("t"))
    # Preserve spaces where needed
    if text[:1].isspace() or text[-1:].isspace() or "  " in text:
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    t.text = text


def set_paragraph_text(p: ET.Element, new_text: str) -> None:
    # Conservative: do not delete drawings; remove other runs and append a single text run.
    remove_non_drawing_runs(p)
    # Also clear remaining text nodes in kept drawing runs (rare)
    for t in p.findall(".//w:t", NS):
        # If this text belongs to a drawing-related run we keep, leave it.
        # We only clear if it's inside a normal run.
        parent = t
        # walk up 2 levels safely
    append_text_run(p, new_text)


def apply_edits(doc_xml: Path, edits: Dict[int, str]) -> None:
    tree = ET.parse(doc_xml)
    root = tree.getroot()
    body = root.find("w:body", NS)
    if body is None:
        raise RuntimeError("Missing w:body")
    paras = body.findall("w:p", NS)

    max_idx = len(paras) - 1

    # 1) Apply text replacements (non-empty)
    for idx, new_text in edits.items():
        if idx < 0 or idx > max_idx:
            raise IndexError(f"Paragraph index out of range: {idx} (max={max_idx})")
        if new_text == "":
            continue
        p = paras[idx]
        set_paragraph_text(p, new_text)

    # 2) Delete empty paragraphs (only if they don't contain drawings)
    delete_indices = [idx for idx, t in edits.items() if t == ""]
    for idx in sorted(delete_indices, reverse=True):
        if idx < 0 or idx > max_idx:
            continue
        p = paras[idx]
        if paragraph_has_drawing(p):
            continue
        body.remove(p)

    tree.write(doc_xml, encoding="utf-8", xml_declaration=True)


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    in_docx = repo / "docx" / "3 软件应用与开发类作品设计和开发文档模板（2026版）.docx"
    work_dir = repo / "tmp" / "docx_2026_template_unzipped_short"
    out_docx = repo / "docx" / "3 软件应用与开发类作品设计和开发文档模板（2026版）_精简版.docx"

    if not in_docx.exists():
        print(f"Input docx not found: {in_docx}")
        return 2

    unzip_docx(in_docx, work_dir)
    doc_xml = work_dir / "word" / "document.xml"

    # Paragraph-index based edits (derived from current template structure).
    edits: Dict[int, str] = {
        # 需求分析：压缩到“背景+目标+痛点+用户+竞品”要点，避免技术细节铺陈
        29: "手机摄影已成为大众记录生活的主流方式，但普通用户在取景与构图上缺少即时指导，常出现“拍得多、满意少”的问题。我们希望把专业构图知识前置到按下快门之前，让用户在拍摄当下就能得到可执行的取景建议。",
        30: "《一拍即合》面向移动端实景拍摄，围绕“更高成片率 + 更低学习门槛”，提供模板参考、实时构图推荐、经典构图识别与导学、场景化拍摄建议与人像姿势引导等功能。",
        31: "",
        32: "",
        33: "",
        36: "在全民摄影时代，用户最缺的不是滤镜，而是“拍摄前的构图与动作指导”。本作品聚焦以下五类痛点（见图 1-5），并给出对应解决思路：",
        40: "新手常不知道主体放哪、画面怎么留白，需要直观的构图参考与即时反馈来降低试错成本。",
        42: "用户希望在取景阶段识别常见构图类型并得到简要要点提示，实现即时修正与边拍边学。",
        44: "不同用户审美偏好差异明显，系统应依据选择/收藏等行为持续校准推荐，避免千人一面。",
        46: "不同场景的构图重点不同，系统应提供场景化、可执行的建议（如角度、主体与背景关系、画面重心）。",
        48: "在人像拍摄中，用户更需要可模仿的姿势示例与文字要点，减少“不会摆、摆不好”的反复尝试。",
        49: "",
        50: "综上，本作品以“模板灵感 + 实时构图 + 构图导学 + 场景建议/姿势引导”的组合，在拍摄前与拍摄中提供前置指导，帮助用户快速获得更高质量的成片。",
        52: "本作品主要面向摄影初学者、社交内容创作者与日常记录用户。其共同特征是高频拍摄、审美诉求明确，但缺少系统训练与即时反馈工具。",
        55: "通过前置的构图辅助与场景化指导，本作品降低学习成本，覆盖日常记录、内容创作与审美提升等典型场景。",
        57: "当前移动摄影应用可分为后期修图类、通用相机类与少量“构图辅助”类产品。为便于对比，我们按功能与介入时机进行竞品梳理（见表 1-1）。",
        60: "总体来看，现有竞品多集中在拍摄后的修饰与裁剪，常见不足包括：个性化学习弱、场景化指导不足、对拍摄当下的实时辅助有限。",
        61: "",
        62: "",
        63: "",
        64: "针对上述不足，本作品在模板参考的基础上，强化取景阶段的实时构图反馈与场景化指导，并结合用户偏好形成持续优化的使用闭环。",

        # 概要设计：保留图为主，压缩文字说明
        67: "系统按“需求—设计—实现—落地”的生命周期推进：围绕核心痛点抽象功能模块，确定端云协同架构与关键接口，最终形成可运行的智能摄影 App（见图 2-1）。",
        68: "技术方案由多源偏好感知、端侧实时构图、轻量级构图识别与多模态大模型能力组成，协同实现“参考—推荐—学习—指导”的完整闭环（见图 2-2）。",
        74: "端侧（Android）负责取景交互与部分实时推理；云端由业务服务与推理服务协同完成数据管理、算法调用与结果返回（见图 2-3）。",
        75: "服务器端提供统一 REST API 与数据/资源管理；GPU 主机侧提供多模态推理能力。两者通过受控通道协作，保证调用稳定与可维护性。",
        89: "云端业务按用户、素材、模板、收藏、偏好、构图分析与大模型调用等模块划分，各模块通过标准接口协同，兼顾实时反馈与推荐精度。",
        98: "下述调用链示例用于说明端云数据流与关键接口（配合图 2-5～2-7）。",

        # 详细设计：删掉常识/公式/训练细节，保留关键设计点
        107: "系统采用 Android（Kotlin）+ Go + MySQL + Python 的端云协同技术栈：端侧负责相机交互与部分实时分析，服务端负责业务编排与数据管理，GPU 主机侧提供多模态推理能力；各组件通过 REST API/HTTP 解耦。",
        108: "核心功能包括模板跟拍、实时构图推荐、经典构图识别与教学、场景化拍摄建议与人像姿势引导、作品与偏好管理等。",
        112: "前端目标是提供低延迟取景交互与清晰的指导信息呈现，确保在实时拍摄场景下“看得懂、跟得上、拍得到”。",
        117: "整体采用清晰的页面与模块划分（Activity/Fragment + 数据与网络层封装），保证实现效率与可维护性。",
        122: "协程用于网络与图像处理等耗时任务，主线程仅负责 UI 更新，以保证取景与滑动交互流畅。",
        123: "状态管理围绕页面生命周期进行保存与恢复，避免配置变更导致的流程中断。",
        124: "多模态结果以卡片形式展示，并提供语音播报入口，降低移动拍摄时的阅读负担。",
        125: "",
        127: "以智能构图场景为例，端侧采集画面并完成实时提示，必要时向云端请求识别/建议结果，最终统一回到取景界面完成拍摄（见图 3-4）。",
        131: "后端提供统一 REST API、权限校验、业务逻辑编排、数据持久化与静态资源管理，并负责将推理任务分发给对应的推理服务。",
        133: "静态资源（模板/上传图片/头像等）采用文件系统存储并通过统一路径访问，降低数据库压力。",
        136: "用户密码采用哈希存储；接口按用户身份校验执行敏感操作。",
        140: "数据层采用 ORM 管理核心表（用户、素材、偏好、收藏、使用记录等），保证一致性与可扩展性。",
        142: "推理能力与业务服务解耦：经典构图识别可在服务端完成；多模态建议/姿势由 GPU 主机侧推理并返回结构化结果，前端可直接渲染。",
        143: "",
        144: "",
        161: "本作品将“偏好感知 + 实时构图 + 构图导学 + 多模态建议/姿势引导”组合为层层递进的拍摄辅助体系：既能给出即时可执行的拍摄动作，也能帮助用户逐步理解构图原理。",
        168: "模板推荐模块以“热度 + 使用行为 + 收藏/偏好信号”为主要依据，为用户提供可解释的模板排序，解决“灵感不足、难以选择”的问题。",
        169: "推荐输入主要来自：模板标签与热度、全局使用量、收藏信号、显式偏好标签、历史作品信号。",
        175: "综合得分由基础热度与偏好匹配加权构成，并对使用量做平滑处理，避免极端热门模板压制个性化结果。",
        177: "",
        178: "该策略兼顾可解释性与工程可落地性，并为后续引入学习型排序模型预留空间。",
        183: "个性化构图推荐面向“实时取景”场景：系统生成多候选构图并结合用户偏好进行排序，在不打断取景交互的前提下输出最优的可视化参考框。",
        184: "端侧将基础交互与本地智能结合，通过轻量化部署实现离线实时反馈；必要时再与云端能力协同，平衡时延与效果。",
        185: "",
        188: "个性化适配通过用户交互行为持续更新偏好，使推荐结果随使用逐步贴合个人审美。",
        190: "",
        193: "从模板参考到实时取景推荐的升级，使用户在按下快门前即可获得更好的画面布局建议。",
        195: "经典构图识别与导学模块用于把“看起来更好”转化为“知道为什么更好”：识别当前画面可能符合的构图类型，并提供简短要点与示例，帮助用户边拍边学。",
        196: "模型侧采用轻量化分类网络识别常见构图规则；工程侧保证结果稳定输出并可在 UI 上直观呈现。",
        197: "",
        200: "通过“识别—提示—点击学习—再次取景”的闭环，用户可以在实践中逐步内化构图方法。",
        202: "多模态拍摄建议与姿势引导模块面向“场景语义理解”需求：在复杂场景与人物拍摄中给出 3–5 条可执行建议与姿势要点，提升可用性。",
        203: "模块采用端云解耦的推理架构，推理结果以严格结构化格式返回，便于前端稳定渲染并支持语音播报。",
        204: "",
        205: "语音播报减少移动拍摄时的注意力切换，使用户可边听边调整取景与动作。",
        210: "整体上，系统从几何层面的构图反馈扩展到语义层面的场景建议，实现了更贴近真实拍摄需求的智能辅助。",

        # 测试报告：去掉常识性“指标定义/标准背景”，保留结果与结论
        214: "选取两款代表性 Android 设备进行测试，并在一致网络环境下重复测量，统计平均值（设备信息见表 4-1）。",
        254: "",
        255: "",
        256: "",
        257: "",
        258: "",
        259: "",
        260: "",
        261: "测试结果表明：两款设备均可流畅完成取景、拍摄与核心智能功能；旗舰设备在时延上更优，中端设备满足可用性要求。",
        263: "从效率、安全、部署、可用性、扩展性五个维度进行评估，关键结论如下：",
        265: "核心功能在两类设备上表现稳定，满足日常拍摄使用的响应与流畅性要求。",
        268: "网络通信采用 HTTPS/TLS 等机制，避免明文传输与常见中间人风险。",
        269: "照片等数据采用应用私有目录与服务器侧权限控制进行保护，避免越权访问。",
        272: "安装包提供离线分发方式，用户按流程即可完成安装与首次授权。",
        275: "交互与系统相机一致，关键状态提供明确反馈，降低学习成本。",
        281: "接口采用标准化 REST/JSON 契约，模块边界清晰，便于后续替换服务或新增能力。",
        282: "",

        # 安装及使用：保留“环境要求+典型流程”，删除过细 UI 描述与下载细节
        286: "建议在 Android 10 及以上设备安装使用，确保相机与网络能力满足智能分析需要。",
        287: "操作系统：Android 10 及以上。",
        288: "硬件要求：具备后置摄像头的 Android 手机。",
        289: "网络要求：联网可使用云端建议/姿势能力。",
        290: "存储空间：建议预留 500MB 以上。",
        291: "权限要求：首次使用按提示授予相机与存储权限。",
        293: "获取安装包可通过二维码或网盘等方式；安装完成后首次启动按提示完成授权即可使用。",
        294: "",
        295: "",
        297: "",
        298: "",
        299: "",
        300: "",
        301: "安装步骤：下载 APK →（如需要）允许安装未知来源 → 安装并打开应用。",
        302: "",
        304: "",
        305: "",
        306: "",
        309: "首次使用会申请相机与存储权限，用于取景拍摄与保存图片；如误拒绝，可在系统设置的应用权限中重新开启。",
        310: "",
        311: "",
        314: "用户首次进入可注册并登录，用户名唯一；登录后可同步管理作品与偏好。",
        319: "典型流程：选择热门模板 → 查看示例与要点 → 进入拍摄取景 → 按提示调整姿势/构图 → 拍摄并保存。",
        320: "",
        325: "",
        327: "热门模板模块以“示例参考 + 跟拍要点”降低入门难度，帮助用户快速获得稳定成片。",
        329: "智能摄影模块在实时取景中提供构图参考与反馈，帮助用户在拍摄当下完成更优画面布局。",
        331: "拍摄时支持对焦、变焦、曝光等常用交互，保证与系统相机一致的操作手感。",
        333: "",
        335: "",
        336: "",
        338: "当用户需要更进一步的指导，可使用“拍摄建议/姿势引导”，系统给出少量可执行要点，并支持语音播报，便于边听边调整。",
        339: "整体流程保持界面简洁，确保提示信息不遮挡取景主体。",
        342: "“我的”模块用于管理草稿、作品与收藏模板，并支持基础的个人信息维护（头像/昵称/密码等）。",
        345: "",
        348: "",

        # 项目总结：压缩到 1 页内的要点
        350: "《一拍即合》面向大众摄影的高废片率问题，将构图知识与智能推荐前置到取景阶段，提供模板参考、实时构图反馈与场景化指导，提升成片率并降低学习门槛。",
        355: "确立端云协同架构：端侧保障取景交互与部分实时分析，服务端负责业务与数据，GPU 主机侧提供多模态推理能力，整体保持模块解耦与可维护。",
        357: "功能按“入门—进阶—高阶”逐步迭代：模板跟拍 → 实时构图 → 构图导学 → 场景建议/姿势引导，并配合语音播报提升移动拍摄可用性。",
        359: "数据库围绕用户、素材、偏好、收藏与使用记录等核心对象建模，为推荐与作品管理提供稳定数据支撑。",
        360: "多媒体资源采用文件系统存储并统一访问；敏感信息采用哈希等方式保护，兼顾性能与安全。",
        364: "研发中主要挑战在于端侧实时性能与多模态结果的工程化稳定输出。",
        365: "通过模型轻量化与端侧优化，确保取景阶段保持可用帧率与低延迟反馈。",
        366: "通过结构化输出约束与校验机制，避免结果格式漂移影响前端渲染稳定性。",
        368: "后续可在不破坏现有架构的前提下扩展更多拍摄场景（如短视频取景辅助）并持续提升个性化能力。",
        369: "商业化可采用基础能力免费、高阶分析/模板订阅增值的方式，先从内容创作者与摄影新手人群切入。",
    }

    apply_edits(doc_xml, edits)
    zip_dir_to_docx(work_dir, out_docx)

    print(f"Wrote: {out_docx}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
