# 向量记忆提供者

基于 FAISS 实现的向量记忆提供者，支持语义相似度搜索和记忆过滤。

## 特性

- 基于语义相似度的记忆存储和检索
- 记忆重要性评估和过滤
- 持久化存储支持
- 异步向量嵌入获取
- 自动维护记忆索引
- 自动清理不重要的记忆

## 配置

在 `config.yaml` 中配置：

```yaml
Memory:
  vector_memory:
    type: vector_memory
    enabled: true
    dimension: 1024
    similarity_threshold: 0.65
    max_batch_size: 8
    api_url: https://open.bigmodel.cn/api/paas/v4/embeddings
    api_key: your-api-key
    model: embedding-3
    max_memories: 1000  # 最大记忆数量，默认5000
    clean_threshold: 0.8  # 清理阈值，当记忆数量达到max_memories的80%时触发清理
    storage:
      index_path: data/vector_memory.index
      metadata_path: data/vector_memory.json
    memory_filter:
      enabled: true  # 是否启用过滤
      min_importance: 3  # 最低重要性评分阈值（1-10）
      min_text_length: 10  # 最短文本长度
      max_text_length: 3000  # 最长文本长度
      keywords: ["温度", "湿度", "设置", "状态", "时间", "提醒", "喜欢", "不喜欢"]  # 关键词过滤
```

## 记忆过滤机制

记忆过滤基于以下几个维度进行：

1. **文本长度**：过滤过短或过长的文本
2. **关键词**：只保留包含特定关键词的记忆
3. **重要性评分**：基于内容智能评估记忆重要性

### 重要性评分规则

- 基础分值: 1分
- 包含指令/操作词: +2分（如"设置"，"打开"，"控制"）
- 包含数字/时间信息: +1分
- 包含设备/场景关键词: +1分
- 包含情感表达: +1分

## 记忆清理机制

系统会自动管理记忆数量，当记忆数量超过设定阈值时触发清理：

1. 保留所有重要性评分高于阈值的记忆
2. 对于低重要性记忆，按时间顺序保留最近的部分
3. 清理后记忆量会降低到最大容量的70%左右

## 依赖

- faiss-cpu
- numpy

## 使用示例

```python
from core.providers.memory.vector_memory import MemoryProvider
from core.utils.dialogue import Message

# 初始化
config = {
    "dimension": 1024,
    "similarity_threshold": 0.65,
    "api_url": "https://api.example.com/embeddings",
    "api_key": "your-api-key",
    "model": "embedding-3"
}
memory = MemoryProvider(config)

# 保存记忆
messages = [
    Message(
        role="user",
        content="设置温度为25度",
        timestamp="2024-04-04T10:00:00",
        tool_name="set_temperature",
        tool_call_id="123"
    )
]
await memory.save_memory(messages)

# 查询记忆
results = await memory.query_memory("温度设置", limit=3)
```

## 重要说明

1. 需要安装 FAISS 库：`pip install faiss-cpu`
2. 需要配置正确的 API 地址和密钥
3. 确保存储路径有写入权限
4. 可以根据需要调整记忆过滤规则 