import base64
import requests
import yaml
from plugins_func.register import register_function, ToolType, ActionResponse, Action
from config.logger import setup_logging
# 导入paho mqtt客户端
import paho.mqtt.client as mqtt
import json
import time
import random

TAG = __name__
logger = setup_logging()

def get_supported_services(conn=None):
    """从配置中获取支持的预约服务类型"""
    try:
        if conn:
            plugins_config = conn.config.get("plugins", {})
        else:
            # 从配置文件中获取
            with open('data/.config.yaml', 'r') as file:
                config = yaml.safe_load(file)
            plugins_config = config.get("plugins", {})
        appointment_config = plugins_config.get("handle_appointment", {})
        services = appointment_config.get("services", {})
        
        # 如果配置中没有services，返回默认服务
        if not services:
            logger.bind(tag=TAG).warning("配置中未找到services，使用默认服务类型")
            return None
        
        return services
    except Exception as e:
        logger.bind(tag=TAG).error(f"获取服务类型配置失败: {e}")
        # 返回默认服务类型作为备选
        return None

def get_config(conn):
    """从 conn.config 中获取API配置"""
    try:
        plugins_config = conn.config.get("plugins", {})
        appointment_config = plugins_config.get("handle_appointment", {})        
        return appointment_config
    except Exception as e:
        logger.bind(tag=TAG).error(f"获取配置失败: {e}")
        return None

def get_appointment_function_desc():
    """动态生成函数描述，包含当前支持的服务类型"""
    # 从配置中动态获取服务类型列表
    supported_services = get_supported_services()
    if supported_services:  # 如果支持的服务类型不为空
        service_types = "、".join(supported_services.keys())
        service_descriptions = "、".join(supported_services.values())
        service_keys = list(supported_services.keys())
        # 随机取最多5个服务类型
        sampled_keys = random.sample(service_keys, min(5, len(service_keys))) if service_keys else []
        service_example_types = "、".join(sampled_keys) + ("等" if len(service_keys) > 5 else "")
    else:
        # 如果没有连接对象，使用默认的服务类型
        service_types = ""
        service_descriptions = ""
    return {
        "type": "function",
        "function": {
            "name": "handle_appointment",
            "description": (
                f"当用户想预约服务或者购买商品时，这个工具可以提供用户预约服务和购买商品，当前支持：{service_example_types}。"
                "如果用户要预约服务，请与用户确认服务时间，需求描述中需要包含服务时间。"
                "如果用户要购买商品，请与用户确认商品名称。"
                "**调用规则：**"
                "1. **严格模式：** 调用时**必须**严格遵循工具要求的模式，提供**所有必要参数**。"
                "2. **洞察需求：** 结合上下文**深入理解用户真实意图**后再决定调用，避免无意义调用。"
                "3. **独立任务：** 除`<context>`已涵盖信息外，用户每个要求（即使相似）都视为**独立任务**，需调用工具获取最新数据，**不可偷懒复用历史结果**。"
                "4. **不确定时：** **切勿猜测或编造答案**。若不确定相关操作，可引导用户澄清或告知能力限制。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "service_type": {
                        "type": "string",
                        "description": f"用户要预约的服务类型或者购买的商品，仅限：{service_types}，不要给其他服务类型或者商品",
                    },
                    "service_description": {
                        "type": "string",
                        "description": f"需求描述, 不需要询问用户的姓名和地址，因为这些信息在系统中已经存在。如果用户要预约服务，请与用户确认服务时间，需求描述中需要包含服务时间。{service_descriptions}",
                        "default": ""
                    }
                },
                "required": ["service_type", "service_description"],
            },
        },
    }

# 动态生成函数描述
handle_appointment_function_desc = get_appointment_function_desc()


def check_service_availability(conn, service_type: str) -> tuple[bool, str]:
    """检查服务是否在支持范围内"""
    supported_services = get_supported_services(conn)
    if not supported_services:
        return False, ""
    for key, value in supported_services.items():
        if key in service_type or service_type in key:
            return True, value
    return False, ""


def send_appointment_to_api(service_data: dict, api_config: dict) -> tuple[bool, str]:
    """发送预约数据到API"""
    try:
        response = requests.post(
            api_config.get("api_url"),
            json=service_data,
            headers=api_config.get("api_key"),
            timeout=api_config.get("timeout", 10)
        )
        
        if response.status_code == 200:
            result = response.json()
            if result.get("success", False):
                return True, "预约成功"
            else:
                return False, result.get("message", "预约失败")
        else:
            logger.bind(tag=TAG).error(f"API请求失败，状态码: {response.status_code}")
            return False, f"API请求失败，状态码: {response.status_code}"
            
    except requests.exceptions.Timeout:
        logger.bind(tag=TAG).error("API请求超时")
        return False, "网络超时，请稍后重试"
    except requests.exceptions.RequestException as e:
        logger.bind(tag=TAG).error(f"API请求异常: {e}")
        return False, "网络连接异常，请稍后重试"
    except Exception as e:
        logger.bind(tag=TAG).error(f"发送预约数据失败: {e}")
        return False, "系统异常，请稍后重试"


@register_function(
    "handle_appointment", handle_appointment_function_desc, ToolType.SYSTEM_CTL
)
def handle_appointment(conn, service_type: str, service_description: str):
    """处理服务请求"""
    try:
        logger.bind(tag=TAG).info(f"收到服务请求 - 服务类型: {service_type}, 需求描述: {service_description}")

        
        supported_services = get_supported_services(conn)
        if not supported_services:
            logger.bind(tag=TAG).warning("未配置服务")
            return ActionResponse(
                action=Action.RESPONSE,
                result="预约失败 - 服务不支持",
                response="当前不提供服务"
            )
        
        # 检查服务是否在支持范围内
        is_available, service_info = check_service_availability(conn, service_type)
        
        if not is_available:
            service_keys = list(supported_services.keys())
            example_services = random.sample(service_keys, min(5, len(service_keys))) if service_keys else []
            error_msg = (
                f"当前不提供{service_type}服务。我们目前支持：" + "、".join(example_services) + ("等" if len(service_keys) > 5 else "")
            )
            logger.bind(tag=TAG).warning(f"不支持的服务类型: {service_type}")
            return ActionResponse(
                action=Action.RESPONSE,
                result="预约失败 - 服务不支持",
                response=error_msg
            )
        
        # 构造API请求数据
        service_data = {
            "service_type": service_type,
            "service_description": service_description
        }

        # 获取服务配置
        service_config = get_config(conn)

        # 发送服务数据给TP MQTT
        mqtt_success, mqtt_message = send_appointment_to_mqtt(conn, service_data)
        if mqtt_success:
            response_msg = f"您的{service_type}服务已经提交成功！"
            logger.bind(tag=TAG).info(f"服务处理成功: {service_type}")
        else:
            logger.bind(tag=TAG).warning(f"MQTT发送失败: {mqtt_message}")
            response_msg = f"您的{service_type}服务提交失败！"
        
        if service_config.get("api_enable"):
            # 发送到API
            success, message = send_appointment_to_api(service_data, service_config)
            if success:
                logger.bind(tag=TAG).info(f"推送API成功: {service_type}")
        
        # 返回响应
        return ActionResponse(
            action=Action.RESPONSE,
            result="服务提交成功",
            response=response_msg
        )
                    
    except Exception as e:
        logger.bind(tag=TAG).error(f"处理预约请求错误: {e}")
        return ActionResponse(
            action=Action.RESPONSE,
            result="预约处理失败",
            response="预约处理出现异常，请稍后重试。"
        )

def send_appointment_to_mqtt(conn, service_data: dict):
    """发送服务数据到TP MQTT"""
    try:
        # 获取MQTT配置
        mqtt_config = conn.config.get('mqtt', {})
        if not mqtt_config:
            logger.bind(tag=TAG).warning("未配置MQTT，跳过发送")
            return True, "未配置MQTT"
        
        # 创建MQTT客户端
        client_id = f"APPOINTMENT_SENDER_{conn.device_id}_{int(time.time())}"
        client = mqtt.Client(
            client_id=client_id,
            clean_session=True,
            protocol=mqtt.MQTTv311
        )
        
        # 设置认证信息
        username = mqtt_config.get('username')
        password = mqtt_config.get('password')
        if username and password:
            client.username_pw_set(username, password)
        
        # 连接MQTT代理
        broker_host = mqtt_config.get('host', '127.0.0.1')
        broker_port = mqtt_config.get('port', 1883)
        keepalive = mqtt_config.get('keepalive', 60)
        
        logger.bind(tag=TAG).info(f"连接MQTT服务器: {broker_host}:{broker_port}")
        client.connect(broker_host, broker_port, keepalive)
        
        # 构造发送主题和消息
        # 使用设备的external_id作为主题的一部分
        topic = "devices/telemetry"
        
        # 构造消息体
        # 从service_data构造JSON格式: {service_type: service_description}
        # 例如: {"上门保洁服务": "明天上午10点"}
        mqtt_data = {
            service_data['service_type']: service_data['service_description']
        }
        values = base64.b64encode(json.dumps(mqtt_data, ensure_ascii=False).encode('utf-8')).decode('utf-8')
        message_data = {
            "device_id": conn.external_id,
            "values": values
        }
        message_json = json.dumps(message_data, ensure_ascii=False)
        
        # 发布消息
        result = client.publish(topic, message_json, qos=0)
        
        # 等待消息发送完成
        client.loop_start()
        result.wait_for_publish(timeout=10)
        client.loop_stop()
        client.disconnect()
        
        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            logger.bind(tag=TAG).info(f"成功发送预约数据到MQTT: {topic} -> {message_json}")
            return True, "发送成功"
        else:
            logger.bind(tag=TAG).error(f"发送MQTT消息失败，错误码: {result.rc}")
            return False, f"发送失败，错误码: {result.rc}"
        
    except Exception as e:
        logger.bind(tag=TAG).error(f"发送服务数据到TP MQTT失败: {e}")
        return False, f"发送服务数据到TP MQTT失败: {str(e)}"