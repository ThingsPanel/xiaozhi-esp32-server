"""向量记忆提供者实现"""
import os
import json
import time
from datetime import datetime
import numpy as np
from typing import List, Dict, Any, Optional
from config.logger import setup_logging
from core.utils.dialogue import Message
from ..base import MemoryProviderBase

TAG = "vector_memory"

class MemoryProvider(MemoryProviderBase):
    """向量记忆提供者，基于FAISS实现语义相似度搜索和记忆过滤"""

    def __init__(self, config, summary_memory=None):
        """初始化向量记忆提供者
        
        Args:
            config: 配置字典，包含以下字段:
                - dimension: 向量维度
                - similarity_threshold: 相似度阈值
                - max_batch_size: 最大批处理大小
                - api_url: 向量服务API地址
                - api_key: 向量服务API密钥
                - model: 向量模型名称，默认为"embedding-3"
                - storage: 存储配置
                    - index_path: 索引文件路径
                    - metadata_path: 元数据文件路径
                - memory_filter: 记忆过滤配置
                    - enabled: 是否启用过滤
                    - min_importance: 最低重要性阈值
                    - min_text_length: 最短文本长度
                    - max_text_length: 最长文本长度
                    - keywords: 关键词列表
                - max_memories: 最大记忆数量，默认5000
                - clean_threshold: 清理阈值，当记忆数量超过 max_memories 的百分比时触发清理，默认0.9
        """
        super().__init__(config)
        self.logger = setup_logging().bind(tag=TAG)
        
        # 保存完整配置
        self.config = config
        
        # 基础配置
        self.dimension = config.get('dimension', 1024)
        self.similarity_threshold = config.get('similarity_threshold', 0.65)
        self.max_batch_size = config.get('max_batch_size', 8)
        
        # 记忆管理配置
        self.max_memories = config.get('max_memories', 5000)
        self.clean_threshold = config.get('clean_threshold', 0.9)
        
        # API配置
        self.api_url = config.get('api_url', '')
        self.api_key = config.get('api_key', '')
        
        # 存储配置
        storage_config = config.get('storage', {})
        self.index_path = storage_config.get('index_path', 'data/vector_memory.index')
        self.metadata_path = storage_config.get('metadata_path', 'data/vector_memory.json')
        
        # 确保存储目录存在
        os.makedirs(os.path.dirname(self.index_path), exist_ok=True)
        os.makedirs(os.path.dirname(self.metadata_path), exist_ok=True)
        
        # 初始化存储
        self.metadata = []
        self.index = None
        
        try:
            # 动态导入FAISS，避免在导入时阻塞
            self._initialize_faiss()
        except Exception as e:
            self.logger.error(f"FAISS初始化失败，将使用简单存储: {e}")
            # 允许在FAISS失败时继续运行
            self.faiss_available = False
        else:
            self.faiss_available = True
            self._initialize_storage()
        
        self.logger.info("向量记忆提供者初始化完成")

    def _initialize_faiss(self):
        """动态初始化FAISS库"""
        try:
            import faiss
            self.faiss = faiss
            self.logger.info("FAISS库加载成功")
        except ImportError as e:
            self.logger.error(f"FAISS库导入失败: {e}")
            self.logger.error("请安装FAISS: pip install faiss-cpu")
            raise

    def _initialize_storage(self) -> None:
        """初始化存储，包括FAISS索引和元数据"""
        if not self.faiss_available:
            return
            
        # 初始化或加载FAISS索引
        if os.path.exists(self.index_path):
            try:
                self.index = self.faiss.read_index(self.index_path)
                self.logger.info(f"已加载FAISS索引: {self.index_path}")
            except Exception as e:
                self.logger.error(f"加载FAISS索引失败: {e}")
                self.index = self.faiss.IndexFlatL2(self.dimension)
        else:
            self.index = self.faiss.IndexFlatL2(self.dimension)
            self.logger.info("已创建新的FAISS索引")
        
        # 初始化或加载元数据
        if os.path.exists(self.metadata_path):
            try:
                with open(self.metadata_path, 'r', encoding='utf-8') as f:
                    self.metadata = json.load(f)
                self.logger.info(f"已加载元数据: {self.metadata_path}")
            except Exception as e:
                self.logger.error(f"加载元数据失败: {e}")
                self.metadata = []
        else:
            self.metadata = []
            self.logger.info("已创建新的元数据列表")

    def _save_storage(self) -> None:
        """保存存储状态到文件"""
        if not self.faiss_available or self.index is None:
            return
            
        try:
            self.faiss.write_index(self.index, self.index_path)
            with open(self.metadata_path, 'w', encoding='utf-8') as f:
                json.dump(self.metadata, f, ensure_ascii=False, indent=2)
            self.logger.info("存储状态已保存")
        except Exception as e:
            self.logger.error(f"保存存储状态失败: {e}")

    async def _get_embedding(self, text: str) -> Optional[np.ndarray]:
        """获取文本的向量嵌入
        
        Args:
            text: 输入文本
            
        Returns:
            文本的向量嵌入，如果失败则返回None
        """
        if not self.api_url or not self.api_key:
            self.logger.warning("API地址或密钥未配置，无法获取向量嵌入")
            return None
            
        try:
            # 动态导入aiohttp，避免在导入时阻塞
            import aiohttp
            
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            }
            
            # 从配置中读取模型名称，默认为 embedding-3
            model_name = self.config.get('model', 'embedding-3')
            
            data = {
                "model": model_name,
                "input": text,
            }
            
            # 可选添加维度参数
            if self.dimension:
                data["dimensions"] = self.dimension
            
            self.logger.debug(f"发送向量请求: {self.api_url}, 模型: {model_name}")
            
            async with aiohttp.ClientSession() as session:
                async with session.post(self.api_url, headers=headers, json=data, timeout=10) as response:
                    if response.status == 200:
                        result = await response.json()
                        embedding = result.get('data', [{}])[0].get('embedding')
                        if embedding:
                            return np.array(embedding, dtype=np.float32)
                    self.logger.error(f"获取向量嵌入失败: {response.status}, URL: {self.api_url}")
                    if response.status != 200:
                        error_text = await response.text()
                        self.logger.error(f"错误详情: {error_text}")
                    return None
        except ImportError:
            self.logger.error("aiohttp库未安装，无法获取向量嵌入")
            return None
        except Exception as e:
            self.logger.error(f"调用向量服务失败: {e}")
            return None

    def _build_memory_text(self, message: Message) -> str:
        """构建记忆文本
        
        Args:
            message: 消息对象
            
        Returns:
            格式化的记忆文本
        """
        text = []
        
        # 添加基础信息
        current_time = datetime.now().isoformat()
        timestamp = current_time
        if hasattr(message, 'timestamp') and message.timestamp:
            timestamp = message.timestamp
            
        text.append(f"时间: {timestamp}")
        text.append(f"角色: {message.role}")
        
        # 添加工具调用信息
        if hasattr(message, 'tool_name') and message.tool_name:
            text.append(f"工具: {message.tool_name}")
        if hasattr(message, 'tool_call_id') and message.tool_call_id:
            text.append(f"调用ID: {message.tool_call_id}")
            
        # 添加内容
        text.append(f"内容: {message.content}")
        
        return "\n".join(text)

    def _filter_memory(self, text: str) -> bool:
        """过滤记忆
        
        Args:
            text: 记忆文本
            
        Returns:
            是否保留该记忆
        """
        # 获取过滤器配置
        filter_config = self.config.get('memory_filter', {})
        if not filter_config.get('enabled', True):
            return True
            
        # 长度过滤
        min_length = filter_config.get('min_text_length', 10)
        max_length = filter_config.get('max_text_length', 3000)
        text_length = len(text)
        
        if text_length < min_length or text_length > max_length:
            self.logger.debug(f"过滤掉长度不符合要求的记忆: {text_length}字符")
            return False
            
        # 关键词过滤
        keywords = filter_config.get('keywords', [])
        if keywords:
            if not any(keyword in text for keyword in keywords):
                self.logger.debug(f"过滤掉不包含关键词的记忆")
                return False
        
        # 重要性评分过滤
        min_importance = filter_config.get('min_importance', 0)
        if min_importance > 0:
            importance = self._calculate_importance(text)
            if importance < min_importance:
                self.logger.debug(f"过滤掉重要性低的记忆: 评分={importance}, 阈值={min_importance}")
                return False
            
        return True
        
    def _calculate_importance(self, text: str) -> int:
        """计算记忆重要性评分
        
        评分规则:
        1. 基础分值: 1
        2. 包含特定指令/操作词加分: +2
        3. 包含数字/时间/特定参数加分: +1
        4. 包含特定场景/关键设备加分: +1
        5. 包含情感表达加分: +1
        
        Args:
            text: 记忆文本
            
        Returns:
            重要性评分: 1-10
        """
        score = 1  # 基础分值
        
        # 指令/操作词加分
        operation_words = ["设置", "打开", "关闭", "调整", "控制", "更改", "启动", "停止"]
        if any(word in text for word in operation_words):
            score += 2
            
        # 数字/时间/参数加分
        import re
        if re.search(r'\d+', text):  # 包含数字
            score += 1
        if re.search(r'(\d+[:.]\d+|上午|下午|晚上|早上|凌晨)', text):  # 包含时间
            score += 1
            
        # 场景/设备加分
        devices = ["灯", "空调", "窗帘", "电视", "音响", "温度", "湿度", "设备"]
        if any(device in text for device in devices):
            score += 1
            
        # 情感表达加分
        emotions = ["喜欢", "讨厌", "满意", "不满", "希望", "期待"]
        if any(emotion in text for emotion in emotions):
            score += 1
            
        # 返回最终评分，最高限制为10分
        return min(score, 10)

    async def save_memory(self, messages: List[Message]) -> bool:
        """保存记忆
        
        Args:
            messages: 消息列表
            
        Returns:
            是否保存成功
        """
        if not messages:
            return True
            
        # 如果没有FAISS，使用简单存储
        if not self.faiss_available:
            self.logger.warning("FAISS不可用，使用简单存储")
            for message in messages:
                memory_text = self._build_memory_text(message)
                if self._filter_memory(memory_text):
                    self.metadata.append({
                        'text': memory_text,
                        'timestamp': datetime.now().isoformat(),
                        'role': message.role
                    })
            
            # 限制元数据大小
            if len(self.metadata) > 1000:
                self.metadata = self.metadata[-1000:]
                
            # 保存元数据
            try:
                with open(self.metadata_path, 'w', encoding='utf-8') as f:
                    json.dump(self.metadata, f, ensure_ascii=False, indent=2)
            except Exception as e:
                self.logger.error(f"保存元数据失败: {e}")
                
            return True
            
        try:
            for message in messages:
                # 构建记忆文本
                memory_text = self._build_memory_text(message)
                
                # 过滤记忆
                if not self._filter_memory(memory_text):
                    continue
                    
                # 获取向量嵌入
                embedding = await self._get_embedding(memory_text)
                if embedding is None:
                    # 如果获取嵌入失败，仍然保存元数据但不添加到索引
                    current_time = datetime.now().isoformat()
                    timestamp = current_time
                    if hasattr(message, 'timestamp') and message.timestamp:
                        timestamp = message.timestamp
                        
                    self.metadata.append({
                        'text': memory_text,
                        'timestamp': timestamp,
                        'role': message.role,
                        'tool_name': getattr(message, 'tool_name', None),
                        'tool_call_id': getattr(message, 'tool_call_id', None),
                        'no_embedding': True
                    })
                    continue
                    
                # 添加到索引
                self.index.add(embedding.reshape(1, -1))
                
                # 添加元数据
                current_time = datetime.now().isoformat()
                timestamp = current_time
                if hasattr(message, 'timestamp') and message.timestamp:
                    timestamp = message.timestamp
                    
                self.metadata.append({
                    'text': memory_text,
                    'timestamp': timestamp,
                    'role': message.role,
                    'tool_name': getattr(message, 'tool_name', None),
                    'tool_call_id': getattr(message, 'tool_call_id', None)
                })
            
            # 检查是否需要清理记忆
            if len(self.metadata) > self.max_memories * self.clean_threshold:
                await self._clean_memories()
            
            # 保存存储状态
            self._save_storage()
            return True
            
        except Exception as e:
            self.logger.error(f"保存记忆失败: {e}")
            return False
            
    async def _clean_memories(self) -> None:
        """清理不重要的历史记忆
        
        清理策略:
        1. 保留所有重要性高于阈值的记忆
        2. 对于重要性低于阈值的记忆，按照时间顺序保留最近的一部分
        """
        if not self.faiss_available or len(self.metadata) == 0:
            return
            
        self.logger.info(f"开始清理记忆，当前记忆数量: {len(self.metadata)}")
        
        try:
            # 提取记忆重要性
            memories_with_importance = []
            for i, meta in enumerate(self.metadata):
                # 跳过没有嵌入的记忆
                if meta.get('no_embedding', False):
                    continue
                    
                importance = self._calculate_importance(meta['text'])
                memories_with_importance.append((i, meta, importance))
            
            # 获取过滤器配置中的重要性阈值
            filter_config = self.config.get('memory_filter', {})
            min_importance = filter_config.get('min_importance', 3)
            
            # 分离重要和不重要的记忆
            important_memories = [(i, meta) for i, meta, imp in memories_with_importance if imp >= min_importance]
            unimportant_memories = [(i, meta) for i, meta, imp in memories_with_importance if imp < min_importance]
            
            # 按时间排序不重要的记忆
            unimportant_memories.sort(key=lambda x: x[1].get('timestamp', ''), reverse=True)
            
            # 计算要保留的记忆数量
            target_count = int(self.max_memories * 0.7)  # 清理到70%容量
            keep_unimportant_count = max(0, target_count - len(important_memories))
            
            # 确定要保留的记忆
            keep_memories = important_memories + unimportant_memories[:keep_unimportant_count]
            keep_indices = [i for i, _ in keep_memories]
            
            # 创建新的FAISS索引
            new_index = self.faiss.IndexFlatL2(self.dimension)
            new_metadata = []
            
            # 重新构建索引和元数据
            for old_idx, meta in keep_memories:
                # 获取嵌入向量 (如果可能)
                query_text = meta['text']
                embedding = await self._get_embedding(query_text)
                
                if embedding is not None:
                    new_index.add(embedding.reshape(1, -1))
                    new_metadata.append(meta)
                
            # 更新索引和元数据
            self.index = new_index
            self.metadata = new_metadata
            
            # 保存更新后的存储
            self._save_storage()
            
            self.logger.info(f"记忆清理完成，已清理 {len(memories_with_importance) - len(keep_memories)} 条记忆，" 
                            f"保留 {len(keep_memories)} 条记忆")
            
        except Exception as e:
            self.logger.error(f"清理记忆失败: {e}")
            
    async def clean_all_memories(self) -> bool:
        """清理所有记忆
        
        Returns:
            是否成功清理
        """
        if not self.faiss_available:
            self.metadata = []
            try:
                with open(self.metadata_path, 'w', encoding='utf-8') as f:
                    json.dump(self.metadata, f, ensure_ascii=False, indent=2)
                self.logger.info("已清空所有记忆")
                return True
            except Exception as e:
                self.logger.error(f"清空记忆失败: {e}")
                return False
        
        try:
            # 创建新的FAISS索引
            self.index = self.faiss.IndexFlatL2(self.dimension)
            self.metadata = []
            
            # 保存空的存储
            self._save_storage()
            
            self.logger.info("已清空所有记忆")
            return True
            
        except Exception as e:
            self.logger.error(f"清空记忆失败: {e}")
            return False

    async def query_memory(self, query: str, limit: int = 3) -> List[Dict[str, Any]]:
        """查询相关记忆
        
        Args:
            query: 查询文本
            limit: 返回结果数量限制
            
        Returns:
            相关记忆列表
        """
        # 如果没有FAISS或没有元数据，返回最近的记忆
        if not self.faiss_available or not self.index or len(self.metadata) == 0:
            self.logger.warning("FAISS不可用或没有记忆，返回最近记忆")
            recent_memories = sorted(self.metadata, key=lambda x: x.get('timestamp', ''), reverse=True)
            return recent_memories[:limit]
            
        try:
            # 获取查询向量
            query_embedding = await self._get_embedding(query)
            if query_embedding is None:
                # 如果获取嵌入失败，返回最近的记忆
                recent_memories = sorted(self.metadata, key=lambda x: x.get('timestamp', ''), reverse=True)
                return recent_memories[:limit]
                
            # 搜索相似向量
            D, I = self.index.search(query_embedding.reshape(1, -1), min(limit, len(self.metadata)))
            
            # 过滤并格式化结果
            results = []
            for i, (distance, idx) in enumerate(zip(D[0], I[0])):
                if idx >= len(self.metadata) or idx < 0:
                    continue
                    
                similarity = 1.0 / (1.0 + distance)  # 将距离转换为相似度
                if similarity < self.similarity_threshold:
                    continue
                    
                memory = self.metadata[idx].copy()
                memory['similarity'] = similarity
                results.append(memory)
                
            return results
            
        except Exception as e:
            self.logger.error(f"查询记忆失败: {e}")
            # 发生错误时返回最近的记忆
            recent_memories = sorted(self.metadata, key=lambda x: x.get('timestamp', ''), reverse=True)
            return recent_memories[:limit] 