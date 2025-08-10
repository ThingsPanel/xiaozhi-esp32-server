from aiohttp import web
from config.logger import setup_logging
import os
import sqlite3

TAG = __name__

class BaseHandler:
    def __init__(self, config: dict):
        self.config = config
        self.logger = setup_logging()
        # 获取manager-api的secret
        self.secret = self.config["server"]["secret"]
        # 建立sqlite数据库存储基础信息
        self.db_path = "data/data.db"
        self._init_db()

    def _add_cors_headers(self, response):
        """添加CORS头信息"""
        response.headers["Access-Control-Allow-Headers"] = (
            "client-id, content-type, device-id"
        )
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Origin"] = "*"
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
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    external_id TEXT,
                    external_key TEXT,
                    external_user_id TEXT
                )
            ''')
            
            # 检查并添加 external_id 字段（如果不存在）
            try:
                db.execute("SELECT external_id FROM devices LIMIT 1")
            except sqlite3.OperationalError:
                # external_id 字段不存在，添加它
                self.logger.bind(tag=TAG).info("为 devices 表添加 external_id 字段")
                db.execute("ALTER TABLE devices ADD COLUMN external_id TEXT")
            
            # 检查并添加 external_key 字段（如果不存在）
            try:
                db.execute("SELECT external_key FROM devices LIMIT 1")
            except sqlite3.OperationalError:
                # external_key 字段不存在，添加它
                self.logger.bind(tag=TAG).info("为 devices 表添加 external_key 字段")
                db.execute("ALTER TABLE devices ADD COLUMN external_key TEXT")

            # 检查并添加 external_user_id 字段（如果不存在）
            try:
                db.execute("SELECT external_user_id FROM devices LIMIT 1")
            except sqlite3.OperationalError:
                # external_user_id 字段不存在，添加它
                self.logger.bind(tag=TAG).info("为 devices 表添加 external_user_id 字段")
                db.execute("ALTER TABLE devices ADD COLUMN external_user_id TEXT")
            
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
