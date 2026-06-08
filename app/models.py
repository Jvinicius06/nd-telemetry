"""Reference tables to decode ESP8266 reset reasons and Xtensa exception causes."""

# ESP8266 RTOS SDK: rst_info->reason  (system_get_rst_info())
RESET_REASONS = {
    0: "Power-on / Brown-out",   # REASON_DEFAULT_RST  (cold boot or power loss)
    1: "Hardware WDT",           # REASON_WDT_RST
    2: "Exception (crash)",      # REASON_EXCEPTION_RST
    3: "Software WDT",           # REASON_SOFT_WDT_RST
    4: "Software restart",       # REASON_SOFT_RESTART (system_restart / OTA)
    5: "Deep-sleep wake",        # REASON_DEEP_SLEEP_AWAKE
    6: "External reset",         # REASON_EXT_SYS_RST  (reset pin)
}

# Reasons that indicate an abnormal / unwanted reboot (worth alerting on)
ABNORMAL_REASONS = {1, 2, 3}

# Xtensa LX106 EXCCAUSE values (only the ones that actually show up on ESP8266)
EXC_CAUSES = {
    0: "IllegalInstruction",
    1: "Syscall",
    2: "InstructionFetchError",
    3: "LoadStoreError",
    4: "Level1Interrupt",
    5: "Alloca",
    6: "IntegerDivideByZero",
    8: "Privileged",
    9: "LoadStoreAlignment",
    12: "InstrPIFDataError",
    13: "LoadStorePIFDataError",
    14: "InstrPIFAddrError",
    15: "LoadStorePIFAddrError",
    16: "InstTLBMiss",
    17: "InstTLBMultiHit",
    18: "InstFetchPrivilege",
    20: "InstFetchProhibited",
    24: "LoadStoreTLBMiss",
    25: "LoadStoreTLBMultiHit",
    26: "LoadStorePrivilege",
    28: "LoadProhibited",
    29: "StoreProhibited",
}


def reason_name(r):
    if r is None:
        return None
    try:
        return RESET_REASONS.get(int(r), f"Unknown ({r})")
    except (TypeError, ValueError):
        return f"Unknown ({r})"


def exc_name(c):
    if c is None:
        return None
    try:
        return EXC_CAUSES.get(int(c), f"Cause {c}")
    except (TypeError, ValueError):
        return f"Cause {c}"


def is_abnormal(r):
    try:
        return int(r) in ABNORMAL_REASONS
    except (TypeError, ValueError):
        return False
