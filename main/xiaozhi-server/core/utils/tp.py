import json
import aiohttp
import asyncio
from typing import Optional, Dict, Any
from config.logger import setup_logging

TAG = __name__


class ThingsPanelClient:
    """ThingsPanel API客户端类"""
    
    def __init__(self):
        """
        初始化ThingsPanel客户端
        """
        self.logger = setup_logging()

        # 获取voucher.json配置
        with open("data/voucher.json", "r") as f:
            voucher_data = json.load(f)

        # 解析嵌套的JSON字符串
        voucher_str = voucher_data.get("voucher", "{}")
        try:
            voucher_obj = json.loads(voucher_str)
            # 获取ThingsPanel的接入信息
            self.base_url = voucher_obj.get("ThingsPanelApiURL")
            self.api_token = voucher_obj.get("ThingsPanelApiKey")
        except json.JSONDecodeError:
            self.logger.bind(tag=TAG).error(f"无法解析voucher JSON字符串: {voucher_str}")
            self.base_url = None
            self.api_token = None
        
    async def device_auth(self, template_secret: str, device_number: str, 
                         device_name: str = None, product_key: str = None) -> tuple[bool, Dict[str, Any]]:
        """
        设备动态认证（一型一密）
        
        Args:
            template_secret: 模板密钥
            device_number: 设备唯一标识
            device_name: 设备名称（可选）
            product_key: 产品密钥（可选）
            
        Returns:
            tuple: (认证是否成功, 认证结果数据)
            
        Raises:
            Exception: 网络请求失败时抛出异常
        """
        url = f"{self.base_url}/device/auth"
        
        # 构建请求头
        headers = {
            'Content-Type': 'application/json'
        }
        if self.api_token:
            headers['x-api-key'] = self.api_token
            
        # 构建请求体
        payload = {
            'template_secret': template_secret,
            'device_number': device_number
        }
        
        # 添加可选参数
        if device_name:
            payload['device_name'] = device_name
        if product_key:
            payload['product_key'] = product_key
            
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=payload) as response:
                    response_data = await response.json()
                    
                    self.logger.bind(tag=TAG).info(f"设备认证请求: {payload}")
                    self.logger.bind(tag=TAG).info(f"设备认证响应: {response_data}")
                    
                    # 当code为200或200082时认为认证成功
                    if response.status == 200 and response_data.get('code') in [200, 200082]:
                        return True, response_data.get('data', {})
                    else:
                        error_msg = response_data.get('message', f'HTTP {response.status}')
                        self.logger.bind(tag=TAG).warning(f"设备认证失败: {error_msg}")
                        return False, {}
                        
        except aiohttp.ClientError as e:
            self.logger.bind(tag=TAG).error(f"设备认证网络错误: {str(e)}")
            raise Exception(f"设备认证网络错误: {str(e)}")
        except json.JSONDecodeError as e:
            self.logger.bind(tag=TAG).error(f"设备认证响应解析错误: {str(e)}")
            raise Exception(f"设备认证响应解析错误: {str(e)}")
    
    async def update_device_status(self, device_number: str, is_online: bool) -> Dict[str, Any]:
        """
        更新设备在线状态
        
        Args:
            device_number: 设备编号
            device_id: 设备ID
            is_online: 是否在线
            
        Returns:
            Dict: 更新结果
            
        Raises:
            Exception: 更新失败时抛出异常
        """
        # 注意：这里假设状态更新接口的路径，实际路径需要根据API文档确认
        url = f"{self.base_url}/device"

        # 写日志开始更新
        self.logger.bind(tag=TAG).info(f"开始更新设备在线状态: {device_number} 为 {is_online}")
        
        # 构建请求头
        headers = {
            'Content-Type': 'application/json'
        }
        if self.api_token:
            headers['x-api-key'] = self.api_token
            
        # 构建请求体
        payload = {
            'device_number': device_number,
            'id': "EMPTY",
            'is_online': 1 if is_online else 0
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.put(url, headers=headers, json=payload) as response:
                    response_data = await response.json()
                    
                    self.logger.bind(tag=TAG).info(f"设备状态更新请求: {payload}")
                    self.logger.bind(tag=TAG).info(f"设备状态更新响应: {response_data}")
                    
                    if response.status == 200 and response_data.get('code') == 200:
                        return True
                    else:
                        return False
                        
        except aiohttp.ClientError as e:
            self.logger.bind(tag=TAG).error(f"设备状态更新网络错误: {str(e)}")
            raise Exception(f"设备状态更新网络错误: {str(e)}")
        except json.JSONDecodeError as e:
            self.logger.bind(tag=TAG).error(f"设备状态更新响应解析错误: {str(e)}")
            raise Exception(f"设备状态更新响应解析错误: {str(e)}")


# 便利函数，用于简化使用
async def authenticate_device(template_secret: str, 
                            device_number: str, device_name: str = None, 
                            product_key: str = None) -> tuple[bool, Dict[str, Any]]:
    """
    设备认证便利函数
    
    Returns:
        tuple: (认证是否成功, 认证结果数据)
    """
    client = ThingsPanelClient()
    return await client.device_auth(template_secret, device_number, device_name, product_key)


async def update_device_online_status(device_number: str, is_online: bool) -> Dict[str, Any]:
    """
    设备状态更新便利函数
    
    Args:
        device_number: 设备编号
        is_online: 是否在线
        
    Returns:
        Dict: 更新结果
    """
    client = ThingsPanelClient()
    return await client.update_device_status(device_number, is_online)