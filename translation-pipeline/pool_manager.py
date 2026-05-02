import os
import time
import requests
import json
import logging
from threading import Lock

class CredentialPool:
    """Rotating Round Robin Credential Pool with Health Checks"""
    def __init__(self, provider, keys):
        self.provider = provider
        self.pool = [{"key": k, "is_valid": True, "error": None, "last_used": 0} for k in keys]
        self.index = 0
        self.lock = Lock()
        self.logger = logging.getLogger(f"CredentialPool-{provider}")

    def get_key(self):
        with self.lock:
            start_index = self.index
            while True:
                item = self.pool[self.index]
                self.index = (self.index + 1) % len(self.pool)
                
                if item['is_valid']:
                    item['last_used'] = time.time()
                    return item['key']
                
                if self.index == start_index:
                    return None

    def report_failure(self, key, error_msg):
        with self.lock:
            for item in self.pool:
                if item['key'] == key:
                    # If it's a rate limit (429), we just deprioritize/delay it, don't mark invalid
                    if "429" in str(error_msg) or "quota" in str(error_msg).lower():
                        self.logger.warning(f"Key [...{key[-4:]}] hit rate limit. Cooling down...")
                        item['last_used'] = time.time() + 60 # Penalty
                    else:
                        self.logger.warning(f"Key [...{key[-4:]}] marked invalid: {error_msg}")
                        item['is_valid'] = False
                        item['error'] = str(error_msg)
                    break

class MultiProviderManager:
    def __init__(self):
        self.pools = {}

    def setup_pool(self, provider, keys):
        self.pools[provider] = CredentialPool(provider, keys)
        logging.info(f"Initialized {provider} pool with {len(keys)} keys.")

    def get_key(self, provider):
        pool = self.pools.get(provider)
        return pool.get_key() if pool else None

    def report_failure(self, provider, key, error):
        pool = self.pools.get(provider)
        if pool:
            pool.report_failure(key, error)

    def get_all_status(self):
        status = {}
        for p, pool in self.pools.items():
            status[p] = {
                "total": len(pool.pool),
                "valid": len([i for i in pool.pool if i['is_valid']]),
                "keys": [{"key": f"...{i['key'][-4:]}", "valid": i['is_valid']} for i in pool.pool]
            }
        return status
