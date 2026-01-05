import asyncio
from datetime import datetime
from dateutil.relativedelta import relativedelta
from ...tasks.bsm_cookie_manager import bsm_cookie_manager
import requests
import json
from ...utils.logger import get_logger

logger = get_logger("extra_bsm")


def getRfqNo(rfq_number: str):
    try:
        url = "https://paleconnect.bs-shipmanagement.com/Home/api/ServiceRouter/POST"

        payload = json.dumps({
            "gridServerOperations": {
                "filters": [
                    {
                        "logic": "and",
                        "filters": [
                            {
                                "field": "referenceNo",
                                "operator": "eq",
                                "value": rfq_number
                            }
                        ]
                    }
                ],
                "page": 1,
                "pageSize": 25
            },
            "dateFrom": (datetime.now() - relativedelta(months=1)).strftime("%d-%b-%Y"),
            "dateTo": datetime.now().strftime("%d-%b-%Y"),
            "smcType": "",
            "docType": "All",
            "referenceNumber": "",
            "code": "ALL"
        })
        headers = {
            'servicepath': 'Dashboard/GetRFQChartGridDetails',
            'Cookie': f'.ASPXAUTH={bsm_cookie_manager.auth_cookie}; __cflb={bsm_cookie_manager.cflb}',
            'Content-Type': 'application/json'
        }

        response = requests.request("POST", url, headers=headers, data=payload)

        rfqNo = response.json()['result'][0]['rfqNo']
        return rfqNo
    except Exception as e:
        logger.debug(f"bsm rfqNo 获取失败: {e}")
        raise e


def getRfqInfo(rfqNo: int):
    try:
        url = f"https://paleconnect.bs-shipmanagement.com/Home/api/ServiceRouter/GET?pData=id%3D{rfqNo}%26quoteStatus%3DPending"

        payload = {}
        headers = {
            'servicepath': 'QuoteCreation/GetEnquiryInfoById',
            'Cookie': f'.ASPXAUTH={bsm_cookie_manager.auth_cookie}; __cflb={bsm_cookie_manager.cflb}',
        }

        response = requests.request("GET", url, headers=headers, data=payload)
        result = response.json()['result']

        meta_data = {
            'Title': result['title'],
            'Remarks To Vendor': result['remarks'],
        }
        return meta_data
    except Exception as e:
        logger.debug(f"bsm rfq info 获取失败: {e}")
        raise e


def getRfqItems(rfqNo: int):
    try:
        url = f"https://paleconnect.bs-shipmanagement.com/Home/api/ServiceRouter/GET?pData=id%3D{rfqNo}%26quoteStatus%3DPending"

        payload = {}
        headers = {
            'servicepath': 'QuoteCreation/GetItemDetailsAndCharges',
            'Cookie': f'.ASPXAUTH={bsm_cookie_manager.auth_cookie}; __cflb={bsm_cookie_manager.cflb}',
        }

        response = requests.request("GET", url, headers=headers, data=payload)
        result = response.json()['result']

        target_keys = ["number", "partNumber", "productCode", "description", "uomName", "quantity",
                       "remarksToVendor", "equipmentName", "maker", "modelNumber", "drawingNumber", "serialNumber"]
        table_data = [
            {k: d[k] for k in target_keys if k in d} for d in result]
        return table_data

    except Exception as e:
        logger.debug(f"bsm rfq items 获取失败: {e}")
        raise e


async def process_bsm_rfq(rfq_number: str):
    rfqNo = getRfqNo(rfq_number)
    meta_data = getRfqInfo(rfqNo)
    table_data = getRfqItems(rfqNo)
    return {
        'meta_data': meta_data,
        'table_data': table_data,
    }
