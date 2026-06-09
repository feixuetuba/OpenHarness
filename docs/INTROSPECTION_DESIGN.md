# OpenHarness 自省系统设计文档

## 1. 概述

### 1.1 目标

为 OpenHarness 添加自省（Introspection）能力，使 Agent 能够：
- **反思**：在会话结束后自动分析任务执行质量
- **学习**：记录成功模式和失败教训，形成可复用的经验库
- **进化**：基于历史经验优化后续决策行为
- **评估**：量化 Agent 性能指标，支持持续改进

### 1.2 预期效果

| 维度 | 预期结果 |
|------|----------|
| **错误率降低** | 通过记录失败模式，避免重复错误，预期降低 30%+ |
| **效率提升** | 复用成功模式，减少探索性试错，预期提升 20%+ |
| **可观测性** | 提供结构化反思报告，便于用户了解 Agent 行为 |
| **自适应能力** | 基于经验自动调整工具使用策略和参数 |

---

## 2. 设计思想

### 2.1 核心原则

#### 2.1.1 非侵入性设计
- 自省系统作为**独立模块**运行，不修改核心查询引擎逻辑
- 通过 **Hook 机制**集成，确保可插拔、可禁用
- 自省过程**不阻塞**主对话流程

#### 2.1.2 数据驱动
- 反思报告以**结构化 JSON** 记录，便于查询和分析
- 可复用经验优先写入现有 durable memory，避免维护第二套长期记忆系统
- 使用**使用频率索引**（已有 `usage_index.json`）追踪经验有效性
- 支持**经验衰减**：长期未使用的经验自动降低权重

#### 2.1.3 渐进式学习
- 初期：仅记录经验，不自动应用
- 中期：在提示词中注入相关经验作为参考
- 后期：基于经验自动调整行为参数

#### 2.1.4 可观测性优先
- 自省系统必须提供结构化日志，便于定位“是否触发、读了哪些会话、为什么跳过、写入了哪些经验”
- 日志使用 Python 标准 `logging`，logger 命名建议为 `openharness.introspection.*`
- 默认记录 INFO 级别的生命周期事件，DEBUG 级别记录检索评分、过滤原因、LLM 原始摘要截断预览
- 不在日志中输出完整用户消息、密钥、附件正文或未脱敏的机器人 sender 标识
- 每次反思生成稳定的 `reflection_id` / `source_id` / `session_id`，贯穿日志、反思报告和写入的 memory，便于串联排查
- 自省结果和可展示的思考过程必须能被 web_config 读取和展示；这里的“思考过程”指反思模型显式输出的决策轨迹、证据摘要、跳过原因和经验生成理由，不要求也不依赖供应商隐藏 chain-of-thought

#### 2.1.5 OpenHarness 原生运行
- 自省能力必须作为 OpenHarness 核心能力运行，不依赖 `ohmo` 包或 `ohmo` 入口
- 后台反思任务优先复用 OpenHarness 的 `QueryEngine`、session snapshot、memory、hook、task manager 等基础设施
- 如需被 ohmo 或其他外壳调用，只通过 OpenHarness 的公共 API / CLI / service 函数集成，避免反向依赖

#### 2.1.6 多来源学习
- 自省系统不只从交互式 CLI/UI 会话学习，也要支持机器人聊天、定时任务、远程触发和后台任务
- 不同来源统一归一化为 `IntrospectionSource`，再进入同一套分析、过滤、写入流程
- 来源适配器负责脱敏、权限检查和上下文裁剪，自省引擎只处理已授权的结构化输入

### 2.2 架构分层

```
┌─────────────────────────────────────────────────────────┐
│                    应用层 (Application)                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
│  │ 会话反思     │  │ 经验检索     │  │ 行为调整     │   │
│  └──────────────┘  └──────────────┘  └──────────────┘   │
├─────────────────────────────────────────────────────────┤
│                    引擎层 (Engine)                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
│  │ 分析器       │  │ 经验存储     │  │ 提示词生成   │   │
│  │ (Analyzer)   │  │ (Store)      │  │ (Prompts)    │   │
│  └──────────────┘  └──────────────┘  └──────────────┘   │
├─────────────────────────────────────────────────────────┤
│                    集成层 (Integration)                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
│  │ Hook 触发器  │  │ 事件总线     │  │ 配置管理     │   │
│  └──────────────┘  └──────────────┘  └──────────────┘   │
├─────────────────────────────────────────────────────────┤
│                    存储层 (Storage)                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
│  │ memory       │  │ usage_index  │  │ reflections  │   │
│  │ .md          │  │ .json        │  │ .jsonl       │   │
│  └──────────────┘  └──────────────┘  └──────────────┘   │
└─────────────────────────────────────────────────────────┘
```

---

## 3. 实现原理

### 3.1 模块结构

```
src/openharness/introspection/
├── __init__.py              # 模块入口
├── engine.py                # 自省引擎主逻辑
├── analyzer.py              # 会话质量分析器
├── sources.py               # 学习来源归一化
├── experience_store.py      # 经验存储与检索（v1 可代理到 memory 系统）
├── prompts.py               # 自省提示词模板
├── types.py                 # 数据类型定义
├── logging.py               # 结构化日志与脱敏辅助
├── web.py                   # web_config 可读的日志查询/格式化辅助
└── config.py                # 配置管理
```

> 建议实现方式：v1 不单独维护第二套长期经验库，而是把高置信度经验写入现有 `src/openharness/memory/` durable memory，使用 `category: introspection` 或 tags 标记来源；`usage_index.json` 继续负责经验被注入后的使用统计。

### 3.2 核心流程

#### 3.2.1 会话反思流程

```
会话结束 (SESSION_END Hook)
        │
        ▼
┌──────────────────┐
│ 收集会话数据     │
│ - 消息历史       │
│ - 工具调用记录   │
│ - 错误信息       │
│ - 使用量统计     │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ 分析会话质量     │
│ - 任务完成度     │
│ - 工具效率       │
│ - 错误模式       │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ 生成反思报告     │
│ (LLM 调用)       │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ 存储经验         │
│ - memory         │
│ - usage_index    │
│ - reflections    │
└──────────────────┘
```

#### 3.2.2 经验检索流程

```
收到新用户任务 / 构建系统提示词
        │
        ▼
┌──────────────────┐
│ 提取任务特征     │
│ - 任务类型       │
│ - 工具需求       │
│ - 上下文关键词   │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ 检索相关经验     │
│ - 相似度匹配     │
│ - 使用频率排序   │
│ - 时效性过滤     │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ 注入系统提示词   │
│ (Top-K 经验)     │
└──────────────────┘
```

说明：`SESSION_START` 发生时通常还没有用户任务文本，不适合作为唯一检索点。推荐在构建 runtime system prompt 时，基于 `latest_user_prompt` 复用现有 relevant memory 检索路径注入经验。

#### 3.2.3 多来源学习流程

```
CLI/UI 会话 ─┐
机器人聊天 ─┼─► Source Adapter ─► IntrospectionSource ─► Analyzer ─► Reflection ─► Memory
定时任务   ─┤
远程触发   ─┘
```

| 来源 | 采集入口 | 学习重点 | 注意事项 |
|------|----------|----------|----------|
| CLI/UI 会话 | session snapshot、`SESSION_END`、`POST_TOOL_USE` | 工具效率、任务完成度、用户反馈 | 保留现有主流程非阻塞 |
| QQ/微信/飞书等机器人聊天 | channel runtime 的消息/session 记录 | 用户偏好、平台特定交互模式、常见失败回复 | sender/group/channel 标识必须脱敏或哈希化 |
| 定时任务 | cron job 执行记录、task manager 结果、`remote_trigger` 结果 | 周期任务失败模式、重试策略、运行时环境差异 | 记录 job id、schedule、exit/error 摘要，避免写入完整敏感输出 |
| 后台/子任务 | task manager、subagent stop 事件 | 委派效果、子任务失败原因 | 避免把 worker 临时噪声沉淀为长期经验 |

### 3.3 数据类型设计

#### 3.3.1 学习来源 (IntrospectionSource)

```python
@dataclass
class IntrospectionSource:
    """归一化后的自省输入来源"""
    id: str
    kind: Literal["interactive", "bot_chat", "cron", "remote_trigger", "subtask"]
    timestamp: str
    cwd: str
    session_id: str | None = None
    channel: str | None = None          # qq / wechat / feishu / cli / web / etc.
    actor_hash: str | None = None       # 脱敏后的用户或群标识
    task_id: str | None = None
    messages: list[dict] = field(default_factory=list)
    tool_events: list[dict] = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
```

#### 3.3.2 经验记录 (ExperienceRecord)

```python
@dataclass
class ExperienceRecord:
    """经验记录基类"""
    id: str                          # 唯一标识
    task_type: str                   # 任务类型 (code_review, bug_fix, etc.)
    timestamp: str                   # ISO 8601 时间戳
    context: dict                    # 上下文信息
    source_kind: Literal["interactive", "bot_chat", "cron", "remote_trigger", "subtask"]
    outcome: Literal["success", "partial", "failure", "abandoned", "unknown"]
    metrics: dict                    # 量化指标
    lessons: list[str]               # 经验教训
    tools_used: list[str]            # 使用的工具
    evidence: list[str]               # 判断依据，如 tests_passed/tool_error/user_feedback
    confidence: float = 1.0          # 置信度 (0-1)
    use_count: int = 0               # 被引用次数
    last_used: str | None = None     # 最后使用时间
```

#### 3.3.3 反思报告 (ReflectionReport)

```python
@dataclass
class ReflectionReport:
    """会话反思报告"""
    session_id: str
    duration_seconds: float
    task_summary: str
    outcome: Literal["success", "partial", "failure", "abandoned", "unknown"]
    source_kind: str
    tools_efficiency: dict[str, float]  # 工具 -> 效率评分
    errors: list[dict]                  # 错误列表
    patterns_identified: list[str]      # 识别的模式
    recommendations: list[str]          # 改进建议
    metadata: dict
```

### 3.4 Hook 集成点

在 `src/openharness/hooks/events.py` 中添加：

```python
class HookEvent(str, Enum):
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    # ... 现有事件 ...
    
    # 新增自省相关事件
    POST_SESSION_REFLECT = "post_session_reflect"  # 会话反思完成
    EXPERIENCE_RETRIEVED = "experience_retrieved"  # 经验检索完成
```

触发时机：

| Hook 事件 | 触发位置 | 作用 |
|-----------|----------|------|
| `SESSION_END` | runtime 会话关闭 | 启动异步反思任务 |
| `POST_SESSION_REFLECT` | `engine.py` 反思完成 | 通知其他模块 |
| `USER_PROMPT_SUBMIT` | `query_engine.py` 收到用户任务 | 记录当前任务特征 |
| `POST_TOOL_USE` | `query.py` 工具完成后 | 记录工具结果摘要 |
| `SESSION_START` | runtime 会话开始 | 初始化自省上下文，不作为唯一检索点 |

机器人和定时任务不应依赖 `query.py` 专属事件；它们通过 source adapter 将 channel session、cron result 或 task record 转成 `IntrospectionSource`。

### 3.5 经验存储格式

#### durable memory（推荐 v1）

```markdown
---
schema_version: 1
id: mem-20260608-103000-abcd1234
type: feedback
scope: project
category: introspection
source: bot_chat
tags: [introspection, qq, image-generation]
importance: 2
created_at: 2026-06-08T10:30:00Z
---

在 QQ 群聊触发图片生成任务时，若用户只回复“继续”且上一轮包含生成图片路径，
应优先把上一轮图片作为上下文，而不是重新要求用户上传。
```

#### JSONL 反思日志（可选调试/审计）

```jsonl
{"id": "exp_20260608_001", "source_kind": "cron", "task_type": "maintenance", "timestamp": "2026-06-08T10:30:00Z", "context": {"job_id": "cron_abc", "schedule": "0 * * * *"}, "outcome": "partial", "metrics": {"duration_seconds": 120, "tool_calls": 5}, "lessons": ["定时任务失败后应记录 exit code 和最后 200 行输出摘要"], "tools_used": ["cron_list", "bash"], "evidence": ["tool_error"], "confidence": 0.75}
```

#### introspection_events.jsonl（web_config 展示日志）

每次自省运行额外写入面向 UI 的事件流日志，建议路径为 `~/.openharness/data/introspection/events.jsonl`，或通过配置覆盖到项目本地 `.openharness/introspection/events.jsonl`。

```jsonl
{"timestamp":"2026-06-08T10:30:00Z","level":"INFO","event":"reflection_started","reflection_id":"refl_abc","source_id":"cron_abc","source_kind":"cron","summary":"开始分析定时任务 cron_abc 的最近一次失败"}
{"timestamp":"2026-06-08T10:30:03Z","level":"INFO","event":"reflection_reasoning","reflection_id":"refl_abc","step":"evidence_review","display_text":"任务退出码为 1，最后输出显示模型连接超时；未发现用户取消信号，因此标记为 partial/failure 候选。"}
{"timestamp":"2026-06-08T10:30:05Z","level":"INFO","event":"experience_candidate","reflection_id":"refl_abc","confidence":0.75,"display_text":"候选经验：定时任务失败后应保留 exit code 和最后输出摘要。"}
{"timestamp":"2026-06-08T10:30:06Z","level":"INFO","event":"memory_written","reflection_id":"refl_abc","memory_id":"mem-20260608-103006-abcd1234","summary":"写入 1 条 introspection memory"}
```

字段约定：

| 字段 | 说明 |
|------|------|
| `timestamp` | ISO 8601 UTC 时间 |
| `level` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `event` | 稳定事件名，供 web_config 过滤 |
| `reflection_id` | 一次反思运行的关联 ID |
| `source_id` / `source_kind` | 来源关联信息 |
| `display_text` | 可展示的脱敏文字，用于显示自省思考过程 |
| `summary` | 简短摘要 |
| `memory_id` | 写入 durable memory 后的 ID |
| `metadata` | 可选结构化调试字段，不含敏感正文 |

### 3.6 web_config 展示集成

web_config 应提供一个“自省日志”视图，用户可以按来源、会话、定时任务、机器人通道、反思 ID、日志级别过滤查看：

- 最近自省运行列表：状态、来源、开始/结束时间、写入 memory 数、跳过原因
- 单次反思详情：证据摘要、可展示思考过程、候选经验、最终写入结果
- 关联跳转：跳到 session、task、cron job、bot chat 或 memory entry
- 安全展示：默认只展示脱敏后的 `display_text` / `summary`，DEBUG 原始预览需要显式开启

建议 API：

| API | 作用 |
|-----|------|
| `GET /api/introspection/events?limit=200&source_kind=cron&reflection_id=...` | 查询 UI 安全事件日志 |
| `GET /api/introspection/reflections` | 列出反思运行摘要 |
| `GET /api/introspection/reflections/{reflection_id}` | 查看单次反思详情 |
| `GET /api/introspection/memories` | 列出由自省写入的 durable memory |

实现上，web_config 不直接解析普通文本日志，而是读取 `introspection_events.jsonl` 的结构化事件。这样页面可以稳定渲染，也能避免把普通 debug 日志里的敏感内容误展示。

#### reflections/{timestamp}.json

```json
{
  "session_id": "sess_abc123",
  "duration_seconds": 300.5,
  "task_summary": "修复用户登录超时问题",
  "outcome": "success",
  "source_kind": "interactive",
  "tools_efficiency": {"read_file": 0.9, "grep": 0.8, "edit": 0.95},
  "errors": [{"type": "timeout", "message": "API call timeout", "resolved": true}],
  "patterns_identified": ["超时问题通常由连接池配置引起"],
  "recommendations": ["检查连接池大小配置"],
  "metadata": {"model": "gpt-4", "total_tokens": 15000}
}
```

---

## 4. 关键实现细节

### 4.1 会话分析器 (Analyzer)

```python
class SessionAnalyzer:
    """分析会话质量，提取关键指标"""
    
    def analyze(self, session_data: SessionData) -> AnalysisResult:
        # 1. 计算任务完成度
        completion = self._calculate_completion(session_data)
        
        # 2. 评估工具使用效率
        tool_efficiency = self._evaluate_tools(session_data)
        
        # 3. 识别错误模式
        error_patterns = self._identify_errors(session_data)
        
        # 4. 提取成功/失败模式
        patterns = self._extract_patterns(session_data)
        
        return AnalysisResult(
            completion=completion,
            tool_efficiency=tool_efficiency,
            error_patterns=error_patterns,
            patterns=patterns
        )
```

### 4.2 LLM 驱动的反思

```python
async def generate_reflection(
    analysis: AnalysisResult,
    session_summary: str,
    model: str
) -> ReflectionReport:
    """使用 LLM 生成深度反思报告"""
    
    prompt = REFLECTION_PROMPT.format(
        session_summary=session_summary,
        analysis=json.dumps(analysis.to_dict(), indent=2)
    )
    
    response = await call_llm(prompt, model=model)
    return ReflectionReport.model_validate_json(response)
```

### 4.3 经验检索算法

```python
class ExperienceRetriever:
    """检索与当前任务相关的历史经验"""
    
    def retrieve(
        self,
        query: ExperienceQuery,
        top_k: int = 5,
        min_confidence: float = 0.7
    ) -> list[ExperienceRecord]:
        # 1. 按任务类型过滤
        candidates = self._filter_by_type(query.task_type)
        
        # 2. 计算相似度得分
        scored = [
            (record, self._similarity_score(record, query))
            for record in candidates
        ]
        
        # 3. 应用使用频率加权
        scored = [
            (record, score * self._recency_weight(record))
            for record, score in scored
        ]
        
        # 4. 排序并返回 Top-K
        scored.sort(key=lambda x: x[1], reverse=True)
        return [r for r, _ in scored[:top_k] if r.confidence >= min_confidence]
```

### 4.4 经验注入提示词

```python
def inject_experiences(
    system_prompt: str,
    experiences: list[ExperienceRecord]
) -> str:
    """将相关经验注入系统提示词"""
    
    if not experiences:
        return system_prompt
    
    experience_context = "\n\n## 历史经验参考\n"
    for exp in experiences:
        experience_context += f"\n### {exp.task_type} ({exp.outcome})\n"
        for lesson in exp.lessons:
            experience_context += f"- {lesson}\n"
    
    return system_prompt + experience_context
```

---

## 5. 配置管理

### 5.1 配置项

在 `settings.json` 中添加：

```json
{
  "introspection": {
    "enabled": false,
    "auto_reflect": false,
    "max_experiences": 1000,
    "experience_ttl_days": 90,
    "min_confidence_threshold": 0.7,
    "top_k_experiences": 5,
    "reflection_model": "",
    "async_reflection": true,
    "store_backend": "memory",
    "sources": {
      "interactive": true,
      "bot_chat": true,
      "cron": true,
      "remote_trigger": true,
      "subtask": false
    },
    "log_level": "INFO",
    "web_logs_enabled": true,
    "web_log_retention_days": 30,
    "web_log_debug_preview": false
  }
}
```

### 5.2 配置说明

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `enabled` | `false` | 是否启用自省系统，v1 建议默认关闭、用户显式开启 |
| `auto_reflect` | `false` | 会话结束是否自动反思，v1 建议默认关闭以控制成本和隐私风险 |
| `max_experiences` | 1000 | 最大经验存储数量 |
| `experience_ttl_days` | 90 | 经验有效期（天） |
| `min_confidence_threshold` | 0.7 | 最小置信度阈值 |
| `top_k_experiences` | 5 | 每次检索的经验数量 |
| `reflection_model` | `""` | 反思使用的模型；为空时复用当前 OpenHarness 模型配置 |
| `async_reflection` | `true` | 是否异步执行反思 |
| `store_backend` | `memory` | 经验写入后端，v1 推荐复用 durable memory |
| `sources` | 见上方 | 控制 CLI/UI、机器人聊天、定时任务等学习来源 |
| `log_level` | `INFO` | 自省模块日志级别 |
| `web_logs_enabled` | `true` | 是否写入 web_config 可展示的结构化自省事件 |
| `web_log_retention_days` | `30` | web 展示日志保留天数 |
| `web_log_debug_preview` | `false` | 是否允许 web_config 展示 DEBUG 级别的截断调试预览 |

---

## 6. 测试方法

### 6.1 单元测试

#### 6.1.1 分析器测试

```python
# tests/test_introspection/test_analyzer.py

def test_analyze_successful_session():
    """测试成功会话分析"""
    analyzer = SessionAnalyzer()
    session = create_mock_session(
        messages=[...],
        tool_calls=[...],
        errors=[]
    )
    
    result = analyzer.analyze(session)
    
    assert result.completion == 1.0
    assert len(result.error_patterns) == 0
    assert all(score > 0.8 for score in result.tool_efficiency.values())


def test_analyze_failed_session():
    """测试失败会话分析"""
    analyzer = SessionAnalyzer()
    session = create_mock_session(
        messages=[...],
        tool_calls=[...],
        errors=[{"type": "timeout", "message": "..."}]
    )
    
    result = analyzer.analyze(session)
    
    assert result.completion < 0.5
    assert len(result.error_patterns) > 0
```

#### 6.1.2 经验存储测试

```python
# tests/test_introspection/test_experience_store.py

def test_store_and_retrieve_experience():
    """测试经验存储和检索"""
    store = ExperienceStore(temp_dir())
    
    exp = ExperienceRecord(
        id="test_001",
        task_type="bug_fix",
        timestamp=utc_now(),
        context={"language": "python"},
        outcome="success",
        metrics={"time_seconds": 60},
        lessons=["检查输入参数"],
        tools_used=["read_file", "edit"]
    )
    
    store.save(exp)
    retrieved = store.retrieve_by_id("test_001")
    
    assert retrieved.id == exp.id
    assert retrieved.lessons == exp.lessons


def test_experience_retrieval_ranking():
    """测试经验检索排序"""
    store = ExperienceStore(temp_dir())
    
    # 存储多条经验
    store.save_many([
        create_exp("bug_fix", "success", use_count=10),
        create_exp("bug_fix", "success", use_count=5),
        create_exp("code_review", "success", use_count=20),
    ])
    
    results = store.retrieve(
        ExperienceQuery(task_type="bug_fix"),
        top_k=2
    )
    
    assert len(results) == 2
    assert results[0].use_count >= results[1].use_count
```

#### 6.1.3 提示词注入测试

```python
def test_inject_experiences_to_prompt():
    """测试经验注入提示词"""
    prompt = "You are a helpful assistant."
    experiences = [
        ExperienceRecord(
            id="exp_001",
            task_type="bug_fix",
            outcome="success",
            lessons=["Always check for None"],
            tools_used=["read_file"]
        )
    ]
    
    result = inject_experiences(prompt, experiences)
    
    assert "历史经验参考" in result
    assert "Always check for None" in result
    assert result.startswith(prompt)
```

### 6.2 集成测试

```python
# tests/test_introspection/test_integration.py

@pytest.mark.asyncio
async def test_full_reflection_cycle():
    """测试完整反思周期"""
    # 1. 创建模拟会话
    session = create_mock_session(...)
    
    # 2. 触发 SESSION_END Hook
    await hook_executor.execute(HookEvent.SESSION_END, session_data=session)
    
    # 3. 等待异步反思完成
    reflection = await wait_for_reflection(session.id)
    
    # 4. 验证反思报告
    assert reflection.session_id == session.id
    assert len(reflection.recommendations) > 0
    
    # 5. 验证经验已存储
    store = ExperienceStore.get_default()
    experiences = store.retrieve_by_session(session.id)
    assert len(experiences) > 0


@pytest.mark.asyncio
async def test_experience_injection_when_building_prompt():
    """测试基于用户任务构建提示词时注入经验"""
    # 1. 存储历史经验
    store = ExperienceStore.get_default()
    store.save(create_exp("bug_fix", "success"))
    
    # 2. 基于当前用户任务构建系统提示词
    prompt = build_runtime_prompt(
        latest_user_prompt="修复 Python NoneType bug",
        include_project_memory=True,
    )
    
    # 3. 验证系统提示词包含相关经验
    assert "历史经验参考" in prompt or "Relevant Memories" in prompt
```

### 6.3 端到端测试

```python
# tests/test_introspection/test_e2e.py

def test_e2e_introspection_workflow():
    """端到端测试自省工作流"""
    with TemporaryOpenHarness() as harness:
        # 1. 执行一个已知会失败的任务
        result = harness.run_query("修复这个 bug: ...")
        assert not result.success
        
        # 2. 验证反思已生成
        reflections = harness.list_reflections()
        assert len(reflections) == 1
        
        # 3. 验证经验已写入 durable memory，并带有 introspection 标记
        memories = harness.list_memories(category="introspection")
        assert len(memories) == 1
        
        # 4. 再次执行类似任务
        result2 = harness.run_query("修复类似的 bug: ...")
        
        # 5. 验证经验被检索并使用
        assert "历史经验参考" in result2.system_prompt
        # 理想情况下，第二次应该更成功或更高效
```

```python
def test_bot_chat_source_is_sanitized_before_reflection():
    """测试机器人聊天来源会脱敏后再进入反思"""
    source = build_bot_chat_source(
        channel="qq",
        sender_id="123456",
        group_id="654321",
        messages=[{"role": "user", "text": "以后图片发群文件"}],
    )

    assert source.kind == "bot_chat"
    assert source.actor_hash
    assert "123456" not in json.dumps(source.__dict__)


def test_cron_source_records_job_metadata_without_full_output():
    """测试定时任务来源只记录必要摘要"""
    source = build_cron_source(
        job_id="cron_abc",
        schedule="0 * * * *",
        output="very long output..." * 1000,
        exit_code=1,
    )

    assert source.kind == "cron"
    assert source.metadata["job_id"] == "cron_abc"
    assert len(source.metadata["output_summary"]) < 4000
```

```python
def test_web_introspection_events_are_sanitized(tmp_path):
    """测试写给 web_config 的自省事件不包含敏感原文"""
    writer = IntrospectionEventWriter(tmp_path / "events.jsonl")

    writer.write_reasoning(
        reflection_id="refl_abc",
        source_id="qq_session_1",
        source_kind="bot_chat",
        display_text="根据脱敏后的聊天摘要，用户希望图片结果直接回传群文件。",
        metadata={"sender_hash": "hash_abc"},
    )

    text = (tmp_path / "events.jsonl").read_text(encoding="utf-8")
    assert "display_text" in text
    assert "sender_hash" in text
    assert "123456789" not in text


def test_web_introspection_api_filters_by_reflection_id(client):
    """测试 web_config 可以按 reflection_id 查询自省日志"""
    response = client.get("/api/introspection/events?reflection_id=refl_abc")

    assert response.status_code == 200
    events = response.json()["events"]
    assert all(event["reflection_id"] == "refl_abc" for event in events)
```

### 6.4 性能测试

```python
def test_experience_retrieval_performance():
    """测试经验检索性能"""
    store = ExperienceStore(temp_dir())
    
    # 存储大量经验
    for i in range(1000):
        store.save(create_exp(random_type(), random_outcome()))
    
    # 测量检索时间
    start = time.perf_counter()
    results = store.retrieve(ExperienceQuery(task_type="bug_fix"), top_k=5)
    elapsed = time.perf_counter() - start
    
    assert elapsed < 0.1  # 检索应在 100ms 内完成
    assert len(results) == 5
```

### 6.5 测试运行命令

```bash
# 运行所有自省测试
pytest tests/test_introspection/ -v

# 运行单元测试
pytest tests/test_introspection/test_analyzer.py -v
pytest tests/test_introspection/test_experience_store.py -v

# 运行集成测试
pytest tests/test_introspection/test_integration.py -v

# 运行端到端测试
pytest tests/test_introspection/test_e2e.py -v

# 生成覆盖率报告
pytest tests/test_introspection/ --cov=src/openharness/introspection --cov-report=html
```

---

## 7. 预期结果与度量

### 7.1 功能度量

| 指标 | 目标值 | 测量方法 |
|------|--------|----------|
| 反思生成成功率 | > 95% | 单元测试覆盖率 |
| 经验检索准确率 | > 80% | 人工评估 Top-5 相关性 |
| 经验注入延迟 | < 50ms | 性能测试 |
| 存储容量 | 1000+ 条经验 | 压力测试 |

### 7.2 效果度量

| 指标 | 基线 | 目标 | 测量周期 |
|------|------|------|----------|
| 重复错误率 | - | 降低 30% | 30 天 |
| 任务完成时间 | - | 缩短 20% | 30 天 |
| 工具调用次数 | - | 减少 15% | 30 天 |
| 用户满意度 | - | 提升 25% | 问卷调查 |

### 7.3 可观测性

自省系统提供以下可观测数据：

```
~/.openharness/data/experience/
├── stats.json              # 统计信息
│   {
│     "total_experiences": 150,
│     "success_rate": 0.73,
│     "avg_confidence": 0.85,
│     "most_common_task_types": ["bug_fix", "code_review"],
│     "last_reflection": "2026-06-08T15:30:00Z"
│   }
└── metrics/
    └── daily.jsonl         # 每日指标
        {"date": "2026-06-08", "sessions": 10, "reflections": 8, "experiences_stored": 15}
```

---

## 8. 风险与缓解

### 8.1 风险矩阵

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| LLM 反思成本高 | 高 | 中 | 使用低成本模型 (gpt-4o-mini)，异步执行 |
| 经验质量不可控 | 中 | 中 | 置信度阈值过滤，用户反馈机制 |
| 存储膨胀 | 低 | 高 | TTL 过期清理，最大数量限制 |
| 错误经验传播 | 高 | 低 | 负面模式标记，人工审核选项 |

### 8.2 降级策略

- **LLM 不可用**: 跳过反思，仅记录原始指标
- **存储不可用**: 内存缓存，定期刷新
- **性能下降**: 禁用经验注入，回退到基础模式

---

## 9. 未来扩展

### 9.1 短期 (v1)
- [x] 基础自省引擎
- [x] 经验存储与检索
- [x] Hook 集成
- [ ] CLI 命令查看经验 (`openharness experience list`)

### 9.2 中期 (v2)
- [ ] 经验相似度向量检索 (embedding)
- [ ] 自动行为调整
- [ ] 用户反馈循环 (thumbs up/down)
- [ ] 经验分享 (团队间同步)

### 9.3 长期 (v3)
- [ ] 多 Agent 经验共享
- [ ] 自进化策略 (自动优化提示词)
- [ ] 可视化仪表盘
- [ ] 经验市场 (社区共享)

---

## 10. 参考

- [ARCHITECTURE.md](../docs/ARCHITECTURE.md) - 文件存储结构规范
- [SESSION_ARCHITECTURE.md](../docs/SESSION_ARCHITECTURE.md) - 会话架构
- `src/openharness/hooks/events.py` - Hook 事件定义
- `src/openharness/memory/` - 记忆系统实现
- `src/openharness/engine/query.py` - 查询引擎实现
