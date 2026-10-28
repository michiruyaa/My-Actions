import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

DEFAULT_ADDRESSES = {
    "eharbot": "https://eh-arc-api.mhdy.icu",
    "ntrehbot": "https://ehbot-api.ntr.you",
    "archiveathome": "https://api.archive-at-home.org/jhentai",
}

GP_UNITS = {
    "ntrehbot": "纯爱点",
}

EH_AR_BOT_TYPES = ("eharbot", "ntrehbot")
ARCHIVE_AT_HOME_TYPES = ("archiveathome",)

ACCOUNT_SECRETS = ["ARCHIVE_BOT"] + [f"ARCHIVE_BOT_{i}" for i in range(1, 6)]

HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "JHenTai-ArchiveBot-GitHubAction/1.0",
}


@dataclass
class CheckInResult:
    success: bool
    reward: Optional[int] = None
    balance: Optional[int] = None
    already_checked_in: bool = False
    message: str = ""


def parse_account(text: str) -> dict:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    keys = ("bot_type", "api_address", "api_key")
    account = {key: (lines[i] if i < len(lines) else "") for i, key in enumerate(keys)}

    bot_type_lower = account["bot_type"].lower()
    if not account["api_address"].lower().startswith("http"):
        account["api_key"] = account["api_address"]
        account["api_address"] = DEFAULT_ADDRESSES.get(bot_type_lower, DEFAULT_ADDRESSES["eharbot"])

    return account


def load_accounts() -> list:
    accounts = []
    for name in ACCOUNT_SECRETS:
        value = os.environ.get(name)
        if value and value.strip():
            accounts.append(parse_account(value))
    return accounts


def query_balance_eh_ar_bot(api_address: str, api_key: str, label: str) -> Optional[int]:
    try:
        resp = requests.post(f"{api_address}/balance", headers=HEADERS, json={"apikey": api_key}, timeout=30)
        data = resp.json()
        log.info(f"[{label}] balance response: {data}")
        if data.get("code") == 0:
            balance_data = data.get("data", {})
            return (
                balance_data.get("current_GP")
                or balance_data.get("current_gp")
                or balance_data.get("GP")
                or balance_data.get("gp")
            )
    except Exception:
        pass
    return None


def check_in_eh_ar_bot(api_address: str, api_key: str, label: str) -> CheckInResult:
    try:
        resp = requests.post(f"{api_address}/checkin", headers=HEADERS, json={"apikey": api_key}, timeout=30)
        data = resp.json()
        log.info(f"[{label}] checkin response: {data}")
        code = data.get("code")
        if code == 0:
            checkin_data = data.get("data", {})
            return CheckInResult(
                success=True,
                reward=checkin_data.get("get_GP"),
                balance=checkin_data.get("current_GP"),
            )
        elif code == 7:
            return CheckInResult(success=True, already_checked_in=True)
        else:
            return CheckInResult(success=False, message=data.get("msg", f"code={code}"))
    except Exception as e:
        return CheckInResult(success=False, message=str(e))


def query_balance_archive_at_home(api_address: str, api_key: str) -> Optional[int]:
    try:
        resp = requests.get(
            f"{api_address}/api/v1/me/balance",
            headers={
                **HEADERS,
                "Authorization": f"Bearer {api_key}",
                "X-Client": "app/jhentai",
            },
            timeout=30,
        )
        log.info(f"[Archive-at-Home] balance status={resp.status_code}, body={resp.text}")
        if resp.status_code == 200:
            data = resp.json()
            if data.get("code") == 0:
                balance_data = data.get("data", {})
                return (
                    balance_data.get("GP")
                    or balance_data.get("gp")
                    or balance_data.get("balance")
                )
            return data.get("GP") or data.get("gp") or data.get("balance")
    except Exception:
        pass
    return None


def check_in_archive_at_home(api_address: str, api_key: str) -> CheckInResult:
    try:
        resp = requests.post(
            f"{api_address}/api/v1/me/checkin",
            headers={
                **HEADERS,
                "Authorization": f"Bearer {api_key}",
                "X-Client": "app/jhentai",
            },
            timeout=30,
        )
        log.info(f"[Archive-at-Home] checkin status={resp.status_code}, body={resp.text}")
        if resp.status_code == 200:
            data = resp.json()
            code = data.get("code")
            if code == 7:
                return CheckInResult(success=True, already_checked_in=True)
            checkin_data = data.get("data", {})
            return CheckInResult(
                success=True,
                reward=checkin_data.get("reward"),
                balance=checkin_data.get("balance"),
            )
        elif resp.status_code == 409:
            return CheckInResult(success=True, already_checked_in=True)
        else:
            return CheckInResult(success=False, message=f"status={resp.status_code}, body={resp.text}")
    except Exception as e:
        return CheckInResult(success=False, message=str(e))


def process_account(account: dict, index: int) -> bool:
    bot_type = account["bot_type"]
    api_address = account["api_address"].rstrip("/")
    api_key = account["api_key"]

    if not api_key:
        return True

    bot_type_lower = bot_type.lower()
    unit = GP_UNITS.get(bot_type_lower, "GP")
    label = "默认账号" if index == 0 else f"账号{index}"

    log.info("")
    log.info(f"========== {label} ==========")
    log.info(f"协议类型：{bot_type}")
    log.info(f"API 地址：{api_address}")

    if bot_type_lower in EH_AR_BOT_TYPES:
        balance = query_balance_eh_ar_bot(api_address, api_key, bot_type)
        result = check_in_eh_ar_bot(api_address, api_key, bot_type)
    elif bot_type_lower in ARCHIVE_AT_HOME_TYPES:
        balance = query_balance_archive_at_home(api_address, api_key)
        result = check_in_archive_at_home(api_address, api_key)
    else:
        log.error(f"未知协议类型: {bot_type}")
        return False

    log.info("签到结果：")
    if not result.success:
        log.info(f"签到失败：{result.message}")
        return False

    if result.already_checked_in:
        log.info("今日已签到")
    else:
        reward_str = str(result.reward) if result.reward is not None else "?"
        log.info(f"签到成功：获得{reward_str}{unit}")

    final_balance = result.balance if (result.balance is not None and result.balance > 0) else balance
    balance_str = str(final_balance) if final_balance is not None else "?"
    log.info(f"当前余额：{balance_str}{unit}")

    return True


def main():
    accounts = load_accounts()

    if not accounts:
        log.warning("未配置任何 Archive Bot 账号（ARCHIVE_BOT / ARCHIVE_BOT_1~5 均为空），跳过。")
        sys.exit(0)

    log.info("=" * 40)
    log.info("Archive Bot 每日签到开始")
    log.info(f"当前配置账号数：{len(accounts)}")
    log.info("=" * 40)

    all_success = True
    for i, account in enumerate(accounts):
        try:
            ok = process_account(account, i)
            if not ok:
                all_success = False
        except Exception as e:
            log.error(f"{'默认账号' if i == 0 else f'账号{i}'} 发生异常: {e}")
            all_success = False

    log.info("")
    log.info("=" * 40)
    if all_success:
        log.info("全部账号签到完成")
    else:
        log.error("部分账号签到失败")
    log.info("=" * 40)

    sys.exit(0 if all_success else 1)


if __name__ == "__main__":
    main()
