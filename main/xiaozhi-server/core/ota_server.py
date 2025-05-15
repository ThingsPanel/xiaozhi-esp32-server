import json
import os
import sqlite3
import time
import asyncio
from aiohttp import web
from config.logger import setup_logging
from core.connection import ConnectionHandler
from core.utils.util import get_local_ip, initialize_modules
from core.utils.tp import authenticate_device, update_device_online_status

TAG = __name__


class SimpleOtaServer:
    def __init__(self, config: dict):
        self.config = config
        self.logger = setup_logging()
        # 获取manager-api的secret
        self.secret = self.config["server"]["secret"]
        # 建立sqlite数据库存储基础信息
        self.db_path = "data/data.db"
        self._init_db()

    def _get_websocket_url(self, local_ip: str, port: int) -> str:
        """获取websocket地址

        Args:
            local_ip: 本地IP地址
            port: 端口号

        Returns:
            str: websocket地址
        """
        server_config = self.config["server"]
        websocket_config = server_config.get("websocket")

        if websocket_config and "你" not in websocket_config:
            return websocket_config
        else:
            return f"ws://{local_ip}:{port}/xiaozhi/v1/"

    async def start(self):
        server_config = self.config["server"]
        host = server_config.get("ip", "0.0.0.0")
        port = int(server_config.get("ota_port"))

        if port:
            app = web.Application()
            # 添加路由
            app.add_routes(
                [
                    web.get("/xiaozhi/ota/", self._handle_ota_get_request),
                    web.post("/xiaozhi/ota/", self._handle_ota_request),
                    web.options("/xiaozhi/ota/", self._handle_ota_request),
                    # 提供外部接口, 获取可激活设备列表
                    web.post("/xiaozhi/device/list", self._handle_device_list),
                ]
            )

            # 运行服务
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, host, port)
            await site.start()

            # 保持服务运行
            while True:
                await asyncio.sleep(3600)  # 每隔 1 小时检查一次

    async def _handle_ota_request(self, request):
        """处理 /xiaozhi/ota/ 的 POST 请求"""
        try:
            data = await request.text()
            self.logger.bind(tag=TAG).info(f"OTA请求方法: {request.method}")
            self.logger.bind(tag=TAG).info(f"OTA请求头: {request.headers}")
            self.logger.bind(tag=TAG).info(f"OTA请求数据: {data}")

            device_id = request.headers.get("device-id", "")
            if device_id:
                self.logger.bind(tag=TAG).info(f"OTA请求设备ID: {device_id}")
            else:
                raise Exception("OTA请求设备ID为空")
            
            template_secret = request.headers.get("template-secret", "")
            if template_secret:
                self.logger.bind(tag=TAG).info(f"OTA请求模板密钥: {template_secret}")
            else:
                raise Exception("OTA请求模板密钥为空")

            data_json = json.loads(data)

            server_config = self.config["server"]
            host = server_config.get("ip", "0.0.0.0")
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

            # 获取voucher.json配置
            with open("data/voucher.json", "r") as f:
                voucher_data = json.load(f)

            # 解析嵌套的JSON字符串
            voucher_str = voucher_data.get("voucher", "{}")
            try:
                voucher_obj = json.loads(voucher_str)
                tp_auth_type = voucher_obj.get("auth_type", "manual")
            except json.JSONDecodeError:
                self.logger.bind(tag=TAG).error(f"无法解析voucher JSON字符串: {voucher_str}")
                tp_auth_type = "manual"  # 设置默认值

            # 检查设备是否存在于数据库中，如果不存在则自动创建此设备
            device_info = self.check_or_create_device(device_id, template_secret)
            if not device_info:
                raise Exception("设备检查或创建失败")
            else:
                # 同步更新设备状态为在线, 如果TP中不存在此设备则会返回False
                is_online = await update_device_online_status(device_id, True)

                # 如果此接入点开启了自动认证，则调用TP的一型一密接口自动认证并生成TP Device
                if tp_auth_type == "auto":
                    # 输出日志开始自动激活
                    self.logger.bind(tag=TAG).info(f"开始认证设备: {device_id}")
                    # 调用TP的一型一密接口自动认证并生成TP Device
                    auth_result, auth_data = await authenticate_device(template_secret, device_id, device_info['device_name'])
                # 如果此接入点开启了人工认证
                else:
                    if is_online: # 说明设备已经激活
                        # 更新设备状态为activated
                        self.update_device_status(device_id, "activated")
                        auth_result = True
                    else:
                        # 设备在TP中并未激活, 则强制走人工激活, 无论ESP DB中是否activated
                        auth_result = False
                        
                # 设备未认证时成功时
                if not auth_result:
                    verify_code = device_info['verify_code']
                    # 如果自动认证失败，可能是设备模块不允许自动认证，则返回activation: code, message, challenge走手动认证
                    return_json["activation"] = {
                        "code": verify_code,
                        "message": "激活码: " + verify_code,
                        "challenge": device_id,
                    }

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
            # 添加header，允许跨域访问
            response.headers["Access-Control-Allow-Headers"] = (
                "client-id, content-type, device-id"
            )
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Allow-Origin"] = "*"
            return response

    async def _handle_ota_get_request(self, request):
        """处理 /xiaozhi/ota/ 的 GET 请求"""
        try:
            self.logger.bind(tag=TAG).info(f"收到OTA GET请求: {request.headers}")
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
            # 添加header，允许跨域访问
            response.headers["Access-Control-Allow-Headers"] = (
                "client-id, content-type, device-id"
            )
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Allow-Origin"] = "*"
            return response

    # 获取可激活设备列表
    async def _handle_device_list(self, request: web.Request) -> web.Response:
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
            with open("data/voucher.json", "w") as f:
                json.dump({
                    "voucher": voucher,
                    "service_identifier": service_identifier
                }, f)

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

    # 初始化数据库
    def _init_db(self):
        """初始化SQLite数据库
        
        创建数据库目录和必要的表结构
        """
        try:
            # 确保数据库目录存在
            db_dir = os.path.dirname(self.db_path)
            if not os.path.exists(db_dir):
                os.makedirs(db_dir)
            
            # 连接数据库
            conn = sqlite3.connect(self.db_path)
            db = conn.cursor()
            
            # 创建设备表
            db.execute('''
                CREATE TABLE IF NOT EXISTS devices (
                    device_id TEXT PRIMARY KEY,
                    device_name TEXT NOT NULL,
                    description TEXT,
                    template_secret TEXT NOT NULL,
                    verify_code TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # 为 verify_code 创建唯一索引
            db.execute('''
                CREATE UNIQUE INDEX IF NOT EXISTS idx_devices_verify_code_unique 
                ON devices(verify_code)
            ''')
            
            # 提交更改
            conn.commit()
            self.logger.bind(tag=TAG).info("数据库初始化成功")
            
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"数据库初始化失败: {str(e)}")
            raise
        finally:
            if 'conn' in locals():
                conn.close() 

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
                          'verify_code', 'status']
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
                    'status': 'pending'
                }
                
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"检查或创建设备失败: {str(e)}")
            return None
        finally:
            if 'conn' in locals():
                conn.close()

    def update_device_status(self, device_id: str, status: str) -> bool:
        """更新设备状态
        
        Args:
            device_id: 设备ID
            status: 新状态
            
        Returns:
            bool: 更新是否成功
        """
        try:
            conn = sqlite3.connect(self.db_path)
            db = conn.cursor()
            
            # 更新设备状态和更新时间
            db.execute('''
                UPDATE devices 
                SET status = ?, updated_at = CURRENT_TIMESTAMP 
                WHERE device_id = ?
            ''', (status, device_id))
            
            # 检查是否有行被更新
            if db.rowcount > 0:
                conn.commit()
                self.logger.bind(tag=TAG).info(f"设备 {device_id} 状态已更新为: {status}")
                return True
            else:
                self.logger.bind(tag=TAG).warning(f"设备 {device_id} 不存在，状态更新失败")
                return False
            
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"更新设备状态失败: {str(e)}")
            return False
        finally:
            if 'conn' in locals():
                conn.close()