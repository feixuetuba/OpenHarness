# OpenHarness 文件存储结构规范

> 本文档定义了 OpenHarness 项目运行时的文件输出结构规范，为 Agent 人格化和自我进化功能提供基础架构支持。

## 1. 设计原则

### 1.1 核心原则

| 原则 | 说明 |
|------|------|
| **分层存储** | 用户级（全局）与项目级（本地）严格分离 |
| **类型隔离** | 不同类型的数据存放在独立目录 |
| **可扩展性** | 预留未来功能扩展空间 |
| **清晰命名** | 使用统一的命名规范（全小写，下划线分隔） |
| **原子性写入** | 关键配置文件必须原子写入，防止损坏 |

### 1.2 用户级 vs 项目级

| 维度 | 用户级 (`~/.openharness/`) | 项目级 (`{project}/.openharness/`) |
|------|---------------------------|-----------------------------------|
| **归属** | 用户专属 | 项目专属 |
| **迁移** | 跨项目共享，不随项目移动 | 随项目迁移和复制 |
| **清理** | 保留直到用户主动删除 | 删除项目时自动清理 |
| **版本控制** | 不纳入版本控制 | 可纳入版本控制（团队共享） |

---

## 2. 用户级目录结构

**基础路径**: `~/.openharness/` (可通过 `OPENHARNESS_CONFIG_DIR` 环境变量覆盖)

```
~/.openharness/
├── config/                          # 配置文件
│   ├── settings.json                # 全局设置
│   ├── cron_jobs.json              # 定时任务注册表
│   └── mcp_servers.json            # MCP服务器配置
│
├── data/                           # 持久化数据
│   ├── agents/                     # Agent定义与配置
│   │   ├── {agent_name}.yaml       # Agent配置文件
│   │   └── skills/                # 技能定义
│   │       └── {skill_name}.md
│   │
│   ├── memory/                    # 项目记忆（按项目hash隔离）
│   │   └── {project_name}-{hash}/
│   │       ├── MEMORY.md          # 主记忆文件
│   │       └── sections/          # 记忆分节
│   │
│   ├── sessions/                  # 会话快照
│   │   └── {session_id}/
│   │       └── snapshot.json
│   │
│   ├── tasks/                    # 后台任务输出
│   │   └── {task_id}/
│   │       ├── output.log
│   │       └── metadata.json
│   │
│   ├── experience/               # Agent经验库
│   │   └── {agent_name}/
│   │       ├── successes.jsonl   # 成功案例
│   │       ├── failures.jsonl    # 失败案例
│   │       └── reflections/      # 反思记录
│   │           └── {timestamp}.json
│   │
│   ├── evolution/                # Agent进化状态（新增）
│   │   └── {agent_name}/
│   │       ├── traits.json       # 人格特征
│   │       ├── skills.json       # 技能熟练度
│   │       └── preferences.json  # 行为偏好
│   │
│   └── feedback/                 # 用户反馈
│       └── feedback.log
│
├── cache/                        # 临时缓存（可清理）
│   ├── tool_artifacts/           # 工具输出产物
│   └── session_memory/           # 会话记忆缓存
│
└── logs/                         # 日志文件
    ├── app.log
    └── tasks/
        └── {task_id}.log
```

### 2.1 经验库格式 (experience/)

#### 成功案例 (successes.jsonl)

```jsonl
{"task_type": "code_review", "approach": "incremental_review", "metrics": {"time_saved": 30, "issues_found": 5}, "timestamp": "2024-01-15T10:30:00Z"}
{"task_type": "bug_fix", "approach": "binary_search", "metrics": {"time_elapsed": 120, "confidence": 0.95}, "timestamp": "2024-01-15T11:00:00Z"}
```

#### 失败案例 (failures.jsonl)

```jsonl
{"task_type": "refactoring", "error": "scope_creep", "context": "attempted_too_many_changes", "timestamp": "2024-01-15T09:00:00Z"}
```

#### 反思记录 (reflections/{timestamp}.json)

```json
{
  "task_summary": "Completed large refactoring task",
  "key_factors": ["broke_into_small_steps", "used_exploration_first"],
  "lessons_learned": ["verify_each_step_before_moving_on"],
  "suggested_improvements": ["increase_test_coverage"],
  "confidence_score": 0.85,
  "timestamp": "2024-01-15T12:00:00Z"
}
```

### 2.2 进化状态格式 (evolution/)

#### 人格特征 (traits.json)

```json
{
  "personality": "严谨细致，追求代码质量",
  "tone": "professional",
  "communication_style": "简洁明了，重点突出",
  "backstory": "10年经验的全栈工程师，擅长系统设计",
  "expertise_level": "expert",
  "decision_style": "analytical",
  "preferred_tools": ["git", "pytest", "black"],
  "created_at": "2024-01-01T00:00:00Z",
  "updated_at": "2024-01-15T10:30:00Z"
}
```

#### 技能熟练度 (skills.json)

```json
{
  "python": {
    "level": "expert",
    "experience": 150,
    "last_used": "2024-01-15T10:30:00Z"
  },
  "git": {
    "level": "expert",
    "experience": 200,
    "last_used": "2024-01-15T11:00:00Z"
  },
  "javascript": {
    "level": "intermediate",
    "experience": 50,
    "last_used": "2024-01-14T15:00:00Z"
  }
}
```

---

## 3. 项目级目录结构

**基础路径**: `{project}/.openharness/` (可通过 `OPENHARNESS_PROJECT_DIR` 环境变量覆盖)

```
{project}/.openharness/
├── config/                       # 项目级配置
│   ├── settings.json             # 项目特定设置（覆盖全局）
│   ├── autopilot_policy.yaml    # 自动驾驶策略
│   ├── verification_policy.yaml  # 验证策略
│   └── release_policy.yaml       # 发布策略
│
├── memory/                       # 项目本地记忆
│   ├── issue.md                # Issue上下文
│   ├── pr_comments.md          # PR评论上下文
│   └── agents/                 # Agent本地记忆
│       └── {agent_name}/
│           └── MEMORY.md       # Agent在项目中的特定知识
│
├── state/                       # 运行时状态
│   ├── repo_journal.jsonl      # 仓库操作日志
│   ├── active_repo_context.md  # 合成的活跃上下文
│   └── autopilot/
│       ├── registry.json       # 任务注册表
│       └── runs/               # 运行记录
│           └── {run_id}/
│               └── ...
│
└── snapshots/                   # 快照备份
    └── agents/                 # Agent记忆快照
        └── {agent_name}/
            └── MEMORY.md       # 定期备份的记忆
```

### 3.1 自动运行策略格式 (config/autopilot_policy.yaml)

```yaml
name: "my-project-autopilot"
version: "1.0"
rules:
  - id: "require_tests"
    condition: "file_contains:*.py"
    action: "check:test_exists"
  - id: "security_review"
    condition: "file_matches:**/auth*.py"
    action: "require_approval"
```

---

## 4. 数据分类与生命周期

| 数据类型 | 存储位置 | 生命周期 | 同步策略 | 可版本控制 |
|----------|----------|----------|----------|-----------|
| **全局配置** | `~/.openharness/config/` | 持久 | 不随项目迁移 | 否 |
| **Agent定义** | `~/.openharness/data/agents/` | 持久 | 全局共享 | 否 |
| **项目记忆** | `~/.openharness/data/memory/` | 持久 | 全局共享 | 否 |
| **经验库** | `~/.openharness/data/experience/` | 持久 | 全局共享 | 否 |
| **进化状态** | `~/.openharness/data/evolution/` | 持久 | 全局共享 | 否 |
| **会话缓存** | `~/.openharness/cache/` | 临时 | 可清理 | 否 |
| **项目配置** | `{project}/.openharness/config/` | 持久 | 随项目迁移 | 是 |
| **本地记忆** | `{project}/.openharness/memory/` | 持久 | 随项目迁移 | 是 |
| **运行状态** | `{project}/.openharness/state/` | 临时 | 随项目迁移 | 可选 |

---

## 5. 命名规范

### 5.1 目录命名

| 规范 | 示例 |
|------|------|
| 全小写 | `agent_memory`, `tool_artifacts` |
| 下划线分隔 | `session_memory`, `repo_journal` |
| 无复数形式 | `memory` (非 `memories`), `logs` (非 `log`) |

### 5.2 文件命名

| 类型 | 规范 | 示例 |
|------|------|------|
| 配置文件 | 小写，下划线，`.json`/`.yaml` | `settings.json`, `autopilot_policy.yaml` |
| 数据文件 | 小写，下划线，`.jsonl` | `successes.jsonl`, `failures.jsonl` |
| 记忆文件 | 固定为 `MEMORY.md` | `MEMORY.md` |
| 日志文件 | 小写，下划线，`.log` | `app.log`, `error.log` |
| 时间戳文件 | ISO 8601 | `2024-01-15T10-30-00.json` |

### 5.3 ID/标识符

| 类型 | 格式 | 示例 |
|------|------|------|
| Agent名称 | 小写字母、数字、下划线 | `researcher`, `tester_v2` |
| 项目标识 | `{name}-{sha1-hash[:12]}` | `my-project-a1b2c3d4e5f6` |
| 会话ID | UUID v4 | `550e8400-e29b-41d4-a716-446655440000` |
| 任务ID | UUID v4 | `660e8400-e29b-41d4-a716-446655440001` |

---

## 6. 路径函数接口

所有路径函数定义在 `openharness/config/paths.py` 中。

### 6.1 用户级路径函数

```python
# 经验库路径
def get_experience_dir() -> Path:
    """Return the agent experience directory: ~/.openharness/data/experience/"""

def get_agent_experience_dir(agent_name: str) -> Path:
    """Return the experience directory for a specific agent."""

def get_agent_successes_file(agent_name: str) -> Path:
    """Return the successes log file for an agent."""

def get_agent_failures_file(agent_name: str) -> Path:
    """Return the failures log file for an agent."""

def get_agent_reflections_dir(agent_name: str) -> Path:
    """Return the reflections directory for an agent."""

# 进化状态路径
def get_evolution_dir() -> Path:
    """Return the agent evolution directory: ~/.openharness/data/evolution/"""

def get_agent_evolution_dir(agent_name: str) -> Path:
    """Return the evolution directory for a specific agent."""

def get_agent_traits_file(agent_name: str) -> Path:
    """Return the traits file for an agent."""

def get_agent_skill_proficiency_file(agent_name: str) -> Path:
    """Return the skill proficiency file for an agent."""

def get_agent_preferences_file(agent_name: str) -> Path:
    """Return the preferences file for an agent."""

# 缓存路径
def get_cache_dir() -> Path:
    """Return the cache directory: ~/.openharness/cache/"""

def get_tool_artifacts_dir() -> Path:
    """Return the tool artifacts directory."""
```

### 6.2 项目级路径函数

```python
# Agent本地记忆
def get_project_agent_memory_dir(cwd: str | Path, agent_name: str) -> Path:
    """Return the project-local agent memory directory."""

def get_project_agent_memory_file(cwd: str | Path, agent_name: str) -> Path:
    """Return the project-local agent memory file."""
```

---

## 7. 环境变量覆盖

| 变量名 | 覆盖目标 | 默认值 |
|--------|----------|--------|
| `OPENHARNESS_CONFIG_DIR` | 整个用户级目录 | `~/.openharness/` |
| `OPENHARNESS_DATA_DIR` | 数据目录 | `~/.openharness/data/` |
| `OPENHARNESS_LOGS_DIR` | 日志目录 | `~/.openharness/logs/` |
| `OPENHARNESS_PROJECT_DIR` | 项目级目录 | `{project}/.openharness/` |

---

## 8. 向后兼容

### 8.1 现有路径迁移

| 旧路径 | 新路径 | 迁移策略 |
|--------|--------|----------|
| `~/.openharness/data/memory/` | `~/.openharness/data/memory/` | 保持不变 |
| `{project}/.openharness/agent-memory-snapshots/` | `{project}/.openharness/snapshots/agents/` | 软链接或迁移 |
| `{project}/.openharness/agent-memory-local/` | `{project}/.openharness/memory/agents/` | 软链接或迁移 |

### 8.2 迁移脚本

建议提供迁移脚本：
```bash
openharness migrate --from-v1 --to-v2
```

---

## 9. 附录

### 9.1 完整目录树

```
~/.openharness/
├── config/
│   ├── settings.json
│   ├── cron_jobs.json
│   └── mcp_servers.json
├── data/
│   ├── agents/
│   │   └── {agent_name}.yaml
│   ├── memory/
│   │   └── {project}-{hash}/
│   ├── sessions/
│   ├── tasks/
│   ├── experience/
│   │   └── {agent_name}/
│   ├── evolution/
│   │   └── {agent_name}/
│   └── feedback/
├── cache/
│   ├── tool_artifacts/
│   └── session_memory/
└── logs/

{project}/.openharness/
├── config/
│   ├── settings.json
│   ├── autopilot_policy.yaml
│   ├── verification_policy.yaml
│   └── release_policy.yaml
├── memory/
│   ├── issue.md
│   ├── pr_comments.md
│   └── agents/
│       └── {agent_name}/
├── state/
│   ├── repo_journal.jsonl
│   ├── active_repo_context.md
│   └── autopilot/
└── snapshots/
    └── agents/
        └── {agent_name}/
```

### 9.2 术语表

| 术语 | 定义 |
|------|------|
| 用户级数据 | 存储在 `~/.openharness/`，跨项目共享的数据 |
| 项目级数据 | 存储在 `{project}/.openharness/`，属于特定项目的数据 |
| 经验库 | Agent 执行任务后的成功/失败案例库 |
| 进化状态 | Agent 的人格特征、技能熟练度等动态属性 |
| 记忆快照 | Agent 记忆的定期备份，用于恢复或迁移 |
