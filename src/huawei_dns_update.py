#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 环境变量说明：HW_AK, HW_SK, HW_PROJECT_ID, HW_ZONE_ID, HW_DOMAIN_NAME（必须带末尾点号）
# TG_BOT_TOKEN, TG_USER_ID（可选，用于通知）

import os
import logging
import configparser
import requests

from huaweicloudsdkcore.auth.credentials import BasicCredentials
from huaweicloudsdkcore.exceptions import exceptions
from huaweicloudsdkdns.v2 import DnsClient
from huaweicloudsdkdns.v2.model import (
    ListRecordSetsRequest,
    UpdateRecordSetRequest,
    CreateRecordSetRequest,
    UpdateRecordSetReq
)

# ===== 读取配置 =====
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../config/config.ini')
config = configparser.ConfigParser()
config.read(CONFIG_FILE, encoding='utf-8')

api_port = config['API'].getint('port', 6788)
API_IPS_URL = f"http://0.0.0.0:{api_port}/api/results"

# ===== 环境变量配置 =====
AK = os.getenv("HW_AK")
SK = os.getenv("HW_SK")
PROJECT_ID = os.getenv("HW_PROJECT_ID")
REGION_NAME = "cn-east-3"
ZONE_ID = os.getenv("HW_ZONE_ID")
DOMAIN_NAME = os.getenv("HW_DOMAIN_NAME")  # 例如 "cdn.example.com."
RECORD_TYPE = "A"
TTL = 300
MAX_RECORDS = 5

# Telegram 推送配置
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_USER_ID = os.getenv("TG_USER_ID")

# ===== 日志配置（输出到 stdout）=====
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

class SimpleRegion:
    def __init__(self, name):
        self.name = name
        self.id = name
        self.endpoints = [f"https://dns.{name}.myhuaweicloud.com"]

def send_telegram_message(msg: str):
    if not TG_BOT_TOKEN or not TG_USER_ID:
        return
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, data={
            "chat_id": TG_USER_ID,
            "text": msg,
            "parse_mode": "Markdown"
        }, timeout=10)
        if resp.ok:
            logging.info("Telegram 通知发送成功")
        else:
            logging.warning(f"Telegram 通知发送失败: {resp.text}")
    except Exception as e:
        logging.error(f"Telegram 推送异常: {e}")

def get_best_ips(limit=50):
    try:
        resp = requests.get(API_IPS_URL, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        ips = [item.get("IP 地址") for item in data if item.get("IP 地址")]
        ips = list(dict.fromkeys(ips))
        logging.info(f"获取优选IP: {ips[:limit]}")
        return ips[:limit]
    except Exception as e:
        logging.error(f"获取优选IP失败: {e}")
        return []

def main():
    logging.info("华为DNS 更新任务启动")

    # 校验环境变量
    if not all([AK, SK, PROJECT_ID, ZONE_ID, DOMAIN_NAME]):
        logging.error("❌ 缺少必要的环境变量，请设置 HW_AK, HW_SK, HW_PROJECT_ID, HW_ZONE_ID, HW_DOMAIN_NAME")
        return

    creds = BasicCredentials(AK, SK, PROJECT_ID)
    client = DnsClient.new_builder() \
        .with_credentials(creds) \
        .with_region(SimpleRegion(REGION_NAME)) \
        .build()

    best_ips = get_best_ips(MAX_RECORDS)
    if not best_ips:
        logging.warning("未获取到优选IP，跳过更新")
        return

    request = ListRecordSetsRequest()
    request.zone_id = ZONE_ID
    request.name = DOMAIN_NAME
    request.type = RECORD_TYPE

    try:
        resp = client.list_record_sets(request)
        records = resp.recordsets
        logging.info(f"查询到记录数: {len(records)}")
    except exceptions.ClientRequestException as e:
        logging.error(f"获取记录失败: {e}")
        return

    default_record = 无
    for r in records:
        line = getattr(r, "line", "") or getattr(r, "line_id", "")
        if line in ("默认", "default", "default_view", ""):
            default_record = r
            break

    if default_record:
        old_ips = default_record.records or []
        if set(old_ips) != set(best_ips):
            update_req_body = UpdateRecordSetReq(
                name=DOMAIN_NAME,
                type=RECORD_TYPE,
                ttl=TTL,
                records=best_ips
            )
            update_req = UpdateRecordSetRequest()
            update_req.zone_id = ZONE_ID
            update_req.recordset_id = default_record.id
            update_req.body = update_req_body

            try:
                client.update_record_set(update_req)
                msg = f"✅ [华为DNS] 默认线路记录更新成功:\n{DOMAIN_NAME}\n{best_ips}"
                logging.info(msg)
                send_telegram_message(msg)
            except exceptions.ClientRequestException as e:
                logging.error(f"默认线路记录更新失败: {e}")
        else:
            logging.info("优选 IP 与现有记录一致，无需更新")
    else:
        create_req_body = UpdateRecordSetReq(
            name=DOMAIN_NAME,
            type=RECORD_TYPE,
            ttl=TTL,
            records=best_ips
        )
        create_req = CreateRecordSetRequest()
        create_req.zone_id = ZONE_ID
        create_req.body = create_req_body

        try:
            client.create_record_set(create_req)
            msg = f"✅ [华为DNS] 新增默认线路记录成功:\n{DOMAIN_NAME}\n{best_ips}"
            logging.info(msg)
            send_telegram_message(msg)
        except exceptions.ClientRequestException as e:
            logging.error(f"新增默认线路记录失败: {e}")

    logging.info("华为DNS 更新任务完成")

if __name__ == "__main__":
    main()
