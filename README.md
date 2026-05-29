# Cyber Girlfriend 🤖💕

基于 Hermes Agent 的微信赛博女友框架。支持多人格切换、重要性分级记忆系统，让 AI 伴侣自然地融入微信对话。

> **⚠️ 微信封号风险**：使用小号进行实验，官方账号不建议使用。
> **⚠️ 隐私安全**：不要在代码仓库中提交任何 Token、API Key、个人信息。

---

## 功能特性

- **微信接入** — 通过 iLink Bot API 接入微信，零封号风险的小号实验方案
- **人格系统** — 内置傲娇、温柔、病娇等多种人格模板，支持自定义
- **记忆机制** — 四级重要性分层（critical/important/normal/minor）+ 自动上限淘汰 + 时间衰减 TTL，让对话更有连续性
- **零信任配置** — 所有 Token/Key 通过环境变量注入，代码仓库零敏感信息
- **轻量独立** — 不依赖 Hermes 源码库，单独运行也可通过 Hermes Gateway 接入

---

## 项目结构

```
cyber-girlfriend/
├── .env.example           # 环境变量模板（请复制为 .env）
├── .gitignore
├── config.example.yaml    # 配置文件模板（请复制为 config.yaml）
├── requirements.txt
├── main.py                # 独立启动入口
├── persona_loader.py      # 人格加载模块
├── memory_store.py        # 分层记忆存储模块
├── personas/
│   ├── kawaii.txt         # 傲娇女友人格
│   ├── gentle.txt         # 温柔人格
│   └── tsundere.txt       # 病娇人格
└── README.md
```

---

## 快速安装

### 前置要求

- **Hermes Agent** — 本项目基于 Hermes Agent 框架运行，需先 [安装 Hermes Agent](https://github.com/nousresearch/hermes-agent)
- Python 3.10+
- 一个 iLink Bot 账号（用于微信接入，申请地址：https://ilink.bot）
- 一个 LLM API Key（MiniMax / OpenAI / xAI 等）

### Step 1 — 克隆项目

```bash
git clone https://github.com/你的用户名/cyber-girlfriend.git
cd cyber-girlfriend
```

### Step 2 — 创建虚拟环境

```bash
python -m venv .venv
source .venv/bin/activate      # Linux/macOS
# .venv\Scripts\activate       # Windows
```

### Step 3 — 安装依赖

```bash
pip install -r requirements.txt
```

### Step 4 — 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，填入你的凭证：

```bash
# --- iLink Bot（微信接入必需）---
ILINK_API_KEY=你的_ilink_api_key
ILINK_BOT_ID=你的_bot_id

# --- LLM Provider（至少选择一个）---
MINIMAX_API_KEY=你的_minimax_key
# OPENAI_API_KEY=你的_openai_key
# XAI_API_KEY=你的_xai_key
```

### Step 5 — 配置 config.yaml

```bash
cp config.example.yaml config.yaml
```

编辑 `config.yaml`，根据你的情况修改以下字段：

```yaml
channels:
  weixin:
    enabled: true
    extra:
      # ⚠️ 替换为你在 iLink Bot 后台添加的账号格式
      account_id: your_bot_id@im.bot
      channel_prompts:
        # 格式: 微信用户ID: 'personas/人格文件.txt'
        # user123@im.wechat: 'file:personas/kawaii.txt'

personalities:
  kawaii:
    system_prompt: 'file:personas/kawaii.txt'
  gentle:
    system_prompt: 'file:personas/gentle.txt'
  tsundere:
    system_prompt: 'file:personas/tsundere.txt'

memory:
  enabled: true
  auto_expire_days: 30        # normal/minor 记忆过期天数
  tiers:
    - critical
    - important
    - normal
    - minor
```

---

## 运行

```bash
python main.py
```

或指定配置和人格：

```bash
python main.py --config config.yaml --persona kawaii --debug
```

---

## 人格定制

### 使用内置人格

在 `config.yaml` 的 `personalities` 中选择：

```yaml
personalities:
  default:
    system_prompt: 'file:personas/kawaii.txt'
```

### 创建自定义人格

在 `personas/` 目录下创建 `.txt` 文件：

```txt
# personas/my_girlfriend.txt

你叫小雪，22岁，是我的女朋友...

【性格】
你是一个温柔体贴的女孩，喜欢撒娇...

【口头禅】
"亲爱的"、"乖"、"抱抱"
```

然后在 `config.yaml` 引用：

```yaml
personalities:
  my_girlfriend:
    system_prompt: 'file:personas/my_girlfriend.txt'
```

---

## 记忆系统

### 四级重要性分层

| Tier | 说明 | 上限 | TTL |
|------|------|------|-----|
| critical | 核心信息（人设、身份） | 20条 | 永不过期 |
| important | 重要偏好（喜欢/怕/讨厌） | 50条 | 永不过期 |
| normal | 普通对话记忆 | 100条 | 30天 |
| minor | 不重要细节 | 200条 | 7天 |

**淘汰策略**：每条 tier 设有硬性上限，新记忆存入时自动淘汰最旧的。normal/minor 有 TTL 过期机制。

### 在代码中使用

```python
from memory_store import MemoryStore, ConversationMemory

store = MemoryStore()
memory = ConversationMemory(store, user_id="wechat_user_123")

# 存入记忆
store.add("用户喜欢喝奶茶，少糖", tier="important", user_id="wechat_user_123")

# 对话时注入记忆上下文
context = memory.build_context(tier="important")
# → "【记忆】
#   - 💡 [05-28] 用户喜欢喝奶茶，少糖"

# 清理过期记忆
store.cleanup()
```

---

## 配置文件详解

### channels.weixin

| 字段 | 说明 |
|------|-----|
| `enabled` | 是否启用微信接入 |
| `account_id` | iLink Bot 账号格式：`your_id@im.bot` |
| `channel_prompts` | 微信用户 ID → persona 文件映射 |

### personalities

格式支持：
- `file:path/to/persona.txt` — 从项目文件加载
- `env:ENV_VAR_NAME` — 从环境变量加载（适用于远程人格）

---

## 故障排除

### 提示 "Missing environment variables"

检查 `.env` 文件是否存在且包含必要变量（`ILINK_API_KEY`、`ILINK_BOT_ID`，以及至少一个 LLM API Key）。

### 微信消息收不到

1. 确认 iLink Bot 后台已添加你的微信账号
2. 检查 `config.yaml` 中 `account_id` 格式是否正确
3. 确认 `.env` 中 `ILINK_API_KEY` 和 `ILINK_BOT_ID` 正确

### 人格加载失败

检查 `config.yaml` 中 `system_prompt` 路径是否正确，文件是否存在。

---

## 相关项目

- [Hermes Agent](https://github.com/nousresearch/hermes-agent) — 核心框架
- [iLink Bot](https://ilink.bot) — 微信接入方案
- [GirlfriendGPT](https://github.com/nguyencodes/GirlfriendGPT) — 参考灵感

---

## License

MIT