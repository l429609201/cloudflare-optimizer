#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 环境变量说明（供 Docker 使用）
# 环境变量	含义说明
# HW_AK	华为云 Access Key
# HW_SK	华为云 Secret Key
# HW_PROJECT_ID	项目 ID（在控制台查看）
# HW_ZONE_ID	DNS 区域 ID（Zone ID）

import os
import time
import logging
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

# ===== 配置 =====
AK = os.getenv("HW_AK")
SK = os.getenv("HW_SK")
PROJECT_ID = os.getenv("HW_PROJECT_ID")
REGION_NAME = "cn-east-3"
ZONE_ID = os.getenv("HW_ZONE_ID")
DOMAIN_NAME = "cdn.akk.pp.ua."
RECORD_TYPE = "A"
TTL = 300
MAX_RECORDS = 10
API_IPS_URL = "https://localhost:6788/api/results"

logging.basicConfig(
    filename="huawei_dns_sdk.log",
    level=logging.INFO,
    format="%(asctime)s - %(message)s"
)

class SimpleRegion:
    def __init__(self, name):
        self.name = name
        self.id = name
        self.endpoints = [f"https://dns.{name}.myhuaweicloud.com"]

def get_best_ips(limit=50):
    try:
        resp = requests.get(API_IPS_URL, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        ips = [item.get("IP 地址") for item in data if item.get("IP 地址")]
        ips = list(dict.fromkeys(ips))
        logging.info(f"获取优选IP: {ips[:limit]}")
        print(f"获取优选IP: {ips[:limit]}")
        return ips[:limit]
    except Exception as e:
        logging.error(f"获取优选IP失败: {e}")
        print(f"获取优选IP失败: {e}")
        return []

def main():
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - 脚本开始执行...")
    logging.info("脚本开始执行")

    creds = BasicCredentials(AK, SK, PROJECT_ID)
    client = DnsClient.new_builder() \
        .with_credentials(creds) \
        .with_region(SimpleRegion(REGION_NAME)) \
        .build()

    best_ips = get_best_ips(MAX_RECORDS)
    if not best_ips:
        print("未获取到优选IP，退出。")
        return

    request = ListRecordSetsRequest()
    request.zone_id = ZONE_ID
    request.name = DOMAIN_NAME
    request.type = RECORD_TYPE

    try:
        resp = client.list_record_sets(request)
        records = resp.recordsets
        print(f"查询到的记录数: {len(records)}")
        logging.info(f"查询到的记录数: {len(records)}")
    except exceptions.ClientRequestException as e:
        print(f"获取记录失败: {e}")
        logging.error(f"获取记录失败: {e}")
        return

    default_record = 无
    for r in records:
        line = getattr(r, "line"， "") or getattr(r, "line_id", "")
        if line 在 ("默认", "default", "default_view", ""):
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
                print(f"修改默认线路记录成功: {best_ips}")
                logging.info(f"修改默认线路记录成功: {best_ips}")
            except exceptions.ClientRequestException as e:
                print(f"修改默认线路记录失败: {e}")
                logging.error(f"修改默认线路记录失败: {e}")
        else:
            print("IP 列表与默认线路已有记录一致，无需更新")
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
            print(f"新增默认线路记录成功: {best_ips}")
            logging.info(f"新增默认线路记录成功: {best_ips}")
        except exceptions.ClientRequestException as e:
            print(f"新增默认线路记录失败: {e}")
            logging.error(f"新增默认线路记录失败: {e}")

    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - 脚本执行结束.")
    logging.info("脚本执行结束")

if __name__ == "__main__":
    main()
