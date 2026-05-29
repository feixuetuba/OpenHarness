# Role & Goal
你是一个精通 TailwindCSS 和响应式布局的前端专家。请为我们的 OpenHarness Agent 管理控制台搭建核心的 UI 基础骨架。

# Tech Stack
- 框架: React (或 Vue3，根据你当前初始化的项目决定)
- 样式: TailwindCSS
- 图标: Lucide-react (或其他常用图标库)

# Layout Architecture (物理空间布局)
请实现一个全屏（100vh）、无法纵向硬溢出的标准三段式混合布局：

1. 🌐 顶部状态栏 (TopBar): 
   - 高度固定 (h-14)，背景色为深灰/白色，带有一条细边框。
   - 包含：系统 Logo、当前 Agent 实例名称、Harness 状态指示灯（在线/离线）。
   - 右侧包含一个“一键热重载 (Hot Reload)”按钮。

2. 👁️ 一级主导航栏 (Left SideBar - Icons Only):
   - 宽度固定 (w-16)，垂直排列。
   - 包含两个核心大图标：【⚙️ 管理面】和【💬 运行面/聊天】。点击可切换二级菜单的内容。

3. 🛠️ 二级内容导航栏 (Sub-SideBar):
   - 宽度固定 (w-64)，带有关闭/展开动画。
   - 当一级导航为【⚙️ 管理面】时：显示纵向列表（OpenHarness 基础设置、Skill 技能、Memory 记忆、Social 社交平台）。
   - 当一级导航为【💬 运行面】时：显示历史会话列表（Chat List），每个会话项包含头像、简短摘要和时间。

4. 🖥️ 右侧主工作区 (Main Workspace):
   - 占据剩余的所有屏幕空间 (`flex-1 h-full overflow-hidden`)。
   - 需要准备两个 Tab 视图供切换测试：
     - 【视图 A：管理表单】：内部包含若干个 Card 卡片（模拟 Skill 列表）。
     - 【视图 B：双栏聊天】：左侧 70% 为聊天对话流与底部固定输入框，右侧 30% 为固定宽度的 "Harness Trace 运行日志面板"。

# Visual Defense Rules (死命令：防止按钮和组件堆叠碎裂)
在编写 HTML/CSS 时，必须无条件遵守以下防御规则：
- 【防止硬挤压】：所有按钮组（如：卡片内的“编辑/删除/启用”按钮）、标签组，必须包裹在 `flex flex-wrap gap-2 items-center` 中。严禁使用不带 wrap 的横向硬撑，确保在小分辨率下按钮能自动折行。
- 【防止文字撑爆】：所有会话摘要、Skill 名称、长标签，必须加上 `truncate block` 类，超出部分自动变省略号（...），禁止撑开父容器。
- 【滚动防御】：主工作区、历史列表、日志面板，必须单独设置 `overflow-y-auto`，绝对不允许整个大网页出现全局双滚动条。
- 【间距规范】：卡片内部一律使用 `space-y-3` 或 `space-y-4` 进行纵向撑开，表单项一律使用 `flex flex-col gap-1`（Label 在上，Input 在下），严禁使用高风险的横向同行排列。

请立刻生成这个核心布局的主组件代码（如 Layout.tsx ），并确保界面看起来具有现代科技感、留白极简、边界清晰。
