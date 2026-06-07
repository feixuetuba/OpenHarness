# Agent 会话记录与上下文管理规范

> 本文档定义了 Agent 会话记录的存储结构、子 Agent 交互追踪机制，以及上下文压缩策略，为反思和自我进化提供数据基础。

---

## 1. 核心设计原则

### 1.1 会话记录架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        会话记录分层架构                                  │
└─────────────────────────────────────────────────────────────────────────┘

     第1层: 完整对话记录 (Full History)
           │
           ├── 原始消息序列
           ├── 工具调用记录
           └── 子Agent交互树

     第2层: 压缩上下文 (Compressed Context)
           │
           ├── 消息摘要
           │   └── 每条消息的简洁摘要
           └── 关键动作提取
               └── tool_use + result 的关键信息

     第3层: 任务级摘要 (Task Summary)
           │
           ├── 任务目标
           ├── 执行路径
           ├── 最终结果
           └── 关键决策点

     第4层: 经验库 (Experience)
           │
           ├── 成功案例
           ├── 失败案例
           └── 反思记录
```

### 1.2 关键设计目标

| 目标 | 说明 |
|------|------|
| **可追溯性** | 完整记录所有交互，支持问题追溯 |
| **可压缩性** | 支持多级摘要，避免上下文爆炸 |
| **可关联** | 子Agent交互可追溯到父会话 |
| **可分析** | 数据结构便于后续反思和学习 |

---

## 2. 会话记录结构

### 2.1 会话消息类型扩展

```python
from enum import Enum
from datetime import datetime
from typing import Any, Optional, List, Dict, Union
from pydantic import BaseModel, Field

class MessageRole(str, Enum):
    """消息角色"""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TEAMMATE = "teammate"      # 子Agent消息
    TEAMMATE_RESULT = "teammate_result"  # 子Agent执行结果

class MessageType(str, Enum):
    """消息类型"""
    TEXT = "text"
    TOOL_USE = "tool_use"
    TOOL_RESULT = "tool_result"
    TEAMMATE_SPAWN = "teammate_spawn"    # 子Agent启动
    TEAMMATE_MESSAGE = "teammate_message" # 子Agent消息
    TEAMMATE_RETURN = "teammate_return"  # 子Agent返回

class MessageContent(BaseModel):
    """消息内容块"""
    type: MessageType
    text: Optional[str] = None
    tool_name: Optional[str] = None
    tool_input: Optional[Dict[str, Any]] = None
    tool_result: Optional[str] = None
    tool_error: Optional[bool] = False
    teammate_id: Optional[str] = None  # 子Agent标识
    teammate_prompt: Optional[str] = None  # 子Agent初始prompt

class ConversationMessage(BaseModel):
    """单条消息记录"""
    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    role: MessageRole
    content: List[MessageContent]
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    parent_message_id: Optional[str] = None  # 父消息ID（用于回复链）
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    # 新增：消息级别摘要
    summary: Optional[str] = None  # 单条消息的摘要（用于压缩）
    key_points: List[str] = Field(default_factory=list)  # 关键点提取
    
    # 新增：子Agent追踪
    spawned_teammates: List[str] = Field(default_factory=list)  # 由此消息启动的子Agent
    is_teammate_message: bool = False  # 是否来自子Agent

class SessionRecord(BaseModel):
    """完整会话记录"""
    session_id: str
    project_id: str  # 项目标识
    agent_name: str  # 执行会话的Agent名称
    parent_session_id: Optional[str] = None  # 父会话（子Agent场景）
    root_session_id: Optional[str] = None  # 根会话（追踪整个会话树）
    
    messages: List[ConversationMessage] = Field(default_factory=list)
    
    # 会话元数据
    started_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    ended_at: Optional[str] = None
    status: str = "active"  # active, completed, failed, aborted
    
    # 执行统计
    tool_call_count: int = 0
    teammate_spawn_count: int = 0
    total_tokens: int = 0
    duration_seconds: float = 0.0
    
    # 会话级别摘要（自动生成）
    summary: Optional[str] = None
    task_objective: Optional[str] = None
    final_outcome: Optional[str] = None
    
    # 经验关联
    experience_tags: List[str] = Field(default_factory=list)
```

### 2.2 子Agent交互记录结构

```python
class TeammateInteraction(BaseModel):
    """子Agent交互记录"""
    teammate_id: str  # 格式: agent_name@team_name
    parent_session_id: str  # 父会话ID
    root_session_id: str  # 根会话ID
    spawned_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    prompt: str  # 发送给子Agent的初始指令
    status: str = "running"  # running, completed, failed
    
    # 子Agent的完整会话记录
    # 注意：这里不存储完整消息，而是存储引用
    child_session_id: Optional[str] = None
    
    # 执行结果
    result_summary: Optional[str] = None
    result_content: Optional[str] = None
    error_message: Optional[str] = None
    
    # 统计信息
    tool_call_count: int = 0
    total_tokens: int = 0
    duration_seconds: float = 0.0
    
class ConversationTree(BaseModel):
    """会话树结构（用于追踪父子关系）"""
    root_session_id: str
    sessions: List[str] = Field(default_factory=list)  # 所有相关会话ID
    edges: List[Dict[str, str]] = Field(default_factory=list)  # {from: parent_id, to: child_id}
    
    def add_session(self, session_id: str, parent_session_id: Optional[str]) -> None:
        """添加会话到树中"""
        if session_id not in self.sessions:
            self.sessions.append(session_id)
        if parent_session_id:
            self.edges.append({"from": parent_session_id, "to": session_id})
    
    def get_descendants(self, session_id: str) -> List[str]:
        """获取会话的所有子会话"""
        descendants = []
        stack = [session_id]
        while stack:
            current = stack.pop()
            for edge in self.edges:
                if edge["from"] == current:
                    child = edge["to"]
                    if child not in descendants:
                        descendants.append(child)
                        stack.append(child)
        return descendants
```

---

## 3. 三层分流存储架构

### 3.1 架构设计

为保障 **"大模型读得快（上下文轻量）"、"自我更新算得准（执行轨迹完整）"、"硬盘开销存得省（海量数据隔离）"**，采用三层分流存储架构：

```
                              ┌──────────────────────┐ 
                              │  用户/子Agent交互输入  │ 
                              └──────────┬───────────┘ 
                                         │ 
                                         ▼ 
                          [数据大小与类型拦截器] 
                                /     |     \ 
           小于阈值文本            /      |      \  超过阈值(如>2KB)的巨量数据 
           ───────────────-─────┘       │       └─────────────────────────────┐ 
           │                            │                                             │ 
           ▼                            ▼                                             ▼ 
 ┌──────────────────┐         ┌────────────────────┐                       ┌───────────────────┐ 
 │ 1. 关系型数据库层  │         │ 2. 图/链路追踪层   │                       │ 3. 对象/二进制层  │ 
 │  (SQLite / PG)   │         │ (Structured Trace) │                       │ (Local Blob File) │ 
 ├──────────────────┤         ├────────────────────┤                       ├───────────────────┤ 
 │ · 干净的消息对话流 │         │ · 工具调用/模型独白 │                       │ · 网页HTML/大JSON │ 
 │ · 长期核心事实记忆 │         │ · 子Agent树状嵌套   │                       │ · 媒体文件/审计日志│ 
 └──────────────────┘         └────────────────────┘                       └───────────────────┘
```

### 3.2 分层职责

| 层级 | 存储类型 | 数据特征 | 核心价值 | 访问频率 |
|------|----------|----------|----------|----------|
| **第1层** | 关系型数据库 | 结构化、小数据、干净文本 | LLM上下文轻量，读取快速 | **高** |
| **第2层** | 图/链路追踪 | 半结构化、中等数据、复杂关系 | 执行轨迹完整，支持深度分析 | **中** |
| **第3层** | 对象存储 | 非结构化、大数据、低访问频率 | 海量数据隔离，节省存储成本 | **低** |

### 3.3 数据分流规则

```python
class DataRouter:
    """数据分流路由器"""
    
    TEXT_THRESHOLD = 2048  # 2KB 阈值
    
    @classmethod
    def route(cls, data: Any, data_type: str) -> str:
        """根据数据特征决定存储位置"""
        
        # 1. 判断是否为大文件
        if cls._is_large_binary(data):
            return "object_store"
        
        # 2. 判断是否为工具调用或子Agent交互
        if data_type in ["tool_call", "tool_result", "teammate_spawn", "teammate_message"]:
            return "graph_store"
        
        # 3. 判断文本大小
        text_size = cls._get_text_size(data)
        if text_size > cls.TEXT_THRESHOLD:
            # 大文本：元数据存数据库，内容存对象存储
            return "hybrid"  # 混合存储
        
        # 4. 默认：干净的对话消息
        return "relational_db"
```

### 3.4 各层数据结构

#### 第1层：关系型数据库层

**表结构设计**

```sql
-- 会话表
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    parent_session_id TEXT,
    root_session_id TEXT,
    status TEXT DEFAULT 'active',
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMP,
    summary TEXT,
    task_objective TEXT,
    final_outcome TEXT,
    FOREIGN KEY(parent_session_id) REFERENCES sessions(id)
);

-- 消息表（干净的对话流）
CREATE TABLE messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,  -- user, assistant, system
    content TEXT NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    parent_message_id TEXT,
    FOREIGN KEY(session_id) REFERENCES sessions(id),
    FOREIGN KEY(parent_message_id) REFERENCES messages(id)
);

-- 事实记忆表
CREATE TABLE facts (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    content TEXT NOT NULL,
    embedding BLOB,  -- 向量嵌入用于相似度搜索
    tags TEXT[],
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_used_at TIMESTAMP
);
```

#### 第2层：图/链路追踪层

```python
class ExecutionNode(BaseModel):
    """执行节点（工具调用/子Agent启动）"""
    id: str
    type: str  # tool_call, teammate_spawn, thought
    name: str  # 工具名或子Agent名
    input: Dict[str, Any]
    output: Any
    error: Optional[str]
    timestamp: str
    duration_ms: int

class ExecutionEdge(BaseModel):
    """执行边（节点关系）"""
    from_node_id: str
    to_node_id: str
    relation_type: str  # calls, spawns, follows

class ExecutionTrace(BaseModel):
    """完整执行轨迹"""
    session_id: str
    root_node_id: str
    nodes: List[ExecutionNode]
    edges: List[ExecutionEdge]
```

#### 第3层：对象/二进制层

**存储结构**

```
~/.openharness/data/blob_store/
├── {project_hash}/
│   ├── {timestamp}_{uuid}.html    # 网页内容
│   ├── {timestamp}_{uuid}.json    # 大JSON数据
│   ├── {timestamp}_{uuid}.txt     # 大文本
│   └── media/
│       └── {timestamp}_{uuid}.{ext}  # 媒体文件
```

**元数据表**

```sql
CREATE TABLE blob_references (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    message_id TEXT,
    file_path TEXT NOT NULL,
    file_size INTEGER,
    content_type TEXT,
    checksum TEXT,  -- 用于去重
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(session_id) REFERENCES sessions(id)
);
```

### 3.5 存储目录结构

```
~/.openharness/data/
├── sessions/                    # 会话记录根目录（第1层+第2层）
│   ├── {project_hash}/          # 按项目隔离
│   │   ├── session-{id}.json    # 完整会话记录（图数据）
│   │   ├── session-{id}_summary.json  # 会话摘要（第1层）
│   │   ├── conversation_tree.json     # 会话树结构（第2层）
│   │   └── teammates/           # 子Agent交互记录（第2层）
│   │       └── {teammate_id}.json
│   │
│   └── cache/                   # 压缩缓存
│       └── {project_hash}/
│           ├── compressed_context_{session_id}.json
│           └── task_summary_{session_id}.json
│
└── blob_store/                  # 对象存储（第3层）
    └── {project_hash}/
        ├── {timestamp}_{uuid}.html
        ├── {timestamp}_{uuid}.json
        └── media/
            └── {timestamp}_{uuid}.{ext}
```

---

## 4. 上下文压缩策略

### 4.1 多级压缩机制

| 级别 | 压缩方式 | 压缩率 | 用途 |
|------|----------|--------|------|
| **L0** | 完整消息 | 100% | 精确追溯、调试 |
| **L1** | 消息摘要 | ~50% | 上下文窗口 |
| **L2** | 动作序列 | ~20% | 快速回顾 |
| **L3** | 任务摘要 | ~5% | 经验库存储 |

### 4.2 压缩算法设计

```python
class ContextCompressor:
    """上下文压缩器"""
    
    def compress_to_level1(self, messages: List[ConversationMessage]) -> List[Dict]:
        """L1压缩：保留每条消息的摘要"""
        compressed = []
        for msg in messages:
            if msg.summary:
                compressed.append({
                    "role": msg.role.value,
                    "summary": msg.summary,
                    "timestamp": msg.timestamp,
                    "key_points": msg.key_points
                })
            else:
                # 自动生成摘要
                summary = self._generate_summary(msg)
                compressed.append({
                    "role": msg.role.value,
                    "summary": summary,
                    "timestamp": msg.timestamp,
                    "key_points": []
                })
        return compressed
    
    def compress_to_level2(self, messages: List[ConversationMessage]) -> List[Dict]:
        """L2压缩：只保留关键动作"""
        actions = []
        for msg in messages:
            for content in msg.content:
                if content.type in [MessageType.TOOL_USE, MessageType.TEAMMATE_SPAWN]:
                    actions.append({
                        "type": content.type.value,
                        "tool_name": content.tool_name,
                        "teammate_id": content.teammate_id,
                        "timestamp": msg.timestamp
                    })
                elif content.type == MessageType.TOOL_RESULT:
                    # 合并到前一个tool_use
                    if actions and actions[-1]["type"] == "tool_use":
                        actions[-1]["result"] = "success" if not content.tool_error else "error"
        return actions
    
    def compress_to_level3(self, session: SessionRecord) -> Dict:
        """L3压缩：任务级摘要"""
        return {
            "session_id": session.session_id,
            "task_objective": session.task_objective,
            "summary": session.summary,
            "final_outcome": session.final_outcome,
            "tool_call_count": session.tool_call_count,
            "teammate_spawn_count": session.teammate_spawn_count,
            "duration_seconds": session.duration_seconds,
            "experience_tags": session.experience_tags,
            "timestamp": session.started_at
        }
    
    def _generate_summary(self, msg: ConversationMessage) -> str:
        """为单条消息生成摘要"""
        # 简化实现：提取关键内容
        summaries = []
        for content in msg.content:
            if content.type == MessageType.TEXT:
                summaries.append(content.text[:50] + "..." if len(content.text) > 50 else content.text)
            elif content.type == MessageType.TOOL_USE:
                summaries.append(f"调用工具: {content.tool_name}")
            elif content.type == MessageType.TEAMMATE_SPAWN:
                summaries.append(f"启动子Agent: {content.teammate_id}")
        return " | ".join(summaries)
```

### 4.3 动态上下文管理

```python
class ContextManager:
    """动态上下文管理器"""
    
    MAX_FULL_MESSAGES = 10  # 最近N条消息保留完整内容
    MAX_SUMMARIZED_MESSAGES = 50  # 最多保留N条摘要消息
    
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.messages: List[ConversationMessage] = []
    
    def add_message(self, message: ConversationMessage) -> None:
        """添加消息并自动压缩"""
        self.messages.append(message)
        self._compress_context()
    
    def _compress_context(self) -> None:
        """压缩上下文，保持在合理大小"""
        if len(self.messages) <= self.MAX_FULL_MESSAGES:
            return  # 不需要压缩
        
        # 保留最近MAX_FULL_MESSAGES条完整消息
        # 将更早的消息转换为摘要
        for i in range(len(self.messages) - self.MAX_FULL_MESSAGES):
            msg = self.messages[i]
            if not msg.summary:
                msg.summary = self._generate_message_summary(msg)
                # 可选：删除完整内容以节省空间
                # msg.content = []
    
    def get_context_for_llm(self, max_tokens: int = 8000) -> List[Dict]:
        """获取适合LLM的上下文（自动选择压缩级别）"""
        # 首先尝试L0（完整）
        if self._estimate_tokens(self.messages) <= max_tokens:
            return [m.dict() for m in self.messages]
        
        # 尝试L1（摘要）
        l1_context = self.compress_to_level1(self.messages)
        if self._estimate_tokens(l1_context) <= max_tokens:
            return l1_context
        
        # 尝试L2（动作序列）
        l2_context = self.compress_to_level2(self.messages)
        if self._estimate_tokens(l2_context) <= max_tokens:
            return l2_context
        
        # 返回最精简的上下文
        return self._get_minimal_context()
```

---

## 5. 子Agent交互追踪

### 5.1 会话树追踪机制

```python
class SessionTracker:
    """会话树追踪器"""
    
    def __init__(self):
        self.conversation_trees: Dict[str, ConversationTree] = {}
    
    def track_session(self, session_id: str, parent_session_id: Optional[str] = None) -> None:
        """追踪会话创建"""
        root_id = self._find_root(parent_session_id) if parent_session_id else session_id
        
        if root_id not in self.conversation_trees:
            self.conversation_trees[root_id] = ConversationTree(root_session_id=root_id)
        
        self.conversation_trees[root_id].add_session(session_id, parent_session_id)
    
    def _find_root(self, session_id: str) -> str:
        """查找根会话ID"""
        for tree in self.conversation_trees.values():
            if session_id in tree.sessions:
                return tree.root_session_id
        return session_id
    
    def get_full_conversation(self, session_id: str) -> List[str]:
        """获取完整的会话链（包括所有子Agent）"""
        root_id = self._find_root(session_id)
        tree = self.conversation_trees.get(root_id)
        if not tree:
            return [session_id]
        
        # 获取从根到当前会话的路径
        path = self._get_path_to_session(tree, session_id)
        # 获取所有子会话
        descendants = tree.get_descendants(session_id)
        
        return path + descendants
    
    def _get_path_to_session(self, tree: ConversationTree, session_id: str) -> List[str]:
        """获取从根到指定会话的路径"""
        path = []
        current = session_id
        while current:
            path.insert(0, current)
            # 找到父节点
            current = next((edge["from"] for edge in tree.edges if edge["to"] == current), None)
        return path
```

### 5.2 子Agent消息关联

```python
class TeammateMessageRelay:
    """子Agent消息中继器"""
    
    @classmethod
    def relay_message_to_parent(cls, teammate_id: str, message: str, parent_session_id: str) -> None:
        """将子Agent消息中继到父会话"""
        # 创建中继消息
        relay_msg = ConversationMessage(
            role=MessageRole.TEAMMATE,
            content=[MessageContent(
                type=MessageType.TEAMMATE_MESSAGE,
                text=message,
                teammate_id=teammate_id
            )],
            parent_message_id=None,
            is_teammate_message=True
        )
        
        # 添加到父会话
        session_store = SessionStore()
        session_store.add_message(parent_session_id, relay_msg)
    
    @classmethod
    def relay_result_to_parent(cls, teammate_id: str, result: str, parent_session_id: str, error: bool = False) -> None:
        """将子Agent结果中继到父会话"""
        result_msg = ConversationMessage(
            role=MessageRole.TEAMMATE_RESULT,
            content=[MessageContent(
                type=MessageType.TEAMMATE_RETURN,
                text=result,
                teammate_id=teammate_id,
                tool_error=error
            )],
            is_teammate_message=True
        )
        
        session_store = SessionStore()
        session_store.add_message(parent_session_id, result_msg)
```

---

## 6. 存储管理

### 6.1 会话存储接口

```python
class SessionStore:
    """会话记录存储"""
    
    def __init__(self):
        self.base_dir = get_sessions_dir()
    
    def save_session(self, session: SessionRecord) -> Path:
        """保存完整会话记录"""
        project_dir = self.base_dir / session.project_id
        project_dir.mkdir(parents=True, exist_ok=True)
        
        path = project_dir / f"session-{session.session_id}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(session.dict(), f, ensure_ascii=False, indent=2)
        
        return path
    
    def load_session(self, project_id: str, session_id: str) -> Optional[SessionRecord]:
        """加载会话记录"""
        path = self.base_dir / project_id / f"session-{session_id}.json"
        if not path.exists():
            return None
        
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return SessionRecord(**data)
    
    def add_message(self, session_id: str, message: ConversationMessage) -> None:
        """向现有会话添加消息"""
        # 简化实现：重新加载会话，添加消息，重新保存
        # 生产环境应使用增量写入
        ...
    
    def save_teammate_interaction(self, interaction: TeammateInteraction) -> Path:
        """保存子Agent交互记录"""
        project_dir = self.base_dir / self._get_project_id(interaction.parent_session_id)
        teammates_dir = project_dir / "teammates"
        teammates_dir.mkdir(parents=True, exist_ok=True)
        
        path = teammates_dir / f"{interaction.teammate_id}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(interaction.dict(), f, ensure_ascii=False, indent=2)
        
        return path
```

### 6.2 定期清理策略

```python
class SessionCleanup:
    """会话清理器"""
    
    MAX_SESSION_AGE_DAYS = 90  # 会话保留最大天数
    MAX_SESSIONS_PER_PROJECT = 100  # 每个项目最多保留会话数
    
    @classmethod
    def cleanup_old_sessions(cls) -> None:
        """清理过期会话"""
        sessions_dir = get_sessions_dir()
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=cls.MAX_SESSION_AGE_DAYS)
        
        for project_dir in sessions_dir.iterdir():
            if not project_dir.is_dir():
                continue
            
            # 统计会话数量
            session_files = list(project_dir.glob("session-*.json"))
            
            # 删除超过数量限制的旧会话
            if len(session_files) > cls.MAX_SESSIONS_PER_PROJECT:
                # 按修改时间排序，保留最新的
                session_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                for old_file in session_files[cls.MAX_SESSIONS_PER_PROJECT:]:
                    old_file.unlink()
            
            # 删除过期会话
            for session_file in project_dir.glob("session-*.json"):
                mtime = datetime.fromtimestamp(session_file.stat().st_mtime, timezone.utc)
                if mtime < cutoff_date:
                    session_file.unlink()
    
    @classmethod
    def cleanup_orphaned_teammate_records(cls) -> None:
        """清理孤立的子Agent记录"""
        sessions_dir = get_sessions_dir()
        
        for project_dir in sessions_dir.iterdir():
            teammates_dir = project_dir / "teammates"
            if not teammates_dir.exists():
                continue
            
            # 获取所有有效的会话ID
            valid_session_ids = set()
            for session_file in project_dir.glob("session-*.json"):
                session_id = session_file.stem.replace("session-", "")
                valid_session_ids.add(session_id)
            
            # 删除没有对应会话的子Agent记录
            for teammate_file in teammates_dir.iterdir():
                # 解析父会话ID（简化：实际实现需要读取文件内容）
                # 这里假设文件名包含会话ID信息
                ...
```

---

## 7. 反思与演化的数据支持

### 7.1 数据提取用于反思

```python
class ReflectionDataExtractor:
    """从会话记录中提取反思数据"""
    
    @classmethod
    def extract_for_reflection(cls, session_id: str) -> Dict:
        """提取反思所需的数据"""
        store = SessionStore()
        session = store.load_session(session_id)
        if not session:
            return {}
        
        # 提取关键信息
        return {
            "session_id": session.session_id,
            "task_objective": session.task_objective,
            "summary": session.summary,
            "final_outcome": session.final_outcome,
            "duration_seconds": session.duration_seconds,
            "tool_call_count": session.tool_call_count,
            "teammate_spawn_count": session.teammate_spawn_count,
            
            # 动作序列
            "actions": cls._extract_actions(session),
            
            # 子Agent交互
            "teammate_interactions": cls._extract_teammate_interactions(session),
            
            # 错误信息
            "errors": cls._extract_errors(session),
            
            # 关键决策点
            "decision_points": cls._extract_decision_points(session)
        }
    
    @classmethod
    def _extract_actions(cls, session: SessionRecord) -> List[Dict]:
        """提取动作序列"""
        actions = []
        for msg in session.messages:
            for content in msg.content:
                if content.type in [MessageType.TOOL_USE, MessageType.TEAMMATE_SPAWN]:
                    actions.append({
                        "type": content.type.value,
                        "name": content.tool_name or content.teammate_id,
                        "timestamp": msg.timestamp
                    })
        return actions
    
    @classmethod
    def _extract_errors(cls, session: SessionRecord) -> List[str]:
        """提取错误信息"""
        errors = []
        for msg in session.messages:
            for content in msg.content:
                if content.type == MessageType.TOOL_RESULT and content.tool_error:
                    errors.append(content.tool_result or "Unknown error")
        return errors
```

### 7.2 经验库关联

```python
class ExperienceAssociator:
    """将会话记录关联到经验库"""
    
    @classmethod
    def associate_with_experience(cls, session_id: str, outcome: str) -> None:
        """根据会话结果关联到经验库"""
        extractor = ReflectionDataExtractor()
        data = extractor.extract_for_reflection(session_id)
        
        if outcome == "success":
            record = SuccessRecord(
                task_type=data.get("task_objective", "unknown"),
                approach=str(data.get("actions", [])),
                metrics=TaskMetrics(
                    time_elapsed=data.get("duration_seconds", 0),
                    confidence=0.8  # 默认值，实际应从评估中获取
                ),
                context=data.get("summary", ""),
                tags=data.get("experience_tags", [])
            )
            experience_store = AgentExperienceStore("default")
            experience_store.add_success(record)
        else:
            record = FailureRecord(
                task_type=data.get("task_objective", "unknown"),
                error=", ".join(data.get("errors", [])),
                context=data.get("summary", ""),
                tags=data.get("experience_tags", [])
            )
            experience_store = AgentExperienceStore("default")
            experience_store.add_failure(record)
```

---

## 8. 总结

### 8.1 核心方案

| 组件 | 职责 |
|------|------|
| **SessionRecord** | 完整会话记录，包含消息、元数据和统计 |
| **ConversationTree** | 追踪父子会话关系，支持会话树遍历 |
| **ContextCompressor** | 多级上下文压缩，避免上下文爆炸 |
| **TeammateInteraction** | 记录子Agent交互，支持完整追溯 |
| **ReflectionDataExtractor** | 从会话中提取反思所需数据 |

### 8.2 数据流转

```
用户输入
    │
    ▼
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│  会话记录        │ ──► │  上下文压缩      │ ──► │  经验库存储      │
│  (SessionRecord) │     │  (Compressor)   │     │  (Experience)   │
└──────────────────┘     └──────────────────┘     └──────────────────┘
        │                                                       │
        │ 子Agent交互                                            │
        ▼                                                       │
┌──────────────────┐                                             │
│  会话树追踪      │                                             │
│  (ConversationTree)                                           │
└──────────────────┘                                             │
        │                                                       │
        ▼                                                       │
┌──────────────────┐                                             │
│  反思数据提取    │ ◄────────────────────────────────────────────┘
│  (Extractor)    │
└──────────────────┘
        │
        ▼
┌──────────────────┐
│  自我进化        │
│  (Evolution)    │
└──────────────────┘
```

这套方案解决了：
1. **会话记录管理**：完整存储所有交互，支持追溯
2. **子Agent追踪**：会话树结构支持完整的父子关系追溯
3. **上下文爆炸**：多级压缩机制保持合理的上下文大小
4. **反思支持**：结构化的数据提取便于后续分析和学习
