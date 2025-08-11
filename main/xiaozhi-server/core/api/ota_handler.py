import json
import time
import sqlite3
from aiohttp import web
from core.utils.tp import authenticate_device, get_device_config_by_number, update_device_online_status
from core.utils.util import get_local_ip
from core.api.base_handler import BaseHandler

TAG = __name__


class OTAHandler(BaseHandler):
    def __init__(self, config: dict):
        super().__init__(config)

    def _get_websocket_url(self, local_ip: str, port: int) -> str:
        """获取websocket地址

        Args:
            local_ip: 本地IP地址
            port: 端口号

        Returns:
            str: websocket地址
        """
        server_config = self.config["server"]
        websocket_config = server_config.get("websocket", "")

        if "你的" not in websocket_config:
            return websocket_config
        else:
            return f"ws://{local_ip}:{port}/xiaozhi/v1/"

    async def handle_post(self, request):
        """处理 OTA POST 请求"""
        try:
            data = await request.text()
            self.logger.bind(tag=TAG).debug(f"OTA请求方法: {request.method}")
            self.logger.bind(tag=TAG).debug(f"OTA请求头: {request.headers}")
            self.logger.bind(tag=TAG).debug(f"OTA请求数据: {data}")

            device_id = request.headers.get("device-id", "")
            if device_id:
                self.logger.bind(tag=TAG).info(f"OTA请求设备ID: {device_id}")
            else:
                raise Exception("OTA请求设备ID为空")
            
            # 一型一密认证
            template_secret = request.headers.get("template-secret", "")
            if template_secret:
                self.logger.bind(tag=TAG).info(f"OTA请求模板密钥: {template_secret}")
            else:
                raise Exception("OTA请求模板密钥为空")

            data_json = json.loads(data)

            server_config = self.config["server"]
            port = int(server_config.get("port", 8000))
            local_ip = get_local_ip()

            # OTA基础信息
            return_json = {
                "server_time": {
                    "timestamp": int(round(time.time() * 1000)),
                    "timezone_offset": server_config.get("timezone_offset", 8) * 60,
                },
                "firmware": {
                    "version": data_json["application"].get("version", "1.0.0"),
                    "url": "",
                },
                "websocket": {
                    "url": self._get_websocket_url(local_ip, port),
                },
            }

            # 获取voucher.json配置，通过template_secret查找对应的voucher数据
            try:
                with open("data/voucher.json", "r") as f:
                    voucher_storage = json.load(f)
                
                # 使用template_secret作为key获取对应的voucher数据
                voucher_str = voucher_storage.get(template_secret,  voucher_storage.get("voucher", "{}"))
                if not voucher_str or voucher_str == "{}":
                    self.logger.bind(tag=TAG).warning(f"未找到template_secret为{template_secret}的voucher配置")
                    tp_auth_type = "manual"  # 设置默认值
                else:
                    try:
                        voucher_obj = json.loads(voucher_str)
                        tp_auth_type = voucher_obj.get("auth_type", "manual")
                    except json.JSONDecodeError:
                        self.logger.bind(tag=TAG).error(f"无法解析voucher JSON字符串: {voucher_str}")
                        tp_auth_type = "manual"  # 设置默认值
            except (FileNotFoundError, json.JSONDecodeError):
                self.logger.bind(tag=TAG).warning("voucher.json文件不存在或格式错误")
                tp_auth_type = "manual"  # 设置默认值

            # 检查设备是否存在于数据库中，如果不存在则自动创建此设备
            device_info = self.check_or_create_device(device_id, template_secret)
            verify_code = device_info['verify_code']
            if not device_info:
                raise Exception("设备检查或创建失败")
            else:
                # 同步更新设备状态为在线, 如果TP中不存在此设备则会返回False
                is_online = await update_device_online_status(template_secret, device_id, True)

                # 如果此接入点开启了自动认证，则调用TP的一型一密接口自动认证并生成TP Device
                if tp_auth_type == "auto":
                    # 输出日志开始自动激活
                    self.logger.bind(tag=TAG).info(f"开始认证设备: {device_id}")
                    # 调用TP的一型一密接口自动认证并生成TP Device
                    auth_result, auth_data = await authenticate_device(template_secret, device_id, device_info['device_name'])
                    if not auth_result:
                        return_json["activation"] = {
                            "code": verify_code,
                            "message": "设备认证失败，请联系管理员",
                            "challenge": device_id,
                        }
                # 如果此接入点开启了人工认证
                else:
                    if is_online: # 说明设备已经激活
                        auth_result = True
                    else:
                        # 设备在TP中并未激活, 则强制走人工激活, 无论ESP DB中是否activated
                        auth_result = False
                        # 如果自动认证失败，可能是设备模块不允许自动认证，则返回activation: code, message, challenge走手动认证
                        return_json["activation"] = {
                            "code": verify_code,
                            "message": "激活码: " + verify_code,
                            "challenge": device_id,
                        }
                        
                # 设备未认证时成功时
                if not auth_result:
                    self.update_device_fields(device_id, {"status": "pending"})
                else:
                    # 设备认证成功，更新设备状态为activated
                    self.update_device_fields(device_id, {"status": "activated"})
                    # 强制同步external_key
                    self.logger.bind(tag=TAG).info(f"同步{device_id}的external_key")
                    success, device_config = await get_device_config_by_number(template_secret, device_id)
                    if success:
                        # 从tenant_user_api_keys数组中取第一个api_key和user_id
                        tenant_user_api_keys = device_config.get('tenant_user_api_keys', [])
                        if tenant_user_api_keys and len(tenant_user_api_keys) > 0:
                            first_api_key = tenant_user_api_keys[0].get('api_key')
                            if first_api_key:
                                self.update_device_fields(device_id, {"external_key": first_api_key, "external_user_id": tenant_user_api_keys[0].get('user_id')})
                                self.logger.bind(tag=TAG).info(f"成功更新设备 {device_id} 的external_key为: {first_api_key} 和 external_user_id为: {tenant_user_api_keys[0].get('user_id')}")
                            else:
                                self.logger.bind(tag=TAG).warning(f"第一个API key为空: {tenant_user_api_keys[0]}")
                        else:
                            self.logger.bind(tag=TAG).warning(f"设备配置中未找到tenant_user_api_keys: {device_config}")
                        
                        # 如果设备删除后重新激活，则同步external_id
                        if device_info.get("external_id") != device_config.get('id'):
                            self.logger.bind(tag=TAG).info(f"重新同步{device_id}的external_id")
                            self.update_device_fields(device_id, {"external_id": device_config.get('id')})
                    else:
                        self.logger.bind(tag=TAG).info(f"{device_id}获取TP Device Config失败")


            # 返回信息输出日志
            response = web.Response(
                text=json.dumps(return_json, separators=(",", ":")),
                content_type="application/json",
            )
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"OTA请求异常: {e}")
            # return_json = {"success": False, "message": "request error."}
            return_json = "" # 返回空用于中断设备初始化
            response = web.Response(
                text=json.dumps(return_json, separators=(",", ":")),
                content_type="application/json",
            )
        finally:
            self._add_cors_headers(response)
            return response

    async def handle_get(self, request):
        """处理 OTA GET 请求"""
        try:
            server_config = self.config["server"]
            local_ip = get_local_ip()
            port = int(server_config.get("port", 8000))
            websocket_url = self._get_websocket_url(local_ip, port)
            message = f"OTA接口运行正常，向设备发送的websocket地址是：{websocket_url}"
            response = web.Response(text=message, content_type="text/plain")
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"OTA GET请求异常: {e}")
            response = web.Response(text="OTA接口异常", content_type="text/plain")
        finally:
            self._add_cors_headers(response)
            return response

    # 获取可激活设备列表
    async def handle_device_list(self, request: web.Request) -> web.Response:
        """处理获取设备列表请求
        
        Args:
            request: web请求对象
            
        Returns:
            web.Response: 包含设备列表的响应
        """

        # 验证请求头中的secret
        error_response = self.validate_secret(request)
        if error_response:
            return error_response
        
        try:
            # 从请求体中解析参数
            data = await request.json()  # 解析POST请求的JSON数据
            voucher = data.get('voucher')
            service_identifier = data.get('service_identifier')
            page_size = data.get('page_size')
            page = data.get('page')
            
            # 将接入点信息写入本地文件缓存
            # 解析voucher JSON字符串获取TemplateSecret作为key
            try:
                voucher_data = json.loads(voucher)
                template_secret = voucher_data.get('TemplateSecret')
                
                if not template_secret:
                    return web.json_response({
                        "code": 10001,
                        "message": "voucher中缺少TemplateSecret",
                        "data": None
                    }, status=400)
                
                # 读取现有的voucher文件（如果存在）
                voucher_storage = {}
                try:
                    with open("data/voucher.json", "r") as f:
                        voucher_storage = json.load(f)
                except (FileNotFoundError, json.JSONDecodeError):
                    voucher_storage = {}
                
                # 使用TemplateSecret作为key，原始voucher数据作为value
                voucher_storage[template_secret] = voucher
                
                # 写入更新后的数据
                with open("data/voucher.json", "w") as f:
                    json.dump(voucher_storage, f, indent=2)
                    
            except json.JSONDecodeError as e:
                return web.json_response({
                    "code": 10001,
                    "message": f"voucher JSON格式错误: {str(e)}",
                    "data": None
                }, status=400)

            # 验证必需参数
            if not all([voucher, page_size, page]):
                return web.json_response({
                    "code": 10001,
                    "message": "缺少必需参数",
                    "data": None
                }, status=400)
            
            try:
                page_size = int(page_size)
                page = int(page)
            except ValueError:
                return web.json_response({
                    "code": 10002,
                    "message": "page_size和page必须是整数",
                    "data": None
                }, status=400)
            
            # 从数据库获取设备列表
            conn = sqlite3.connect(self.db_path)
            db = conn.cursor()
            
            try:
                # 获取总记录数
                db.execute("SELECT COUNT(*) FROM devices WHERE status = 'pending'")
                total = db.fetchone()[0]
                
                # 获取分页数据
                offset = (page - 1) * page_size
                db.execute('''
                    SELECT device_id, device_name, description, status
                    FROM devices
                    WHERE status = 'pending'
                    LIMIT ? OFFSET ?
                ''', (page_size, offset))
                
                devices = []
                for row in db.fetchall():
                    device_info = {
                        "device_name": row[1],
                        "description": row[2],
                        "device_number": row[0]
                    }
                    devices.append(device_info)
                
                return web.json_response({
                    "code": 200,
                    "message": "success",
                    "data": {
                        "list": devices,
                        "total": total
                    }
                })
                
            finally:
                conn.close()
            
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"获取设备列表失败: {str(e)}")
            return web.json_response({
                "code": 500,
                "message": f"获取设备列表失败: {str(e)}",
                "data": None
            }, status=500)

    # 验证请求头中的secret
    def validate_secret(self, request):
        secret = request.headers.get("x-token")
        if secret != self.secret:
            return web.json_response({
                "code": 401,
                "message": "Unauthorized",
                "data": None
            }, status=401)
        return None  # 返回 None 表示验证通过

    def check_or_create_device(self, device_id: str, template_secret: str, device_name: str = None) -> dict:
        """检查设备是否在数据库中，如果不存在则创建
        
        Args:
            device_id: 设备ID
            template_secret: 模板密钥
            device_name: 设备名称（可选）
            
        Returns:
            dict: 设备信息字典，如果失败则返回None
        """
        try:
            conn = sqlite3.connect(self.db_path)
            db = conn.cursor()
            
            # 检查设备是否存在
            db.execute("SELECT * FROM devices WHERE device_id = ?", (device_id,))
            device_info = db.fetchone()
            
            if device_info:
                self.logger.bind(tag=TAG).info(f"设备 {device_id} 已存在于数据库中")
                # 将查询结果转换为字典
                columns = ['device_id', 'device_name', 'description', 'template_secret', 
                          'verify_code', 'status', 'created_at', 'updated_at', 'external_id', 'external_key', 'external_user_id']
                return dict(zip(columns, device_info))
            else:
                # 设备不存在，创建新设备
                self.logger.bind(tag=TAG).info(f"设备 {device_id} 不存在，开始创建...")
                
                # 生成唯一的6位验证码
                import random
                max_attempts = 100  # 最大尝试次数，防止无限循环
                verify_code = None
                for _ in range(max_attempts):
                    verify_code = str(random.randint(100000, 999999))
                    
                    # 检查验证码是否已存在
                    db.execute("SELECT device_id FROM devices WHERE verify_code = ?", (verify_code,))
                    if db.fetchone() is None:
                        # 验证码不存在，可以使用
                        break
                else:
                    # 达到最大尝试次数，生成失败
                    self.logger.bind(tag=TAG).error(f"无法为设备 {device_id} 生成唯一验证码")
                    return None
                
                # 如果没有提供设备名称，使用设备verify_code作为名称
                if not device_name:
                    device_name = f"ESP-{verify_code}"
                
                description = f"Auto-created device {device_id}"
                
                # 插入新设备记录
                db.execute('''
                    INSERT INTO devices (device_id, device_name, description, template_secret, verify_code, status)
                    VALUES (?, ?, ?, ?, ?, 'pending')
                ''', (device_id, device_name, description, template_secret, verify_code))
                
                conn.commit()
                self.logger.bind(tag=TAG).info(f"设备 {device_id} 创建成功，验证码: {verify_code}")
                
                # 返回新创建的设备信息
                return {
                    'device_id': device_id,
                    'device_name': device_name,
                    'description': description,
                    'template_secret': template_secret,
                    'verify_code': verify_code,
                    'status': 'pending',
                    'external_id': None
                }
                
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"检查或创建设备失败: {str(e)}")
            return None
        finally:
            if 'conn' in locals():
                conn.close()

    def update_device_fields(self, device_id: str, fields: dict) -> bool:
        """灵活更新设备字段
        
        Args:
            device_id: 设备ID
            fields: 要更新的字段字典，格式为 {"字段名": "新值"}
            
        Returns:
            bool: 更新是否成功
            
        Example:
            # 更新单个字段
            update_device_fields("device123", {"external_id": "new_external_id"})
            
            # 更新多个字段
            update_device_fields("device123", {
                "device_name": "新设备名称",
                "description": "新描述",
                "external_id": "new_external_id"
            })
            
            # 更新状态（替代原来的update_device_status）
            update_device_fields("device123", {"status": "activated"})
        """
        try:
            if not fields:
                self.logger.bind(tag=TAG).warning("没有提供要更新的字段")
                return False
                
            conn = sqlite3.connect(self.db_path)
            db = conn.cursor()
            
            # 构建动态SQL语句
            set_clauses = []
            values = []
            
            # 验证字段名是否合法（防止SQL注入）
            allowed_fields = {
                'device_name', 'description', 'template_secret', 
                'verify_code', 'status', 'external_id', 'external_key', 'external_user_id'
            }
            
            for field_name, field_value in fields.items():
                if field_name not in allowed_fields:
                    self.logger.bind(tag=TAG).warning(f"不允许更新字段: {field_name}")
                    continue
                    
                set_clauses.append(f"{field_name} = ?")
                values.append(field_value)
            
            if not set_clauses:
                self.logger.bind(tag=TAG).warning("没有有效的字段需要更新")
                return False
            
            # 添加更新时间
            set_clauses.append("updated_at = CURRENT_TIMESTAMP")
            
            # 构建完整的SQL语句
            sql = f"UPDATE devices SET {', '.join(set_clauses)} WHERE device_id = ?"
            values.append(device_id)
            
            # 执行更新
            db.execute(sql, values)
            
            # 检查是否有行被更新
            if db.rowcount > 0:
                conn.commit()
                self.logger.bind(tag=TAG).info(f"设备 {device_id} 字段更新成功: {list(fields.keys())}")
                return True
            else:
                self.logger.bind(tag=TAG).warning(f"设备 {device_id} 不存在，字段更新失败")
                return False
            
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"更新设备字段失败: {str(e)}")
            return False
        finally:
            if 'conn' in locals():
                conn.close()
    