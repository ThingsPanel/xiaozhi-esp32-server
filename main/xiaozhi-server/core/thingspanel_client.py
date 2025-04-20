import httpx
from config.logger import setup_logging
from typing import Optional, Dict

TAG = __name__
logger = setup_logging()

class ThingsPanelClient:
    _instance = None
    _client = None

    def __new__(cls, config):
        """单例模式确保全局唯一实例"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._init_client(config)
        return cls._instance

    @classmethod
    def _init_client(cls, config):
        """初始化 HTTP 客户端"""
        cls.config = config.get("thingspanel", {})
        
        if not cls.config:
            logger.bind(tag=TAG).warning("未配置 ThingsPanel，设备状态更新功能将不可用")
            return

        base_url = cls.config.get("base_url")
        api_key = cls.config.get("api_key")

        if not base_url or not api_key:
            logger.bind(tag=TAG).warning("ThingsPanel 配置不完整，设备状态更新功能将不可用")
            return

        # 初始化 HTTP 客户端
        cls._client = httpx.Client(
            base_url=base_url,
            headers={
                "x-api-key": f"{api_key}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    @classmethod
    def update_device_status(cls, device_id: str, status: int) -> bool:
        """更新设备状态
        
        Args:
            device_id: 设备ID
            status: 设备状态，1表示在线，0表示离线
            
        Returns:
            bool: 更新是否成功
        """
        if not cls._client:
            logger.bind(tag=TAG).warning("ThingsPanel 客户端未初始化，无法更新设备状态")
            return False

        try:
            response = cls._client.put(
                "/device",
                json={
                    "Id": "EMPTY",
                    "device_number": device_id,
                    "is_online": status
                }
            )
            response.raise_for_status()
            logger.bind(tag=TAG).info(f"设备 {device_id} 状态已更新为 {status}")
            return True
        except Exception as e:
            logger.bind(tag=TAG).error(f"更新设备状态失败: {str(e)}")
            return False

    @classmethod
    def safe_close(cls):
        """安全关闭 HTTP 客户端"""
        if cls._client:
            cls._client.close()
            cls._instance = None 