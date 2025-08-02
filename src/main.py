# d:\桌面\cloudflare-ip-optimizer-main\src\main.py
import configparser
from typing import Any
import logging
import os
import sys
import threading
import subprocess
from apscheduler.schedulers.background import BackgroundScheduler
from waitress import serve
from apscheduler.triggers.cron import CronTrigger 

# 使用相对导入，因为所有 .py 文件都在 src 包中
from 。optimizer import CloudflareOptimizer
from 。heartbeat import check_best_ip
from 。state import app_state
from 。api import create_app  # 导入新的 api 模块


def setup_scheduler(optimizer: CloudflareOptimizer, config: configparser.ConfigParser) -> BackgroundScheduler:
    """配置并启动调度器"""
    scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    
    # 添加 fallback 增加健壮性
    optimize_cron = config.get('Scheduler'， 'optimize_cron', fallback='0 */4 * * *')
    scheduler.add_job(
        optimizer.run_speed_test,
        trigger=CronTrigger.from_crontab(optimize_cron),
        id='job_optimize_ip',
        name='定时优选Cloudflare IP'
    )
    logging.info(f"已添加定时优选任务，Cron: {optimize_cron}")

    # 添加 fallback 增加健壮性
    heartbeat_cron = config.get('Scheduler'， 'heartbeat_cron', fallback='*/5 * * * *')
    scheduler.add_job(
        lambda: check_best_ip(optimizer),
        trigger=CronTrigger.from_crontab(heartbeat_cron),
        id='job_heartbeat_check',
        name='最优IP心跳检测'
    )
    logging.info(f"已添加心跳检测任务，Cron: {heartbeat_cron}")
    
    # 新增：华为DNS更新任务
dns_update_cron = config.get('Scheduler', 'dns_update_cron', fallback=None)
    if dns_update_cron:
        def run_huawei_dns_update():
            try:
                result = subprocess.run(
                    ["python3", "src/huawei_dns_update.py"]，
                    capture_output=True,
                    text=True,
                    check=False
                )
                if result.stdout:
                    logging.info(f"华为DNS更新输出:\n{result.stdout}")
                if result.stderr:
                    logging.error(f"华为DNS更新错误输出:\n{result.stderr}")
            except Exception as e:
                logging.error(f"华为DNS更新任务执行异常: {e}")

        scheduler.add_job(
            run_huawei_dns_update,
            trigger=CronTrigger.from_crontab(dns_update_cron),
            id='job_huawei_dns_update',
            name='华为DNS定时更新'
        )
        logging.info(f"已添加华为DNS更新任务，Cron: {dns_update_cron}")

    scheduler.start()
    return scheduler

def main() -> None:
    # 1. 确定路径
    # 无论从哪里运行脚本，都能找到正确的项目根目录和配置目录
    # __file__ -> .../src/main.py
    # os.path.dirname(__file__) -> .../src
    # os.path.abspath(os.path.join(os.path.dirname(__file__), '..')) -> .../ (项目根目录)
    PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    CONFIG_DIR = os.path.join(PROJECT_ROOT, 'config')
    CONFIG_FILE_PATH = os.path.join(CONFIG_DIR, 'config.ini')
    LOG_FILE_PATH = os.path.join(PROJECT_ROOT, 'app.log') # 定义日志文件路径
    STATIC_DIR = os.path.join(PROJECT_ROOT, 'static')
    TEMPLATE_DIR = os.path.join(PROJECT_ROOT, 'templates')

    # 确保配置目录存在
    os.makedirs(CONFIG_DIR, exist_ok=True)

    # 2. 读取配置
    if not os.path.exists(CONFIG_FILE_PATH):
        logging.warning(f"配置文件未找到: {CONFIG_FILE_PATH}，将使用默认配置并创建文件。")
        config = configparser.ConfigParser()
        config['cfst'] = {
            'params': '-p 0 -o result.csv -url https://cf.xiu2.xyz/url -dn 10 -t 2 -dd '
        }
        config['Scheduler'] = {
            'optimize_cron': '0 3 * * *',
            'heartbeat_cron': '*/5 * * * *'
        }
        config['OpenWRT'] = {
            'enabled': 'false',
            'host': '192.168.1.1',
            'port': '22',
            'username': 'root',
            'password': 'your_password',
            'target': 'openwrt',
            'openwrt_hosts_path': '/etc/hosts',
            'adguardhome_config_path': '/etc/AdGuardHome.yaml',
            'mosdns_hosts_path': '/etc/mosdns/rule/hosts.txt',
            'post_update_command': ''
        }
        config['Download'] = {
            'proxy': 'https://ghproxy.com/'
        }
        config['API'] = {'port': 6788}
        with open(CONFIG_FILE_PATH, 'w', encoding='utf-8') as configfile:
            config.write(configfile)
    else:
        config = configparser.ConfigParser()
        config.read(CONFIG_FILE_PATH, encoding='utf-8')

    # 配置日志系统，同时输出到文件和控制台
    log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # 移除所有现有的处理器，以避免重复日志
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # 文件处理器
    file_handler = logging.FileHandler(LOG_FILE_PATH, mode='w', encoding='utf-8')
    file_handler.setFormatter(log_formatter)
    root_logger.addHandler(file_handler)

    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(log_formatter)
    root_logger.addHandler(console_handler)

    # 3. 初始化核心优选器，并传入配置目录
    optimizer = CloudflareOptimizer(config, config_dir=CONFIG_DIR)

    # 4. 下载/检查工具
    optimizer.download_and_extract_tool()

    # 5. 启动时检查 result.csv 并决定初始操作
    def startup_check():
        """检查现有结果或运行新测试的启动逻辑"""
        if not os.path.exists(optimizer.output_filepath):
            # 文件不存在，立即执行一次优选
            logging.info("启动检查: result.csv 不存在，将立即执行一次IP优选...")
            optimizer.run_speed_test()
        else:
            # 文件存在，解析文件并进行心跳检测
            logging.info(f"启动检查: 发现已存在的 result.csv，将进行解析和心跳测试。")
            optimizer.load_results_from_file()
            if app_state.best_ip:
                check_best_ip(optimizer)
            else:
                logging.warning("启动检查: result.csv 解析失败或为空，将执行一次新的IP优选。")
                optimizer.run_speed_test()

    initial_run_thread = threading.Thread(target=startup_check, name="StartupCheckThread")
    initial_run_thread.start()

    # 6. 创建 Flask App, 并传入模板和静态文件夹路径
    app = create_app(optimizer, template_folder=TEMPLATE_DIR, static_folder=STATIC_DIR)

    # 7. 配置并启动调度器
    scheduler = setup_scheduler(optimizer, config)

    # 8. 在 app.config 中存储核心对象，方便在 API 路由中访问
    app.config['CONFIG'] = config
    app.config['SCHEDULER'] = scheduler
    app.config['CONFIG_FILE_PATH'] = CONFIG_FILE_PATH
    app.config['LOG_FILE_PATH'] = LOG_FILE_PATH

    # 9. 启动API服务
    api_port = config['API'].getint('port', 6788)
    logging.info(f"API服务将在 http://0.0.0.0:{api_port} 上启动")
    try:
        # 使用 waitress 作为生产级 WSGI 服务器
        serve(app, host='0.0.0.0', port=api_port)
    except (KeyboardInterrupt, SystemExit):
        logging.info("收到退出信号，正在关闭调度器...")
        scheduler.shutdown()
        logging.info("等待初次优选任务完成...")
        initial_run_thread.join() # 确保初次运行在退出前完成


if __name__ == '__main__':
    main()


