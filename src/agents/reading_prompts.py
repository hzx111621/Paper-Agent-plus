"""保存用户提供的逐章精读和一图总结提示词，方便直接查看与修改。"""

PLANNING_PROMPT = '''请阅读全文全文，识别论文的主要章节结构，并只返回 JSON，不要输出解释文字。

返回格式必须是：
{"chapters": [{"id": "ch1", "title_zh": "引言", "title_en": "Introduction"}, {"id": "ch2", "title_zh": "第二章", "title_en": "Related Work 或 Method"}]}

要求：
1. 优先使用论文原文中的章节标题。
2. 如果论文标题不是中文，请给出简短中文译名和英文原名。
3. 至少返回两个章节；如果结构不清晰，就返回“引言”和“第二章”。
4. JSON 字段会直接用于逐章精读提示词模板：title_zh 对应 {{title_zh}}，title_en 对应 {{title_en}}，id 仅用于内部标识。'''

CHAPTER_PROMPT = '''请精读论文中的“{{title_zh}}（{{title_en}}）”这一章。

请围绕下面问题组织回答：
1. 这一章在全文中的作用是什么？
2. 这一章提出了哪些关键概念、论证或技术细节？
3. 哪些内容是读者理解后续章节必须掌握的？
4. 如果这一章有公式、实验设置或定义，请用通俗中文解释。

输出要求：
- 使用 Markdown。
- 不要寒暄，不要重复题目。
- 标题层级从三级标题开始，例如“### 本章作用”。
- 尽量让没有该小方向背景的读者也能看懂。'''

DEEP_QUESTIONS = [
    ("核心贡献判断", "请基于论文全文，用中文判断本文最核心的贡献是什么，并说明它为什么重要。输出 Markdown，标题层级从三级标题开始。"),
    ("局限与疑问", "请基于论文全文，用中文列出本文最值得注意的局限、风险或仍未解决的问题。输出 Markdown，标题层级从三级标题开始。"),
]

VISUAL_PROMPT = '''请阅读我提供的论文内容，提取用于生成"学术概念海报"的关键视觉信息。

请确保描述具体、形象，适合画面呈现。
请输出如下内容（只输出内容，不要废话），使用${language}：

1. 研究问题：提到的核心问题
2. 创新方法：论文提出的主要方法或技术，要找到Aha！的那个点。
3. 工作流程：从输入到输出的处理流程
4. 关键结果：主要实验发现或性能提升
5. 应用价值：该研究的实际意义

---

论文内容如下：
${context}'''

IMAGE_PROMPT = '''根据"${summaryForImage}"，生成一张学术论文概念图，清晰展示以下内容：

研究问题：提到的核心问题
创新方法：论文提出的主要方法或技术
工作流程：从输入到输出的处理流程
关键结果：主要实验发现或性能提升
应用价值：该研究的实际意义
论文标题：${title}
要求：
**设计要求 (Design Guidelines - STRICTLY FOLLOW):**

1. **艺术风格 (Style):**
   - Modern Minimalist Tech Infographic (现代极简科技信息图).
   - Flat vector illustration with subtle isometric elements (带有微妙等距元素的扁平矢量插画).
   - High-quality corporate Memphis design style (高质量企业级孟菲斯设计风格).
   - Clean lines, geometric shapes (线条干净，几何形状).
2. **构图 (Composition):**
   - **Layout:** Central composition or Left-to-Right Process Flow (居中构图或从左到右的流程).
   - **Background:** Clean, solid off-white or very light grey background (#F5F5F7). No clutter. (干净的米白或浅灰背景，无杂乱).
   - **Structure:** Organize elements logically like a presentation slide or a academic poster.
3. **配色方案 (Color Palette):**
   - Primary: Deep Academic Blue (深学术蓝) & Slate Grey (板岩灰).
   - Accent: Vibrant Orange or Teal for highlights (活力橙或青色用于高亮).
   - High contrast, professional color grading (高对比度，专业调色).
4. **文字渲染 (Text Rendering):**
   - Use Times New Roman font for English.
   - Use SimSun font for Chinese.
   - Main text language: ${language} (User defined language).
   - The title does not need to be reflected in the figure.
   - The text, especially Chinese, needs to be clear and free of garbled characters.
5. **负面提示 (Negative Prompt - Avoid these):**
   - No photorealism (不要照片写实风格).
   - No messy sketches (不要草图).
   - No blurry text (不要模糊文字).
   - No chaotic background (不要混乱背景).
     **Generation Instructions:**
     Generate an academic infographic poster.'''
