import asyncio
import sys
import signal
from config.settings import load_config
from core.websocket_server import WebSocketServer
from core.ota_server import SimpleOtaServer
from core.utils.util import check_ffmpeg_installed
from config.logger import setup_logging
from core.utils.util import get_local_ip

TAG = __name__
logger = setup_logging()


async def wait_for_exit():
    """Windows 和 Linux 兼容的退出监听"""
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    if sys.platform == "win32":
        # Windows: 用 sys.stdin.read() 监听 Ctrl + C
        await loop.run_in_executor(None, sys.stdin.read)
    else:
        # Linux/macOS: 用 signal 监听 Ctrl + C
        def stop():
            stop_event.set()

        loop.add_signal_handler(signal.SIGINT, stop)
        loop.add_signal_handler(signal.SIGTERM, stop)  # 支持 kill 进程
        await stop_event.wait()


async def main():
    check_ffmpeg_installed()
    config = load_config()

    # 启动 WebSocket 服务器
    ws_server = WebSocketServer(config)
    ws_task = asyncio.create_task(ws_server.start())
    ota_task = None

    read_config_from_api = config.get("read_config_from_api", False)
    if not read_config_from_api:
        # 启动 Simple OTA 服务器
        ota_server = SimpleOtaServer(config)
        ota_task = asyncio.create_task(ota_server.start())

        logger.bind(tag=TAG).info(
            "OTA接口是\t\thttp://{}:{}/xiaozhi/ota/",
            get_local_ip(),
            config["server"]["ota_port"],
        )

    # 获取WebSocket配置，使用安全的默认值
    websocket_port = 8000
    server_config = config.get("server", {})
    if isinstance(server_config, dict):
        websocket_port = int(server_config.get("port", 8000))

    logger.bind(tag=TAG).info(
        "Websocket地址是\tws://{}:{}/xiaozhi/v1/",
        get_local_ip(),
        websocket_port,
    )

    logger.bind(tag=TAG).info(
        "=======上面的地址是websocket协议地址，请勿用浏览器访问======="
    )
    logger.bind(tag=TAG).info(
        "如想测试websocket请用谷歌浏览器打开test目录下的test_page.html"
    )
    logger.bind(tag=TAG).info(
        "=============================================================\n"
    )

    try:
        await wait_for_exit()  # 监听退出信号
    except asyncio.CancelledError:
        print("任务被取消，清理资源中...")
    finally:
        ws_task.cancel()
        if ota_task:
            ota_task.cancel()
        try:
            await ws_task
            if ota_task:
                await ota_task
        except asyncio.CancelledError:
            pass
        print("服务器已关闭，程序退出。")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("手动中断，程序终止。")
