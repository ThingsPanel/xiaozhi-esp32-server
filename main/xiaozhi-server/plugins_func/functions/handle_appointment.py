import requests
import json
from datetime import datetime
from core.utils.tp import get_user_info
from plugins_func.register import register_function, ToolType, ActionResponse, Action
from config.logger import setup_logging

TAG = __name__
logger = setup_logging()

# 支持的预约服务类型
SUPPORTED_SERVICES = {
    "上门保洁": {
        "service_code": "SERVICE_CLEANING",
        "service_name": "上门保洁服务"
    },
    "上门测量血压血糖": {
        "service_code": "SERVICE_HEALTH_CHECK",
        "service_name": "上门测量血压血糖服务"
    },
    "上门维修": {
        "service_code": "SERVICE_REPAIR",
        "service_name": "上门维修服务"
    },
    "上门护理": {
        "service_code": "SERVICE_NURSING",
        "service_name": "上门护理服务"
    }
}

def get_api_config(conn):
    """从 conn.config 中获取API配置"""
    try:
        plugins_config = conn.config.get("plugins", {})
        appointment_config = plugins_config.get("handle_appointment", {})
        
        api_url = appointment_config.get("api_url", "")
        api_key = appointment_config.get("api_key", "")
        
        if not api_url or not api_key or not appointment_config.get("enable"):
            logger.bind(tag=TAG).warning("预约服务暂时不可用")
            return None
        
        return {
            "url": api_url,
            "timeout": 10,
            "headers": {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            }
        }
    except Exception as e:
        logger.bind(tag=TAG).error(f"获取API配置失败: {e}")
        return None

def get_appointment_function_desc():
    """动态生成函数描述，包含当前支持的服务类型"""
    # 从配置中动态获取服务类型列表
    service_examples = "、".join(SUPPORTED_SERVICES.keys())
    
    return {
        "type": "function",
        "function": {
            "name": "handle_appointment",
            "description": (
                f"当用户想预约服务时，这个工具可以提供用户预约服务，当前支持的服务类型：{service_examples}。"
                "要与用户确认服务时间。"
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
                        "description": f"用户要预约的服务类型，支持的服务：{service_examples}",
                    },
                    "appointment_time": {
                        "type": "string",
                        "description": "预约时间，格式：YYYY-MM-DD HH:MM:SS，如：2024-01-15 10:00:00，一定要和用户确认预约时间，不要给历史时间或者默认时间",
                    },
                    "additional_info": {
                        "type": "string",
                        "description": "额外的预约信息或特殊要求, 不需要询问用户的姓名和地址，因为这些信息在用户信息中已经包含",
                        "default": ""
                    }
                },
                "required": ["service_type", "appointment_time"],
            },
        },
    }

# 动态生成函数描述
handle_appointment_function_desc = get_appointment_function_desc()


def validate_appointment_time(time_str: str) -> tuple[bool, str]:
    """验证预约时间格式是否正确"""
    try:
        # 验证时间格式 YYYY-MM-DD HH:MM:SS
        datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
        
        # 检查预约时间是否在未来
        appointment_time = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
        now = datetime.now()
        
        if appointment_time <= now:
            return False, "预约时间必须是未来时间"
        
        return True, "时间格式正确"
        
    except ValueError:
        return False, "时间格式不正确，请使用 YYYY-MM-DD HH:MM:SS 格式"
    except Exception as e:
        logger.bind(tag=TAG).error(f"验证时间格式失败: {e}")
        return False, "时间格式验证失败"


def check_service_availability(service_type: str) -> tuple[bool, dict]:
    """检查服务是否在支持范围内"""
    for key, value in SUPPORTED_SERVICES.items():
        if key in service_type or service_type in key:
            return True, value
    return False, {}


def send_appointment_to_api(appointment_data: dict, api_config: dict) -> tuple[bool, str]:
    """发送预约数据到API"""
    try:
        response = requests.post(
            api_config["url"],
            json=appointment_data,
            headers=api_config["headers"],
            timeout=api_config["timeout"]
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
def handle_appointment(conn, service_type: str, appointment_time: str, additional_info: str = ""):
    """处理预约服务请求"""
    try:
        logger.bind(tag=TAG).info(f"收到预约请求 - 服务类型: {service_type}, 时间: {appointment_time}")
        
        # 检查服务是否在支持范围内
        is_available, service_info = check_service_availability(service_type)
        
        if not is_available:
            error_msg = "预约失败，当前不提供此类服务。我们目前支持：" + "、".join(SUPPORTED_SERVICES.keys())
            logger.bind(tag=TAG).warning(f"不支持的服务类型: {service_type}")
            return ActionResponse(
                action=Action.RESPONSE,
                result="预约失败 - 服务类型不支持",
                response=error_msg
            )
        
        # 验证预约时间格式
        time_valid, time_message = validate_appointment_time(appointment_time)
        
        if not time_valid:
            error_msg = f"预约失败，{time_message}"
            logger.bind(tag=TAG).warning(f"时间格式错误: {appointment_time} - {time_message}")
            return ActionResponse(
                action=Action.RESPONSE,
                result="预约失败 - 时间格式错误",
                response=error_msg
            )
        
        # 获取用户信息
        user_info = {}
        external_user_id = conn.external_user_id
        
        try:
            if external_user_id != None:
                success, user_data = get_user_info(external_user_id)
                if success:
                    user_info = user_data
                    logger.bind(tag=TAG).info(f"成功获取用户信息: {user_info.get('name', 'unknown')}")
                else:
                    logger.bind(tag=TAG).warning(f"获取用户信息失败: {external_user_id}")
            else:
                logger.bind(tag=TAG).warning(f"获取用户信息失败: {external_user_id}")
                return ActionResponse(
                    action=Action.RESPONSE,
                    result="预约失败 - 用户信息获取失败",
                    response="预约失败 - 用户信息获取失败"
                )
        except Exception as e:
            logger.bind(tag=TAG).error(f"获取用户信息异常: {e}")
        
        # 处理地址信息
        address_info = user_info.get('address', {})
        full_address = ""
        if address_info:
            # 拼接完整地址
            address_parts = [
                address_info.get('country', ''),
                address_info.get('province', ''),
                address_info.get('city', ''),
                address_info.get('district', ''),
                address_info.get('street', ''),
                address_info.get('detailed_address', '')
            ]
            full_address = ''.join([part for part in address_parts if part])
        
        # 构造API请求数据
        appointment_data = {
            "service_code": service_info["service_code"],
            "service_name": service_info["service_name"],
            "appointment_time": appointment_time,
            "customer_info": {
                "customer_id": external_user_id,
                "customer_name": user_info.get('name', ''),
                "phone_number": user_info.get('phone_number', ''),
                "email": user_info.get('email', ''),
                "address": {
                    "full_address": full_address,
                    "country": address_info.get('country', ''),
                    "province": address_info.get('province', ''),
                    "city": address_info.get('city', ''),
                    "district": address_info.get('district', ''),
                    "detailed_address": address_info.get('detailed_address', ''),
                    "postal_code": address_info.get('postal_code', ''),
                    "additional_info": address_info.get('additional_info', '')
                }
            },
            "additional_info": additional_info,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        
        # 获取API配置
        api_config = get_api_config(conn)
        if not api_config:
            return ActionResponse(
                action=Action.RESPONSE,
                result="预约服务暂时不可用",
                response="预约服务暂时不可用"
            )
        
        # 发送到API
        success, message = send_appointment_to_api(appointment_data, api_config)
        
        if success:
            success_msg = "预约成功，服务人员将尽快与您联系。"
            logger.bind(tag=TAG).info(f"预约成功: {service_type} - {appointment_time}")
            return ActionResponse(
                action=Action.RESPONSE,
                result="预约成功",
                response=success_msg
            )
        else:
            error_msg = f"预约失败，{message}"
            logger.bind(tag=TAG).error(f"预约失败: {message}")
            return ActionResponse(
                action=Action.RESPONSE,
                result="预约失败",
                response=error_msg
            )
            
    except Exception as e:
        logger.bind(tag=TAG).error(f"处理预约请求错误: {e}")
        return ActionResponse(
            action=Action.RESPONSE,
            result="预约处理失败",
            response="预约处理出现异常，请稍后重试。"
        )


def get_supported_services():
    """获取支持的服务列表"""
    return list(SUPPORTED_SERVICES.keys())


if __name__ == "__main__":
    # 测试代码
    print("支持的服务类型:")
    for service in get_supported_services():
        print(f"- {service}")
    
    print("\n动态生成的函数描述:")
    desc = get_appointment_function_desc()
    print(f"函数描述: {desc['function']['description']}")
    print(f"服务类型参数描述: {desc['function']['parameters']['properties']['service_type']['description']}")
