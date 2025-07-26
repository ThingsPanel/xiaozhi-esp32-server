import asyncio
import json
import threading
from typing import Dict, Any, Optional, Callable
from config.logger import setup_logging
import paho.mqtt.client as mqtt
import time
import inspect

TAG = "mqtt_notification"

class MQTTNotificationListener:
    """MQTT通知监听器"""
    
    def __init__(self, config: Dict[str, Any], device_id: str, notification_callback: Callable):
        """
        初始化MQTT通知监听器
        
        Args:
            config: MQTT配置
            device_id: 设备ID
            notification_callback: 通知回调函数，接收消息内容作为参数

        消息格式:
            {"notification":"消息内容"}
            关联MQTT主题: service/esp32/devices/telemetry/control/#设备编号#
        """
        self.config = config
        self.device_id = device_id
        self.notification_callback = notification_callback
        self.logger = setup_logging().bind(tag=TAG)
        
        # 保存主线程的事件循环
        self.main_loop = asyncio.get_event_loop()
        
        # MQTT相关
        self.mqtt_client = None
        self.mqtt_config = config.get('mqtt', {})
        self.stop_event = threading.Event()
        self.mqtt_thread = None
        
        # 配置参数
        self.broker_host = self.mqtt_config.get('host', '127.0.0.1')
        self.broker_port = self.mqtt_config.get('port', 1883)
        self.username = self.mqtt_config.get('username')
        self.password = self.mqtt_config.get('password')
        self.topic = self.mqtt_config.get('topic', f'service/esp32/devices/telemetry/control/{device_id}')
        self.client_id = "ESP_CLIENT_" + device_id
        self.keepalive = self.mqtt_config.get('keepalive', 60)
        
    def start(self):
        """启动MQTT通知监听"""
        try:
            self.mqtt_thread = threading.Thread(target=self._mqtt_worker, daemon=True)
            self.mqtt_thread.start()
            self.logger.info(f"MQTT通知监听器已启动: {self.topic}")
        except Exception as e:
            self.logger.error(f"启动MQTT通知监听器失败: {e}")
    
    def stop(self):
        """停止MQTT通知监听"""
        try:
            self.stop_event.set()
            
            if self.mqtt_client:
                self.mqtt_client.disconnect()
                self.mqtt_client.loop_stop()
                
            if self.mqtt_thread and self.mqtt_thread.is_alive():
                self.mqtt_thread.join(timeout=5)
                
            self.logger.info("MQTT通知监听器已停止")
        except Exception as e:
            self.logger.error(f"停止MQTT通知监听器失败: {e}")
    
    def _mqtt_worker(self):
        """MQTT工作线程"""
        try:
            # 创建MQTT客户端
            self.mqtt_client = mqtt.Client(
                client_id=self.client_id,
                clean_session=True,
                protocol=mqtt.MQTTv311
            )
            
            # 设置回调函数
            self.mqtt_client.on_connect = self._on_connect
            self.mqtt_client.on_message = self._on_message
            self.mqtt_client.on_disconnect = self._on_disconnect
            self.mqtt_client.on_log = self._on_log
            
            # 设置认证信息
            if self.username and self.password:
                self.mqtt_client.username_pw_set(self.username, self.password)
            
            # 连接到MQTT代理
            self.mqtt_client.connect(self.broker_host, self.broker_port, self.keepalive)
            
            # 开始MQTT循环
            self.mqtt_client.loop_start()
            
            # 等待停止信号
            while not self.stop_event.is_set():
                self.stop_event.wait(1)
                
        except Exception as e:
            self.logger.error(f"MQTT工作线程异常: {e}")
        finally:
            if self.mqtt_client:
                self.mqtt_client.loop_stop()
    
    def _on_connect(self, client, userdata, flags, rc):
        """MQTT连接回调"""
        if rc == 0:
            self.logger.info(f"MQTT连接成功: {self.broker_host}:{self.broker_port}")
            # 订阅主题
            client.subscribe(self.topic, qos=1)
            self.logger.info(f"已订阅主题: {self.topic}")
        else:
            self.logger.error(f"MQTT连接失败，错误码: {rc}")
    
    def _on_message(self, client, userdata, msg):
        """MQTT消息回调"""
        try:
            topic = msg.topic
            payload = msg.payload.decode('utf-8')
            
            self.logger.info(f"收到MQTT消息: {topic} -> {payload}")
            
            # 处理消息
            self._process_message(payload)
            
        except Exception as e:
            self.logger.error(f"处理MQTT消息失败: {e}")
    
    def _on_disconnect(self, client, userdata, rc):
        """MQTT断开连接回调"""
        if rc != 0:
            self.logger.warning(f"MQTT连接意外断开，错误码: {rc}")
        else:
            self.logger.info("MQTT连接已断开")
    
    def _on_log(self, client, userdata, level, buf):
        """MQTT日志回调"""
        if level == mqtt.MQTT_LOG_ERR:
            self.logger.error(f"MQTT错误: {buf}")
        elif level == mqtt.MQTT_LOG_WARNING:
            self.logger.warning(f"MQTT警告: {buf}")
        elif level == mqtt.MQTT_LOG_INFO:
            self.logger.info(f"MQTT信息: {buf}")
        else:
            self.logger.debug(f"MQTT调试: {buf}")
    
    def _process_message(self, payload: str):
        """处理MQTT消息"""
        try:
            # 尝试解析为JSON格式
            try:
                data = json.loads(payload)
                message = data.get('notification', payload)
                priority = data.get('priority', 'normal')
                notification_type = data.get('type', 'text')
                
                self.logger.info(f"解析MQTT通知: {message} (优先级: {priority}, 类型: {notification_type})")
                
                # 调用回调函数处理通知
                self._call_notification_callback(message, priority, notification_type)
                
            except json.JSONDecodeError:
                # 如果不是JSON格式，直接作为文本处理
                self.logger.info(f"MQTT通知: {payload}")
                self._call_notification_callback(payload, 'normal', 'text')
                
        except Exception as e:
            self.logger.error(f"处理MQTT消息失败: {e}")
    
    def _call_notification_callback(self, message: str, priority: str, notification_type: str):
        """调用通知回调函数"""
        try:
            # 判断回调是否为协程函数
            if inspect.iscoroutinefunction(self.notification_callback):
                # 使用保存的主线程事件循环来调度异步回调
                asyncio.run_coroutine_threadsafe(
                    self.notification_callback(message, priority, notification_type),
                    self.main_loop
                )
            else:
                # 如果是普通函数，直接调用
                self.notification_callback(message, priority, notification_type)
        except Exception as e:
            self.logger.error(f"通知回调函数执行失败: {e}")